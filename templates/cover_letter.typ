// Cover letter. Data arrives as a JSON string in `sys.inputs.data`.
#let data = json(bytes(sys.inputs.data))
#let contact = data.contact

#set document(title: "Cover Letter - " + contact.name)
#set page(margin: (x: 2cm, y: 2cm))
#set text(size: 11pt)
#set par(justify: true, leading: 0.62em)

#align(right)[
  #text(weight: "bold", size: 13pt)[#contact.name] \
  #let bits = (
    contact.at("email", default: none),
    contact.at("phone", default: none),
  ).filter(x => x != none)
  #if bits.len() > 0 [ #bits.join(" / ") ]
]
#v(1.2em)

#let recipient = data.at("recipient", default: none)
#if recipient != none [ #recipient \ #v(0.6em) ]

#data.greeting
#v(0.6em)

#for p in data.at("paragraphs", default: ()) [
  #p.text
  #v(0.6em)
]

#data.closing
