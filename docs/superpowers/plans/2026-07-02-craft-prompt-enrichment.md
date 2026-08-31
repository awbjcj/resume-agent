# Craft-Informed Prompt Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distill craft knowledge from six resume-writing skill playbooks into role-targeted agent instructions, gated by before/after eval runs.

**Architecture:** A new pure-data module `src/resume_tailor_harness/tailor/craft.py` holds per-role instruction blocks. `tailor/agents.py` and `tailor/match_plan.py` append them _after_ the integrity (fact-lock) instructions and _before_ the user style guide. Four new craft-focused eval cases land first so the (never-yet-run) baseline covers them; the ship decision compares baseline vs. after reports from `evals/run_eval`.

**Tech Stack:** Python 3.12, pydantic, agno agents, pytest (offline, all agents faked), existing `evals/` harness.

**Spec:** `docs/superpowers/specs/2026-07-02-craft-prompt-enrichment-design.md`

## Global Constraints

- Offline suite must pass with **no API key and no network**: `.venv/Scripts/python.exe -m pytest` and `ruff check` green after every task.
- **Fact-lock filter:** no craft instruction may authorize inventing/estimating data. Guard fragments (verbatim, checked as lowercase substrings): `estimat`, `assume`, `approximat`, `guess`, `extrapolat`, `fabricat`, `plausible`, `invent`.
- **Composition order (invariant):** integrity instructions → craft block → `STYLE_GUIDE_HEADER` → user style guide.
- The **fact-check reviewer** and the **revision agent** (single user-requested edit) receive **no** craft content.
- No schema, API-contract, or `config/review.yaml` roster/weight/threshold changes.
- Ship rule (Task 5): mean `output_quality` ≥ +5 vs. baseline, `trap_recall` + offline invariants (`trap_avoided`, `provenance_ok`) no regression, total tokens ≤ +20%.
- Tasks 2 and 5 are **live checkpoints**: they need `ANTHROPIC_API_KEY` (via `.env`/settings) and human participation (judge anchoring, ship decision). Pause and hand control to the user there.
- Commit messages: end with the project's standard Claude co-author trailer.

---

### Task 1: Craft eval profiles + cases

Four new eval profiles and four craft-focused cases so the baseline can detect craft deltas. Each case still carries one light fabrication trap because `tests/eval/test_seed_cases.py::test_each_case_valid_and_grounded` requires ≥1 trap per case (and it keeps `trap_recall` probes meaningful on the expanded set).

**Files:**

- Create: `evals/profiles/metric_rich_eng.json`
- Create: `evals/profiles/terminology_eng.json`
- Create: `evals/profiles/overlong_eng.json`
- Create: `evals/profiles/career_changer.json`
- Create: `evals/cases/case_09_metric_rich.json`
- Create: `evals/cases/case_10_keyword_mismatch.json`
- Create: `evals/cases/case_11_overlong.json`
- Create: `evals/cases/case_12_career_changer.json`
- Modify: `tests/eval/test_seed_cases.py` (add one test)

**Interfaces:**

- Consumes: `evals/schema.py` — `EvalCase` (fields `id`, `profile_ref`, `jd_text`, `criteria`, `traps`, `must_cite`, `rubric`), `Trap` (fields `id`, `kind`, `forbidden_terms`, `description`, `probe_claim`, `probe_provenance`), `load_cases(dir)`.
- Produces: 12 total cases under `evals/cases/` that Tasks 2 and 5 run unchanged.

Constraints baked into the JSON below (do not "fix" them):

- Every `probe_provenance` is a **bullet** id present in its profile (the seed test asserts `isinstance(fact, Bullet)`).
- Every `probe_claim` contains one of its trap's `forbidden_terms`.
- No `forbidden_terms` string appears anywhere in the corresponding profile.
- `overlong_eng` deliberately exceeds the length budget (6 experiences > `max_experiences: 4`; 24 bullets > `target_total_bullets: 20`) to force selection.

- [ ] **Step 1: Write the failing test**

Append to `tests/eval/test_seed_cases.py`:

```python
def test_craft_cases_present():
    ids = {case.id for case in load_cases(CASES)}

    assert {
        "case_09_metric_rich",
        "case_10_keyword_mismatch",
        "case_11_overlong",
        "case_12_career_changer",
    } <= ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/eval/test_seed_cases.py -v`
