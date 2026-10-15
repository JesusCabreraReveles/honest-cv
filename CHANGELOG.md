# Changelog

All notable changes to honest-cv. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] — in development

Work on `master`.

### Added

- `export_json_resume` and `honest-cv export`: a variant as JSON Resume, in one language. X skills
  never appear and F skills keep their label; importing the file back gives the same profile.
- Your own checklist templates, for any profession: files in `<profile>/checklists/` show up in
  `checklist_list` and combine with the built-in ones in `checklist_new`, which also takes a path.
- `checklist_apply` returns `skills_without_achievements`, the P and L skills no bullet shows, and
  `key_skills_without_achievements`, the P ones in the ★ section or a variant. The assistant asks
  first for the person's biggest achievements, then for the key skills still uncovered. The rest
  wait for a job post: `gap_report` → `no_achievement` lists the ones it asks for.
- Templates can declare synonyms (`same: Work Breakdown Structure = WBS = EDT`). Those in
  `<profile>/checklists/` count in the job score, the gaps, checklist merging and the letter check,
  which also learns their skill names, so it works for any profession.
- An example template for another profession: `examples/checklists/project-management.md`.
- A built-in `software-architecture` checklist: styles and patterns, integration, quality
  attributes, data architecture and the practice (ADRs, reviews, technical debt). New synonyms:
  ADRs, ports and adapters, diseño de sistemas, CDC.
- Application tracking in `<profile>/applications.yaml`: `log_application`, `list_applications`
  and `honest-cv apps log|list`. Each status change keeps its date; open applications with no
  news for 14 days are listed as waiting.
- LinkedIn texts from a variant, within LinkedIn's limits: `linkedin_profile` (tool and prompt) and
  `honest-cv linkedin`. Headline, About, one description per position and the skills, P and L only.
- The interview handles dictated answers: it reads names and numbers back before saving them, and
  turns a long spoken answer into a bullet for the person to approve.
- A Courses section (`courses` in `profile.yaml`, set with `set_profile_details`) for training
  without an exam, which is not a certification. JSON Resume has no field for it, so the export
  leaves it out.
- The checklist header shows a marked example line.
- Publications: books, articles and papers the person wrote (`upsert_publication`,
  `remove_publication`), in their own CV section. A variant shows all of them or the ones it lists.
  The LinkedIn and JSON Resume imports read publications (and LinkedIn's courses), and the JSON
  Resume export writes them.
- Spanish spellings of leadership and practice terms in job posts (liderazgo de equipos, revisión
  de código, patrones de diseño, agentes de IA…) match the skill. In a letter, practices are not
  claims to check.
- Evidence must say where and how: the assistant asks for each skill instead of taking a bare
  "yes" to a list.
- The interview warns that it can take hours, proposes a first session that is enough for a CV,
  and picks up where it stopped. The READMEs say so too.
- The interview asks once for certifications, courses and anything the person wrote, which people
  rarely mention unasked.

### Changed

- The server's instructions cover checklists, dictated answers, applications, LinkedIn and export,
  for clients that don't load the skill.
- `checklist list` shows "(yours)" next to the title of your own templates.
- Clearer error for an application date that isn't YYYY-MM-DD.

### Fixed

- A checklist mark typed with spaces, like `[ P]`, was skipped in silence; it now counts, and
  any other text in the brackets is reported as a problem.
- A composed checklist's title said "imported skills" whenever the inventory had skills outside
  the chosen lists.

## [0.1.0] — unreleased, frozen

Frozen on the `release/0.1` branch on 2026-10-14; it will be published from there.

The first release: an MCP server, a CLI and a Claude Code skill that turn one profile folder into
honest, ATS-safe CVs and cover letters.

### Profile and honesty

- A profile is four YAML files: contact and roles, a pool of achievement bullets, a skill inventory
  and variants per type of role, with `extends:` inheritance. Texts can be per language (EN, ES).
- Skill levels: P (production), L (own project or lab), F (familiarity, always labeled as such)
  and X (never shown, but kept so gap reports are honest).
- Raising a level needs written evidence and the person's own confirmation. In MCP clients that
  support elicitation, a form asks "no / sí" for each upgrade, up to 10 at a time; elsewhere the
  CLI asks in the terminal. The model cannot confirm for the person.
- Tools to edit every part of the profile, each validating the whole profile before writing, and
  to remove a skill, bullet or role without leaving a broken reference.

### CVs

- PDF with Typst and the bundled Carlito font, the same on every machine with no system fonts;
  DOCX with python-docx. `fit_pages` adjusts density to meet a variant's page limit.
- ATS guarantees checked on every build with pypdf and pdfminer.six: one column, no ligatures,
  no kerning, no hyphenation, dates on their role's line, reading order, every bullet extracted,
  and terms like "CI/CD", URLs and emails never split across lines.
- `verify` checks any PDF, including CVs made with other tools.

### Job posts

- Keyword coverage per variant, with synonyms in English and Spanish.
- Gaps classified against the person's own inventory: in the inventory but not on this CV,
  familiarity only, or not held.

### Skill checklists

- Mark many skills at once in a Markdown file: one letter per line, evidence after " — ", an
  optional evidence line per section, years and last year used.
- Seven built-in checklists (backend JVM, Python and Go, frontend, platform/SRE, data,
  engineering leadership), merged without duplicates and prefilled from the inventory.
- Any checklist written by hand can be applied, in English or Spanish. Lines without evidence
  come back as pending and are asked about in groups.

### Cover letters

- `check_claims` reads any text against the profile. It blocks an X skill, or an F skill
  presented as experience, and warns about technologies and numbers the profile doesn't show.
- `build_letter` renders a one-page letter to PDF and DOCX with the CV's ATS checks, and refuses
  while there are problems.

### Import

- JSON Resume and LinkedIn's data export (ZIP of CSVs): contact, roles, achievements,
  education, certifications and languages. It only adds what is missing and never overwrites.
  Skills arrive without a level, as a checklist to mark.
- LinkedIn's profile PDF: the server returns its text and the client proposes each section for
  the person to approve.
- The export may be a ZIP or the folder a browser unzipped it into, and a profile may have no
  email. The report names the files the export lacks: LinkedIn's basic export has only the
  profile, without roles or email.

### Clients

- Tested in Claude Code (confirmation in the chat) and Claude Desktop (confirmation in a
  terminal). The server needs no API key and makes no network calls.

[0.1.0]: https://github.com/JesusCabreraReveles/honest-cv/releases/tag/v0.1.0
