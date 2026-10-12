import sys
from pypdf import PdfReader
from pdfminer.high_level import extract_text
LIGS = ["ﬀ", "ﬁ", "ﬂ", "ﬃ", "ﬄ"]
for name in ("typst", "chrome"):
    p = f"{sys.path[0]}/{name}.pdf"
    r = PdfReader(p)
    a, b = "\n".join(pg.extract_text() for pg in r.pages), extract_text(p)
    fonts = sorted({str(f.get_object().get("/BaseFont")) for pg in r.pages for f in (pg["/Resources"].get("/Font") or {}).values()})
    print(f"===== {name}: pages={len(r.pages)} fonts={fonts}")
    for lib, txt in (("pypdf", a), ("pdfminer", b)):
        print(f"--- {lib}: ligature glyphs={[l for l in LIGS if l in txt]} soft-hyphen={'­' in txt}")
        print(txt.strip())
