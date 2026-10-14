"""Command-line entry point."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from honest_cv import __version__, checklist, importer, letter, store
from honest_cv.build import FORMATS, build_cv
from honest_cv.model import LANGS, LEVEL_RANK, Level, ProfileError, explain, is_yes, load
from honest_cv.score import Gap, Keyword, Status, score_job
from honest_cv.verify import Report, verify_pdf




def cmd_build(args: argparse.Namespace) -> int:
    source = load(args.profile)
    variants = args.variant or list(source.variants)
    if not variants:
        print(f"{args.profile}: no variants defined in variants.yaml", file=sys.stderr)
        return 1
    status = 0
    for variant in variants:
        for lang in args.lang or ["en"]:
            for b in build_cv(source, variant, lang, Path(args.out), tuple(args.format or FORMATS)):
                note = ""
                if b.pages is not None:
                    note = f"  {b.pages} page(s)"
                    if not b.fits:
                        note += " — over the variant's max_pages"
                        status = 1
                print(f"{b.path}{note}")
                if b.report is not None and not b.report.ok:
                    print_failures(b.report)
                    status = 1
    return status


def print_failures(report: Report) -> None:
    for c in report.failures:
        print(f"  FAIL {c.name}: {c.detail}")


def cmd_verify(args: argparse.Namespace) -> int:
    status = 0
    for path in args.pdf:
        report = verify_pdf(path, max_pages=args.max_pages)
        print(f"{path}  {report.pages} page(s)  {'OK' if report.ok else 'FAIL'}")
        for c in report.checks:
            if not c.ok or args.verbose:
                print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}{': ' + c.detail if c.detail else ''}")
        if args.text:
            print(report.text)
        status |= not report.ok
    return status


def cmd_init(args: argparse.Namespace) -> int:
    for path in store.init_profile(args.profile):
        print(path)
    print("Fill these in, or let your MCP client interview you. Keep real profiles out of git.")
    return 0


def cmd_skill(args: argparse.Namespace) -> int:
    current = load(args.profile).inventory.get(args.name)
    old, new = (current.level if current else Level.NONE), Level(args.level)
    confirmed = False
    if LEVEL_RANK[new] > LEVEL_RANK[old]:
        if not sys.stdin.isatty():
            print("error: raising a level needs an interactive confirmation", file=sys.stderr)
            return 1
        print(f"Upgrade {args.name}: {old} -> {new}\nEvidence: {args.evidence}")
        confirmed = is_yes(input("Is this true, and can you defend it in an interview? [y/N] "))
        if not confirmed:
            print("Not saved.")
            return 1
    skill = store.upsert_skill(
        args.profile, args.name, new, evidence=args.evidence, confirmed=confirmed,
        years=args.years, last_used_year=args.last_used_year, aliases=args.alias, notes=args.notes,
    )
    print(f"Saved {skill.name}: {skill.level}")
    return 0


PENDING_SHOWN = 15


def cmd_checklist_list(args: argparse.Namespace) -> int:
    for b in checklist.available():
        print(f"{b.id:<18} {b.skills:>3} skills  {b.title}: {b.description}")
    return 0


def cmd_checklist_new(args: argparse.Namespace) -> int:
    ids = _split(args.lists)
    if not ids:
        print("error: name one or more checklists, e.g. backend-jvm,engineering-lead", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else Path(args.profile).expanduser() / "checklist.md"
    if out.exists() and not args.force:
        print(f"error: {out} exists; use --force to replace it, or --out for another file", file=sys.stderr)
        return 1
    out.write_text(checklist.compose(ids, load(args.profile)), encoding="utf-8")
    print(f"{out}\nMark each line in your editor, then run: honest-cv checklist apply {args.profile} {out}")
    return 0


def cmd_checklist_apply(args: argparse.Namespace) -> int:
    source = load(args.profile)
    plan = checklist.plan(source, checklist.read(args.file))
    for problem in plan.problems:
        print(f"note: {problem}")
    if plan.updates:
        print(f"{len(plan.updates)} change(s) that keep or lower a level (X, same level, details).")
    if plan.upgrades:
        print(checklist.describe(plan.upgrades, source))
    if plan.pending:
        print(f"\n{len(plan.pending)} marked line(s) need evidence before they can be saved:")
        for item in plan.pending[:PENDING_SHOWN]:
            print(f"  line {item.line}: [{item.mark}] {item.name}")
        if len(plan.pending) > PENDING_SHOWN:
            print(f"  ... and {len(plan.pending) - PENDING_SHOWN} more")
        print("Add it after ' — ' on the line, or as an 'evidence: ...' line under the section heading,\n"
              "then run this again. An MCP client can also ask you for it in groups.")
    if plan.unsure:
        print(f"{len(plan.unsure)} line(s) marked [?] were skipped.")
    if not plan.changes:
        print("Nothing to save.")
        return 0
    if not sys.stdin.isatty():
        print("error: saving a checklist needs an interactive confirmation", file=sys.stderr)
        return 1
    if not is_yes(input(f"\nSave {len(plan.changes)} change(s)? [y/N] ")):
        print("Not saved.")
        return 1
    saved = store.upsert_skills(args.profile, plan.changes, confirmed=True)
    print(f"Saved {len(saved)} skill(s).")
    return 0


def _paragraphs(path: Path) -> list[str]:
    """A letter file is plain text: paragraphs separated by blank lines."""
    text = Path(path).expanduser().read_text(encoding="utf-8")
    return [" ".join(p.split()) for p in text.split("\n\n") if p.strip()]


def _print_claims(claims: letter.Claims) -> None:
    for f in claims.problems:
        print(f"  PROBLEM {f.term} ({f.kind}): {f.detail}\n    in: {f.sentence}")
    for f in claims.warnings:
        print(f"  check   {f.term} ({f.kind}): {f.detail}\n    in: {f.sentence}")


def cmd_letter_check(args: argparse.Namespace) -> int:
    claims = letter.check_claims("\n\n".join(_paragraphs(args.file)), load(args.profile), _split(args.keyword))
    if claims.ok and not claims.warnings:
        print("OK: nothing the profile does not support.")
    _print_claims(claims)
    return 0 if claims.ok else 1


def cmd_letter_build(args: argparse.Namespace) -> int:
    source = load(args.profile)
    draft = letter.make(source, args.lang, args.company, args.role, _paragraphs(args.file), recipient=args.recipient)
    claims = letter.check_claims("\n\n".join(draft.paragraphs), source, _split(args.keyword))
    _print_claims(claims)
    if not claims.ok:
        print("Not built: fix the problems above by removing or qualifying those claims.", file=sys.stderr)
        return 1
    status = 0
    for b in letter.build(draft, Path(args.out), tuple(args.format or letter.FORMATS)):
        print(f"{b.path}" + (f"  {b.report.pages} page(s)" if b.report else ""))
        if b.report is not None and not b.report.ok:
            print_failures(b.report)
            status = 1
    return status


def cmd_import(args: argparse.Namespace) -> int:
    report = importer.merge(args.profile, importer.read(args.file), dry_run=args.dry_run)
    print("Would add:" if args.dry_run else "Added:")
    for what, names in report.added.items():
        print(f"  {what}: {', '.join(names)}")
    for what, names in report.skipped.items():
        print(f"  skipped {what}: {', '.join(names)}")
    if report.skills_checklist:
        state = "kept as it was (it may hold your marks)" if report.skills_checklist_kept else "written to"
        print(f"{report.skills} skill(s), without levels, {state}: {report.skills_checklist}\n"
              f"Mark it, then run: honest-cv checklist apply {args.profile} {report.skills_checklist}")
    if not args.dry_run and report.added.get("bullets"):
        print("Imported achievements are tagged 'imported' in bullets.yaml: review their wording.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    what = f"{args.kind} '{args.id}'" + (" and its bullets" if getattr(args, "with_bullets", False) else "")
    if not sys.stdin.isatty():
        print("error: removing needs an interactive confirmation", file=sys.stderr)
        return 1
    if not is_yes(input(f"Remove {what} from {args.profile}? It cannot be undone. [y/N] ")):
        print("Nothing removed.")
        return 1
    if args.kind == "skill":
        result = store.remove_skill(args.profile, args.id)
    elif args.kind == "bullet":
        result = store.remove_bullet(args.profile, args.id)
    else:
        result = store.remove_role(args.profile, args.id, with_bullets=args.with_bullets)
    print(f"Removed {result['removed']}.")
    if result.get("bullets_removed"):
        print(f"  bullets removed: {', '.join(result['bullets_removed'])}")
    if result["variants_updated"]:
        print(f"  variants updated: {', '.join(result['variants_updated'])}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    from honest_cv.server import main as serve

    if args.profile:
        os.environ["HONEST_CV_PROFILE"] = args.profile
    serve()
    return 0


def _split(values: list[str] | None) -> list[str]:
    return [t.strip() for v in values or [] for t in v.split(",") if t.strip()]


GAP_HINT = {
    Gap.IN_INVENTORY_NOT_IN_CV: "you have it; add it to this variant",
    Gap.FAMILIARITY_ONLY: "familiarity only",
    Gap.NOT_IN_INVENTORY: "you don't have it",
}


def cmd_score(args: argparse.Namespace) -> int:
    source = load(args.profile)
    keywords = [Keyword(t) for t in _split(args.keyword)] + [Keyword(t, required=False) for t in _split(args.preferred)]
    if not keywords:
        print("error: give keywords with -k (required) and/or -p (preferred)", file=sys.stderr)
        return 1
    scores = score_job(source, keywords, args.lang, args.variant)
    if args.json:
        print(json.dumps([s.to_dict() for s in scores], ensure_ascii=False, indent=2))
        return 0
    for s in scores:
        print(f"{s.variant} [{s.lang}]  required {s.required_coverage:.0%}  overall {s.coverage:.0%}")
        for r in s.keywords:
            mark = {Status.FOUND: "+", Status.FOUND_AS_FAMILIARITY: "~", Status.MISSING: "-"}[r.status]
            line = f"  {mark} {r.keyword}{'' if r.required else ' (preferred)'}"
            if r.matched_as and r.matched_as != r.keyword:
                line += f"  as '{r.matched_as}'"
            if r.gap:
                line += f"  — {GAP_HINT[r.gap]}"
            if r.unused_bullets:
                line += f" (bullets: {', '.join(r.unused_bullets)})"
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="honest-cv", description="Honest, ATS-safe CVs from a single source of truth."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="run the MCP server over stdio")
    p.add_argument("--profile", help="default profile folder for every tool (or set HONEST_CV_PROFILE)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("init", help="create a profile folder with commented YAML templates")
    p.add_argument("profile")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("skill", help="add or change a skill; raising a level asks you to confirm")
    p.add_argument("profile")
    p.add_argument("name")
    p.add_argument("level", choices=[lvl.value for lvl in Level])
    p.add_argument("--evidence", help="where and how you used it; required to raise a level")
    p.add_argument("--years", type=float, help="years of use, e.g. 2.5")
    p.add_argument("--last-used-year", type=int, help="last calendar year you used it, e.g. 2026")
    p.add_argument("--alias", action="append", help="another spelling, e.g. k8s; repeatable")
    p.add_argument("--notes", help="private notes, never printed on the CV")
    p.set_defaults(func=cmd_skill)

    p = sub.add_parser("checklist", help="mark many skills at once in a Markdown checklist")
    checklist_sub = p.add_subparsers(dest="checklist_command", required=True)
    c = checklist_sub.add_parser("list", help="show the built-in checklists")
    c.set_defaults(func=cmd_checklist_list)
    c = checklist_sub.add_parser("new", help="merge built-in checklists into one, prefilled from your inventory")
    c.add_argument("profile")
    c.add_argument("lists", nargs="+", help="checklist ids, e.g. backend-jvm engineering-lead")
    c.add_argument("-o", "--out", help="file to write (default: <profile>/checklist.md)")
    c.add_argument("--force", action="store_true", help="replace the file if it exists")
    c.set_defaults(func=cmd_checklist_new)
    c = checklist_sub.add_parser("apply", help="save the marked lines; upgrades ask you to confirm once")
    c.add_argument("profile")
    c.add_argument("file", type=Path, help="a checklist in Markdown, e.g. <profile>/checklist.md")
    c.set_defaults(func=cmd_checklist_apply)

    p = sub.add_parser("remove", help="delete a skill, bullet or role, and its uses in the variants")
    p.add_argument("kind", choices=["skill", "bullet", "role"])
    p.add_argument("profile")
    p.add_argument("id", help="skill name, bullet id or role id")
    p.add_argument("--with-bullets", action="store_true", help="role only: also delete its bullets")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("import", help="import JSON Resume (.json) or a LinkedIn data export (.zip)")
    p.add_argument("profile", help="profile folder; created if it does not exist")
    p.add_argument("file", type=Path)
    p.add_argument("--dry-run", action="store_true", help="show what would be added, write nothing")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("letter", help="check and render a cover letter written in a text file")
    letter_sub = p.add_subparsers(dest="letter_command", required=True)
    c = letter_sub.add_parser("check", help="flag claims the profile does not support")
    c.add_argument("profile")
    c.add_argument("file", type=Path, help="plain text, paragraphs separated by blank lines")
    c.add_argument("-k", "--keyword", action="append", help="job post keywords, comma-separated; repeatable")
    c.set_defaults(func=cmd_letter_check)
    c = letter_sub.add_parser("build", help="render PDF and DOCX after checking the claims")
    c.add_argument("profile")
    c.add_argument("file", type=Path, help="plain text, paragraphs separated by blank lines")
    c.add_argument("--company", required=True)
    c.add_argument("--role", required=True, help="job title, as in the post")
    c.add_argument("--recipient", help="hiring manager or team, if the post names one")
    c.add_argument("-l", "--lang", choices=LANGS, default="en")
    c.add_argument("-k", "--keyword", action="append", help="job post keywords, comma-separated; repeatable")
    c.add_argument("-f", "--format", action="append", choices=letter.FORMATS)
    c.add_argument("-o", "--out", default="out", help="output folder (default: out)")
    c.set_defaults(func=cmd_letter_build)

    p = sub.add_parser("build", help="render PDF and DOCX for one or more variants")
    p.add_argument("profile", help="profile folder (profile.yaml, bullets.yaml, skills.yaml, variants.yaml)")
    p.add_argument("-v", "--variant", action="append", help="variant id; repeatable (default: all)")
    p.add_argument("-l", "--lang", action="append", choices=LANGS, help="language; repeatable (default: en)")
    p.add_argument("-f", "--format", action="append", choices=FORMATS, help="repeatable (default: pdf and docx)")
    p.add_argument("-o", "--out", default="out", help="output folder (default: out)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="check that PDFs are ATS-safe (works on any PDF)")
    p.add_argument("pdf", nargs="+", type=Path)
    p.add_argument("--max-pages", type=int)
    p.add_argument("--verbose", action="store_true", help="also list passing checks")
    p.add_argument("--text", action="store_true", help="print the text an ATS would extract")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("score", help="keyword coverage per variant, with gaps against your inventory")
    p.add_argument("profile")
    p.add_argument("-k", "--keyword", action="append", help="required keywords, comma-separated; repeatable")
    p.add_argument("-p", "--preferred", action="append", help="nice-to-have keywords, comma-separated; repeatable")
    p.add_argument("-v", "--variant", action="append", help="variant id; repeatable (default: all)")
    p.add_argument("-l", "--lang", choices=LANGS, default="en")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_score)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (ProfileError, ValidationError, ValueError) as e:
        print(f"error: {explain(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
