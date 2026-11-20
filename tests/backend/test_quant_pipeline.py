import json
import tempfile
import unittest
from pathlib import Path

from quant.pipeline import RunConfig, run


class QuantPipelineTests(unittest.TestCase):
    def test_small_demo_writes_report_and_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run(
                RunConfig(
                    seed=5,
                    years=2,
                    n_symbols=30,
                    out_dir=folder,
                    verbose=False,
                )
            )
            summary = result["summary"]
            self.assertTrue(Path(folder, "index.html").exists())
            self.assertTrue(Path(folder, "summary.json").exists())
            self.assertTrue(Path(folder, "factor_ic.csv").exists())
            self.assertTrue(Path(folder, "equity_curve.csv").exists())
            self.assertEqual(summary["meta"]["data_kind"], "synthetic")
            self.assertGreater(len(summary["factors"]), 3)
            self.assertGreater(len(summary["backtest"]["equity"]["adaptive"]), 100)
            self.assertTrue(summary["risk"]["ok"])
            self.assertLessEqual(summary["backtest"]["adaptive"]["metrics"]["average_gross"], 1.0001)
            self.assertLessEqual(summary["backtest"]["long_short"]["metrics"]["average_gross"], 1.2001)
            html = Path(folder, "index.html").read_text(encoding="utf-8")
            self.assertIn("合成数据", html)
            self.assertIn("纯因子多空", html)
            loaded = json.loads(Path(folder, "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded["meta"]["data_kind"], "synthetic")


if __name__ == "__main__":
    unittest.main()

