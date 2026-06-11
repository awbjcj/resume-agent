// Single-column, ATS-parseable resume. Data arrives as a JSON string in
// `sys.inputs.data` (see render/renderer.py) and is decoded here.
#let data = json(bytes(sys.inputs.data))
#let contact = data.contact

#set document(title: contact.name)
#set page(margin: (x: 1.6cm, y: 1.4cm))
#set text(size: 10pt)
#set par(justify: false)

#let section-title(t) = [
  #v(6pt)
  #text(size: 12pt, weight: "bold", upper(t))
  #v(-4pt)
  #line(length: 100%, stroke: 0.5pt)
  #v(3pt)
]

#let maybe-join(values) = values.filter(x => x != none and x != "").join(", ")

// Header
#align(center)[
  #text(size: 18pt, weight: "bold")[#contact.name]
  #if contact.at("headline", default: none) != none [
    \ #text(size: 11pt)[#contact.headline]
  ]
  #let parts = (
    contact.at("location", default: none),
    contact.at("email", default: none),
    contact.at("phone", default: none),
  ).filter(x => x != none and x != "")
  #if parts.len() > 0 [ \ #parts.join("  •  ") ]
  #let links = contact.at("links", default: ())
  #if links.len() > 0 [
    \ #links.map(l => link(l.url)[#l.label]).join("  •  ")
  ]
]

#let summary-block() = {
  let summary = data.at("summary", default: none)
  if summary != none and summary != "" {
    [
      #section-title("Summary")
      #summary
    ]
  }
}

#let experience-block() = {
  let xs = data.at("experience", default: ())
  if xs.len() > 0 {
    [
      #section-title("Experience")
      #for e in xs [
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
  }
}

#let education-block() = {
  let xs = data.at("education", default: ())
  if xs.len() > 0 {
    [
      #section-title("Education")
      #for ed in xs [
        #grid(
          columns: (1fr, auto),
          [*#ed.institution*#if ed.at("degree", default: none) != none [ — #ed.degree#if ed.at("field", default: none) != none [, #ed.field]]],
          [#ed.at("end", default: "")],
        )
        #let tail = (
          if ed.at("gpa", default: none) != none { "GPA: " + ed.gpa } else { none },
          if ed.at("honors", default: ()).len() > 0 { ed.honors.join(", ") } else { none },
        ).filter(x => x != none and x != "")
        #if tail.len() > 0 [ #emph(tail.join("  •  ")) \ ]
        #let coursework = ed.at("relevant_coursework", default: ())
        #if coursework.len() > 0 [ #emph("Coursework: " + coursework.join(", ")) \ ]
        #v(2pt)
      ]
    ]
  }
}

#let projects-block() = {
  let xs = data.at("projects", default: ())
  if xs.len() > 0 {
    [
      #section-title("Projects")
      #for p in xs [
        *#p.name*#if p.at("description", default: none) != none [ — #p.description]
        #let tech = p.at("tech", default: ())
        #if tech.len() > 0 [ \ #emph("Tech: " + tech.join(", ")) ]
        #for b in p.at("bullets", default: ()) [ - #b.text ]
        #v(2pt)
      ]
    ]
  }
}

#let skills-block() = {
  let skills = data.at("skills", default: (:))
  if skills.len() > 0 {
    [
      #section-title("Skills")
      #for (category, items) in skills [
        *#category:* #items.map(s => s.name).join(", ") \
      ]
    ]
  }
}

#let publications-block() = {
  let xs = data.at("publications", default: ())
  if xs.len() > 0 {
    [
      #section-title("Publications")
      #for p in xs [
        #let meta = maybe-join((p.at("venue", default: none), p.at("date", default: none)))
        - #p.title#if meta != "" [ — #emph(meta)]
      ]
    ]
  }
}

#let certifications-block() = {
  let xs = data.at("certifications", default: ())
  if xs.len() > 0 {
    [
      #section-title("Certifications")
      #for c in xs [
        #let meta = maybe-join((c.at("issuer", default: none), c.at("date", default: none)))
        - *#c.name*#if meta != "" [ — #meta]
      ]
    ]
  }
}

#let awards-block() = {
  let xs = data.at("awards", default: ())
  if xs.len() > 0 {
    [
      #section-title("Awards")
      #for a in xs [
        #let meta = maybe-join((a.at("issuer", default: none), a.at("date", default: none)))
        - *#a.name*#if meta != "" [ — #meta]#if a.at("description", default: none) != none [. #a.description]
      ]
    ]
  }
}

#let languages-block() = {
  let xs = data.at("languages", default: ())
  if xs.len() > 0 {
    [
      #section-title("Languages")
      #xs.map(l => {
        let proficiency = l.at("proficiency", default: none)
        if proficiency == none or proficiency == "" {
          l.language
        } else {
          l.language + " (" + proficiency + ")"
        }
      }).join("  •  ")
    ]
  }
}

#let volunteer-block() = {
  let xs = data.at("volunteer", default: ())
  if xs.len() > 0 {
    [
      #section-title("Volunteer")
      #for vol in xs [
        *#vol.organization*#if vol.at("role", default: none) != none [ — #vol.role]
        #if vol.at("description", default: none) != none [ \ #vol.description]
        #for b in vol.at("bullets", default: ()) [ - #b.text ]
        #v(2pt)
      ]
    ]
  }
}

#let default-order = (
  "summary",
  "experience",
  "education",
  "projects",
  "skills",
  "publications",
  "certifications",
  "awards",
  "languages",
  "volunteer",
)

#let order = data.at("section_order", default: none)
#let chosen = if order == none { default-order } else { order }

#for section in chosen {
  if section == "summary" {
    summary-block()
  } else if section == "experience" {
    experience-block()
  } else if section == "education" {
    education-block()
  } else if section == "projects" {
    projects-block()
  } else if section == "skills" {
    skills-block()
  } else if section == "publications" {
    publications-block()
  } else if section == "certifications" {
    certifications-block()
  } else if section == "awards" {
    awards-block()
  } else if section == "languages" {
    languages-block()
  } else if section == "volunteer" {
    volunteer-block()
  }
}
