import json
import unittest
from types import SimpleNamespace

from src.github.pr_commenter import post_inline_finding_comments
from src.models import CheckResult, ChangedFile, Finding, PullRequest


class FakeGitHubClient:
    def __init__(self, comments=None):
        self.comments = comments or []
        self.requests = []

    def request(self, url, *, method="GET", payload=None, **_kwargs):
        self.requests.append((url, method, payload))
        if method == "GET":
            return SimpleNamespace(
                body=json.dumps(self.comments).encode("utf-8"),
                headers={"Link": ""},
            )
        return SimpleNamespace(body=b"{}", headers={})


class InlineCommentTests(unittest.TestCase):
    def setUp(self):
        self.pull_request = PullRequest(
            number=17,
            title="Improve validation",
            url="https://github.com/acme/example/pull/17",
            base_ref="main",
            base_sha="base123",
            head_ref="feature",
            head_sha="head456",
            comments_url="https://api.github.com/repos/acme/example/issues/17/comments",
            review_comments_url=(
                "https://api.github.com/repos/acme/example/pulls/17/comments"
            ),
        )
        self.changed_files = [
            ChangedFile(
                path="src/module.py",
                status="modified",
                patch="@@ -1,2 +1,3 @@\n def old():\n+    bad_name = True\n     return 1",
                content="def old():\n    bad_name = True\n    return 1",
            )
        ]
        self.checks = [
            CheckResult(
                "naming",
                "naming",
                "fail",
                "One issue.",
                [
                    Finding(
                        file="src/module.py",
                        line=2,
                        message="Name does not follow the standard.",
                        severity="medium",
                        reasoning="Use snake_case.",
                        potential_solution="Rename the variable.",
                    )
                ],
            )
        ]

    def test_posts_resolvable_inline_comment_for_diff_line(self):
        client = FakeGitHubClient()

        posted, skipped = post_inline_finding_comments(
            client,
            self.pull_request,
            self.checks,
            self.changed_files,
        )

        self.assertEqual((posted, skipped), (1, 0))
        url, method, payload = client.requests[-1]
        self.assertEqual(url, self.pull_request.review_comments_url)
        self.assertEqual(method, "POST")
        self.assertEqual(payload["path"], "src/module.py")
        self.assertEqual(payload["line"], 2)
        self.assertEqual(payload["side"], "RIGHT")
        self.assertEqual(payload["commit_id"], "head456")
        self.assertIn("Rename the variable.", payload["body"])
        self.assertIn("<!-- ai-pr-standardization-finding:", payload["body"])

    def test_leaves_non_diff_findings_in_summary_only(self):
        self.checks[0].findings[0].line = 50
        client = FakeGitHubClient()

        posted, skipped = post_inline_finding_comments(
            client,
            self.pull_request,
            self.checks,
            self.changed_files,
        )

        self.assertEqual((posted, skipped), (0, 1))
        self.assertEqual(client.requests, [])

    def test_updates_existing_inline_comment_instead_of_duplicating(self):
        client = FakeGitHubClient(
            comments=[
                {
                    "url": "https://api.github.com/repos/acme/example/pulls/comments/1",
                    "body": (
                        "<!-- ai-pr-standardization-finding:"
                        "d3adb33fd3adb33fd3ad -->\nOld finding"
                    ),
                }
            ]
        )
        from src.github.pr_commenter import _finding_marker

        client.comments[0]["body"] = _finding_marker(
            self.checks[0].check_id,
            self.checks[0].findings[0],
        )

        posted, skipped = post_inline_finding_comments(
            client,
            self.pull_request,
            self.checks,
            self.changed_files,
        )

        self.assertEqual((posted, skipped), (1, 0))
        self.assertEqual(client.requests[-1][1], "PATCH")
        self.assertEqual(
            client.requests[-1][0],
            "https://api.github.com/repos/acme/example/pulls/comments/1",
        )


if __name__ == "__main__":
    unittest.main()
