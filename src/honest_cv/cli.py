"""Command-line entry point."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from honest_cv import __version__, store
from honest_cv.build import FORMATS, build_cv
from honest_cv.model import LANGS, LEVEL_RANK, Level, ProfileError, explain, load
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
        confirmed = input("Is this true, and can you defend it in an interview? [y/N] ").strip().lower() in ("y", "yes", "s", "si", "sí")
        if not confirmed:
            print("Not saved.")
            return 1
    skill = store.upsert_skill(
        args.profile, args.name, new, evidence=args.evidence, confirmed=confirmed,
        years=args.years, last_used_year=args.last_used_year, aliases=args.alias, notes=args.notes,
    )
    print(f"Saved {skill.name}: {skill.level}")
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
