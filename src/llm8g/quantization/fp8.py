"""Create a local FP8_BLOCK checkpoint from the Qwen3.5-4B BF16 model.

This script deliberately uses llm-compressor's model-free PTQ entrypoint so the
entire 4B model never has to fit in the RTX 5060's 8 GB VRAM at once.
It never modifies the source checkpoint and refuses to overwrite an output
directory that already exists.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from .models import ArtifactManifest


DEFAULT_MODEL = Path(os.environ.get("QWEN_BF16_DIR", "models/qwen3.5-4b"))
DEFAULT_OUTPUT = Path(
    os.environ.get(
        "QWEN_FP8_OUTPUT",
        "models/qwen3.5-4b-fp8-self-v3",
    )
)

# Qwen3.5 is a hybrid vision-language model. Keep the vision tower, embeddings,
# small linear-attention A/B projections, and the MTP fusion projection in BF16.
# Quantize the large fused linear-attention projections and ordinary MTP Linear
# layers; this matches the coverage of the working reference FP8 checkpoint.
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

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_OUTPUT",
    "IGNORE",
    "parse_args",
    "copy_supporting_files",
    "main",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--device",
        default="cpu",
        help="Use cpu by default because the BF16 checkpoint is larger than VRAM.",
    )
    return parser.parse_args()


def copy_supporting_files(source: Path, output: Path) -> None:
    """Copy tokenizer/processor assets not produced by model_free_ptq."""
    excluded = {"config.json", "model.safetensors.index.json"}
    for item in source.iterdir():
        if item.is_dir() or item.name in excluded or item.suffix == ".safetensors":
            continue
        target = output / item.name
        if not target.exists():
            shutil.copy2(item, target)


def main() -> None:
    args = parse_args()

    # Keep the heavyweight quantization stack out of module import so
    # ``--help`` and argument validation work on a CPU-only host.
    from llmcompressor import model_free_ptq  # type: ignore[import-not-found]

    source = args.model.resolve()
    output = args.output.resolve()

    if not source.is_dir():
        raise SystemExit(f"Source model directory does not exist: {source}")
    if not (source / "config.json").is_file():
        raise SystemExit(f"Missing config.json in source model: {source}")
    if output.exists():
        raise SystemExit(
            f"Output already exists; refusing to overwrite it: {output}\n"
            "Choose a new --output path or inspect/remove the old test output manually."
        )

    print(f"Source: {source}")
    print(f"Output: {output}")
    print(f"Device: {args.device}")
    print("Scheme: FP8_BLOCK (128x128 block-wise weights, dynamic activations)")
    print("Ignored modules:")
    for pattern in IGNORE:
        print(f"  - {pattern}")

    model_free_ptq(
        model_stub=source,
        save_directory=output,
        scheme="FP8_BLOCK",
        ignore=IGNORE,
        max_workers=1,
        device=args.device,
    )
    copy_supporting_files(source, output)
    ArtifactManifest.from_directory(
        output,
        name=output.name,
        source_model=source.name,
        algorithm="FP8_BLOCK",
        algorithm_version="llm-compressor 0.13.0",
    ).write(output / "artifact-manifest.json")
    print(f"Completed: {output}")


if __name__ == "__main__":
    main()
