import csv
import tempfile
import unittest
from pathlib import Path

from quant.csv_loader import load_panel
from quant.evaluate import ic_series
from quant.factors import momentum_score, value_score
from quant.panel import Panel
from quant.synthetic import SyntheticConfig, generate_panel


class QuantFactorTests(unittest.TestCase):
    def test_momentum_does_not_use_future_prices(self):
        panel = generate_panel(SyntheticConfig(seed=3, years=2, n_symbols=25))
        t = 400
        before = momentum_score(panel, t)
        panel.close[panel.symbols[0]][t + 1] = 999999.0
        after = momentum_score(panel, t)
        self.assertEqual(before, after)

    def test_value_ignores_unpublished_report(self):
        panel = generate_panel(SyntheticConfig(seed=4, years=2, n_symbols=25))
        t = 400
        symbol = panel.symbols[0]
        records = panel.fundamentals[symbol]
        self.assertTrue(records)
        known = panel.fundamental_asof(symbol, t)
        self.assertIsNotNone(known)
        self.assertLessEqual(known.publish_date, panel.dates[t - 1])
        values = value_score(panel, t)
        self.assertIn(symbol, values)

    def test_perfect_rank_ic(self):
        symbols = [f"T{index:02d}" for index in range(20)]
        dates = ["2024-01-02", "2024-01-03"]
        scores = {symbol: index / 20.0 for index, symbol in enumerate(symbols)}
        close = {}
        volume = {}
        cap = {}
        for symbol in symbols:
            close[symbol] = [100.0, 100.0 * (1.0 + scores[symbol] * 0.1)]
            volume[symbol] = [1000.0, 1000.0]
            cap[symbol] = [1e9, 1e9]
        panel = Panel(
            dates=dates,
            symbols=symbols,
            close=close,
            volume=volume,
            market_cap=cap,
            industry={symbol: "Technology" for symbol in symbols},
        )
        prepared = {0: {"scores": {"test": scores}}}
        series = ic_series(panel, prepared, "test", min_names=15)
        self.assertEqual(len(series), 1)
        self.assertAlmostEqual(series[0]["ic"], 1.0, places=9)

    def test_csv_loader_keeps_missing_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prices.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["date", "symbol", "close", "volume", "market_cap", "industry"])
                writer.writerow(["2024-01-02", "AAA", "10", "1000", "1000000", "Tech"])
                writer.writerow(["2024-01-02", "BBB", "20", "2000", "3000000", "Health"])
                writer.writerow(["2024-01-03", "AAA", "", "0", "1000000", "Tech"])
                writer.writerow(["2024-01-03", "BBB", "21", "2500", "3100000", "Health"])
            panel = load_panel(path)
            self.assertEqual(panel.dates, ["2024-01-02", "2024-01-03"])
            self.assertIsNone(panel.close["AAA"][1])
            self.assertEqual(panel.industry["BBB"], "Health")


if __name__ == "__main__":
    unittest.main()

