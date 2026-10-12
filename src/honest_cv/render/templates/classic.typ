// Classic one-column, ATS-safe CV.
// Data comes in as JSON through sys.inputs and is only ever inserted as text,
// never evaluated as markup. Reading order is source order.

#let d = json(bytes(sys.inputs.data))
#let size = float(sys.inputs.size) * 1pt
#let leading = float(sys.inputs.leading) * 1em
#let section-gap = float(sys.inputs.section_gap) * 1mm
#let item-gap = float(sys.inputs.item_gap) * 1mm

#set document(title: d.name + " - " + d.title, author: d.name)
#set page(paper: "us-letter", margin: (x: 13mm, y: 11mm), header: none, footer: none)
#set text(
  font: "Carlito",
  size: size,
  lang: d.lang,
  ligatures: false,
  discretionary-ligatures: false,
  historical-ligatures: false,
  hyphenate: false,
)
#set smartquote(enabled: false)
#set par(justify: false, leading: leading, spacing: leading + item-gap)
#set list(marker: [•], indent: 1mm, body-indent: 2mm, spacing: leading + item-gap)
#show heading.where(level: 1): set text(size: size * 1.9, weight: "bold")
#show heading.where(level: 2): it => block(above: section-gap + 1mm, below: 1.2mm, text(size: size * 1.2, weight: "bold", it.body))

#let line-of(items) = items.join(" · ")

= #d.name
#text(size: size * 1.15, weight: "bold", d.title)

#line-of(d.contact)

== #d.headings.summary
#d.summary

#if d.competencies.len() > 0 [
  == #d.headings.competencies
  #line-of(d.competencies)
]

#if d.impact.len() > 0 [
  == #d.headings.impact
  #for b in d.impact [- #b
  ]
]

#if d.roles.len() > 0 [
  == #d.headings.experience
  #for r in d.roles {
    block(above: section-gap, below: 1mm, [#strong(r.heading) · #r.dates])
    if r.context != none { par(r.context) }
    for b in r.bullets [- #b
    ]
  }
]

#if d.skills.len() > 0 [
  == #d.headings.skills
  #for s in d.skills { par[#strong(s.label + ":") #s.skills.join(", ")] }
]

#if d.education.len() > 0 [
  == #d.headings.education
  #for e in d.education { par(e) }
]

#if d.certifications.len() > 0 [
  == #d.headings.certifications
  #for c in d.certifications { par(c) }
]

#if d.languages != none [
  == #d.headings.languages
  #d.languages
]
