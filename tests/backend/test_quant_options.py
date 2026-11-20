import math
import unittest

from quant.options import black_scholes, implied_vol, protective_put_overlay


class QuantOptionTests(unittest.TestCase):
    def test_put_call_parity(self):
        call = black_scholes(100, 105, 0.5, 0.04, 0.22, "call")
        put = black_scholes(100, 105, 0.5, 0.04, 0.22, "put")
        expected = 100 - 105 * math.exp(-0.04 * 0.5)
        self.assertAlmostEqual(call["price"] - put["price"], expected, places=9)

    def test_implied_vol_round_trip(self):
        price = black_scholes(100, 90, 0.25, 0.04, 0.27, "put")["price"]
        solved = implied_vol(price, 100, 90, 0.25, 0.04, "put")
        self.assertIsNotNone(solved)
        self.assertAlmostEqual(solved, 0.27, places=5)

    def test_greeks(self):
        put = black_scholes(100, 90, 0.25, 0.04, 0.2, "put")
        self.assertLess(put["delta"], 0)
        self.assertGreater(put["gamma"], 0)
        self.assertGreater(put["vega"], 0)
        self.assertLess(put["price"], 100)

    def test_hedge_caps_tail_loss(self):
        overlay = protective_put_overlay(
            portfolio_value=1_000_000,
            beta=1.0,
            vol=0.20,
            loss_cap=0.10,
            stress_move=-0.20,
        )
        self.assertGreater(overlay["hedge_notional"], 0)
        stress = {round(row["spot_shock"], 2): row for row in overlay["stress"]}
        self.assertLess(stress[-0.2]["hedged_pct"], 0)
        self.assertGreater(stress[-0.2]["hedged_pct"], -0.12)
        self.assertGreater(stress[-0.2]["hedged_pct"], stress[-0.2]["unhedged_pct"])
        for row in overlay["greeks_matrix"]["rows"]:
            self.assertEqual(len(row["values"]), len(overlay["greeks_matrix"]["vols"]))
            for value in row["values"]:
                self.assertTrue(math.isfinite(value))


if __name__ == "__main__":
    unittest.main()

