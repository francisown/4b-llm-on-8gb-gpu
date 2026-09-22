from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.cost_calculator import (  # noqa: E402
    cost_per_million,
    local_hourly_cost,
    throughput_from_benchmark,
    tokens_per_hour,
)


class CostCalculatorTests(unittest.TestCase):
    def test_cloud_cost_formula(self) -> None:
        self.assertEqual(tokens_per_hour(100), 360_000)
        self.assertAlmostEqual(cost_per_million(1.0, 100), 2.7777777778)

    def test_local_cost_combines_amortization_and_electricity(self) -> None:
        result = local_hourly_cost(
            hardware_price=8760,
            lifetime_years=2,
            utilization=0.5,
            power_watts=200,
            electricity_price_per_kwh=1.0,
        )
        self.assertAlmostEqual(result["amortization_per_active_hour"], 1.0)
        self.assertAlmostEqual(result["electricity_per_active_hour"], 0.2)
        self.assertAlmostEqual(result["total_per_active_hour"], 1.2)

    def test_reads_vllm_output_throughput(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(
                json.dumps({"output_throughput": 359.708557}), encoding="utf-8"
            )
            self.assertAlmostEqual(
                throughput_from_benchmark(path, "output_throughput"), 359.708557
            )

    def test_rejects_zero_throughput(self) -> None:
        with self.assertRaises(ValueError):
            cost_per_million(1.0, 0)

    def test_rejects_invalid_utilization(self) -> None:
        with self.assertRaises(ValueError):
            local_hourly_cost(
                hardware_price=1000,
                lifetime_years=3,
                utilization=1.1,
                power_watts=0,
                electricity_price_per_kwh=0,
            )


if __name__ == "__main__":
    unittest.main()
