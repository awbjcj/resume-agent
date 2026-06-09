// Single-column, ATS-parseable resume. Data arrives as a JSON string in
// `sys.inputs.data` (see render/renderer.py) and is decoded here.
#let data = json(bytes(sys.inputs.data))
#let contact = data.contact

#set document(title: contact.name)
#set page(margin: (x: 1.6cm, y: 1.4cm))
#set text(size: 10pt)
#set par(justify: false)
#show heading.where(level: 1): it => [
  #v(6pt)
  #text(size: 12pt, weight: "bold", upper(it.body))
  #v(-4pt)
  #line(length: 100%, stroke: 0.5pt)
]

// Header
#align(center)[
  #text(size: 18pt, weight: "bold")[#contact.name]
  #if "headline" in contact and contact.headline != none [
    \ #text(size: 11pt)[#contact.headline]
  ]
  #let parts = (
    contact.at("location", default: none),
    contact.at("email", default: none),
    contact.at("phone", default: none),
  ).filter(x => x != none)
  #if parts.len() > 0 [ \ #parts.join("  •  ") ]
  #let links = contact.at("links", default: ())
  #if links.len() > 0 [
    \ #links.map(l => link(l.url)[#l.label]).join("  •  ")
  ]
]

#let summary = data.at("summary", default: none)
#if summary != none and summary != "" [
  = Summary
  #summary
]

#let experience = data.at("experience", default: ())
#if experience.len() > 0 [
  = Experience
  #for e in experience [
    #grid(
      columns: (1fr, auto),
      [*#e.title* — #e.company],
      [#e.at("start", default: "") #h(2pt)–#h(2pt) #e.at("end", default: "Present")],
    )
    #if e.at("location", default: none) != none [ #emph(e.location) \ ]
    #for b in e.at("bullets", default: ()) [ - #b.text ]
    #v(2pt)
  ]
]

#let projects = data.at("projects", default: ())
#if projects.len() > 0 [
  = Projects
  #for p in projects [
    *#p.name*#if p.at("description", default: none) != none [ — #p.description]
    #let tech = p.at("tech", default: ())
    #if tech.len() > 0 [ \ #emph("Tech: " + tech.join(", ")) ]
    #for b in p.at("bullets", default: ()) [ - #b.text ]
    #v(2pt)
  ]
]

#let skills = data.at("skills", default: (:))
#if skills.len() > 0 [
  = Skills
  #for (category, items) in skills [
    *#category:* #items.map(s => s.name).join(", ") \
  ]
]

#let education = data.at("education", default: ())
#if education.len() > 0 [
  = Education
  #for ed in education [
    *#ed.institution*#if ed.at("degree", default: none) != none [ — #ed.degree#if ed.at("field", default: none) != none [, #ed.field]]
    #if ed.at("end", default: none) != none [ #h(1fr) #ed.end ]
    \
  ]
]
