"""Offline checks: execution mechanics and the retained historical CSV."""
import csv
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import quantihack_alt_data_50 as engine


class ExecutionChecks(unittest.TestCase):
    def setUp(self):
        self.index = pd.date_range("2020-01-01", periods=4)
        self.prices = pd.Series([100, 110, 121, 121], index=self.index)

    def test_single_positions_take_effect_on_next_bar(self):
        positions = pd.Series([0, 1, 0, 0], index=self.index)
        equity = engine.bt_single(positions, self.prices, capital=100, slip=0)
        np.testing.assert_allclose(equity, [100, 100, 110, 110])

    def test_cost_is_applied_on_each_signal_change(self):
        positions = pd.Series([0, 1, 0, 0], index=self.index)
        equity = engine.bt_single(positions, self.prices, capital=100, slip=10)
        expected = 100 * np.cumprod([1, 0.999, 1.099, 1])
        np.testing.assert_allclose(equity, expected)

    def test_multi_asset_weights_are_lagged(self):
        weights = pd.DataFrame({"A": [0, 1, 0, 0], "B": [0, 0, 1, 0]}, index=self.index)
        prices = pd.DataFrame({"A": self.prices, "B": [100, 100, 100, 110]}, index=self.index)
        equity = engine.bt_multi(weights, prices, capital=100, slip=0)
        np.testing.assert_allclose(equity, [100, 100, 110, 121])

    def test_zero_exposure_does_not_trade(self):
        equity = engine.bt_single(pd.Series(0, index=self.index), self.prices)
        np.testing.assert_allclose(equity, engine.CAP)

    def test_local_ohlcv_schema_loads_without_requesting_prices(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            path.write_text("date,open,high,low,close,volume\n2020-01-02,100,110,90,105,200\n")
            with patch.object(engine.yf, "download", side_effect=AssertionError("unexpected network")):
                frame = engine.load_ibkr(path)
            self.assertEqual(list(frame.columns), ["Open", "High", "Low", "Close", "Volume"])
            self.assertEqual(frame.iloc[0]["Close"], 105)

    def test_archived_counts_and_combined_rank_match_readme(self):
        with (ROOT / "quantihack_alt_data_50_results.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 50)
        self.assertEqual(sum(float(r["wf1_sharpe"]) > 0 for r in rows), 39)
        self.assertEqual(sum(float(r["wf2_ret"]) > 0 for r in rows), 12)
        self.assertEqual(sum(float(r["wf1_sharpe"]) > 0 and float(r["wf2_ret"]) > 0 for r in rows), 11)
        for row in rows:
            self.assertAlmostEqual(float(row["combined_rank"]),
                                   (float(row["wf1_rank"]) + float(row["wf2_rank"])) / 2)


if __name__ == "__main__":
    unittest.main()
