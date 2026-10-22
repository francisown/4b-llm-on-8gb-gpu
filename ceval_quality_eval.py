"""Prepare and run a reproducible C-Eval validation-set quality benchmark.

The INT4-AWQ calibration used C-Eval *dev*. This evaluator deliberately uses
the disjoint *val* split so the reported quality is not measured on calibration
examples. The prepared manifest freezes the exact 200 questions for every
model configuration.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import time
from typing import Any
import urllib.error
import urllib.request
import zipfile


DEFAULT_ZIP = Path(os.environ.get("CEVAL_ZIP", "/mnt/e/AI-Inference-Lab/datasets/ceval.zip"))
DEFAULT_MANIFEST = Path("benchmark/eval/ceval-val-200.json")
CHOICES = ("A", "B", "C", "D")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_ceval_split(zip_path: Path, split: str) -> dict[str, list[dict[str, str]]]:
    if split not in {"dev", "val", "test"}:
        raise ValueError(f"unsupported split: {split}")
    grouped: dict[str, list[dict[str, str]]] = {}
    marker = f"/{split}/"
    suffix = f"_{split}.csv"
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if marker in name and name.endswith(suffix)
        )
        for name in names:
            subject = Path(name).stem.removesuffix(f"_{split}")
            with archive.open(name) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))
                rows: list[dict[str, str]] = []
                for row in reader:
                    answer = (row.get("answer") or "").strip().upper()
                    if split != "test" and answer not in CHOICES:
                        raise ValueError(f"invalid answer in {name}: {answer!r}")
                    rows.append(
                        {
                            "id": (row.get("id") or str(len(rows))).strip(),
                            "question": (row.get("question") or "").strip(),
                            **{
                                choice: (row.get(choice) or "").strip()
                                for choice in CHOICES
                            },
                            "answer": answer,
                        }
                    )
                grouped[subject] = rows
    if not grouped:
        raise ValueError(f"no C-Eval {split} CSV files found in {zip_path}")
    return grouped


def select_stratified_cases(
    grouped: dict[str, list[dict[str, str]]],
    samples: int,
    seed: int,
) -> list[dict[str, str]]:
    subjects = sorted(grouped)
    if samples < len(subjects):
        raise ValueError("samples must be at least the number of subjects")
    if samples > sum(len(rows) for rows in grouped.values()):
        raise ValueError("samples exceeds available rows")

    base, remainder = divmod(samples, len(subjects))
    if any(len(grouped[subject]) < base + (1 if remainder else 0) for subject in subjects):
        raise ValueError("a subject has too few rows for balanced sampling")

    rng = random.Random(seed)
    extra_subjects = set(rng.sample(subjects, remainder))
    selected: list[dict[str, str]] = []
    for subject in subjects:
        quota = base + (1 if subject in extra_subjects else 0)
        rows = list(grouped[subject])
        rng.shuffle(rows)
        for row in rows[:quota]:
            selected.append(
                {
                    "case_id": f"{subject}:{row['id']}",
                    "subject": subject,
                    **row,
                }
            )
    rng.shuffle(selected)
    return selected


def prepare_manifest(zip_path: Path, output: Path, samples: int, seed: int) -> dict[str, Any]:
    grouped = load_ceval_split(zip_path, "val")
    cases = select_stratified_cases(grouped, samples=samples, seed=seed)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset": "C-Eval",
        "split": "val",
        "samples": len(cases),
        "subjects": len(grouped),
        "seed": seed,
        "source_zip_sha256": sha256_file(zip_path),
        "calibration_leakage_note": (
            "INT4-AWQ calibration used C-Eval dev; evaluation uses disjoint val."
        ),
        "cases": cases,
    }
    manifest["cases_sha256"] = sha256_json(cases)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_prompt(case: dict[str, str]) -> str:
    return (
        "请完成下面的单项选择题。只输出一个大写字母 A、B、C 或 D，"
        "不要解释，不要输出其他内容。\n\n"
        f"科目：{case['subject']}\n"
        f"题目：{case['question']}\n"
        f"A. {case['A']}\n"
        f"B. {case['B']}\n"
        f"C. {case['C']}\n"
        f"D. {case['D']}\n"
        "答案："
    )


def parse_prediction(text: str) -> str | None:
    cleaned = text.strip().upper()
    patterns = (
        r"^([ABCD])(?:\b|[.、。:：)])",
        r"(?:答案|选项)(?:是|为|：|:)?\s*([ABCD])(?:\b|[.、。:：)]|$)",
        r"(?<![A-Z])([ABCD])(?![A-Z])",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return match.group(1)
    return None


def request_chat(
    *,
    base_url: str,
    model: str,
    prompt: str,
    timeout: float,
) -> tuple[str, dict[str, int], float]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8,
        "temperature": 0,
        "seed": 42,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": "Bearer EMPTY",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    latency = time.perf_counter() - started
    answer = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return (
        answer,
        {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
        latency,
    )


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(results)
    valid = sum(result["prediction"] in CHOICES for result in results)
    correct = sum(bool(result["correct"]) for result in results)
    by_subject: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = by_subject.setdefault(
            result["subject"], {"attempted": 0, "valid": 0, "correct": 0}
        )
        bucket["attempted"] += 1
        bucket["valid"] += int(result["prediction"] in CHOICES)
        bucket["correct"] += int(result["correct"])
    return {
        "attempted": attempted,
        "valid_predictions": valid,
        "correct": correct,
        "accuracy": correct / attempted if attempted else 0.0,
        "invalid_prediction_rate": (attempted - valid) / attempted if attempted else 0.0,
        "mean_latency_seconds": (
            sum(float(result["latency_seconds"]) for result in results) / attempted
            if attempted
            else 0.0
        ),
        "by_subject": by_subject,
    }


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def run_evaluation(args: argparse.Namespace) -> None:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = manifest["cases"][: args.limit or None]
    report: dict[str, Any] = {
        "schema_version": 1,
        "label": args.label,
        "model": args.model,
        "base_url": args.base_url,
        "manifest": str(args.manifest),
        "cases_sha256": manifest["cases_sha256"],
        "results": [],
    }
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text(encoding="utf-8"))
        if report.get("cases_sha256") != manifest["cases_sha256"]:
            raise ValueError("existing report uses a different manifest")

    completed = {result["case_id"] for result in report["results"]}
    for index, case in enumerate(cases, 1):
        if case["case_id"] in completed:
            continue
        answer, usage, latency = request_chat(
            base_url=args.base_url,
            model=args.model,
            prompt=build_prompt(case),
            timeout=args.timeout,
        )
        prediction = parse_prediction(answer)
        result = {
            "case_id": case["case_id"],
            "subject": case["subject"],
            "expected": case["answer"],
            "prediction": prediction,
            "correct": prediction == case["answer"],
            "raw_answer": answer,
            "latency_seconds": round(latency, 6),
            "usage": usage,
        }
        report["results"].append(result)
        report["summary"] = summarize(report["results"])
        atomic_write_json(args.output, report)
        mark = "OK" if result["correct"] else "FAIL"
        print(
            f"[{index:03d}/{len(cases)}] {mark:4s} {case['case_id']:<40s} "
            f"expected={case['answer']} predicted={prediction or '-'}"
        )
    report["summary"] = summarize(report["results"])
    atomic_write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved: {args.output}")


def run_local_evaluation(args: argparse.Namespace) -> None:
    """Evaluate a checkpoint through Transformers with GPU/CPU layer placement.

    This path exists for the BF16 reference, whose 8.7 GiB checkpoint cannot
    reside completely on the 8 GiB test GPU.  Its latency is therefore not
    comparable with the GPU-resident quantized vLLM services.
    """
    import torch
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = manifest["cases"][: args.limit or None]
    report: dict[str, Any] = {
        "schema_version": 1,
        "label": args.label,
        "model": str(args.model_path),
        "backend": "transformers-device-map-auto",
        "gpu_memory_limit": args.gpu_memory,
        "cpu_memory_limit": args.cpu_memory,
        "batch_size": args.batch_size,
        "latency_comparable": False,
        "manifest": str(args.manifest),
        "cases_sha256": manifest["cases_sha256"],
        "results": [],
    }
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text(encoding="utf-8"))
        if report.get("cases_sha256") != manifest["cases_sha256"]:
            raise ValueError("existing report uses a different manifest")

    print(f"Loading local reference: {args.model_path}")
    print(f"Device map limits: GPU={args.gpu_memory}, CPU={args.cpu_memory}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_path)
    model = AutoModelForImageTextToText.from_pretrained(
        args.model_path,
        dtype=torch.bfloat16,
        device_map="auto",
        max_memory={0: args.gpu_memory, "cpu": args.cpu_memory},
        low_cpu_mem_usage=True,
    )
    model.eval()
    input_device = model.get_input_embeddings().weight.device
    print(f"Input embedding device: {input_device}")

    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    tokenizer.padding_side = "left"

    completed = {result["case_id"] for result in report["results"]}
    pending = [(index, case) for index, case in enumerate(cases, 1)
               if case["case_id"] not in completed]
    for offset in range(0, len(pending), args.batch_size):
        batch = pending[offset : offset + args.batch_size]
        encoded = tokenizer.apply_chat_template(
            [[{"role": "user", "content": build_prompt(case)}] for _, case in batch],
            tokenize=True,
            add_generation_prompt=True,
            padding=True,
            return_tensors="pt",
            return_dict=True,
            enable_thinking=False,
        )
        encoded = {key: value.to(input_device) for key, value in encoded.items()}
        input_width = int(encoded["input_ids"].shape[1])
        prompt_lengths = encoded["attention_mask"].sum(dim=1).tolist()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=8,
                pad_token_id=tokenizer.eos_token_id,
            )
        batch_latency = time.perf_counter() - started
        for row, ((index, case), prompt_length) in enumerate(zip(batch, prompt_lengths)):
            new_tokens = generated[row, input_width:]
            answer = tokenizer.decode(new_tokens, skip_special_tokens=True)
            prediction = parse_prediction(answer)
            result = {
                "case_id": case["case_id"],
                "subject": case["subject"],
                "expected": case["answer"],
                "prediction": prediction,
                "correct": prediction == case["answer"],
                "raw_answer": answer,
                "latency_seconds": round(batch_latency / len(batch), 6),
                "batch_latency_seconds": round(batch_latency, 6),
                "usage": {
                    "prompt_tokens": int(prompt_length),
                    "completion_tokens": int(new_tokens.shape[0]),
                    "total_tokens": int(prompt_length) + int(new_tokens.shape[0]),
                },
            }
            report["results"].append(result)
            mark = "OK" if result["correct"] else "FAIL"
            print(
                f"[{index:03d}/{len(cases)}] {mark:4s} {case['case_id']:<40s} "
                f"expected={case['answer']} predicted={prediction or '-'}",
                flush=True,
            )
        report["summary"] = summarize(report["results"])
        atomic_write_json(args.output, report)
    report["summary"] = summarize(report["results"])
    atomic_write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved: {args.output}")


def compare_reports(paths: list[Path]) -> None:
    print("label\tmodel\tattempted\tcorrect\taccuracy\tinvalid_rate\tmean_latency_s")
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        summary = report["summary"]
        print(
            f"{report['label']}\t{report['model']}\t{summary['attempted']}\t"
            f"{summary['correct']}\t{summary['accuracy']:.4f}\t"
            f"{summary['invalid_prediction_rate']:.4f}\t"
            f"{summary['mean_latency_seconds']:.4f}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--ceval-zip", type=Path, default=DEFAULT_ZIP)
    prepare.add_argument("--output", type=Path, default=DEFAULT_MANIFEST)
    prepare.add_argument("--samples", type=int, default=200)
    prepare.add_argument("--seed", type=int, default=20260920)

    run = subparsers.add_parser("run")
    run.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    run.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    run.add_argument("--model", required=True)
    run.add_argument("--label", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--resume", action="store_true")

    run_local = subparsers.add_parser("run-local")
    run_local.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    run_local.add_argument("--model-path", type=Path, required=True)
    run_local.add_argument("--label", required=True)
    run_local.add_argument("--output", type=Path, required=True)
    run_local.add_argument("--gpu-memory", default="5GiB")
    run_local.add_argument("--cpu-memory", default="12GiB")
    run_local.add_argument("--batch-size", type=int, default=1)
    run_local.add_argument("--limit", type=int, default=0)
    run_local.add_argument("--resume", action="store_true")

    compare = subparsers.add_parser("compare")
    compare.add_argument("reports", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        manifest = prepare_manifest(
            args.ceval_zip.resolve(), args.output, args.samples, args.seed
        )
        print(
            f"Prepared {manifest['samples']} validation questions from "
            f"{manifest['subjects']} subjects."
        )
        print(f"Cases SHA256: {manifest['cases_sha256']}")
        print(f"Saved: {args.output}")
    elif args.command == "run":
        run_evaluation(args)
    elif args.command == "run-local":
        run_local_evaluation(args)
    else:
        compare_reports(args.reports)


if __name__ == "__main__":
    main()
