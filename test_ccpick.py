"""Unit tests for ccpick's pure, TTY-independent functions."""
import os
import sys
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


if __name__ == "__main__":
    unittest.main()
