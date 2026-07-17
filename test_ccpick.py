"""Unit tests for ccpick's pure, TTY-independent functions."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ccpick


class FuzzyScoreTests(unittest.TestCase):
    def test_exact_prefix_match(self):
        score, indices = ccpick.fuzzy_score("abc", "abc")
        self.assertEqual(indices, [0, 1, 2])

    def test_scattered_subsequence_match(self):
        score, indices = ccpick.fuzzy_score("cspkr", "claude-session-picker")
        self.assertEqual(indices, [0, 7, 15, 18, 20])

    def test_missing_character_returns_none(self):
        self.assertIsNone(ccpick.fuzzy_score("xyz", "claude-session-picker"))

    def test_out_of_order_returns_none(self):
        self.assertIsNone(ccpick.fuzzy_score("ba", "ab"))

    def test_case_insensitive(self):
        score, indices = ccpick.fuzzy_score("ABC", "xabcx")
        self.assertEqual(indices, [1, 2, 3])

    def test_contiguous_run_scores_better_than_scattered(self):
        contiguous = ccpick.fuzzy_score("ab", "xxabxx")
        scattered = ccpick.fuzzy_score("ab", "xaxbxx")
        self.assertLess(contiguous[0], scattered[0])

    def test_word_boundary_scores_better_than_mid_word(self):
        boundary = ccpick.fuzzy_score("s", "session")
        mid_word = ccpick.fuzzy_score("s", "xsession")
        self.assertLess(boundary[0], mid_word[0])

    def test_empty_token_matches_trivially(self):
        self.assertEqual(ccpick.fuzzy_score("", "anything"), (0, []))


class MatchFilterTests(unittest.TestCase):
    def _meta(self, title="", cwd="", branch="", prompt=""):
        return {"title": title, "cwd": cwd, "gitBranch": branch, "firstPrompt": prompt}

    def test_empty_query_matches_everything(self):
        self.assertEqual(ccpick.match("", self._meta(title="anything")), 0)

    def test_single_token_fuzzy_match(self):
        m = self._meta(title="claude-session-picker")
        self.assertIsNotNone(ccpick.match("cspkr", m))

    def test_no_match_returns_none(self):
        m = self._meta(title="claude-session-picker")
        self.assertIsNone(ccpick.match("xyz", m))

    def test_multi_token_and_semantics(self):
        m = self._meta(title="ccpick", cwd=r"C:\git\obsidian-wiki", branch="n8n-fix")
        self.assertIsNotNone(ccpick.match("obsidian n8n", m))

    def test_multi_token_all_must_match(self):
        m = self._meta(title="ccpick", cwd=r"C:\git\obsidian-wiki")
        self.assertIsNone(ccpick.match("obsidian n8n", m))

    def test_fuzzy_and_substring_combined(self):
        m = self._meta(title="claude-session-picker", cwd=r"C:\git\obsidian-wiki")
        self.assertIsNotNone(ccpick.match("cspkr obsidian", m))

    def test_fuzzy_token_and_missing_token_fails(self):
        m = self._meta(title="claude-session-picker", cwd=r"C:\git\obsidian-wiki")
        self.assertIsNone(ccpick.match("cspkr n8n", m))


class ClipTests(unittest.TestCase):
    def test_clip_no_truncation(self):
        self.assertEqual(ccpick.clip("abc", 10), "abc")

    def test_clip_truncates_with_ellipsis(self):
        self.assertEqual(ccpick.clip("abcdef", 4), "abc…")

    def test_clip_narrow_width_no_ellipsis(self):
        self.assertEqual(ccpick.clip("abcdef", 1), "a")


class HighlightTests(unittest.TestCase):
    def test_clip_prefix_no_truncation(self):
        chars, truncated = ccpick.clip_prefix("abc", 10)
        self.assertEqual(chars, ["a", "b", "c"])
        self.assertFalse(truncated)

    def test_clip_prefix_truncates(self):
        chars, truncated = ccpick.clip_prefix("abcdef", 4)
        self.assertEqual("".join(chars), "abc")
        self.assertTrue(truncated)

    def test_colorize_title_no_highlights(self):
        self.assertEqual(ccpick.colorize_title("abc", 10, set()), "abc")

    def test_colorize_title_highlights_chars(self):
        result = ccpick.colorize_title("abc", 10, {0, 2})
        expected = (
            ccpick.BOLD + ccpick.CYAN + "a" + ccpick.RESET
            + "b"
            + ccpick.BOLD + ccpick.CYAN + "c" + ccpick.RESET
        )
        self.assertEqual(result, expected)

    def test_title_highlights_returns_matched_indices(self):
        idxs = ccpick.title_highlights("cspkr", "claude-session-picker")
        self.assertEqual(idxs, {0, 7, 15, 18, 20})

    def test_title_highlights_empty_query(self):
        self.assertEqual(ccpick.title_highlights("", "anything"), set())


class TrashPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig_projects = ccpick.PROJECTS_DIR
        self.orig_trash = ccpick.TRASH_DIR
        ccpick.PROJECTS_DIR = os.path.join(self.tmp.name, "projects")
        ccpick.TRASH_DIR = os.path.join(self.tmp.name, "trash")
        self.addCleanup(self._restore_globals)

    def _restore_globals(self):
        ccpick.PROJECTS_DIR = self.orig_projects
        ccpick.TRASH_DIR = self.orig_trash

    def test_trash_path_for_mirrors_structure(self):
        live = os.path.join(ccpick.PROJECTS_DIR, "encoded-proj", "sess1.jsonl")
        expected = os.path.join(ccpick.TRASH_DIR, "encoded-proj", "sess1.jsonl")
        self.assertEqual(ccpick.trash_path_for(live), expected)

    def test_round_trip(self):
        live = os.path.join(ccpick.PROJECTS_DIR, "encoded-proj", "sess1.jsonl")
        trashed = ccpick.trash_path_for(live)
        self.assertEqual(ccpick.live_path_for(trashed), live)

    def test_move_to_trash_and_restore(self):
        live_dir = os.path.join(ccpick.PROJECTS_DIR, "encoded-proj")
        os.makedirs(live_dir)
        live_path = os.path.join(live_dir, "sess1.jsonl")
        with open(live_path, "w", encoding="utf-8") as fh:
            fh.write('{"type": "user"}\n')

        trash_path = ccpick.move_to_trash(live_path)

        self.assertFalse(os.path.exists(live_path))
        self.assertTrue(os.path.exists(trash_path))

        restored_path = ccpick.restore_from_trash(trash_path)

        self.assertFalse(os.path.exists(trash_path))
        self.assertTrue(os.path.exists(restored_path))
        self.assertEqual(restored_path, live_path)


class PurgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig_trash = ccpick.TRASH_DIR
        ccpick.TRASH_DIR = os.path.join(self.tmp.name, "trash")
        self.addCleanup(self._restore_globals)

    def _restore_globals(self):
        ccpick.TRASH_DIR = self.orig_trash

    def _make_trashed(self, name, age_days):
        d = os.path.join(ccpick.TRASH_DIR, "proj")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_purge_removes_only_expired(self):
        old_path = self._make_trashed("old.jsonl", age_days=40)
        new_path = self._make_trashed("new.jsonl", age_days=5)

        purged = ccpick.purge_expired_trash(retention_days=30)

        self.assertEqual(purged, 1)
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(new_path))

    def test_purge_empty_trash_dir(self):
        self.assertEqual(ccpick.purge_expired_trash(retention_days=30), 0)


class TrashScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig_trash = ccpick.TRASH_DIR
        ccpick.TRASH_DIR = os.path.join(self.tmp.name, "trash")
        self.addCleanup(self._restore_globals)

    def _restore_globals(self):
        ccpick.TRASH_DIR = self.orig_trash

    def test_trash_session_files_empty_when_no_dir(self):
        self.assertEqual(ccpick.trash_session_files(), [])

    def test_trash_session_files_finds_nested_jsonl(self):
        d = os.path.join(ccpick.TRASH_DIR, "proj")
        os.makedirs(d)
        path = os.path.join(d, "sess1.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"type": "user"}\n')
        self.assertEqual(ccpick.trash_session_files(), [path])


class ProjectLabelTests(unittest.TestCase):
    def test_posix_style_path_uses_native_separator(self):
        expected = "giovanni" + os.sep + "project"
        self.assertEqual(ccpick.project_label("/home/giovanni/project"), expected)

    def test_windows_style_path_uses_native_separator(self):
        expected = "Giovanni" + os.sep + "project"
        self.assertEqual(ccpick.project_label(r"C:\Users\Giovanni\project"), expected)

    def test_single_component_path(self):
        self.assertEqual(ccpick.project_label("/home"), "home")

    def test_home_directory_returns_tilde(self):
        self.assertEqual(ccpick.project_label(ccpick.HOME), "~")

    def test_empty_cwd_returns_question_mark(self):
        self.assertEqual(ccpick.project_label(""), "?")
        self.assertEqual(ccpick.project_label(None), "?")


class MarksTests(unittest.TestCase):
    def test_pin_and_unpin(self):
        m = ccpick.Marks()
        self.assertEqual(m.toggle_pin("a", 3), "pinned")
        self.assertTrue(m.is_pinned("a"))
        self.assertEqual(m.toggle_pin("a", 3), "unpinned")
        self.assertFalse(m.is_pinned("a"))

    def test_pin_cap_refuses(self):
        m = ccpick.Marks(pins=["a", "b", "c"])
        self.assertEqual(m.toggle_pin("d", 3), "cap")
        self.assertFalse(m.is_pinned("d"))
        self.assertEqual(m.pins, ["a", "b", "c"])

    def test_pin_custom_cap(self):
        m = ccpick.Marks(pins=["a"])
        self.assertEqual(m.toggle_pin("b", 1), "cap")
        m2 = ccpick.Marks(pins=["a"])
        self.assertEqual(m2.toggle_pin("b", 5), "pinned")

    def test_pin_preserves_order(self):
        m = ccpick.Marks()
        m.toggle_pin("a", 3)
        m.toggle_pin("b", 3)
        self.assertEqual(m.pins, ["a", "b"])

    def test_pinning_saved_item_promotes_it(self):
        m = ccpick.Marks(saved=["a"])
        self.assertEqual(m.toggle_pin("a", 3), "pinned")
        self.assertTrue(m.is_pinned("a"))
        self.assertFalse(m.is_saved("a"))

    def test_save_and_unsave(self):
        m = ccpick.Marks()
        self.assertEqual(m.toggle_save("a"), "saved")
        self.assertTrue(m.is_saved("a"))
        self.assertEqual(m.toggle_save("a"), "unsaved")
        self.assertFalse(m.is_saved("a"))

    def test_saving_pinned_item_moves_it(self):
        m = ccpick.Marks(pins=["a"])
        self.assertEqual(m.toggle_save("a"), "saved")
        self.assertTrue(m.is_saved("a"))
        self.assertFalse(m.is_pinned("a"))

    def test_drop_removes_from_both(self):
        m = ccpick.Marks(pins=["a"], saved=["b"])
        self.assertTrue(m.drop("a"))
        self.assertTrue(m.drop("b"))
        self.assertFalse(m.drop("c"))
        self.assertEqual(m.pins, [])
        self.assertEqual(m.saved, [])


class MarksPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig = ccpick.MARKS_PATH
        ccpick.MARKS_PATH = os.path.join(self.tmp.name, "ccpick-marks.json")
        self.addCleanup(self._restore)

    def _restore(self):
        ccpick.MARKS_PATH = self.orig

    def test_missing_file_returns_empty(self):
        m = ccpick.load_marks()
        self.assertEqual(m.pins, [])
        self.assertEqual(m.saved, [])

    def test_round_trip(self):
        ccpick.save_marks(ccpick.Marks(pins=["a", "b"], saved=["c"]))
        m = ccpick.load_marks()
        self.assertEqual(m.pins, ["a", "b"])
        self.assertEqual(m.saved, ["c"])

    def test_malformed_file_returns_empty(self):
        with open(ccpick.MARKS_PATH, "w", encoding="utf-8") as fh:
            fh.write("not json{{{")
        self.assertEqual(ccpick.load_marks().pins, [])

    def test_wrong_version_returns_empty(self):
        with open(ccpick.MARKS_PATH, "w", encoding="utf-8") as fh:
            json.dump({"v": 999, "pins": ["a"], "saved": []}, fh)
        self.assertEqual(ccpick.load_marks().pins, [])


class GroupingTests(unittest.TestCase):
    def _meta(self, sid, title="t"):
        return {"sessionId": sid, "title": title, "cwd": "", "gitBranch": "",
                "firstPrompt": "", "summary": None, "lastTs": ""}

    def test_row_marker_glyphs(self):
        marks = ccpick.Marks(pins=["a"], saved=["b"])
        self.assertEqual(ccpick.display_width(ccpick.row_marker(marks, "a")), 2)
        self.assertEqual(ccpick.display_width(ccpick.row_marker(marks, "b")), 2)
        self.assertEqual(ccpick.row_marker(marks, "c"), "  ")
        self.assertTrue(ccpick.row_marker(marks, "a").startswith(ccpick.PIN_GLYPH))
        self.assertTrue(ccpick.row_marker(marks, "b").startswith(ccpick.SAVE_GLYPH))

    def test_partition_orders_and_excludes(self):
        metas = [self._meta("a"), self._meta("b"), self._meta("c"), self._meta("d")]
        marks = ccpick.Marks(pins=["c", "a"], saved=["d"])
        pinned, saved, others = ccpick.partition_marked(metas, marks)
        self.assertEqual([m["sessionId"] for m in pinned], ["c", "a"])  # pin order
        self.assertEqual([m["sessionId"] for m in saved], ["d"])
        self.assertEqual([m["sessionId"] for m in others], ["b"])

    def test_partition_skips_dangling_pin(self):
        metas = [self._meta("a")]
        marks = ccpick.Marks(pins=["a", "ghost"])
        pinned, saved, others = ccpick.partition_marked(metas, marks)
        self.assertEqual([m["sessionId"] for m in pinned], ["a"])
        self.assertEqual(others, [])

    def test_build_rows_flat(self):
        metas = [self._meta("a"), self._meta("b")]
        rows = ccpick.build_rows([], [], metas, grouped=False)
        self.assertTrue(all(r["kind"] == "session" for r in rows))
        self.assertEqual(len(rows), 2)

    def test_build_rows_grouped_has_headers(self):
        rows = ccpick.build_rows(
            [self._meta("a")], [self._meta("b")], [self._meta("c")], grouped=True
        )
        kinds = [(r["kind"], r.get("label")) for r in rows]
        self.assertEqual(kinds[0], ("header", "PINNED"))
        self.assertEqual(rows[1]["meta"]["sessionId"], "a")
        self.assertEqual(kinds[2], ("header", "SAVED FOR LATER"))
        self.assertEqual(kinds[4][0], "header")  # "── sessions ──"

    def test_build_rows_omits_empty_group(self):
        rows = ccpick.build_rows(
            [self._meta("a")], [], [self._meta("c")], grouped=True
        )
        labels = [r["label"] for r in rows if r["kind"] == "header"]
        self.assertNotIn("SAVED FOR LATER", labels)
        self.assertIn("PINNED", labels)

    def test_session_row_indices_skips_headers(self):
        rows = ccpick.build_rows(
            [self._meta("a")], [self._meta("b")], [], grouped=True
        )
        sel = ccpick.session_row_indices(rows)
        self.assertEqual([rows[i]["meta"]["sessionId"] for i in sel], ["a", "b"])
        self.assertTrue(all(rows[i]["kind"] == "session" for i in sel))


import io
import contextlib


class ListMarkerTests(unittest.TestCase):
    def _meta(self, sid, title="t"):
        return {"sessionId": sid, "title": title, "cwd": "/x/y",
                "gitBranch": "", "firstPrompt": "", "summary": None, "lastTs": ""}

    def test_print_list_no_markers_by_default(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ccpick.print_list([self._meta("a")])
        self.assertFalse(buf.getvalue().startswith("★"))
        self.assertFalse(buf.getvalue().startswith("◆"))

    def test_print_list_shows_pin_glyph(self):
        marks = ccpick.Marks(pins=["a"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ccpick.print_list([self._meta("a")], marks=marks, show_markers=True)
        self.assertTrue(buf.getvalue().startswith(ccpick.PIN_GLYPH))


if __name__ == "__main__":
    unittest.main()
