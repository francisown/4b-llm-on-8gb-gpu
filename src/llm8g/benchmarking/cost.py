"""Estimate inference capacity cost from measured token throughput.

This intentionally uses a small, explicit model rather than pretending to be
an accounting system. It supports either a cloud GPU hourly price or a local
hardware amortization estimate. Network, storage, engineering labour, taxes,
and model-provider margins are outside the calculation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TOKENS_PER_MILLION = 1_000_000
HOURS_PER_YEAR = 365 * 24

__all__ = [
    "validate_positive",
    "validate_fraction",
    "tokens_per_hour",
    "cost_per_million",
    "local_hourly_cost",
    "throughput_from_benchmark",
    "calculate",
    "cli",
]


def validate_positive(name: str, value: float) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def validate_fraction(name: str, value: float) -> float:
    if not 0 < value <= 1:
        raise ValueError(f"{name} must be in the interval (0, 1]")
    return value


def tokens_per_hour(tokens_per_second: float) -> float:
    return validate_positive("tokens_per_second", tokens_per_second) * 3600


def cost_per_million(hourly_cost: float, tokens_per_second: float) -> float:
    validate_positive("hourly_cost", hourly_cost)
    return hourly_cost / tokens_per_hour(tokens_per_second) * TOKENS_PER_MILLION


def local_hourly_cost(
    *,
    hardware_price: float,
    lifetime_years: float,
    utilization: float,
    power_watts: float,
    electricity_price_per_kwh: float,
) -> dict[str, float]:
    validate_positive("hardware_price", hardware_price)
    validate_positive("lifetime_years", lifetime_years)
    validate_fraction("utilization", utilization)
    if power_watts < 0:
        raise ValueError("power_watts cannot be negative")
    if electricity_price_per_kwh < 0:
        raise ValueError("electricity_price_per_kwh cannot be negative")

    productive_hours = lifetime_years * HOURS_PER_YEAR * utilization
    amortization = hardware_price / productive_hours
    electricity = power_watts / 1000 * electricity_price_per_kwh
    return {
        "amortization_per_active_hour": amortization,
        "electricity_per_active_hour": electricity,
        "total_per_active_hour": amortization + electricity,
    }


def throughput_from_benchmark(path: Path, field: str) -> float:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    value: Any = data
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"field {field!r} was not found in {path}")
        value = value[part]
    if not isinstance(value, (int, float)):
        raise ValueError(f"field {field!r} must contain a number")
    return validate_positive(field, float(value))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    throughput = parser.add_mutually_exclusive_group(required=True)
    throughput.add_argument(
        "--tokens-per-second",
        type=float,
        help="Measured sustained token throughput for the workload being priced.",
    )
    throughput.add_argument(
        "--benchmark-json",
        type=Path,
        help="vLLM benchmark JSON containing the measured throughput.",
    )
    parser.add_argument(
        "--throughput-field",
        default="output_throughput",
        help="JSON field used with --benchmark-json; dotted paths are supported.",
    )

    pricing = parser.add_mutually_exclusive_group(required=True)
    pricing.add_argument(
        "--gpu-hour-price",
        type=float,
        help="Cloud/server cost for one GPU hour.",
    )
    pricing.add_argument(
        "--hardware-price",
        type=float,
        help="Local machine purchase price for amortization mode.",
    )
    parser.add_argument("--lifetime-years", type=float, default=3.0)
    parser.add_argument(
        "--utilization",
        type=float,
        default=0.5,
        help="Fraction of lifetime hours doing useful inference, from 0 to 1.",
    )
    parser.add_argument(
        "--power-watts",
        type=float,
        default=0.0,
        help="Whole-system wall power while serving, not GPU TDP alone.",
    )
    parser.add_argument(
        "--electricity-price-per-kwh",
        type=float,
        default=0.0,
    )
    parser.add_argument("--currency", default="CNY")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def calculate(args: argparse.Namespace) -> dict[str, Any]:
    if args.benchmark_json is not None:
        throughput = throughput_from_benchmark(
            args.benchmark_json.resolve(), args.throughput_field
        )
        throughput_source = str(args.benchmark_json)
    else:
        throughput = validate_positive(
            "tokens_per_second", float(args.tokens_per_second)
        )
        throughput_source = "command line"

    if args.gpu_hour_price is not None:
        hourly_cost = validate_positive("gpu_hour_price", args.gpu_hour_price)
        cost_mode = "cloud_hourly_price"
        breakdown: dict[str, float] = {"gpu_hour_price": hourly_cost}
    else:
        breakdown = local_hourly_cost(
            hardware_price=args.hardware_price,
            lifetime_years=args.lifetime_years,
            utilization=args.utilization,
            power_watts=args.power_watts,
            electricity_price_per_kwh=args.electricity_price_per_kwh,
        )
        hourly_cost = breakdown["total_per_active_hour"]
        cost_mode = "local_amortization"

    return {
        "currency": args.currency,
        "cost_mode": cost_mode,
        "throughput_source": throughput_source,
        "tokens_per_second": throughput,
        "tokens_per_hour": tokens_per_hour(throughput),
        "hourly_cost": hourly_cost,
        "cost_per_million_tokens": cost_per_million(hourly_cost, throughput),
        "cost_breakdown": breakdown,
        "scope_note": (
            "Capacity estimate based on measured sustained throughput. "
            "It excludes idle gaps, prompt/output price differences, network, "
            "storage, labour, tax, and redundancy unless included in hourly cost."
        ),
    }


def cli() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = calculate(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    currency = result["currency"]
    print("===== Inference capacity cost estimate =====")
    print(f"Mode:                    {result['cost_mode']}")
    print(f"Measured throughput:     {result['tokens_per_second']:.2f} tokens/s")
    print(f"Hourly token capacity:   {result['tokens_per_hour']:,.0f} tokens")
    print(f"Estimated hourly cost:   {result['hourly_cost']:.4f} {currency}")
    print(
        "Cost per 1M tokens:     "
        f"{result['cost_per_million_tokens']:.4f} {currency}"
    )
    if result["cost_mode"] == "local_amortization":
        detail = result["cost_breakdown"]
        print(
            "  Hardware amortization: "
            f"{detail['amortization_per_active_hour']:.4f} {currency}/active hour"
        )
        print(
            "  Electricity:            "
            f"{detail['electricity_per_active_hour']:.4f} {currency}/active hour"
        )
    print("Note: " + result["scope_note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
