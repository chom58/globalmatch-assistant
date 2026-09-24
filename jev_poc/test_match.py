"""match.py のオフラインテスト（Jev・claude は呼ばない）

使い方: python -m unittest jev_poc/test_match.py
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import match  # noqa: E402
from cv_jd_score import DIM_KEYS  # noqa: E402


def _row(company, title, calibrated, ja):
    dims = {k: {"score": 3.0, "confidence": 0.7} for k in DIM_KEYS}
    dims["language_japanese"]["score"] = ja
    return {"company": company, "title": title, "path": f"{company}/{title}.pdf", "text": "JD",
            "result": {"dimensions": dims, "calibrated_total_pct": calibrated, "total_pct": calibrated,
                       "usage": {"input_tokens": 100}}}


class LoadJdsTest(unittest.TestCase):
    def test_excludes_archived_and_uses_folder_as_company(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(match, "CACHE_DIR", Path(d) / "cache"):
            root = Path(d) / "jds"
            (root / "Acme" / "archived").mkdir(parents=True)
            (root / "Acme" / "Backend Engineer.txt").write_text("req: Go")
            (root / "Acme" / "AI R&amp;D Lead.txt").write_text("req: ML")
            (root / "Acme" / "archived" / "Old.txt").write_text("old")
            jds = match.load_jds(root)
            self.assertEqual([(j["company"], j["title"]) for j in jds],
                             [("Acme", "AI R&D Lead"), ("Acme", "Backend Engineer")])
            self.assertEqual(len(match.load_jds(root, include_archived=True)), 3)

    def test_prompt_requires_all_nine_rows(self):
        self.assertIn("9次元はすべて行を出す", match.STAGE2_PROMPT)
        self.assertNotIn("行ごと省く", match.STAGE2_PROMPT)


class RankTest(unittest.TestCase):
    def test_japanese_gate_then_score(self):
        rows = [_row("A", "low", 60, 4.0), _row("B", "high-but-ja-ng", 90, 1.5),
                _row("C", "high", 80, 3.0), {"company": "D", "title": "err", "path": "D/err", "error": "x"}]
        ranked = match.rank(rows, ja_min=2.5)
        self.assertEqual([r["title"] for r in ranked], ["high", "low", "high-but-ja-ng"])
        self.assertFalse(ranked[-1]["ja_ok"])

    def test_no_gate_when_job_does_not_need_japanese(self):
        english_only = _row("E", "english-only", 70, 1.0)
        english_only["result"]["jd_requires_japanese_p"] = 0.1
        needs_ja = _row("J", "needs-ja", 90, 1.0)
        needs_ja["result"]["jd_requires_japanese_p"] = 0.9
        ranked = match.rank([needs_ja, english_only], ja_min=2.5)
        self.assertEqual([r["title"] for r in ranked], ["english-only", "needs-ja"])
        self.assertTrue(ranked[0]["ja_ok"])
        self.assertFalse(ranked[0]["ja_required"])


class Stage2Test(unittest.TestCase):
    def test_runs_claude_without_tools_and_redacts_cv(self):
        captured = {}

        def fake_run(cmd, input, **kw):
            captured["cmd"], captured["input"] = cmd, input
            return subprocess.CompletedProcess(cmd, 0, stdout="## 推薦順\n1. A", stderr="")

        cv = "Kenji Tanaka\nkenji@example.com\nPython 5 years"
        with mock.patch.object(match.subprocess, "run", fake_run):
            out = match.stage2(cv, [_row("A", "Backend", 80, 4.0)], "sonnet")
        self.assertIn("推薦順", out)
        cmd = captured["cmd"]
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertNotIn("kenji@example.com", captured["input"])
        self.assertNotIn("Tanaka", captured["input"])
        self.assertIn('company="A"', captured["input"])

    def test_reports_failure(self):
        fail = subprocess.CompletedProcess([], 1, stdout="", stderr="auth expired")
        with mock.patch.object(match.subprocess, "run", return_value=fail):
            out = match.stage2("cv", [_row("A", "B", 80, 4.0)], "sonnet")
        self.assertIn("失敗", out)


class ReportTest(unittest.TestCase):
    def test_report_has_table_and_stage2(self):
        ranked = match.rank([_row("A", "Backend", 80, 4.0)], 2.5)
        ranked[0]["status"] = "open"
        ats = {"closed": 3, "added": 1, "unavailable": ["X｜Y（HERP）"], "note": ""}
        rep = match.build_report("cv.pdf", ranked, [], 20, "## 推薦順", {"load": 1, "stage1": 2, "stage2": 3}, 100, ats)
        self.assertIn("| 1 | 80.0% | ○ | 募集中 | A | Backend |", rep)
        self.assertIn("締め切り済み 3件", rep)
        self.assertIn("- X｜Y（HERP）", rep)
        self.assertIn("第2段", rep)


class ApplyAtsTest(unittest.TestCase):
    def test_drops_closed_and_adds_board_jobs(self):
        jds = [{"company": "ExampleRobotics", "title": "Open Role", "text": "t", "mtime": 0},
               {"company": "ExampleRobotics", "title": "Closed Role", "text": "t", "mtime": 0}]
        open_jobs = {"Example Robotics": {"ats": "Workable", "open": ["Open Role"], "updated": 1.0}}
        added = [{"company": "acme", "title": "New", "text": "t", "status": "open", "source": "Ashby", "path": "x"}]
        with mock.patch.object(match.jd_sources, "COMPANY_FOLDERS", {"Example Robotics": ["ExampleRobotics"]}), \
             mock.patch.object(match.jd_sources, "load_open_jobs", return_value=open_jobs), \
             mock.patch.object(match.jd_sources, "load_hrmos_export", return_value=({}, {})), \
             mock.patch.object(match.jd_sources, "fetch_board_jobs", return_value={}), \
             mock.patch.object(match.jd_sources, "missing_jobs", return_value=(added, ["H｜J（HERP）"])):
            kept, info = match.apply_ats(jds, include_closed=False)
        self.assertEqual([j["title"] for j in kept], ["Open Role", "New"])
        self.assertEqual((info["closed"], info["added"]), (1, 1))

    def test_missing_state_file_keeps_everything(self):
        jds = [{"company": "ExampleRobotics", "title": "Role", "text": "t", "mtime": 0}]
        with mock.patch.object(match.jd_sources, "load_open_jobs", side_effect=FileNotFoundError):
            kept, info = match.apply_ats(jds, include_closed=False)
        self.assertEqual(kept, jds)
        self.assertIn("未確認", info["note"])


if __name__ == "__main__":
    unittest.main()
