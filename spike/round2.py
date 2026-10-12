import typst, tempfile, os
from pypdf import PdfReader
from pdfminer.high_level import extract_text
BODY = r'''
*Staff Engineer — Fictional Fintech* #h(1fr) 2020 – Present
- Designed an affiliate reconciliation flow; first-in-first-out "fit" guarantees.

*Backend Engineer — Example Bank* #h(1fr) 2014 – 2020
- Built an efficient, fault-tolerant official workflow.
'''
CASES = {
  "libertinus+ligatures ON": '#set text(font: "Libertinus Serif")',
  "libertinus+ligatures OFF": '#set text(font: "Libertinus Serif", ligatures: false, discretionary-ligatures: false, historical-ligatures: false)\n#set smartquote(enabled: false)',
  "no system fonts, OFF": '#set text(ligatures: false)',
}
d = tempfile.mkdtemp()
for name, pre in CASES.items():
    src = os.path.join(d, "t.typ"); out = os.path.join(d, "t.pdf")
    open(src, "w").write('#set page(paper: "us-letter")\n' + pre + BODY)
    typst.compile(src, output=out, ignore_system_fonts=name.startswith("no system"))
    r = PdfReader(out)
    fonts = sorted({str(f.get_object()["/BaseFont"]) for f in r.pages[0]["/Resources"]["/Font"].values()})
    a, b = r.pages[0].extract_text(), extract_text(out)
    print(f"===== {name} fonts={fonts}")
    print("pypdf   :", repr(a))
    print("pdfminer:", repr(b.strip()))
