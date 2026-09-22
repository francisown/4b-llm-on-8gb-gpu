"""Small, deterministic quality regression suite for local vLLM checkpoints.

This is not a general intelligence benchmark.  It is a reproducible smoke test
for comparing quantized checkpoints with the same tokenizer and chat template.
It intentionally uses local, deterministic questions so it works offline.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    prompt: str
    answers: tuple[str, ...]
    strict: bool = False


def long_context_case(case_id: str, target: int, answer: str) -> Case:
    rows = []
    for index in range(1, 121):
        if index == target:
            rows.append(f"第{index:03d}条记录：项目密钥为 {answer}。")
        else:
            rows.append(f"第{index:03d}条记录：本条是普通设备巡检记录，状态正常。")
    prompt = (
        "阅读下面的记录，只输出指定编号记录里的项目密钥，不要解释。\n"
        + "\n".join(rows)
        + f"\n问题：第{target:03d}条记录中的项目密钥是什么？"
    )
    return Case(case_id, "long_context", prompt, (answer,), strict=True)


CASES: tuple[Case, ...] = (
    Case("math_01", "math", "计算 17×23。只输出阿拉伯数字。", ("391",), True),
    Case("math_02", "math", "计算 96÷8+7×5。只输出阿拉伯数字。", ("47",), True),
    Case("math_03", "math", "240 的 15% 是多少？只输出阿拉伯数字。", ("36",), True),
    Case("math_04", "math", "数列 2, 6, 12, 20 的下一项是什么？只输出数字。", ("30",), True),
    Case("math_05", "math", "84 和 126 的最大公约数是多少？只输出数字。", ("42",), True),
    Case("math_06", "math", "二进制 101101 转成十进制是多少？只输出数字。", ("45",), True),
    Case("math_07", "math", "解方程 3x+7=34。只输出 x 的数值。", ("9",), True),
    Case("math_08", "math", "某商品 80 元，先涨价 25%，再降价 20%，最终多少元？只输出数字。", ("80",), True),
    Case(
        "logic_01",
        "logic",
        "所有玫瑰都是花；有些花会凋谢。能否必然推出有些玫瑰会凋谢？只回答“能”或“不能”。",
        ("不能",),
        True,
    ),
    Case(
        "logic_02",
        "logic",
        "所有 A 都是 B，所有 B 都是 C。能否必然推出所有 A 都是 C？只回答“能”或“不能”。",
        ("能",),
        True,
    ),
    Case(
        "logic_03",
        "logic",
        "没有程序员是粗心的；小李是程序员。能否推出小李不粗心？只回答“能”或“不能”。",
        ("能",),
        True,
    ),
    Case(
        "logic_04",
        "logic",
        "命题 A 与命题 B 恰有一个为真，已知 A 为假。B 是真还是假？只回答“真”或“假”。",
        ("真",),
        True,
    ),
    Case(
        "logic_05",
        "logic",
        "若 P 则 Q；现在已知 Q 为假。能否推出 P 为假？只回答“能”或“不能”。",
        ("能",),
        True,
    ),
    Case("logic_06", "logic", "找规律：1,4,2,8,3,12，下一项是什么？只输出数字。", ("4",), True),
    Case(
        "format_01",
        "instruction",
        "把颜色=蓝色、形状=圆形、数量=7 按照 颜色|形状|数量 输出。只能输出结果。",
        ("蓝色|圆形|7",),
        True,
    ),
    Case("format_02", "instruction", "将 9,2,11,2 从小到大排序，用英文逗号连接，只输出结果。", ("2,2,9,11",), True),
    Case("format_03", "instruction", "把“推理工程”四个汉字倒序，只输出结果。", ("程工理推",), True),
    Case(
        "format_04",
        "instruction",
        "只输出一行合法 JSON，键依次为 name 和 score，值依次为 qwen 和 8。不要 Markdown。",
        ('{"name":"qwen","score":8}',),
        True,
    ),
    Case(
        "format_05",
        "instruction",
        "从文本“会议在2026-09-21举行，报名截止2026-09-18”提取日期，按时间升序用英文逗号连接。只输出结果。",
        ("2026-09-18,2026-09-21",),
        True,
    ),
    Case("format_06", "instruction", "删除句子“模型，已经启动！”中的全部标点。只输出结果。", ("模型已经启动",), True),
    Case(
        "code_01",
        "code",
        "Python 表达式 sum(range(5)) 的值是什么？只输出运行结果。",
        ("10",),
        True,
    ),
    Case(
        "code_02",
        "code",
        "Python 表达式 [x*x for x in range(1,6,2)] 的值是什么？只输出标准列表表示。",
        ("[1,9,25]", "[1, 9, 25]"),
        True,
    ),
    Case(
        "code_03",
        "code",
        "Python 表达式 len(set('banana')) 的值是什么？只输出数字。",
        ("3",),
        True,
    ),
    Case(
        "code_04",
        "code",
        "JavaScript 语句 console.log(1 + '2' + 3) 输出什么？只输出结果。",
        ("123",),
        True,
    ),
    Case(
        "code_05",
        "code",
        "一列数据依次是 1,NULL,2,NULL，SQL 的 COUNT(该列) 返回多少？只输出数字。",
        ("2",),
        True,
    ),
    Case(
        "code_06",
        "code",
        "在已排序数组中进行标准二分查找，时间复杂度是什么？只输出大 O 记号。",
        ("O(logn)", "O(log n)"),
        True,
    ),
    Case("fact_01", "knowledge", "水的化学式是什么？只输出化学式。", ("H2O", "H₂O"), True),
    Case("fact_02", "knowledge", "澳大利亚的首都是哪里？只输出中文城市名。", ("堪培拉",), True),
    Case("fact_03", "knowledge", "1 字节等于多少比特？只输出数字。", ("8",), True),
    Case("fact_04", "knowledge", "SHA-256 摘要长度是多少比特？只输出数字。", ("256",), True),
    long_context_case("context_01", 7, "AX-19-KQ"),
    long_context_case("context_02", 113, "M7-ZETA-42"),
)


def normalized(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = text.strip()
    text = text.replace("```json", "").replace("```", "")
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def score(case: Case, response: str) -> tuple[bool, bool]:
    cleaned = normalized(response)
    expected = tuple(normalized(value) for value in case.answers)
    strict_pass = cleaned in expected
    # Substring matching is useful for answers with a short explanation, but a
    # one-character Chinese answer such as “能” must not match “不能”.  Numeric
    # answers also need digit boundaries so “3” does not match “123”.
    relaxed_pass = strict_pass
    if not relaxed_pass:
        for value in expected:
            if not value:
                continue
            if value.isdigit():
                matched = re.search(rf"(?<!\d){re.escape(value)}(?!\d)", cleaned)
            elif len(value) == 1:
                matched = re.search(rf"(?:^|答案[:：]?){re.escape(value)}(?:[。.!！]?$)", cleaned)
            else:
                matched = value in cleaned
            if matched:
                relaxed_pass = True
                break
    return strict_pass, relaxed_pass


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def request_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def save_report(
    *,
    label: str,
    model: str,
    backend: str,
    max_tokens: int,
    started: float,
    results: list[dict[str, Any]],
    output: Path,
) -> None:
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_category[row["category"]].append(row)
    latencies = [row["latency_seconds"] for row in results]
    summary = {
        "cases": len(results),
        "strict_pass": sum(row["strict_pass"] for row in results),
        "relaxed_pass": sum(row["relaxed_pass"] for row in results),
        "strict_accuracy": sum(row["strict_pass"] for row in results) / len(results),
        "relaxed_accuracy": sum(row["relaxed_pass"] for row in results) / len(results),
        "latency_mean_seconds": statistics.fmean(latencies),
        "latency_p50_seconds": statistics.median(latencies),
        "latency_p95_seconds": percentile(latencies, 0.95),
        "by_category": {
            category: {
                "cases": len(rows),
                "strict_pass": sum(row["strict_pass"] for row in rows),
                "relaxed_pass": sum(row["relaxed_pass"] for row in rows),
            }
            for category, rows in sorted(by_category.items())
        },
    }
    report = {
        "schema_version": 1,
        "label": label,
        "model": model,
        "backend": backend,
        "temperature": 0,
        "max_tokens": max_tokens,
        "started_at_unix": started,
        "summary": summary,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


def run(args: argparse.Namespace) -> None:
    endpoint = args.base_url.rstrip("/") + "/chat/completions"
    results = []
    started = time.time()
    for index, case in enumerate(CASES, 1):
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": case.prompt}],
            "temperature": 0,
            "max_tokens": args.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        t0 = time.perf_counter()
        data = request_json(endpoint, payload, args.timeout)
        latency = time.perf_counter() - t0
        answer = data["choices"][0]["message"].get("content") or ""
        strict_pass, relaxed_pass = score(case, answer)
        usage = data.get("usage") or {}
        row = {
            "case_id": case.case_id,
            "category": case.category,
            "expected": list(case.answers),
            "response": answer,
            "strict_pass": strict_pass,
            "relaxed_pass": relaxed_pass,
            "latency_seconds": round(latency, 6),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }
        results.append(row)
        mark = "PASS" if strict_pass else ("SOFT" if relaxed_pass else "FAIL")
        print(f"[{index:02d}/{len(CASES)}] {mark:4s} {case.case_id:12s} {latency:6.2f}s  {answer[:70]!r}")

    save_report(
        label=args.label,
        model=args.model,
        backend=args.base_url,
        max_tokens=args.max_tokens,
        started=started,
        results=results,
        output=args.output,
    )


def run_local(args: argparse.Namespace) -> None:
    """Evaluate an unquantized local checkpoint without starting vLLM."""
    import torch
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    started = time.time()
    print(f"Loading local BF16 reference: {args.model_path}")
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

    selected_cases = CASES[: args.limit] if args.limit else CASES
    results = []
    for index, case in enumerate(selected_cases, 1):
        messages = [{"role": "user", "content": case.prompt}]
        encoded = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
            enable_thinking=False,
        )
        encoded = {key: value.to(input_device) for key, value in encoded.items()}
        input_length = encoded["input_ids"].shape[1]
        t0 = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=args.max_tokens,
                pad_token_id=tokenizer.eos_token_id,
            )
        latency = time.perf_counter() - t0
        new_tokens = generated[0, input_length:]
        answer = tokenizer.decode(new_tokens, skip_special_tokens=True)
        strict_pass, relaxed_pass = score(case, answer)
        row = {
            "case_id": case.case_id,
            "category": case.category,
            "expected": list(case.answers),
            "response": answer,
            "strict_pass": strict_pass,
            "relaxed_pass": relaxed_pass,
            "latency_seconds": round(latency, 6),
            "prompt_tokens": input_length,
            "completion_tokens": int(new_tokens.shape[0]),
        }
        results.append(row)
        mark = "PASS" if strict_pass else ("SOFT" if relaxed_pass else "FAIL")
        print(
            f"[{index:02d}/{len(selected_cases)}] {mark:4s} {case.case_id:12s} "
            f"{latency:6.2f}s  {answer[:70]!r}",
            flush=True,
        )

    save_report(
        label=args.label,
        model=str(args.model_path),
        backend="transformers-device-map-auto",
        max_tokens=args.max_tokens,
        started=started,
        results=results,
        output=args.output,
    )


def compare(args: argparse.Namespace) -> None:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    print("label\tstrict\trelaxed\tmean_latency_s\tp95_latency_s")
    for report in reports:
        summary = report["summary"]
        print(
            f"{report['label']}\t"
            f"{summary['strict_pass']}/{summary['cases']}\t"
            f"{summary['relaxed_pass']}/{summary['cases']}\t"
            f"{summary['latency_mean_seconds']:.3f}\t"
            f"{summary['latency_p95_seconds']:.3f}"
        )
    if len(reports) == 2:
        left = {row["case_id"]: row for row in reports[0]["results"]}
        right = {row["case_id"]: row for row in reports[1]["results"]}
        print("\nCases with different strict results")
        changed = 0
        for case_id in sorted(left.keys() & right.keys()):
            if left[case_id]["strict_pass"] != right[case_id]["strict_pass"]:
                changed += 1
                print(f"- {case_id}: {reports[0]['label']}={left[case_id]['strict_pass']}, "
                      f"{reports[1]['label']}={right[case_id]['strict_pass']}")
        if not changed:
            print("- none")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run all cases against a vLLM endpoint")
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--label", required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--max-tokens", type=int, default=96)
    run_parser.add_argument("--timeout", type=float, default=120.0)
    run_parser.set_defaults(func=run)

    local_parser = subparsers.add_parser(
        "run-local", help="run against a local BF16 checkpoint with Transformers"
    )
    local_parser.add_argument("--model-path", type=Path, required=True)
    local_parser.add_argument("--label", required=True)
    local_parser.add_argument("--output", type=Path, required=True)
    local_parser.add_argument("--max-tokens", type=int, default=96)
    local_parser.add_argument("--gpu-memory", default="5GiB")
    local_parser.add_argument("--cpu-memory", default="12GiB")
    local_parser.add_argument("--limit", type=int, default=0)
    local_parser.set_defaults(func=run_local)

    compare_parser = subparsers.add_parser("compare", help="compare saved JSON reports")
    compare_parser.add_argument("reports", nargs="+", type=Path)
    compare_parser.set_defaults(func=compare)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
