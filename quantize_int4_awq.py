"""Quantize the local Qwen3.5-4B BF16 checkpoint to W4A16 INT4 with AWQ.

The calibration corpus is read directly from the C-Eval ZIP.  Only the dev
split is used for calibration so validation/test rows remain available for
quality evaluation.  The source checkpoint is never modified and an existing
output directory is never overwritten.
"""

from __future__ import annotations

import argparse
import csv
import inspect
import io
import random
import shutil
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

import torch
from datasets import Dataset
from llmcompressor import oneshot
from llmcompressor.modifiers.quantization import QuantizationModifier
from llmcompressor.modifiers.transform.awq import AWQModifier
from transformers import AutoModelForImageTextToText, AutoTokenizer


DEFAULT_MODEL = Path(os.environ.get("QWEN_BF16_DIR", "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b"))
DEFAULT_OUTPUT = Path(os.environ.get("QWEN_INT4_OUTPUT", "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1"))
DEFAULT_CEVAL_ZIP = Path(os.environ.get("CEVAL_ZIP", "/mnt/e/AI-Inference-Lab/datasets/ceval.zip"))

# Keep modules that either do not benefit enough from packing, are sensitive,
# or are outside the text-only language model path in BF16.
IGNORE = [
    "lm_head",
    "model.language_model.embed_tokens",
    "re:.*visual.*",
    "re:.*linear_attn.conv1d$",
    "re:.*linear_attn.in_proj_a$",
    "re:.*linear_attn.in_proj_b$",
    "mtp.fc",
    "mtp.pre_fc_norm_embedding",
    "mtp.pre_fc_norm_hidden",
]


def restore_qwen35_gated_delta_net_signature() -> None:
    """Restore signature metadata lost by a Transformers 5.14 decorator.

    AWQ caches a parent module's call arguments via ``inspect.signature`` and
    later replays that call.  Transformers' ``force_accelerate_hooks`` wrapper
    currently exposes only ``(self, *args, **kwargs)`` for Qwen3.5's gated
    delta-net block, which makes AWQ cache a nested ``kwargs`` mapping instead
    of the required ``hidden_states`` argument.  The original function remains
    in the wrapper closure, so only its signature metadata needs restoring.
    """
    from transformers.models.qwen3_5.modeling_qwen3_5 import (
        Qwen3_5GatedDeltaNet,
    )

    decorated = Qwen3_5GatedDeltaNet.forward
    parameters = inspect.signature(decorated).parameters
    if "hidden_states" in parameters:
        return

    originals = [
        cell.cell_contents
        for cell in (decorated.__closure__ or ())
        if inspect.isfunction(cell.cell_contents)
        and "hidden_states" in inspect.signature(cell.cell_contents).parameters
    ]
    if len(originals) != 1:
        raise RuntimeError(
            "Could not uniquely recover Qwen3_5GatedDeltaNet.forward signature"
        )
    decorated.__signature__ = inspect.signature(originals[0])
    print(
        "Restored Qwen3_5GatedDeltaNet.forward signature for AWQ calibration"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ceval-zip", type=Path, default=DEFAULT_CEVAL_ZIP)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20260917)
    return parser.parse_args()


def is_dev_csv(name: str) -> bool:
    path = PurePosixPath(name)
    lowered = [part.lower() for part in path.parts]
    return name.lower().endswith(".csv") and (
        "dev" in lowered or path.stem.lower().endswith("_dev")
    )


def subject_from_name(name: str) -> str:
    stem = PurePosixPath(name).stem
    return stem[:-4] if stem.lower().endswith("_dev") else stem


def row_to_text(subject: str, row: dict[str, str]) -> str:
    question = (row.get("question") or "").strip()
    options = []
    for key in ("A", "B", "C", "D"):
        value = (row.get(key) or "").strip()
        if value:
            options.append(f"{key}. {value}")
    answer = (row.get("answer") or "").strip()
    explanation = (row.get("explanation") or "").strip()
    parts = [f"科目：{subject}", question, *options]
    if answer:
        parts.append(f"答案：{answer}")
    if explanation:
        parts.append(f"解析：{explanation}")
    return "\n".join(part for part in parts if part)


def load_ceval_dev(zip_path: Path, samples: int, seed: int) -> Dataset:
    rows: list[dict[str, str]] = []
    with zipfile.ZipFile(zip_path) as archive:
        members = sorted(name for name in archive.namelist() if is_dev_csv(name))
        if not members:
            raise SystemExit(
                "No C-Eval dev CSV files were found in the ZIP. "
                "Expected paths containing /dev/ or names ending in _dev.csv."
            )
        for name in members:
            subject = subject_from_name(name)
            raw = archive.read(name).decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(raw))
            for row in reader:
                text = row_to_text(subject, row)
                if text:
                    rows.append({"text": text, "subject": subject})

    if len(rows) < samples:
        raise SystemExit(
            f"C-Eval dev split contains only {len(rows)} usable rows, "
            f"but {samples} were requested."
        )
    rng = random.Random(seed)
    rng.shuffle(rows)
    selected = rows[:samples]
    counts = Counter(row["subject"] for row in selected)
    print(f"C-Eval dev rows found: {len(rows)}")
    print(f"Calibration rows selected: {len(selected)} from {len(counts)} subjects")
    return Dataset.from_list([{"text": row["text"]} for row in selected])


