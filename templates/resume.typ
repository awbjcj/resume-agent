// Single-column, ATS-parseable resume. Data arrives as a JSON string in
// `sys.inputs.data` (see render/renderer.py) and is decoded here.
//
// Visual language ported from the classic "Jake's Resume" LaTeX template:
// centered small-caps header, bold-caps section titles under a full-width
// rule, two-row bold/italic subheadings (entity+dates, then role+location),
// and tight zero-indent bullets. Typst is the only rendering engine wired up
// (render/renderer.py calls typst.compile — there is no LaTeX toolchain in
// this repo), so the LaTeX macros below are reimplemented as Typst functions
// rather than transliterated.
#let data = json(bytes(sys.inputs.data))
#let contact = data.contact

// `zoom` is an auto-fit factor the renderer sweeps down from 1.0 until the
// resume fits one page (see render/renderer.py). All sizes below are expressed
// in em (relative to this base) so a single base-size change cascades through
// the whole layout — section titles, header, and vertical gaps all shrink
// proportionally, keeping the design intact at any zoom.
#let zoom = float(sys.inputs.at("zoom", default: "1.0"))

#set document(title: contact.name)
#set page(margin: (x: 1.4cm, y: 1.3cm))
#set text(size: 10pt * zoom)
#set par(justify: false, leading: 0.46em)
#set list(indent: 0pt, marker: [•], spacing: 0.4em)

#let section-title(t) = [
  #v(0.4em)
  #text(size: 1.2em, weight: "bold")[#upper(t)]
  #v(-0.6em)
  #line(length: 100%, stroke: 0.6pt)
  #v(0.2em)
]

// --- Tech-stack + metric highlighting -------------------------------------
// The LLM emits plain bullet text (never markup — fact-lock). To echo the
// reference LaTeX template's bold tech terms and metrics, we bold — at render
// time only — any occurrence of a known skill/tech keyword or a numeric metric
// (e.g. "37%", "$20,000", "1200+"). Purely visual: the extracted ATS text is
// byte-identical and no new claims are introduced.
//
// Typst's regex engine (Rust) has no lookbehind, so we run one combined
// alternation and reject partial hits by inspecting the grapheme clusters
// on either side of each match (keeps the "1" in "L1-L3" from bolding).
#let _alnum = regex("^[A-Za-z0-9]$")
#let _is-alnum(c) = c != "" and c.matches(_alnum).len() > 0

#let highlight(body, keywords) = {
  // Escape regex metacharacters in keywords; match longest first so
  // "JavaScript" wins over "Java" and "AWS Lambda" over "AWS".
  let esc = keywords
    .filter(k => k != none and k != "")
    .sorted(key: k => -k.len())
    .map(k => k.replace(regex("[.^$|?*+()\\[\\]{}\\\\]"), m => "\\" + m.text))
  let metric = "\\$?\\d(?:[\\d,]*\\d)?(?:\\.\\d+)?[%+kKMBxX]?"
  let pat = regex("(?i)(" + (esc + (metric,)).join("|") + ")")
  let out = []
  let cursor = 0
  for m in body.matches(pat) {
    let pre = body.slice(cursor, m.start)
    let before = pre.clusters().at(-1, default: "")
    let after = body.slice(m.end).clusters().at(0, default: "")
    if _is-alnum(before) or _is-alnum(after) {
      out += [#(pre + m.text)]  // glued to a word — leave unstyled
    } else {
      out += [#pre] + strong(m.text)
    }
    cursor = m.end
  }
  out += [#body.slice(cursor)]
  out
}

// Union of this resume's selected skills and per-project tech — the exact
// tech stack chosen for this JD, reused as the highlight dictionary.
#let tech-keywords = {
  let ks = ()
  for (_, items) in data.at("skills", default: (:)) {
    for s in items { ks.push(s.name) }
  }
  for p in data.at("projects", default: ()) {
    for t in p.at("tech", default: ()) { ks.push(t) }
  }
  ks
}

#let maybe-join(values) = values.filter(x => x != none and x != "").join(", ")

// Two-row subheading: row1 is bold (entity — dates), row2 is italic
// (role/degree — location), mirroring \resumeSubheading in Jake's template.
// Pass `none` for either row2 slot to omit it.
#let subheading(row1-left, row1-right, row2-left, row2-right) = [
  #grid(
    columns: (1fr, auto),
    [*#row1-left*], align(right)[*#row1-right*],
  )
  #if row2-left != none or row2-right != none [
    #grid(
      columns: (1fr, auto),
      emph[#(if row2-left != none { row2-left } else { [] })],
      align(right)[#emph[#(if row2-right != none { row2-right } else { [] })]],
    )
  ]
]