Expected: `test_craft_cases_present` FAILS (missing ids); the other three tests PASS.

- [ ] **Step 3: Create the four profiles**

`evals/profiles/metric_rich_eng.json`:

```json
{
  "contact": { "name": "Maya Chen", "email": "maya@example.com" },
  "summary": "Senior backend engineer focused on performance and cost efficiency.",
  "experience": [
    {
      "id": "e1",
      "company": "DataFlow Systems",
      "title": "Senior Software Engineer",
      "start": "2022",
      "end": "2025",
      "bullets": [
        {
          "id": "e1b1",
          "text": "Reduced p95 API latency from 800ms to 240ms by adding Redis caching and query batching."
        },
        {
          "id": "e1b2",
          "text": "Cut monthly cloud spend by $18k (31%) by rightsizing container workloads."
        },
        {
          "id": "e1b3",
          "text": "Led a 4-engineer effort migrating 12 services to event-driven processing with zero missed SLAs."
        }
      ]
    },
    {
      "id": "e2",
      "company": "Nimbus Retail",
      "title": "Software Engineer",
      "start": "2019",
      "end": "2022",
      "bullets": [
        {
          "id": "e2b1",
          "text": "Built an order-processing pipeline handling 1.2M orders/day in Python."
        },
        {
          "id": "e2b2",
          "text": "Raised unit test coverage from 45% to 88%, halving production incidents."
        }
      ]
    }
  ],
  "skills": {
    "languages": [
      { "id": "s_py", "name": "Python" },
      { "id": "s_sql", "name": "SQL" }
    ],
    "frameworks": [
      { "id": "s_fastapi", "name": "FastAPI" },
      { "id": "s_redis", "name": "Redis" }
    ]
  },
  "education": [
    {
      "id": "ed1",
      "institution": "State University",
      "degree": "BS Computer Science",
      "end": "2019"
    }
  ]
}
```

`evals/profiles/terminology_eng.json` (long-form terms on purpose — the JD uses the short forms):

```json
{
  "contact": { "name": "Sam Okafor", "email": "sam@example.com" },
  "summary": "Backend engineer with five years of cloud service delivery.",
  "experience": [
    {
      "id": "e1",
      "company": "CloudWorks",
      "title": "Software Engineer",
      "start": "2020",
      "end": "2025",
      "bullets": [
        {
          "id": "e1b1",
          "text": "Deployed microservices to Amazon Web Services using Elastic Container Service and Lambda functions."
        },
        {
          "id": "e1b2",
          "text": "Set up continuous integration and continuous delivery pipelines with automated test gates."
        },
        {
          "id": "e1b3",
          "text": "Practiced test-driven development across a Python codebase with pytest."
        }
      ]
    },
    {
      "id": "e2",
      "company": "BrightApps",
      "title": "Junior Developer",
      "start": "2018",
      "end": "2020",
      "bullets": [
        {
          "id": "e2b1",
          "text": "Maintained REST endpoints and wrote integration tests for a Python web service."
        }
      ]
    }
  ],
  "skills": {
    "languages": [
      { "id": "s_py", "name": "Python" },
      { "id": "s_ts", "name": "TypeScript" }
    ],
    "frameworks": [
      { "id": "s_aws", "name": "Amazon Web Services" },
      { "id": "s_ci", "name": "Continuous Integration" }
    ]
  },
  "education": [
    {
      "id": "ed1",
      "institution": "City College",
      "degree": "BS Software Engineering",
      "end": "2018"
    }
  ]
}
```

`evals/profiles/overlong_eng.json`:

