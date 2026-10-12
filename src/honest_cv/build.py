"""Build CV files for a profile: one entry point shared by the CLI and the MCP server."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from honest_cv import document
from honest_cv.model import Lang, Source
from honest_cv.render.docx import render_docx
from honest_cv.render.pdf import fit_pages

FORMATS = ("pdf", "docx")


@dataclass
class Built:
    path: Path
    variant: str
    lang: Lang
    format: str
    pages: int | None = None  # PDF only
    fits: bool | None = None  # PDF only: within the variant's max_pages


def file_stem(name: str, variant: str, lang: Lang) -> str:
    safe = re.sub(r"[^\w]+", "_", name, flags=re.UNICODE).strip("_")
    return f"{safe}_CV_{variant}_{lang.upper()}"


def build_cv(
    source: Source, variant: str, lang: Lang, out_dir: Path, formats: tuple[str, ...] = FORMATS
) -> list[Built]:
    doc = document.build(source, variant, lang)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem(doc.name, variant, lang)
    results = []
    if "pdf" in formats:
        fit = fit_pages(doc)
        path = out_dir / f"{stem}.pdf"
        path.write_bytes(fit.pdf)
        results.append(Built(path, variant, lang, "pdf", fit.pages, fit.fits))
    if "docx" in formats:
        path = out_dir / f"{stem}.docx"
        path.write_bytes(render_docx(doc))
        results.append(Built(path, variant, lang, "docx"))
    return results
