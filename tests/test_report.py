import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from report import generate, analyse, wilson  # noqa: E402


class TestReport(unittest.TestCase):
    def test_wilson_bounds(self):
        lo, hi = wilson(50, 100)
        self.assertTrue(0 < lo < 0.5 < hi < 1)
        self.assertAlmostEqual(lo, 0.4038, places=3)

    def test_analysis_consistent(self):
        df = generate()
        r = analyse(df)
        self.assertEqual(r["households"], len(df))
        self.assertEqual(int(r["by_district"]["households"].sum()), len(df))
        self.assertAlmostEqual(r["difference_pct_points"],
                               r["success_with_follow_up_pct"] - r["success_without_follow_up_pct"], delta=0.11)
        self.assertLess(r["difference_95ci"][0], r["difference_pct_points"])

    def test_reproducible(self):
        self.assertTrue(generate().equals(generate()))


if __name__ == "__main__":
    unittest.main()
