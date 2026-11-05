import os
import sys
import unittest
from unittest.mock import patch

from src.github.pr_listener import parse_arguments


class PullRequestListenerTests(unittest.TestCase):
    def _parse(self, *arguments: str):
        with (
            patch.object(sys, "argv", ["ai-pr-review", *arguments]),
            patch.dict(os.environ, {}, clear=True),
        ):
            return parse_arguments()

    def test_posts_comment_by_default(self):
        arguments = self._parse("--repo", "owner/repository", "--pr", "12")

        self.assertTrue(arguments.comment)

    def test_no_comment_flag_disables_comment_posting(self):
        arguments = self._parse(
            "--repo",
            "owner/repository",
            "--pr",
            "12",
            "--no-comment",
        )

        self.assertFalse(arguments.comment)

    def test_comment_flag_is_supported(self):
        arguments = self._parse(
            "--repo",
            "owner/repository",
            "--pr",
            "12",
            "--comment",
        )

        self.assertTrue(arguments.comment)


if __name__ == "__main__":
    unittest.main()