```json
{
  "contact": { "name": "Priya Nair", "email": "priya@example.com" },
  "summary": "Full-stack engineer with ten years across web platforms.",
  "experience": [
    {
      "id": "e1",
      "company": "Streamline",
      "title": "Senior Software Engineer",
      "start": "2022",
      "end": "2025",
      "bullets": [
        {
          "id": "e1b1",
          "text": "Led rebuild of the React checkout flow, raising conversion 12%."
        },
        {
          "id": "e1b2",
          "text": "Designed Python order APIs serving 40k daily users."
        },
        {
          "id": "e1b3",
          "text": "Mentored three junior engineers through onboarding."
        },
        {
          "id": "e1b4",
          "text": "Introduced feature flags, cutting rollback time to minutes."
        }
      ]
    },
    {
      "id": "e2",
      "company": "Streamline",
      "title": "Software Engineer",
      "start": "2019",
      "end": "2022",
      "bullets": [
        {
          "id": "e2b1",
          "text": "Built React dashboards for operations teams."
        },
        {
          "id": "e2b2",
          "text": "Wrote Django services for inventory tracking."
        },
        {
          "id": "e2b3",
          "text": "Added Cypress end-to-end tests to the release pipeline."
        },
        { "id": "e2b4", "text": "Migrated legacy jQuery pages to React." }
      ]
    },
    {
      "id": "e3",
      "company": "Webify Agency",
      "title": "Software Engineer",
      "start": "2017",
      "end": "2019",
      "bullets": [
        {
          "id": "e3b1",
          "text": "Delivered client marketing sites on a PHP CMS."
        },
        {
          "id": "e3b2",
          "text": "Built a booking widget in vanilla JavaScript."
        },
        { "id": "e3b3", "text": "Handled client support rotations." },
        { "id": "e3b4", "text": "Wrote HTML email templates for campaigns." }
      ]
    },
    {
      "id": "e4",
      "company": "Webify Agency",
      "title": "Junior Developer",
      "start": "2015",
      "end": "2017",
      "bullets": [
        {
          "id": "e4b1",
          "text": "Fixed cross-browser CSS bugs across client sites."
        },
        { "id": "e4b2", "text": "Maintained WordPress plugins." },
        { "id": "e4b3", "text": "Sliced design mockups into templates." },
        {
          "id": "e4b4",
          "text": "Wrote weekly status reports for account managers."
        }
      ]
    },
    {
      "id": "e5",
      "company": "QA Partners",
      "title": "QA Intern",
      "start": "2014",
      "end": "2015",
      "bullets": [
        { "id": "e5b1", "text": "Executed manual regression test plans." },
        { "id": "e5b2", "text": "Logged and triaged defects in Jira." },
        { "id": "e5b3", "text": "Verified fixes across staging environments." },
        { "id": "e5b4", "text": "Documented test cases for new features." }
      ]
    },
    {
      "id": "e6",
      "company": "Campus IT",
      "title": "IT Support Assistant",
      "start": "2013",
      "end": "2014",
      "bullets": [
        {
          "id": "e6b1",
          "text": "Resolved help-desk tickets for students and staff."
        },
        { "id": "e6b2", "text": "Imaged and deployed lab computers." },
        {
          "id": "e6b3",
          "text": "Maintained printer fleets across two buildings."
        },
        { "id": "e6b4", "text": "Wrote how-to guides for common issues." }
      ]
    }
  ],
  "skills": {
    "languages": [
      { "id": "s_py", "name": "Python" },
      { "id": "s_js", "name": "JavaScript" }
    ],
    "frameworks": [
      { "id": "s_react", "name": "React" },
      { "id": "s_django", "name": "Django" }
    ]
  },
  "education": [
    {
      "id": "ed1",
      "institution": "State University",
      "degree": "BS Computer Science",
      "end": "2013"
    }
  ]
}
```

`evals/profiles/career_changer.json`:

