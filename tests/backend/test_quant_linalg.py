import math
import random
import unittest

from quant.evaluate import performance
from quant.linalg import condition_number, correlation, ols, pearson, spearman
from quant.preprocess import orthogonalize_symmetric, robust_z, winsorize_mad


class QuantLinearAlgebraTests(unittest.TestCase):
    def test_ols_recovers_linear_model(self):
        rng = random.Random(7)
        rows = [[1.0, rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(300)]
        y = [1.5 + 2.2 * row[1] - 0.7 * row[2] + rng.gauss(0, 0.05) for row in rows]
        fit = ols(rows, y)
        self.assertAlmostEqual(fit["beta"][0], 1.5, delta=0.03)
        self.assertAlmostEqual(fit["beta"][1], 2.2, delta=0.03)
        self.assertAlmostEqual(fit["beta"][2], -0.7, delta=0.03)
        self.assertGreater(fit["r2"], 0.99)

    def test_rank_correlation(self):
        x = [1, 2, 3, 4, 5]
        y = [10, 20, 30, 40, 50]
        self.assertAlmostEqual(spearman(x, y), 1.0)
        self.assertAlmostEqual(pearson(x, y), 1.0)

    def test_winsorize_and_robust_z(self):
        values = [0.0] * 20 + [1000.0]
        clipped = winsorize_mad(values, k=3)
        self.assertLess(max(clipped), 1000)
        z = robust_z(values)
        self.assertLess(max(abs(value) for value in z), 5.0)

    def test_symmetric_orthogonalization(self):
        rng = random.Random(11)
        symbols = [f"S{index:03d}" for index in range(80)]
        latent = [[rng.gauss(0, 1) for _ in range(3)] for _ in symbols]
        score_map = {}
        for index, key in enumerate(("a", "b", "c", "d", "e")):
            values = [
                latent[i][index % 3] * (1.5 if index < 3 else 0.8) + rng.gauss(0, 0.6)
                for i in range(len(symbols))
            ]
            score_map[key] = dict(zip(symbols, values))
        result = orthogonalize_symmetric(score_map, list(score_map), shrink=0.0)
        self.assertFalse(result["skipped"])
        rows = [[result["scores"][key][symbol] for key in result["keys"]] for symbol in symbols]
        corr = correlation(rows)
        offdiag = max(abs(corr[i][j]) for i in range(len(corr)) for j in range(i + 1, len(corr)))
        self.assertLess(offdiag, 0.02)
        self.assertLess(condition_number(corr), 1.02)
        self.assertLess(result["max_offdiag_after"], 0.01)
        self.assertGreater(result["max_offdiag_before"], 0.3)

    def test_performance_max_drawdown(self):
        points = [("2024-01-02", 0.10), ("2024-01-03", -0.20), ("2024-01-04", 0.05)]
        metrics = performance(points)
        self.assertAlmostEqual(metrics["max_drawdown"], -0.20)
        self.assertLess(metrics["cagr"], 0.0)
        self.assertTrue(math.isfinite(metrics["sharpe"]))


if __name__ == "__main__":
    unittest.main()

