# Contributing to honest-cv

Thanks for helping. Issues and pull requests are welcome, in English or Spanish.

## Ground rules

- **Never commit real personal data.** Tests, demos, screenshots and issues use only the fictional
  profile in `examples/ada/`. Put real profiles in `profiles/`, which is ignored by git, or outside
  the repository.
- **The code enforces honesty, not a prompt.**
  - An `F` skill is always rendered under the "Familiarity" / "Familiaridad" label.
  - An `X` skill is never rendered.
  - Raising a level requires `evidence` and the person's confirmation.

  A change that touches these rules must keep their tests passing, and a new rule needs a new test.
- **ATS guarantees are invariants.**
  - One column; no layout tables, images, icons, headers or footers.
  - Ligatures off; source order equals reading order.
  - Text extractable by pypdf and pdfminer.six.

  If a design idea breaks one of these, it doesn't go into the default template.
- **The server stays deterministic and keyless.** The MCP client's model does the language work;
  the server validates, builds, verifies and measures.
- **Scope.** The v0.1 scope is in [`docs/PLAN.md`](docs/PLAN.md). Larger ideas (JSON Resume
  import, LinkedIn import, cover letters, more templates) start as an issue.

## Setup

```bash
uv sync
uv run pytest                                   # the whole suite runs in a few seconds
uv run honest-cv build examples/ada -l en -l es # writes to out/
```

Python 3.11 or newer. Code, names and comments are in English.

## Useful pieces

| Path | What lives there |
|---|---|
| `src/honest_cv/model.py` | YAML schemas, `extends:` resolution and the skill-upgrade rule. |
| `src/honest_cv/document.py` | Turns a variant and a language into a document. The honesty rules apply here. |
| `src/honest_cv/render/` | The Typst template, the bundled fonts, the PDF renderer with `fit_pages`, and the DOCX renderer. |
| `src/honest_cv/verify.py` | ATS checks. |
| `src/honest_cv/score.py` | Keyword coverage, synonyms and gaps. |
| `src/honest_cv/server.py` | MCP tools and prompts. |
| `src/honest_cv/prompts/`, `skills/honest-cv/SKILL.md` | Conversation flows. A test keeps the tool names they mention in sync with the server. |

## Common contributions

- **Synonyms.** Add a group to `SYNONYMS` in `score.py`, with the canonical name first. Add a case
  to `tests/test_score.py`. Terms of three characters or fewer match case-sensitively.
- **Checklists.** Add `src/honest_cv/checklists/<id>.md` for a kind of role that is missing: a
  `# Title`, a one-line description, a `## ★ Main skills — years and last year used` section with
  the skills that filter the most, then sections by topic. Leave every line unmarked (`- [ ] Name`)
  and use the canonical names from `SYNONYMS`. `tests/test_checklist.py` checks all of this.
- **Templates.** A new template must pass `verify_pdf` with the Ada profile in both languages.
  Never put text in a box aligned to the right.
- **The demo GIF.** Regenerate it with `vhs docs/demo.tape` after the CLI output changes.
- **Packaging.** After `uv build`, `scripts/smoke.sh` checks the wheel on a clean Linux in
  Docker; the command is at the top of the script.

## Pull requests

- Keep each pull request small and focused, with tests.
- CI must pass on Linux, macOS and Windows.
- Describe what changes for the person using the tool.