def copy_supporting_files(source: Path, output: Path) -> None:
    excluded = {"config.json", "model.safetensors.index.json"}
    for item in source.iterdir():
        if item.is_dir() or item.name in excluded or item.suffix == ".safetensors":
            continue
        target = output / item.name
        if not target.exists():
            shutil.copy2(item, target)


def main() -> None:
    args = parse_args()
    source = args.model.resolve()
    output = args.output.resolve()
    ceval_zip = args.ceval_zip.resolve()

    if not source.is_dir() or not (source / "config.json").is_file():
        raise SystemExit(f"Invalid source checkpoint: {source}")
    if not ceval_zip.is_file():
        raise SystemExit(f"Missing C-Eval ZIP: {ceval_zip}")
    if output.exists():
        raise SystemExit(
            f"Output already exists; refusing to overwrite it: {output}\n"
            "Choose a new --output path or inspect/remove the old output manually."
        )

    print(f"Source: {source}")
    print(f"Output: {output}")
    print(f"Calibration ZIP: {ceval_zip}")
    print("Scheme: W4A16_ASYM (INT4 group-128 weights, BF16 activations)")
    print("Algorithm: AWQ PTQ, no training or gradients")
    calibration = load_ceval_dev(ceval_zip, args.samples, args.seed)

    restore_qwen35_gated_delta_net_signature()
    print("Loading BF16 source checkpoint on CPU...")
    tokenizer = AutoTokenizer.from_pretrained(source)
    model = AutoModelForImageTextToText.from_pretrained(
        source,
        dtype=torch.bfloat16,
        device_map="cpu",
        low_cpu_mem_usage=True,
    )
    model.eval()

    recipe = [
        AWQModifier(
            duo_scaling=True,
            n_grid=20,
            offload_device=torch.device("cpu"),
        ),
        QuantizationModifier(
            targets=["Linear"],
            scheme="W4A16_ASYM",
            ignore=IGNORE,
        ),
    ]

    print("Starting sequential AWQ calibration and INT4 packing...")
    oneshot(
        model=model,
        tokenizer=tokenizer,
        dataset=calibration,
        recipe=recipe,
        output_dir=output,
        num_calibration_samples=args.samples,
        max_seq_length=args.max_seq_length,
        batch_size=1,
        shuffle_calibration_samples=False,
        pipeline="sequential",
        sequential_targets=["Qwen3_5DecoderLayer"],
        sequential_offload_device="cpu",
        save_compressed=True,
    )
    copy_supporting_files(source, output)
    print(f"Completed: {output}")


if __name__ == "__main__":
    main()