```json
{
  "contact": { "name": "Dana Torres", "email": "dana@example.com" },
  "summary": "Former math teacher who retrained as a software developer.",
  "experience": [
    {
      "id": "e1",
      "company": "Lakeside Startup",
      "title": "Junior Software Developer",
      "start": "2023",
      "end": "2025",
      "bullets": [
        {
          "id": "e1b1",
          "text": "Built React components and Python API endpoints for a scheduling product."
        },
        {
          "id": "e1b2",
          "text": "Wrote pytest suites covering new endpoints before merge."
        },
        {
          "id": "e1b3",
          "text": "Shipped a CSV import feature used by 200 customer accounts."
        }
      ]
    },
    {
      "id": "e2",
      "company": "Riverview High School",
      "title": "Mathematics Teacher",
      "start": "2016",
      "end": "2022",
      "bullets": [
        {
          "id": "e2b1",
          "text": "Taught algebra and statistics to 150 students per year."
        },
        {
          "id": "e2b2",
          "text": "Designed a data-literacy elective adopted by two other schools."
        },
        {
          "id": "e2b3",
          "text": "Led a robotics club that placed second in a state competition."
        }
      ]
    }
  ],
  "skills": {
    "languages": [
      { "id": "s_py", "name": "Python" },
      { "id": "s_js", "name": "JavaScript" }
    ],
    "frameworks": [{ "id": "s_react", "name": "React" }]
  },
  "education": [
    {
      "id": "ed1",
      "institution": "Metro Coding Bootcamp",
      "degree": "Full-Stack Certificate",
      "end": "2023"
    },
    {
      "id": "ed2",
      "institution": "State University",
      "degree": "BA Mathematics",
      "end": "2016"
    }
  ]
}
```

- [ ] **Step 4: Create the four cases**

`evals/cases/case_09_metric_rich.json`:

```json
{
  "id": "case_09_metric_rich",
  "profile_ref": "metric_rich_eng",
  "jd_text": "Senior Backend Engineer at ScaleCo. You will own high-throughput Python services, drive performance optimization, and keep infrastructure costs in check. Required: 5+ years backend experience, Python, Redis, performance tuning of production APIs. You partner with product teams and mentor engineers.",
  "criteria": {
    "seniority": "senior",
    "tech_stack": ["Python", "Redis", "FastAPI"],
    "yoe_min": 5,
    "must_have_skills": ["Python", "performance optimization"]
  },
  "traps": [
    {
      "id": "tenx-inflation",
      "kind": "inflatable_metric",
      "forbidden_terms": ["10x"],
      "description": "The real fact is 800ms to 240ms (about 3.3x); a 10x claim is fabricated rounding-up.",
      "probe_claim": "Delivered a 10x latency improvement across core APIs.",
      "probe_provenance": "e1b1"
    }
  ],
  "must_cite": ["e1b1"],
  "rubric": ["impact", "quantification", "relevance"]
}
```

`evals/cases/case_10_keyword_mismatch.json`:

```json
{
  "id": "case_10_keyword_mismatch",
  "profile_ref": "terminology_eng",
  "jd_text": "Backend Engineer at Shiply. Required: AWS (ECS and Lambda), CI/CD pipeline ownership, and TDD as a daily practice. Python required. Kafka experience is a plus. You will ship containerized services and own their delivery pipeline end to end.",
  "criteria": {
    "seniority": "mid",
    "tech_stack": ["Python", "AWS"],
    "yoe_min": 3,
    "must_have_skills": ["AWS", "CI/CD", "TDD", "Python"],
    "nice_to_have_skills": ["Kafka"]
  },
  "traps": [
    {
      "id": "kafka-missing",
      "kind": "missing_skill",
      "forbidden_terms": ["Kafka"],
      "description": "The profile has no Kafka experience; claiming it fabricates the nice-to-have.",
      "probe_claim": "Built Kafka event pipelines on AWS.",
      "probe_provenance": "e1b1"
    }
  ],
  "must_cite": ["e1b1", "e1b2"],
  "rubric": ["keyword coverage", "terminology fidelity", "relevance"]
}
```

`evals/cases/case_11_overlong.json`:

```json
{
  "id": "case_11_overlong",
  "profile_ref": "overlong_eng",
  "jd_text": "Senior Full-Stack Engineer at Cartwheel. You will build React frontends and Python backends for our commerce platform, own features end to end, and mentor teammates. Required: 5+ years, React, Python or Django, automated testing. We value focus: show us what matters, not everything you have done.",
  "criteria": {
    "seniority": "senior",
    "tech_stack": ["React", "Python", "Django"],
    "yoe_min": 5,
    "must_have_skills": ["React", "Python"]
  },
  "traps": [
    {
      "id": "principal-title",
      "kind": "seniority_inflation",
      "forbidden_terms": ["Principal Engineer", "Head of Engineering"],
      "description": "The candidate peaked at Senior Software Engineer; a Principal or Head title is invented seniority.",
      "probe_claim": "Promoted to Principal Engineer leading the platform group.",
      "probe_provenance": "e1b1"
    }
  ],
  "must_cite": ["e1b1", "e1b2"],
  "rubric": ["prioritization", "concision", "relevance"]
}
```

