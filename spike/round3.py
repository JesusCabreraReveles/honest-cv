import typst, tempfile, os
from pdfminer.high_level import extract_text
d = tempfile.mkdtemp(); src, out = os.path.join(d, "t.typ"), os.path.join(d, "t.pdf")
open(src, "w").write('''#set page(paper: "us-letter")
#set text(ligatures: false)
*Staff Engineer — Fictional Fintech* · 2020 – Present
- Designed an affiliate reconciliation flow.

*Backend Engineer — Example Bank* · 2014 – 2020
- Built an efficient workflow.
''')
typst.compile(src, output=out, ignore_system_fonts=True)
print(repr(extract_text(out).strip()))
