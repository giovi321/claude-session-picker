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


if __name__ == "__main__":
    unittest.main()