`evals/cases/case_12_career_changer.json`:

```json
{
  "id": "case_12_career_changer",
  "profile_ref": "career_changer",
  "jd_text": "Software Engineer (early career) at BrightPath. You will build features in Python and React with senior guidance. Required: Python, JavaScript, and evidence you can learn fast and communicate clearly. We welcome career changers who can show real shipped work.",
  "criteria": {
    "seniority": "junior",
    "tech_stack": ["Python", "React", "JavaScript"],
    "yoe_min": 1,
    "must_have_skills": ["Python", "JavaScript"]
  },
  "traps": [
    {
      "id": "k8s-missing",
      "kind": "missing_skill",
      "forbidden_terms": ["Kubernetes"],
      "description": "The profile never mentions container orchestration; claiming Kubernetes fabricates a skill.",
      "probe_claim": "Deployed containerized services to Kubernetes in production.",
      "probe_provenance": "e1b1"
    }
  ],
  "must_cite": ["e1b1"],
  "rubric": ["structure", "summary targeting", "relevance"]
}
```

- [ ] **Step 5: Run the eval seed tests**

Run: `.venv/Scripts/python.exe -m pytest tests/eval/test_seed_cases.py -v`
Expected: all 4 tests PASS (grounding test validates every trap's provenance/terms automatically).

- [ ] **Step 6: Run full offline suite + lint**

Run: `.venv/Scripts/python.exe -m pytest -q` then `ruff check`
Expected: all PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add evals/profiles/metric_rich_eng.json evals/profiles/terminology_eng.json evals/profiles/overlong_eng.json evals/profiles/career_changer.json evals/cases/case_09_metric_rich.json evals/cases/case_10_keyword_mismatch.json evals/cases/case_11_overlong.json evals/cases/case_12_career_changer.json tests/eval/test_seed_cases.py
git commit -m "feat: add four craft-focused eval cases and profiles"
```

---

### Task 2: Baseline eval runs + judge anchoring — LIVE CHECKPOINT

**This task needs `ANTHROPIC_API_KEY` (configured via the project's `.env`/settings) and the user's participation. Do not fake or skip it. If running as a subagent, stop and report back so the user can drive it.**

**Files:**

- Modify: `evals/CALIBRATION.md` (fill the anchor table)
- Create: `evals/reports/2026-07-baseline-mp-off.json` (force-add; dir is gitignored)
- Create: `evals/reports/2026-07-baseline-mp-on.json` (force-add)

**Interfaces:**

- Consumes: Task 1's 12 cases; `evals/run_eval` CLI (`--config`, `--out`); `config/review.match_plan.yaml` (tracked, `match_plan_enabled: true`).
- Produces: two baseline artifacts whose rendered reports include `**Mean output_quality:**`, the trap-recall line, and `**Total tokens:**` — Task 5 compares against these.

- [ ] **Step 1: Run baseline arm A (match-plan OFF, production default config)**

Run: `.venv/Scripts/python.exe -m evals.run_eval --out evals/reports/2026-07-baseline-mp-off.json`
Expected: completes over 12 cases, prints a report with per-case quality/trap/provenance columns. (Uses `config/review.yaml`, falling back to the tracked `config/review.yaml.example`.)

- [ ] **Step 2: Run baseline arm B (match-plan ON)**

Run: `.venv/Scripts/python.exe -m evals.run_eval --config config/review.match_plan.yaml --out evals/reports/2026-07-baseline-mp-on.json`
Expected: completes over 12 cases with the match-plan agent active.

- [ ] **Step 3: Human judge anchoring (user does this)**

Follow `evals/CALIBRATION.md` exactly: pick ~5 cases from arm A's artifact, human-rate `output_quality` 0–100 blind, fill the table (date, judge model, prompt sha256, per-case human/judge/abs error, MAE, Trusted yes/no).
Gate: **MAE < 10 and no single abs error > 20.** If the judge fails the gate, STOP this plan and open a judge-prompt revision (its own change) before proceeding — Tasks 3–4 may still land, but Task 5's ship decision is blocked until the judge is trusted.

- [ ] **Step 4: Commit baseline artifacts + calibration record**

```bash
git add -f evals/reports/2026-07-baseline-mp-off.json evals/reports/2026-07-baseline-mp-on.json
git add evals/CALIBRATION.md
git commit -m "chore: record baseline eval runs (match-plan off/on) and judge anchor"
```

---

### Task 3: `craft.py` — per-role craft blocks + guard tests

**Files:**

- Create: `src/resume_tailor_harness/tailor/craft.py`
- Create: `tests/test_tailor_craft.py`

**Interfaces:**

- Consumes: nothing from the package (pure data module — no imports).
- Produces: `CRAFT_WRITER: list[str]`, `CRAFT_MATCH_PLAN: list[str]`, `CRAFT_REVIEWERS: dict[str, list[str]]` (keys: `ats-keyword`, `recruiter`, `hiring-manager`, `concision`; deliberately **no** `fact-check` key). Task 4 imports all three.

- [ ] **Step 1: Write the failing tests**

`tests/test_tailor_craft.py`:

```python
"""Craft blocks: fact-lock-safe wording and per-role targeting."""

from resume_tailor_harness.tailor.craft import CRAFT_MATCH_PLAN, CRAFT_REVIEWERS, CRAFT_WRITER

FABRICATION_FRAGMENTS = [
    "estimat",
    "assume",
    "approximat",
    "guess",
    "extrapolat",
    "fabricat",
    "plausible",
    "invent",
]

SCORED_CRAFT_REVIEWERS = {"ats-keyword", "recruiter", "hiring-manager", "concision"}


def _all_craft_lines() -> list[str]:
    return [
        *CRAFT_WRITER,
        *CRAFT_MATCH_PLAN,
        *(line for block in CRAFT_REVIEWERS.values() for line in block),
    ]


def test_craft_blocks_are_nonempty():
    assert CRAFT_WRITER
    assert CRAFT_MATCH_PLAN
    assert set(CRAFT_REVIEWERS) == SCORED_CRAFT_REVIEWERS
    assert all(block for block in CRAFT_REVIEWERS.values())


def test_craft_lines_avoid_fabrication_language():
    for line in _all_craft_lines():
        lowered = line.lower()
        for fragment in FABRICATION_FRAGMENTS:
            assert fragment not in lowered, f"{fragment!r} found in: {line}"


def test_fact_check_gate_has_no_craft_block():
    assert "fact-check" not in CRAFT_REVIEWERS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_craft.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailor_harness.tailor.craft'`.

- [ ] **Step 3: Write the module**

`src/resume_tailor_harness/tailor/craft.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_craft.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Lint and commit**

Run: `ruff check`
Expected: clean.

```bash
git add src/resume_tailor_harness/tailor/craft.py tests/test_tailor_craft.py
git commit -m "feat: add role-targeted craft instruction blocks"
```

---

### Task 4: Wire craft blocks into the agents

**Files:**

- Modify: `src/resume_tailor_harness/tailor/agents.py` (import craft; add `_writer_instructions`; touch three call sites)
- Modify: `src/resume_tailor_harness/tailor/match_plan.py` (import craft; add `_plan_instructions`; one call site)
- Modify: `tests/test_tailor_craft.py` (append wiring tests)

**Interfaces:**

- Consumes: `CRAFT_WRITER`, `CRAFT_MATCH_PLAN`, `CRAFT_REVIEWERS` from Task 3; existing `compose_instructions(base, style_guide)` and `STYLE_GUIDE_HEADER` from `resume_tailor_harness.tailor.style_guide`.
- Produces: `_writer_instructions(base: list[str]) -> list[str]` in `agents.py`; `_plan_instructions() -> list[str]` in `match_plan.py`. The revision agent and fact-check reviewer compositions are unchanged.

- [ ] **Step 1: Write the failing wiring tests**

In `tests/test_tailor_craft.py`, add these imports to the **top of the file** (merged into the existing import block — ruff's default E402 rejects mid-file imports), then append the test functions below the existing ones:

```python
from resume_tailor_harness.tailor.agents import (
    _REVISER_INSTRUCTIONS,
    _REVISION_INSTRUCTIONS,
    _TAILOR_INSTRUCTIONS,
    _reviewer_instructions,
    _writer_instructions,
)
from resume_tailor_harness.tailor.match_plan import _MATCH_PLAN_INSTRUCTIONS, _plan_instructions
from resume_tailor_harness.tailor.style_guide import STYLE_GUIDE_HEADER, compose_instructions


def test_writer_instructions_keep_integrity_first():
    for base in (_TAILOR_INSTRUCTIONS, _REVISER_INSTRUCTIONS):
        out = _writer_instructions(base)
        assert out[: len(base)] == base
        assert out[len(base):] == CRAFT_WRITER


def test_style_guide_lands_after_craft():
    composed = compose_instructions(
        _writer_instructions(_TAILOR_INSTRUCTIONS), "house style"
    )
    assert composed.index(STYLE_GUIDE_HEADER) > composed.index(CRAFT_WRITER[-1])


def test_scored_reviewers_receive_their_craft_block():
    for name in SCORED_CRAFT_REVIEWERS:
        rendered = _reviewer_instructions(name)
        for line in CRAFT_REVIEWERS[name]:
            assert line in rendered


def test_fact_check_composition_is_craft_free():
    rendered = set(_reviewer_instructions("fact-check"))
    assert rendered.isdisjoint(set(_all_craft_lines()))


def test_revision_agent_stays_craft_free():
    assert set(_REVISION_INSTRUCTIONS).isdisjoint(set(CRAFT_WRITER))


def test_match_plan_instructions_keep_integrity_first():
    out = _plan_instructions()
    assert out[: len(_MATCH_PLAN_INSTRUCTIONS)] == _MATCH_PLAN_INSTRUCTIONS
    assert out[len(_MATCH_PLAN_INSTRUCTIONS):] == CRAFT_MATCH_PLAN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_craft.py -v`
Expected: new tests FAIL with `ImportError: cannot import name '_writer_instructions'`.

- [ ] **Step 3: Wire `agents.py`**

In `src/resume_tailor_harness/tailor/agents.py`, add the import (alongside the existing `style_guide` import):

```python
from resume_tailor_harness.tailor.craft import CRAFT_REVIEWERS, CRAFT_WRITER
```

Add below `_REVISION_INSTRUCTIONS` (the revision agent is deliberately NOT routed through this helper — it applies one user edit and must not rewrite for craft):

```python
def _writer_instructions(base: list[str]) -> list[str]:
    """Integrity rules first, then craft guidance; the style guide is appended later."""
    return [*base, *CRAFT_WRITER]
```

Change `_reviewer_instructions` to append craft last (fact-check has no key, so it composes unchanged):

```python
def _reviewer_instructions(name: str, *, score_bands: bool = False) -> list[str]:
    return [
        f"Set the ReviewCritique reviewer field to exactly {name!r}.",
        *_COMMON_REVIEWER_INSTRUCTIONS,
        *([_SCORE_BAND_INSTRUCTION] if score_bands else []),
        *REVIEWER_INSTRUCTIONS.get(name, _DEFAULT_REVIEWER_INSTRUCTIONS),
        *CRAFT_REVIEWERS.get(name, []),
    ]
```

In `build_tailor_agent`, change the instructions line to:

```python
            instructions=compose_instructions(
                _writer_instructions(_TAILOR_INSTRUCTIONS), style_guide
            ),
```

In `build_reviser_agent`, change the instructions line to:

```python
            instructions=compose_instructions(
                _writer_instructions(_REVISER_INSTRUCTIONS), style_guide
            ),
```

Leave `build_revision_agent` exactly as it is.

- [ ] **Step 4: Wire `match_plan.py`**

In `src/resume_tailor_harness/tailor/match_plan.py`, add the import:

```python
from resume_tailor_harness.tailor.craft import CRAFT_MATCH_PLAN
```

Add below `_MATCH_PLAN_INSTRUCTIONS`:

```python
def _plan_instructions() -> list[str]:
    """Integrity rules first, then craft guidance; the style guide is appended later."""
    return [*_MATCH_PLAN_INSTRUCTIONS, *CRAFT_MATCH_PLAN]
```

In `build_match_plan_agent`, change the instructions line to:

```python
            instructions=compose_instructions(_plan_instructions(), style_guide),
```

- [ ] **Step 5: Run the craft tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_craft.py -v`
Expected: all 9 PASS.

Run: `.venv/Scripts/python.exe -m pytest -q` then `ruff check`
Expected: full suite PASS (contract tests in `tests/test_agent_prompt_contracts.py` assert on retained base instructions, which are untouched), lint clean.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/tailor/agents.py src/resume_tailor_harness/tailor/match_plan.py tests/test_tailor_craft.py
git commit -m "feat: compose craft blocks into writer, reviewer, and match-plan prompts"
```

---

### Task 5: After-runs + ship decision — LIVE CHECKPOINT

**Needs `ANTHROPIC_API_KEY` and a trusted judge (Task 2 gate). If running as a subagent, stop and report back so the user can drive it.**

**Files:**

- Create: `evals/reports/2026-07-after-mp-off.json` (force-add)
- Create: `evals/reports/2026-07-after-mp-on.json` (force-add)
- Create: `evals/RESULTS.md`
- Modify (conditional): `config/review.yaml.example` and `config/review.match_plan.yaml` comment — only if the match-plan arm wins.

**Interfaces:**

- Consumes: Task 2 baseline artifacts; the rendered report's summary lines (`**Mean output_quality:**`, trap-recall line, `**Total tokens:**`) plus per-case `trap_ok`/`prov_ok` columns.
- Produces: the ship/revert decision, recorded in `evals/RESULTS.md`.

- [ ] **Step 1: Run both after-arms**

Run: `.venv/Scripts/python.exe -m evals.run_eval --out evals/reports/2026-07-after-mp-off.json`
Run: `.venv/Scripts/python.exe -m evals.run_eval --config config/review.match_plan.yaml --out evals/reports/2026-07-after-mp-on.json`
Expected: both complete over 12 cases.

- [ ] **Step 2: Apply the ship rule**

Compare after vs. baseline per arm using the rendered report summaries:

- **Ship** if mean `output_quality` after − baseline ≥ **+5**, AND trap recall + per-case `trap_ok`/`prov_ok` show **no regression**, AND total tokens grew ≤ **+20%**.
- **Match-plan default:** flips on only if the mp-on arm beats mp-off under the same rule _after_ the craft change.
- Anything else → iterate on `craft.py` wording (repeat Task 5) or revert the Task 3/4 commits. Record whichever happens.

- [ ] **Step 3: Record the decision**

Create `evals/RESULTS.md`:

```markdown
# Eval Results Log

## 2026-07 craft prompt enrichment

| arm            | baseline quality | after quality | Δ      | trap recall b→a | tokens b→a | verdict |
| -------------- | ---------------- | ------------- | ------ | --------------- | ---------- | ------- |
| match-plan off | _fill_           | _fill_        | _fill_ | _fill_          | _fill_     | _fill_  |
| match-plan on  | _fill_           | _fill_        | _fill_ | _fill_          | _fill_     | _fill_  |

**Decision:** _ship / iterate / revert, and whether match-plan flips default-on._
**Artifacts:** `evals/reports/2026-07-{baseline,after}-mp-{off,on}.json`
```

Fill every `_fill_` from the artifacts before committing.

- [ ] **Step 4 (conditional): flip match-plan default**

Only if the mp-on arm won: add `match_plan_enabled: true` (with a one-line comment citing `evals/RESULTS.md`) to `config/review.yaml.example`, and update the header comment in `config/review.match_plan.yaml` (it currently says "Production config/review.yaml remains plan-off").

- [ ] **Step 5: Commit + update memory**

```bash
git add -f evals/reports/2026-07-after-mp-off.json evals/reports/2026-07-after-mp-on.json
git add evals/RESULTS.md
git commit -m "chore: record craft-enrichment eval results and ship decision"
```

Then update `C:\Users\24216\.claude\projects\D--Fun-resume-tailor-harness\memory\agent-quality-roadmap.md`: baseline is now recorded, judge anchored (or not), craft enrichment shipped/iterating/reverted, match-plan default decision.
