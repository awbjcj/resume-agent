"""Role-targeted craft guidance distilled from resume-writing playbooks.

These blocks teach HOW to write well; they never establish WHAT is true.
They are appended after the integrity (fact-lock) instructions and before
the user's house style, and must never contain wording that authorizes
inventing or embellishing evidence (guarded by tests/test_tailor_craft.py).
The fact-check reviewer deliberately has no entry here: it is the safety
gate, and holding its prompt fixed keeps trap-recall measurements
attributable to writer changes rather than checker drift.
"""

CRAFT_WRITER = [
    "Write every bullet as an accomplishment: lead with the outcome and its "
    "number when a cited profile fact supplies one, then the action that "
    "produced it. When the cited facts carry no number, lead with the concrete "
    "action and its scope instead.",
    "Start bullets with strong past-tense verbs such as built, shipped, scaled, "
    "reduced, led, or designed. Never open with duty phrasing like 'responsible "
    "for', 'helped with', 'worked on', or passive voice.",
    "Place the most role-relevant evidence in the top third of the resume, and "
    "order bullets within each role by relevance to this job rather than their "
    "original order.",
    "When a cited fact names the same thing the job names, prefer the job's "
    "exact term (a fact stating Amazon Web Services experience may be written "
    "as AWS). Cover a must-have skill both as a skills-section entry and inside "
    "one supporting bullet when the evidence exists.",
    "Keep the summary to at most three lines aimed at this role: seniority, the "
    "strongest matching skills, and one signature outcome, each supported by "
    "facts cited elsewhere in the resume.",
    "Prefer concrete nouns and numbers over adjectives, delete filler words, "
    "and keep each bullet under roughly thirty words.",
]

CRAFT_MATCH_PLAN = [
    "Plan coverage for every must-have requirement before any nice-to-have, "
    "and for each requirement prefer the strongest evidence: quantified "
    "outcomes over plain statements, recent over old, direct over transferable.",
]

CRAFT_REVIEWERS: dict[str, list[str]] = {
    "ats-keyword": [
        "Strong coverage places a must-have skill both as a skills-section "
        "entry and in context inside at least one bullet; a skills-list-only "
        "mention is weak coverage. Weight must-have coverage above "
        "nice-to-have coverage.",
        "Check that the summary or most recent title visibly aligns with the "
        "job's role name and seniority when the underlying evidence supports it.",
    ],
    "recruiter": [
        "Apply a six-second scan standard: the summary, first role, and its "
        "first bullets must carry the strongest role-relevant evidence, and a "
        "resume whose best material sits below the top third scans poorly.",
        "Bullet lead words carry the scan: flag bullets that open with weak, "
        "generic, or duty phrasing instead of a strong verb or outcome.",
    ],
    "hiring-manager": [
        "Reward concrete scale signals such as users, throughput, data volume, "
        "latency, revenue, or team size that make evidence credible at the "
        "expected seniority.",
        "Distinguish ownership verbs (designed, led, built) from participation "
        "verbs (contributed to, assisted with), and flag evidence whose "
        "ownership level does not match the role's seniority.",
    ],
    "concision": [
        "Flag any bullet over roughly thirty words, any bullet opened by a "
        "weak verb or passive construction, and any repeated verb or "
        "duplicated evidence across bullets.",
    ],
}
