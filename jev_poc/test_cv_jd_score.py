"""cv_jd_score のオフラインテスト（API は呼ばない）

使い方: python -m unittest jev_poc/test_cv_jd_score.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv_jd_score  # noqa: E402
from cv_jd_score import DIM_KEYS, build_questions, redact_cv, total_pct  # noqa: E402

SAMPLE_CV = """Kenji Tanaka
kenji.tanaka@gmail.com | +81-90-1234-5678 | linkedin.com/in/kenji-tanaka
Experience
Mercari, Engineering Manager  2019 - 2023
Rakuten, Backend Engineer  Apr 2016 - Mar 2019
Kenji led a team of 8.
"""


class RedactTest(unittest.TestCase):
    def setUp(self):
        self.out = redact_cv(SAMPLE_CV)

    def test_removes_pii(self):
        for s in ["Kenji", "Tanaka", "gmail", "1234-5678", "linkedin"]:
            self.assertNotIn(s, self.out)

    def test_keeps_date_ranges(self):
        self.assertIn("2019 - 2023", self.out)
        self.assertIn("Apr 2016 - Mar 2019", self.out)


class StripRubricTest(unittest.TestCase):
    JD = ("求人詳細\n企業:X\n主な要件\n- Python\n主要スキル\nPython\nSQL\n📊 評価ルーブリック\n— 9 dimensions\nExpand\n\n"
          "このルーブリックは候補者像を定義します。\nDesired Skills\n5/5 - 完璧\nLanguage - Other\n中国語があれば加点\n")

    def test_strips_after_skills(self):
        out = cv_jd_score.strip_recruitline_rubric(self.JD)
        self.assertTrue(out.endswith("SQL\n"), repr(out[-30:]))
        for s in ["評価ルーブリック", "このルーブリック", "Desired Skills", "中国語"]:
            self.assertNotIn(s, out)

    def test_plain_jd_unchanged(self):
        jd = "Requirements\n- Python\nDesired Skills\n- Go\n"
        self.assertEqual(cv_jd_score.strip_recruitline_rubric(jd), jd)


class QuestionTest(unittest.TestCase):
    def test_nine_scores_and_gate(self):
        q = build_questions()
        gates = [cv_jd_score.OTHER_LANG_GATE, cv_jd_score.JA_REQ_GATE]
        self.assertEqual(list(q), DIM_KEYS + gates)
        for k in DIM_KEYS:
            self.assertEqual(q[k]["type"], "score")
            self.assertEqual(len(q[k]["criteria"]), 5)
        for g in gates:
            self.assertEqual(q[g]["type"], "noul")


def _fake_response(gate_p):
    answers = {k: {"type": "score", "score": 3.0, "confidence": 0.8,
                   "probabilities": {"0": 0, "1": 0, "2": 0, "3": 1.0, "4": 0}} for k in DIM_KEYS}
    answers[cv_jd_score.OTHER_LANG_GATE] = {"type": "noul", "noul": gate_p}
    answers[cv_jd_score.JA_REQ_GATE] = {"type": "noul", "noul": 0.2}
    return {"model": "jev-test", "usage": {}, "answers": answers}


class ScorePairTest(unittest.TestCase):
    def setUp(self):
        self._orig = cv_jd_score.ask_jev

    def tearDown(self):
        cv_jd_score.ask_jev = self._orig

    def test_other_languages_na_when_jd_does_not_require(self):
        cv_jd_score.ask_jev = lambda *a, **k: _fake_response(0.1)
        r = cv_jd_score.score_pair(SAMPLE_CV, "JD")
        self.assertIsNone(r["dimensions"]["other_languages"]["score"])
        self.assertEqual(r["total_pct"], 80.0)  # 残り8次元がすべて4点
        self.assertEqual(r["jd_requires_japanese_p"], 0.2)

    def test_other_languages_scored_when_jd_requires(self):
        cv_jd_score.ask_jev = lambda *a, **k: _fake_response(0.9)
        r = cv_jd_score.score_pair(SAMPLE_CV, "JD")
        self.assertEqual(r["dimensions"]["other_languages"]["score"], 4.0)


class TotalTest(unittest.TestCase):
    def test_equal_weights(self):
        # Recruitline の実測例: 素点 33/45 → 均等重みなら 73.3%
        dims = dict(zip(DIM_KEYS, [4, 3, 2, 3, 4, 2, 5, 5, 5]))
        self.assertEqual(total_pct(dims), 73.3)

    def test_na_dimension_excluded_from_denominator(self):
        dims = {k: 5 for k in DIM_KEYS} | {"other_languages": None}
        self.assertEqual(total_pct(dims), 100.0)

    def test_calibrate_clamps(self):
        orig = cv_jd_score.CALIBRATION
        try:
            cv_jd_score.CALIBRATION = (1.2, 5.0)
            self.assertEqual(cv_jd_score.calibrate(50.0), 65.0)
            self.assertEqual(cv_jd_score.calibrate(95.0), 100.0)
        finally:
            cv_jd_score.CALIBRATION = orig

    def test_custom_weights(self):
        dims = {k: 5 for k in DIM_KEYS} | {"domain_knowledge": 1}
        w = {k: 0.0 for k in DIM_KEYS} | {"domain_knowledge": 1.0}
        self.assertEqual(total_pct(dims, w), 20.0)


if __name__ == "__main__":
    unittest.main()