// Header
#align(center)[
  #text(size: 1.9em, weight: "bold")[#smallcaps[#contact.name]]
  #if contact.at("headline", default: none) != none [
    \ #text(size: 1.05em, style: "italic")[#contact.headline]
  ]
  #let parts = (
    contact.at("location", default: none),
    contact.at("email", default: none),
    contact.at("phone", default: none),
  ).filter(x => x != none and x != "")
  #if parts.len() > 0 [ \ #text(size: 0.95em)[#parts.join("   |   ")] ]
  #let links = contact.at("links", default: ())
  #if links.len() > 0 [
    \ #text(size: 0.95em)[#links.map(l => underline[#link(l.url)[#l.label]]).join("   |   ")]
  ]
]
#v(-0.4em)

#let summary-block() = {
  let summary = data.at("summary", default: none)
  if summary != none and summary != "" {
    [
      #section-title("Summary")
      #highlight(summary, tech-keywords)
    ]
  }
}

#let experience-block() = {
  let xs = data.at("experience", default: ())
  if xs.len() > 0 {
    [
      #section-title("Experience")
      #for e in xs [
        #subheading(
          e.company,
          [#e.at("start", default: "") #h(2pt)–#h(2pt) #e.at("end", default: "Present")],
          e.title,
          e.at("location", default: none),
        )
        #for b in e.at("bullets", default: ()) [ - #highlight(b.text, tech-keywords) ]
        #v(0.2em)
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
        #let degree-field = if ed.at("degree", default: none) != none [
          #ed.degree#if ed.at("field", default: none) != none [, #ed.field]
        ] else { none }
        #subheading(
          ed.institution,
          [#ed.at("end", default: "")],
          degree-field,
          none,
        )
        #let tail = (
          if ed.at("gpa", default: none) != none { "GPA: " + ed.gpa } else { none },
          if ed.at("honors", default: ()).len() > 0 { ed.honors.join(", ") } else { none },
        ).filter(x => x != none and x != "")
        #if tail.len() > 0 [ #emph(tail.join("   |   ")) \ ]
        #let coursework = ed.at("relevant_coursework", default: ())
        #if coursework.len() > 0 [ #emph("Coursework: " + coursework.join(", ")) \ ]
        #v(4pt)
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
        #grid(
          columns: (1fr, auto),
          [*#p.name*#if p.at("description", default: none) != none [ — #p.description]],
          align(right)[
            #let tech = p.at("tech", default: ())
            #if tech.len() > 0 [*#tech.join("  |  ")*]
          ],
        )
        #for b in p.at("bullets", default: ()) [ - #highlight(b.text, tech-keywords) ]
        #v(0.2em)
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
      }).join("   |   ")
    ]
  }
}

#let volunteer-block() = {
  let xs = data.at("volunteer", default: ())
  if xs.len() > 0 {
    [
      #section-title("Volunteer")
      #for vol in xs [
        #subheading(
          vol.organization,
          [#vol.at("start", default: "") #h(2pt)–#h(2pt) #vol.at("end", default: "Present")],
          vol.at("role", default: none),
          none,
        )
        #if vol.at("description", default: none) != none [ #highlight(vol.description, tech-keywords) \ ]
        #for b in vol.at("bullets", default: ()) [ - #highlight(b.text, tech-keywords) ]
        #v(0.2em)
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
