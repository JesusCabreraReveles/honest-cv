"""Command-line entry point."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from honest_cv import __version__
from honest_cv.build import FORMATS, build_cv
from honest_cv.model import LANGS, ProfileError, load


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
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="honest-cv", description="Honest, ATS-safe CVs from a single source of truth."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("build", help="render PDF and DOCX for one or more variants")
    p.add_argument("profile", help="profile folder (profile.yaml, bullets.yaml, skills.yaml, variants.yaml)")
    p.add_argument("-v", "--variant", action="append", help="variant id; repeatable (default: all)")
    p.add_argument("-l", "--lang", action="append", choices=LANGS, help="language; repeatable (default: en)")
    p.add_argument("-f", "--format", action="append", choices=FORMATS, help="repeatable (default: pdf and docx)")
    p.add_argument("-o", "--out", default="out", help="output folder (default: out)")
    p.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (ProfileError, ValidationError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
