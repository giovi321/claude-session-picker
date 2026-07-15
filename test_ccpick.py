"""Unit tests for ccpick's pure, TTY-independent functions."""
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


if __name__ == "__main__":
    unittest.main()
