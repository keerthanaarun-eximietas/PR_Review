# AI PR Standardization

A Python command-line tool and GitHub Actions workflow for reviewing pull requests against coding
standards. It retrieves PR files, runs deterministic checks, optionally requests an AI review, and
produces JSON and Markdown reports.

## Project layout

```text
.github/workflows/ai-pr-review.yml    GitHub Actions PR and manual workflow
.ai-review/                           Default coding rules, guidance, and metadata
src/github/                           PR input, GitHub API access, and comments
src/standards/                        Base-branch standards discovery and parsing
src/analyzers/                        Deterministic naming, size, formatting, and secret checks
src/ai/                               Optional AI client and review context
src/reporting/                        JSON report and Markdown formatting
src/config/settings.py                Environment and default configuration
src/main.py                           CLI entry point and review orchestration
tests/                                Unit tests
requirements.txt                      Python runtime dependency declaration
```

## Requirements and local use

- Python 3.10 or later
- A GitHub token for private repositories or higher API rate limits. The program reads
  `GITHUB_TOKEN` or falls back to `gh auth token` when GitHub CLI is authenticated.

There are no third-party Python runtime dependencies. From the project root:

```powershell
python -m src.main --repo owner/repository --pr 123
```

The application automatically reads a `.env` file in the current project directory. For Groq, put
the Groq key and settings there:

```dotenv
GITHUB_TOKEN=your_github_token
GROQ_API_KEY=your_groq_api_key
PR_REVIEW_AI_ENDPOINT=https://api.groq.com/openai/v1/chat/completions
PR_REVIEW_AI_MODEL=your-groq-model-id
```

The `.env` file is git-ignored. Existing process environment variables take precedence over values
from `.env`. `GROQ_API_KEY` takes precedence over `AI_GATEWAY_API_KEY` and the legacy
`PR_REVIEW_AI_API_KEY`. Start the command from the project directory so it can find `.env`.

The CLI also accepts GitHub Actions context automatically:

```powershell
python -m src.main
```

In that form it reads `GITHUB_REPOSITORY` and the pull request number from the
`GITHUB_EVENT_PATH` payload. Useful options:

```text
--repo owner/repository   Repository (defaults to GITHUB_REPOSITORY)
--pr 123                  Pull request number (defaults to the event payload)
--output PATH             Report directory (default: ./pr-review-reports)
--allow-ai-upload         Explicitly permit the redacted diff to be sent to the AI endpoint
--no-comment              Generate reports without posting inline finding comments
```

The tool reads PR metadata and changed files from GitHub. It discovers standards on the PR's **base
branch**, then reads changed file contents at the PR's **head commit**. Deleted files are not scanned.
The base branch is used for standards so a pull request cannot change the rules that judge its own
changes.
After both reports are written, findings with a line represented in the pull request diff are posted
as individual inline review comments. These comments have resolvable GitHub conversation threads,
and reruns update the tool's existing inline thread rather than duplicating it. The tool does not
post an overall summary comment. Findings without a line number, or whose line is not present in the
diff, are available in the generated reports but are not posted to GitHub because GitHub cannot
anchor an inline review comment there. The GitHub token must have permission to write pull request
comments; use `--no-comment` to disable inline posting.

## Coding standards

The preferred standards files are `.ai-review/coding-standards.md` and
`.ai-review/coding-standards.json` on the base branch. The JSON file configures deterministic checks:

```json
{
  "filename_convention": "lower_snake_case",
  "function_name_convention": "snake_case",
  "variable_name_convention": "snake_case",
  "max_file_lines": 500,
  "max_function_lines": 80,
  "max_line_length": 120,
  "require_final_newline": true,
  "filename_exemptions": ["README.md", "LICENSE", "CHANGELOG.md"],
  "language_conventions": {
    "python": {
      "function_name_convention": "snake_case",
      "variable_name_convention": "snake_case"
    }
  }
}
```

Other recognized base-branch documents include `guidelines.md`, `GUIDELINES.md`,
`CONTRIBUTING.md`, `.github/CONTRIBUTING.md`, and `AGENTS.md`. Markdown can also provide automated
rules in a fenced block labelled `json pr-review-rules`; when a companion standards JSON file
exists, its values take precedence. Invalid or unknown settings cause a clear error.

If no standards document exists on the base branch, the tool inspects that exact base commit and
generates Markdown, JSON, and metadata under `pr-review-reports/.ai-review/`. It checks common
editor/linter configuration for line-length rules, then examines at most 40 Python, JavaScript, and
TypeScript source files (at most 15 per language), with 100 KB per file and 1 MB total source data.
It infers language-specific function and variable naming when at least three identifiers provide a
consistent signal, measures file and Python function lengths conservatively, and records the sample,
counts, confidence, skipped files, and warnings in `standards-metadata.json`. Insufficient evidence
retains the default for that rule. These are heuristics, not authoritative repository policy.

The report identifies these standards as `base_branch_inference` and records the base commit and
evidence. The standards are not committed back to the repository. Generated JSON can be customized;
when a later PR uses a different base commit, inferred rules are refreshed while edits to generated
rules are preserved. To make rules authoritative and version-controlled, add standards to the PR
base branch under `.ai-review/`.

