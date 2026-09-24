"""jd_sources のオフラインテスト（Drive・公開 API・sources.local.json は使わない）

会社名はすべて架空。取引先ごとの設定は FAKE_CONFIG に差し替えて検証する。
使い方: python -m unittest jev_poc/test_jd_sources.py
"""

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jd_sources as js  # noqa: E402

NOW = 1_790_000_000.0  # 2026-09-21 頃

FAKE_FOLDERS = {
    "株式会社サンプルテック": ["Sample Tech"],
    "Example Robotics": ["ExampleRobotics"],
    "Acme": ["acme", "ａｃｍｅ"],
    "株式会社サンプルホールディングス": ["Sample AI"],
}
FAKE_SUFFIXES = ["example robotics", "acme"]


def _iso(days_ago):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(NOW - days_ago * 86400, tz=timezone.utc).isoformat().replace("+00:00", "Z")


class _FakeConfig(unittest.TestCase):
    def setUp(self):
        patches = [unittest.mock.patch.object(js, "COMPANY_FOLDERS", FAKE_FOLDERS),
                   unittest.mock.patch.object(js, "TITLE_SUFFIXES", FAKE_SUFFIXES)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class SameJobTest(_FakeConfig):
    def test_herp_renumbering_and_suffix(self):
        self.assertTrue(js.same_job("Product - 04. Staff Software Engineer - Backend - 株式会社サンプルテック - HERP Hire",
                                    "Product - 02. Staff Software Engineer - Backend"))

    def test_code_match_wins(self):
        self.assertTrue(js.same_job("【R&D-012】Research Scientist (VLAs)", "R&D-012 Research Scientist (VLA)"))
        self.assertFalse(js.same_job("R&D-034 Robotics Controls Engineer", "R&D-025 Robotics Controls Engineer"))

    def test_underscore_filenames_and_containment(self):
        self.assertTrue(js.same_job("Data_Engineer___Example_Robotics___Jobs_By_Workable", "R&D-020 Data Engineer"))
        self.assertTrue(js.same_job("Service Robot System Engineer at Development Division",
                                    "R&D-025 Service Robot System Engineer"))

    def test_language_variants_are_different_jobs(self):
        self.assertFalse(js.same_job("【Sample AI】Agent Harness Engineer _ English _ 株式会社サンプルホールディングス",
                                     "【Sample AI】Agent Harness Engineer / Japanese"))
        self.assertTrue(js.same_job("【Sample AI】Agent Harness Engineer _ English _ 株式会社サンプルホールディングス",
                                    "【Sample AI】Agent Harness Engineer / English"))

    def test_company_prefix_title_is_kept(self):
        self.assertTrue(js.same_job("株式会社サンプルテック Senior Agentic AI Engineer",
                                    "株式会社サンプルテック Senior Agentic AI Engineer"))

    def test_different_jobs(self):
        self.assertFalse(js.same_job("Account Manager", "Accounting @ acme"))
        self.assertFalse(js.same_job("Research Engineer - Audio", "Research Engineer - Applied / 顧客協業"))


class StatusTest(_FakeConfig):
    def _open_jobs(self, herp_days_ago):
        state = {"herp": {"株式会社サンプルテック": {"open": ["DZD-03-Data Analyst, Data Section"],
                                                "updatedAt": _iso(herp_days_ago)}},
                 "boards": {"Workable|Example Robotics": {"open": ["Machine Learning Engineer (FDE)"], "updatedAt": _iso(0)}}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(state, f)
        return js.load_open_jobs(Path(f.name), now=NOW)

    def test_open_closed_unknown(self):
        jds = [{"company": "ExampleRobotics", "title": "Machine Learning Engineer (FDE)", "mtime": NOW - 5 * 86400},
               {"company": "ExampleRobotics", "title": "Senior Talent Acquisition", "mtime": NOW - 5 * 86400},
               {"company": "Unlisted Co", "title": "Agent Harness Engineer", "mtime": 0}]
        js.annotate_status(jds, self._open_jobs(3))
        self.assertEqual([j["status"] for j in jds], ["open", "closed", "unknown"])

    def test_stale_herp_list_is_ignored(self):
        jds = [{"company": "Sample Tech", "title": "DBE-12-Software Engineer", "mtime": 0}]
        js.annotate_status(jds, self._open_jobs(js.STALE_DAYS + 5))
        self.assertEqual(jds[0]["status"], "unknown")

    def test_jd_saved_after_snapshot_is_unknown(self):
        jds = [{"company": "Sample Tech", "title": "New Role", "mtime": NOW}]
        js.annotate_status(jds, self._open_jobs(3))
        self.assertEqual(jds[0]["status"], "unknown")

    def test_no_config_means_unknown(self):
        jds = [{"company": "Sample Tech", "title": "Any", "mtime": 0}]
        with unittest.mock.patch.object(js, "COMPANY_FOLDERS", {}):
            js.annotate_status(jds, self._open_jobs(3))
        self.assertEqual(jds[0]["status"], "unknown")


class MissingJobsTest(_FakeConfig):
    def test_adds_board_jd_and_lists_herp_without_text(self):
        open_jobs = {"Acme": {"ats": "Ashby", "open": ["Developer Relations", "Accounting"], "updated": NOW},
                     "株式会社サンプルテック": {"ats": "HERP", "open": ["DZD-02-Analytics Engineer"], "updated": NOW}}
        jds = [{"company": "ａｃｍｅ", "title": "Accounting @ acme"}]
        board = {"Acme": [{"title": "Developer Relations", "url": "https://x", "text": "DevRel JD"},
                          {"title": "Accounting", "url": "https://y", "text": "Acc JD"}]}
        added, unavailable = js.missing_jobs(jds, open_jobs, board)
        self.assertEqual([(a["company"], a["title"], a["status"]) for a in added], [("acme", "Developer Relations", "open")])
        self.assertEqual(unavailable, ["Sample Tech｜DZD-02-Analytics Engineer（HERP）"])


class HrmosExportTest(_FakeConfig):
    def _write(self, d, exported_days_ago):
        data = {"source": "HRMOS", "exportedAt": _iso(exported_days_ago), "corporates": [{"name": "株式会社サンプルホールディングス", "jobs": [
            {"jobId": "1", "title": "【Sample AI】Agent Harness Engineer / English", "archived": False, "closeAt": None, "text": "JD1"},
            {"jobId": "2", "title": "【Sample AI】Old Role", "archived": False, "closeAt": _iso(exported_days_ago + 10), "text": "JD2"},
            {"jobId": "3", "title": "【Sample AI】Archived Role", "archived": True, "closeAt": None, "text": "JD3"},
        ]}]}
        (Path(d) / "hrmos_export_20260924.json").write_text(json.dumps(data, ensure_ascii=False))

    def test_live_jobs_only(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, 1)
            open_jobs, board = js.load_hrmos_export([Path(d)], now=NOW)
        self.assertEqual(open_jobs["株式会社サンプルホールディングス"]["open"], ["【Sample AI】Agent Harness Engineer / English"])
        self.assertEqual(board["株式会社サンプルホールディングス"][0]["text"], "JD1")

    def test_stale_or_missing_export_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(js.load_hrmos_export([Path(d)], now=NOW), ({}, {}))
            self._write(d, js.STALE_DAYS + 1)
            self.assertEqual(js.load_hrmos_export([Path(d)], now=NOW), ({}, {}))

    def test_drive_title_matches_hrmos_title(self):
        self.assertTrue(js.same_job("【Sample AI】Agent Harness Engineer _ English _ 株式会社サンプルホールディングス",
                                    "【Sample AI】Agent Harness Engineer / English"))


class ConfigTest(unittest.TestCase):
    def test_example_config_is_valid_and_missing_file_is_empty(self):
        example = js.load_config(Path(js.__file__).with_name("sources.example.json"))
        self.assertIn("company_folders", example)
        self.assertEqual(js.load_config(Path("/nonexistent/sources.local.json")), {})


class DrivePathTest(unittest.TestCase):
    def test_picks_mount_that_has_the_target(self):
        with tempfile.TemporaryDirectory() as home:
            cs = Path(home) / "Library/CloudStorage"
            (cs / "GoogleDrive-a@example.com/マイドライブ").mkdir(parents=True)
            (cs / "GoogleDrive-b@example.com/共有ドライブ/JDs").mkdir(parents=True)
            with unittest.mock.patch.object(js.Path, "home", return_value=Path(home)), \
                 unittest.mock.patch.dict(js.os.environ, {}, clear=True):
                self.assertEqual(js.drive_path("共有ドライブ/JDs"), cs / "GoogleDrive-b@example.com/共有ドライブ/JDs")
            with unittest.mock.patch.dict(js.os.environ, {"JEV_DRIVE_ROOT": "/x"}):
                self.assertEqual(js.drive_path("y"), Path("/x/y"))


class HtmlToTextTest(unittest.TestCase):
    def test_lists_and_entities(self):
        self.assertEqual(js._html_to_text("<p>Req&amp;s</p><ul><li>Python</li><li>Go</li></ul>"),
                         "Req&s\n- Python\n- Go")


if __name__ == "__main__":
    unittest.main()
