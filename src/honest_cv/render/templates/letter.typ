// Cover letter, with the CV's ATS rules: one column, Carlito, no ligatures,
// no kerning, no hyphenation. Data comes in as JSON and is only inserted as text.

#let d = json(bytes(sys.inputs.data))

#set document(title: d.name + " - " + d.role, author: d.name)
#set page(paper: "us-letter", margin: (x: 22mm, y: 20mm), header: none, footer: none)
#set text(
  font: "Carlito",
  size: 11pt,
  lang: d.lang,
  ligatures: false,
  discretionary-ligatures: false,
  historical-ligatures: false,
  kerning: false,
  hyphenate: false,
)
#set smartquote(enabled: false)
#set par(justify: false, leading: 0.6em, spacing: 1.1em)
#show regex("[\w.+#]+(?:[/-][\w.+#]+)+"): it => box(it)

#text(size: 18pt, weight: "bold", d.name)

#d.contact.map(box).join(" · ")

#v(4mm)
#d.date

#if d.recipient != none [#d.recipient \ ]
#d.company

#v(2mm)
#strong(d.role + " — " + d.company)

#v(2mm)
#d.greeting

#for p in d.paragraphs [
  #par(p)
]

#v(2mm)
#d.closing

#v(8mm)
#d.name
