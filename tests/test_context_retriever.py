import unittest

from src.ai.context_retriever import (
    MAX_DIFF_CHUNK_CHARS,
    _file_chunks,
    build_review_contexts,
    retrieve_related_chunks,
    DiffChunk,
)
from src.models import ChangedFile


class ContextRetrieverTests(unittest.TestCase):
    def test_splits_large_diff_without_dropping_patch_lines(self):
        patch_lines = ["@@ -1,0 +1,300 @@"]
        patch_lines.extend(f"+result_{line_number} = search_index({line_number})" for line_number in range(300))
        changed_file = ChangedFile(
            "src/search.py",
            "modified",
            patch="\n".join(patch_lines),
        )

        chunks = _file_chunks(changed_file)

        self.assertGreater(len(chunks), 1)
        for line_number in range(300):
            self.assertTrue(any(f"+result_{line_number} =" in chunk for chunk in chunks))
        self.assertTrue(all(len(chunk) <= MAX_DIFF_CHUNK_CHARS for chunk in chunks))

    def test_retrieves_related_diff_from_another_changed_file(self):
        chunks = [
            DiffChunk(
                "### src/search.py\n+def binary_search(values):\n+    midpoint = len(values) // 2",
                frozenset({"src/search.py"}),
            ),
            DiffChunk(
                "### src/other.py\n+def linear_search(values):\n+    midpoint = len(values) // 2",
                frozenset({"src/other.py"}),
            ),
            DiffChunk(
                "### README.md\n+This project contains search algorithms and examples.",
                frozenset({"README.md"}),
            ),
        ]

        related = retrieve_related_chunks(chunks, 0)

        self.assertEqual(len(related), 2)
        self.assertEqual(related[0].files, frozenset({"src/other.py"}))

    def test_build_contexts_reviews_diff_and_redacts_secrets(self):
        contexts = build_review_contexts(
            "Follow small functions.",
            [
                ChangedFile(
                    "src/config.py",
                    "modified",
                    patch='+api_key = "secret-value-should-not-leak"',
                )
            ],
        )

        self.assertEqual(len(contexts), 1)
        self.assertIn("Target diff chunk", contexts[0])
        self.assertNotIn("secret-value-should-not-leak", contexts[0])

    def test_uses_numbered_current_content_when_diff_is_missing(self):
        contexts = build_review_contexts(
            "Standards",
            [ChangedFile("src/example.py", "modified", content="def check():\n    return True\n")],
        )

        self.assertEqual(len(contexts), 1)
        self.assertIn("full content because GitHub did not provide a diff", contexts[0])
        self.assertIn("    1 | def check():", contexts[0])
        self.assertIn("    2 |     return True", contexts[0])


if __name__ == "__main__":
    unittest.main()