## Deterministic checks

- **Naming:** validates changed filenames against the configured convention.
- **Function and variable names:** checks Python AST names and JavaScript/TypeScript function and
  variable declarations against their configured conventions. Unsupported languages are marked
  `skipped`.
- **File length:** counts lines in each changed file.
- **Function length:** uses Python AST parsing and supported-language scanning for JavaScript,
  TypeScript, Java, Kotlin, C#, C/C++, Go, and Rust. Unsupported languages are marked `skipped`.
- **Formatting:** checks final newlines, trailing whitespace, and maximum line length.
- **Hardcoded secrets:** detects common credential assignments (including camelCase names such as
  `gitToken`), known token prefixes, AWS access-key IDs, and private-key markers. This heuristic
  cannot guarantee that all secrets are detected.

## Optional AI review and privacy

The AI stage is limited to context-dependent review: architectural patterns and layer boundaries,
duplication against related code, error-handling consistency, unnecessary complexity, documented
design principles, and documentation accuracy. It must not repeat deterministic naming, size,
formatting, or secret checks. A post-review filter also suppresses AI findings that clearly restate
those deterministic check categories. The AI review is disabled unless both the environment is
configured and `--allow-ai-upload` is provided:

```powershell
$env:PR_REVIEW_AI_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
$env:GROQ_API_KEY = "..."
$env:PR_REVIEW_AI_MODEL = "your-groq-model-id"
python -m src.main --repo owner/repository --pr 123 --allow-ai-upload
```

The model ID must be available to your Groq account. The configured service must support an
OpenAI-compatible Chat Completions API and the requested response format. Groq documents this API at
`https://api.groq.com/openai/v1`; the review client already sends a Chat Completions request, so no
provider-specific Python SDK is required. The tool sends the standards text and PR diff to that
external endpoint. It redacts values
matched by its secret-detection patterns first, but redaction is heuristic and not a guarantee.
Only enable uploads when the applicable data-handling policy allows it. AI findings are suggestions,
not replacements for human review.
Each AI finding includes its reasoning and a potential solution. Suggested solutions are
recommendations for review, not automatic patches.
After the review, a separate bounded AI request generates potential solutions for any findings
without one, including deterministic naming, size, formatting, and secret findings. It uses the
finding, repository standards, and a short redacted excerpt from the changed file; it does not
re-evaluate findings or change deterministic check results. This request is also gated by
`--allow-ai-upload`. When uploads are disabled or suggestion generation fails, the finding remains
unchanged and the AI check details explain why a solution is unavailable.

### Large pull requests and retrieval

The AI review does not upload or index the whole repository. It splits every available PR diff into
bounded chunks, reviews each target chunk, and retrieves up to two lexically similar chunks from
other changed code as comparison context. This lightweight retrieval-augmented review uses identifier
and keyword similarity; it does not require embeddings, a vector database, or additional packages.
When GitHub omits a patch but provides file content, the reviewer chunks that content with line
numbers. If a chunk fails, the report records how many chunks completed and retains findings already
returned. The response parser accepts valid JSON wrapped in a Markdown code fence or brief
surrounding text. If a response is still malformed, it makes one bounded JSON-repair request; an
unrecoverable response remains an error rather than being treated as an empty successful review.

Chunking lowers the token cost of an individual request, but it does not raise Groq's account-level
tokens-per-minute quota; many chunks may still require multiple rate-limit windows. When Groq returns
a retry interval for a rate limit, the client waits and retries that request up to two times, for
intervals no longer than 120 seconds. If the limit persists, the AI check reports an error and the
review can be rerun later. The deterministic checks still run independently.

For Groq GPT-OSS models, requests use hidden reasoning, low reasoning effort, and a bounded
2,048-token completion budget to favor a concise final answer. The GPT-OSS 20B request uses Groq's
strict JSON-schema output for the findings shape; other configured models use JSON-object mode.
Empty responses are reported with finish reason, refusal/reasoning presence, and completion-token
metadata rather than passed to JSON repair or counted as a clean review. Responses stopped at the
completion limit are also reported as errors.

The GitHub Actions workflow runs for opened, updated, reopened, and ready-for-review PRs. It posts or
updates inline comments for findings and uploads both reports as a workflow artifact. AI upload is available
only by explicitly selecting it on a manual workflow run and configuring the
`PR_REVIEW_AI_ENDPOINT` / `PR_REVIEW_AI_MODEL` repository variables and either the `GROQ_API_KEY`
or `AI_GATEWAY_API_KEY` repository secret.

## Reports and exit status

The default output directory contains `pr-N-review.json` and `pr-N-review.md`. Every check has a
status (`pass`, `fail`, `skipped`, or `error`), a summary, and findings with severity, location, and
reasoning. The overall status is:

- `pass`: all checks passed.
- `fail`: at least one check found an issue.
- `incomplete`: no check failed, but a check was skipped or errored.

Exit codes are `0` for pass, `1` for fail or incomplete, and `2` for setup, API, standards, comment,
or report-writing errors. The GitHub Actions workflow uploads reports before failing the job when
the review result is `fail`.

## Tests

Run the standard-library unit tests with:

```powershell
python -m unittest discover -s tests -v
```
