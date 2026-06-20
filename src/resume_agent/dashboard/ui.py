"""Broadsheet design system: theme CSS, palette, and pure HTML helpers.

All functions here are pure (no Streamlit calls at import or call time) so the
module imports cleanly and the helpers are unit-testable without a server.
"""

from datetime import datetime, timezone
from html import escape

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600;6..72,700&family=IBM+Plex+Mono:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
  --paper:#f4f1ea; --paper-2:#efeae0; --ink:#16130f; --muted:#6c6253;
  --oxblood:#8c2f1f; --rule:rgba(22,19,15,0.16);
  /* One radius scale used everywhere (was an ad-hoc mix of 3/4/6px). */
  --radius:8px; --radius-sm:4px;
}

.stApp { background: var(--paper); color: var(--ink); }

/* Fluid root: every rem-based size (including the sidebar and Streamlit's own
   header) scales with the viewport. ~16px on a 14" laptop (~1366px wide) up to
   ~22px on a 32" 4K — one declaration instead of a media-query ladder. */
html { font-size: clamp(16px, calc(11px + 0.42vw), 22px) !important; }

/* Streamlit's top chrome is a FIXED bar that floats over content. Make it
   blend into the paper and hold enough top padding so the masthead clears it. */
[data-testid="stHeader"] { background: transparent; box-shadow: none; }
[data-testid="stDecoration"] { display: none; }
/* min(95vw, …) fills a 4K screen instead of stranding content in a narrow
   centered column, while still capping line length on ultrawide displays. */
/* Trim Streamlit's wide default side padding so the grid uses the full canvas
   (cuts the sparse margins, and lets a laptop fit 2 columns). */
.block-container { padding: 5rem 2rem 4rem; max-width: min(95vw, 2040px); }

html, body, [class*="css"], .stMarkdown, p, li, label,
.stTextInput input, .stSelectbox div, .stDataFrame, table {
  font-family: 'IBM Plex Sans', -apple-system, sans-serif;
  font-size: 1.05rem;
}
h1, h2, h3, h4, .card-title, .nameplate, .empty-title {
  font-family: 'Newsreader', Georgia, serif !important; letter-spacing: -0.01em;
}

/* ── Masthead / nameplate ─────────────────────────────────────── */
/* Sidebar is a fixed width, so the fluid root can blow the nameplate past it on
   a 4K screen (wrapping "Broadsheet" mid-word). Keep it generous but contained. */
.nameplate { font-family:'Newsreader',serif; font-size: 1.55rem; font-weight: 700; margin-bottom: 1rem; line-height: 1.1; overflow-wrap: normal; word-break: normal; }
.masthead { margin: 0 0 1.6rem 0; padding-bottom: 1.0rem; border-bottom: 2px solid var(--ink); }
.masthead-kicker {
  font-family:'IBM Plex Mono', monospace; font-size: 0.86rem; letter-spacing: 0.3em;
  text-transform: uppercase; color: var(--oxblood); margin-bottom: 0.5rem;
}
.masthead-title { font-size: clamp(2.2rem, 2.4vw, 3.0rem); font-weight: 700; line-height: 1.02; margin: 0; color: var(--ink); }
.masthead-title .dot { color: var(--oxblood); }
.masthead-sub { color: var(--muted); margin-top: 0.5rem; font-size: 1.1rem; max-width: 70ch; }

/* ── Metric strip ─────────────────────────────────────────────── */
.metric-row { display:flex; gap: 1.0rem; margin: 0.4rem 0 1.6rem 0; flex-wrap: wrap; }
.metric { flex:1; min-width: 150px; background: var(--paper-2); border:1px solid var(--rule); border-radius: var(--radius); padding: 1.0rem 1.2rem; }
.metric-value { font-family:'Newsreader', serif; font-size: clamp(1.8rem, 1.8vw, 2.4rem); font-weight: 700; color: var(--ink); line-height:1; }
.metric-label { font-family:'IBM Plex Mono', monospace; font-size: 0.74rem; letter-spacing: 0.18em; text-transform: uppercase; color: var(--muted); margin-top: 0.45rem; }

/* ── Responsive card grids ────────────────────────────────────── */
/* st.container(key="cardgrid_…") puts a stable st-key-cardgrid… class on the
   SAME node that carries data-testid="stVerticalBlock" (Streamlit ≥1.39), so the
   grid must be the keyed element itself — a child combinator matches nothing.
   Its direct children (the bordered st.container cards) become the grid items. */

/* Shortlist — scannable summary cards. A 520px min-track keeps this to a
   regulated 2–3 columns from a 14" laptop up to a 4K canvas (rather than 5
   cramped ones or 2 lost in whitespace); align-items:stretch equalises height. */
div[data-testid="stVerticalBlock"][class*="st-key-cardgrid_shortlist"] {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 480px), 1fr));
  gap: clamp(1rem, 1.4vw, 1.6rem);
  align-items: stretch;
}

/* Pipeline — detail cards. One per row: they carry an expandable job
   description, status selector and notes field that need the full width and
   look broken (and absurdly tall) when squeezed into a narrow grid column. */
div[data-testid="stVerticalBlock"][class*="st-key-cardgrid_pipeline"] {
  display: grid;
  grid-template-columns: 1fr;
  gap: clamp(0.8rem, 1vw, 1.2rem);
}

/* ── Badges ───────────────────────────────────────────────────── */
.badge { display:inline-block; font-family:'IBM Plex Mono', monospace; font-size: 0.66rem; letter-spacing: 0.12em; text-transform: uppercase; padding: 0.2rem 0.6rem; border-radius: 3px; color: var(--badge, #6c6253); border: 1px solid color-mix(in srgb, var(--badge, #6c6253) 55%, transparent); background: color-mix(in srgb, var(--badge, #6c6253) 12%, transparent); white-space: nowrap; }

/* ── Fit block ────────────────────────────────────────────────── */
.fit { text-align:center; }
.fit-num { font-family:'Newsreader', serif; font-size: clamp(2.0rem, 2vw, 2.8rem); font-weight: 700; line-height: 1; }
.fit-num .fit-max { font-family:'IBM Plex Mono', monospace; font-size: 0.8rem; color: var(--muted); }
.fit-bar { height: 5px; border-radius: 999px; background: rgba(22,19,15,0.12); margin: 0.5rem 0 0.3rem; overflow:hidden; }
.fit-fill { height: 100%; border-radius: 999px; }
.fit-cap { font-family:'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.22em; color: var(--muted); }

.card-title { font-size: 1.5rem; font-weight: 600; color: var(--ink); margin: 0; line-height: 1.2; }
.card-meta { color: var(--muted); font-size: 1.0rem; margin-top: 0.3rem; }
.rationale { color: #3f382e; font-size: 1.02rem; line-height: 1.6; margin-top: 0.7rem; border-left: 2px solid var(--oxblood); padding-left: 0.9rem; }
.rail-head { font-family:'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.24em; font-size: 0.74rem; color: var(--muted); margin: 1.5rem 0 0.4rem; display:flex; align-items:center; gap: 0.7rem; }
.rail-head::after { content:""; flex:1; height:1px; background: var(--rule); }

/* ── Cards (bordered st.container inside a cardgrid) ───────────── */
/* Streamlit 1.58 wraps each grid item in an stLayoutWrapper; the bordered card
   is the stVerticalBlock just inside it (NOT a direct child of the keyed grid). */
div[class*="st-key-cardgrid"] > div[data-testid="stLayoutWrapper"]
  > div[data-testid="stVerticalBlock"] {
  background: var(--paper-2); border: 1px solid var(--rule) !important; border-radius: var(--radius);
  box-shadow: 0 1px 0 rgba(22,19,15,0.04); transition: border-color .18s ease;
  padding: 0.6rem 0.7rem 0.3rem;
}
div[class*="st-key-cardgrid"] > div[data-testid="stLayoutWrapper"]
  > div[data-testid="stVerticalBlock"]:hover { border-color: var(--oxblood) !important; }

/* Pin the Approve button to the bottom of every (equal-height) shortlist card so
   the buttons line up across a row regardless of rationale length. Cascade height
   from the grid-stretched layout wrapper down through the card, then push the
   keyed approve-button container down with margin-top:auto. The button is a
   full-width footer (rendered outside the meter|body columns). */
div[class*="st-key-cardgrid_shortlist"] > div[data-testid="stLayoutWrapper"] { display: flex; }
div[class*="st-key-cardgrid_shortlist"] > div[data-testid="stLayoutWrapper"]
  > div[data-testid="stVerticalBlock"] { flex: 1; display: flex; flex-direction: column; }
div[class*="st-key-cardgrid_shortlist"] > div[data-testid="stLayoutWrapper"]
  > div[data-testid="stVerticalBlock"] > div[data-testid="stLayoutWrapper"] {
  flex: 1; display: flex; flex-direction: column;
}
div[class*="st-key-cardgrid_shortlist"]
  div[data-testid="stElementContainer"][class*="st-key-approve"] {
  margin-top: auto; border-top: 1px solid var(--rule); padding-top: 0.7rem;
}
div[class*="st-key-cardgrid_shortlist"]
  div[data-testid="stElementContainer"][class*="st-key-approve"] .stButton,
div[class*="st-key-cardgrid_shortlist"]
  div[data-testid="stElementContainer"][class*="st-key-approve"] .stButton > button { width: 100%; }

/* ── Buttons ──────────────────────────────────────────────────── */
.stButton > button { font-family:'IBM Plex Mono', monospace; font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; border-radius: var(--radius-sm); border: 1px solid var(--oxblood); background: var(--oxblood); color: var(--paper); font-weight: 600; padding: 0.45rem 1.1rem; transition: all .15s ease; }
.stButton > button:hover { background: #75271a; border-color:#75271a; }
.stDownloadButton > button { font-family:'IBM Plex Mono', monospace; font-size: 0.74rem; letter-spacing: 0.06em; border-radius: 3px; background: transparent; color: var(--ink); border: 1px solid var(--rule); }
.stDownloadButton > button:hover { border-color: var(--oxblood); color: var(--oxblood); }

/* ── Sidebar ──────────────────────────────────────────────────── */
[data-testid="stSidebar"] { background: var(--paper-2); border-right: 2px solid var(--ink); }
[data-testid="stSidebar"] > div { padding-top: 2.4rem; }
/* The nav radio is the primary sidebar control — size it up generously so it
   reads on both a dense 4K canvas and a small laptop (scales via the rem root). */
[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] .stRadio label p {
  font-family:'IBM Plex Sans'; font-size: 1.12rem; font-weight: 500;
}
[data-testid="stSidebar"] .stRadio label { padding: 0.28rem 0; }
[data-testid="stSidebar"] .masthead-kicker { font-size: 0.78rem; }

/* ── Inputs / tables / expander (re-themed for paper) ─────────── */
/* One look for the whole select family — selectbox AND multiselect AND number
   input — so "Sort by" no longer reads as a different component than the filters. */
.stTextInput input,
.stNumberInput [data-baseweb="input"],
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div {
  background: #fff !important; border-color: var(--rule) !important;
  border-radius: var(--radius-sm) !important; color: var(--ink) !important;
}
.stNumberInput [data-baseweb="input"] input { background: transparent !important; }
[data-testid="stExpander"] summary { font-family:'IBM Plex Mono', monospace; font-size: 0.76rem; letter-spacing: 0.06em; color: var(--muted); }
table { border-collapse: collapse; }
thead th { font-family:'IBM Plex Mono', monospace !important; font-size: 0.7rem !important; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted) !important; border-bottom: 2px solid var(--ink) !important; }
tbody td { border-bottom: 1px solid var(--rule) !important; }

/* ── Focus visibility (keyboard a11y) ─────────────────────────── */
.stButton > button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.stTextInput input:focus-visible,
.stNumberInput [data-baseweb="input"]:focus-within,
.stSelectbox [data-baseweb="select"] > div:focus-within,
.stMultiSelect [data-baseweb="select"] > div:focus-within { border-color: var(--oxblood) !important; box-shadow: 0 0 0 2px color-mix(in srgb, var(--oxblood) 30%, transparent) !important; }

/* ── Empty states ─────────────────────────────────────────────── */
.empty-state { text-align:center; padding: 3.4rem 1.2rem; border: 1px dashed var(--rule); border-radius: var(--radius); margin-top: 0.4rem; background: var(--paper-2); }
.empty-glyph { font-family:'Newsreader', serif; font-size: 2.6rem; color: var(--oxblood); opacity: .9; line-height: 1; }
.empty-title { font-size: 1.34rem; color: var(--ink); margin-top: .5rem; }
.empty-body { color: var(--muted); font-size: .96rem; margin-top: .45rem; }
.empty-body code { font-family:'IBM Plex Mono', monospace; font-size: .85em; color: var(--ink); background: #fff; border: 1px solid var(--rule); border-radius: 3px; padding: .1rem .42rem; }

/* ── Control desk + skill chips ───────────────────────────────── */
/* The filter panel must be a real keyed st.container, NOT a bare <div> marker:
   Streamlit renders each st.markdown in its own sanitized block and auto-closes
   an unbalanced "<div class='controldesk'>", leaving an empty box with the
   controls stranded as siblings below it. Style the keyed container itself —
   the same fix the card grids use. */
div[data-testid="stVerticalBlock"][class*="st-key-controldesk"] {
  background: var(--paper-2); border: 1px solid var(--rule); border-radius: var(--radius);
  padding: 0.95rem 1.1rem 1.05rem; margin: 0 0 1.4rem; gap: 0.65rem !important;
}
.controldesk-head {
  font-family:'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.22em;
  font-size: 0.72rem; color: var(--muted); margin: 0;
  padding-bottom: 0.55rem; border-bottom: 1px solid var(--rule);
}
div[class*="st-key-controldesk"] div[data-testid="stElementContainer"]:has(.controldesk-head) {
  margin-bottom: 0.55rem;
}
div[class*="st-key-controldesk"]
  > div[data-testid="stElementContainer"]:has(.controldesk-head)
  + div[data-testid="stLayoutWrapper"] {
  padding-top: 0.55rem;
}
div[class*="st-key-controldesk"] [data-testid="stHorizontalBlock"] {
  gap: clamp(0.65rem, 1.1vw, 1rem);
  align-items: flex-start;
}
div[class*="st-key-controldesk"] .stNumberInput,
div[class*="st-key-controldesk"] .stSlider,
div[class*="st-key-controldesk"] .stSelectbox,
div[class*="st-key-controldesk"] .stMultiSelect,
div[class*="st-key-controldesk"] .stRadio { min-width: 0; }
/* Compact, uniform widget labels inside the panel (mono caps, tight to control). */
div[class*="st-key-controldesk"] [data-testid="stWidgetLabel"] { margin-bottom: 0.15rem; }
div[class*="st-key-controldesk"] [data-testid="stWidgetLabel"] p {
  font-family:'IBM Plex Mono', monospace; font-size: 0.7rem; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--muted); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;
}
.metaline { font-family:'IBM Plex Mono', monospace; font-size: 0.84rem; color: var(--ink);
  margin-top: 0.45rem; }
.skills {
  display:flex; flex-wrap:wrap; align-items:center; gap: 0.3rem; margin-top: 0.55rem;
  max-width: 100%; min-width: 0;
}
.chip {
  display:inline-flex; align-items:center; max-width: 100%; min-width: 0; min-height: 1.45rem;
  font-family:'IBM Plex Mono', monospace; font-size: 0.66rem; line-height: 1;
  letter-spacing: 0.04em; padding: 0.16rem 0.5rem; border-radius: 999px; border: 1px solid var(--rule);
  background:#fff; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.chip-text { display:block; min-width: 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chip-have { color: var(--emerald, #2f7d4f); border-color: var(--emerald, #2f7d4f);
  background: color-mix(in srgb, var(--emerald, #2f7d4f) 10%, #fff); }
.chip-gap { color: var(--muted); border-color: var(--rule); }
.chip-nice { border-style: dashed; font-size: 0.6rem; opacity: 0.92; }
.chip-sel { box-shadow: 0 0 0 2px color-mix(in srgb, var(--oxblood) 60%, transparent); font-weight: 700; }

/* Shortlist titles clamp to 2 lines so a long title can't add card height. */
div[class*="st-key-cardgrid_shortlist"] .card-title {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

/* ── Inline preview + expand (native <details>) ───────────────────
   Used for the fit rationale and the pipeline job description: a clamped
   summary with a mono more/less cue, the disclosure marker hidden. Keeps every
   collapsed card uniform while letting the full text reveal in place. */
details.xt { margin: 0.5rem 0 0; }
details.xt > summary, details.xt-skills > summary { list-style: none; cursor: pointer; }
details.xt > summary { display: block; }
details.xt > summary::-webkit-details-marker,
details.xt-skills > summary::-webkit-details-marker { display: none; }
.xt-clamp {
  display: -webkit-box; -webkit-line-clamp: var(--xt-lines, 2);
  -webkit-box-orient: vertical; overflow: hidden;
}
details.xt[open] .xt-clamp { display: block; -webkit-line-clamp: unset; overflow: visible; }
.xt-full { display: none; }
details.xt[open] .xt-excerpt { display: none; }
details.xt[open] .xt-full { display: block; overflow: visible; }
.xt-pre { white-space: pre-wrap; }
.jd-text { color: var(--muted); font-size: 0.95rem; line-height: 1.55; margin-top: 0.2rem; }
.xt-cue {
  display: inline-block; margin-top: 0.3rem; font-family:'IBM Plex Mono', monospace;
  font-size: 0.62rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--oxblood);
}
.xt-cue::after { content: "▸ more"; }
details.xt[open] .xt-cue::after { content: "▾ less"; }

/* Skills strip: a single clipped row + a "+N more" pill that reveals the rest
   inline. The count is exact (computed server-side, not from CSS clipping). */
details.xt-skills { margin: 0.45rem 0 0; max-width: 100%; }
details.xt-skills > summary.skills-line {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center;
  gap: 0.4rem; max-width: 100%; min-width: 0;
}
details.xt-skills > summary.skills-line .skills { margin-top: 0; }
.skills-clip {
  flex-wrap: nowrap; overflow: hidden; min-width: 0; max-width: 100%; height: 1.55rem;
  -webkit-mask: linear-gradient(90deg, #000 88%, transparent);
          mask: linear-gradient(90deg, #000 88%, transparent);
}
.skills-clip .chip { flex: 0 0 auto; max-width: min(16ch, 42vw); }
details.xt-skills[open] .skills-clip {
  flex-wrap: wrap; overflow: visible; height: auto; min-height: 1.55rem;
  -webkit-mask: none; mask: none;
}
details.xt-skills[open] .skills-clip .chip,
details.xt-skills[open] .skills-rest .chip { max-width: 100%; }
details.xt-skills[open] .skills-clip .chip-text,
details.xt-skills[open] .skills-rest .chip-text {
  overflow: visible; text-overflow: clip; white-space: normal; line-height: 1.25;
}
.chip-more {
  flex: 0 0 auto; cursor: pointer; color: var(--oxblood); max-width: none;
  justify-content: center; white-space: nowrap;
  border-color: color-mix(in srgb, var(--oxblood) 45%, transparent);
  background: color-mix(in srgb, var(--oxblood) 8%, #fff);
}
.chip-more::after { content: "+" attr(data-n) " more"; }
details.xt-skills[open] .chip-more::after { content: "− less"; }
.skills-rest { display: none; }
details.xt-skills[open] .skills-rest { display: flex; flex-wrap: wrap; margin-top: 0.35rem; }

@media (prefers-reduced-motion: reduce) { *, .masthead { animation: none !important; transition: none !important; } }
#MainMenu, footer { visibility: hidden; }
</style>
"""

# ── Broadsheet palette ───────────────────────────────────────────────────────
PAPER = "#f4f1ea"
INK = "#16130f"
MUTED = "#6c6253"
OXBLOOD = "#8c2f1f"
# Status hues, re-tuned for contrast on a light canvas.
EMERALD = "#2f7d4f"
AMBER = "#9a6b16"
ROSE = "#a83246"
SKY = "#2f6b8c"

STATUS_COLORS = {
    # job pipeline
    "raw": MUTED, "extracted": MUTED, "filtered": SKY, "rejected": ROSE,
    "shortlisted": AMBER, "approved": AMBER, "tailored": SKY, "rendered": EMERALD,
    # application funnel
    "ready": MUTED, "submitted": SKY, "interview": AMBER, "offer": EMERALD, "closed": MUTED,
    # sponsorship
    "offered": EMERALD, "denied": ROSE, "silent": MUTED, "unknown": MUTED,
}


def status_badge(status: str) -> str:
    """Return an HTML pill for a job/application/sponsorship status token."""
    token = (status or "unknown").lower()
    color = STATUS_COLORS.get(token, MUTED)
    label = (status or "—").replace("_", " ")
    return f'<span class="badge" style="--badge:{color}">{label}</span>'


def fit_block(score: int | None) -> str:
    """Return the HTML fit-score meter (big numeral + colored bar)."""
    pct = score if score is not None else 0
    if score is None:
        color = MUTED
    elif score >= 80:
        color = EMERALD
    elif score >= 60:
        color = AMBER
    else:
        color = ROSE
    shown = score if score is not None else "—"
    aria = (
        f'role="meter" aria-valuenow="{score}" aria-valuemin="0" aria-valuemax="100" '
        f'aria-label="Fit score {score} out of 100"'
        if score is not None
        else 'role="meter" aria-label="Fit score not yet computed"'
    )
    return (
        f'<div class="fit" {aria}>'
        f'<div class="fit-num" style="color:{color}">{shown}<span class="fit-max">/100</span></div>'
        f'<div class="fit-bar"><div class="fit-fill" style="width:{pct}%;background:{color}"></div></div>'
        '<div class="fit-cap">FIT SCORE</div>'
        "</div>"
    )


def skill_chip(tag, active: bool) -> str:
    """Render a skill chip with coverage, requirement, and active-filter channels."""
    classes = ["chip", "chip-have" if tag.covered else "chip-gap"]
    if not tag.required:
        classes.append("chip-nice")
    if active:
        classes.append("chip-sel")
    label = tag.name if tag.required else f"+{tag.name}"
    safe = escape(label)
    return f'<span class="{" ".join(classes)}" title="{safe}"><span class="chip-text">{safe}</span></span>'


def salary_label(salary_min: int | None, salary_max: int | None) -> str | None:
    """Format a salary range as ``$120k-160k`` (omitting an absent bound), or None."""
    if salary_min is None and salary_max is None:
        return None
    lo = f"{salary_min // 1000}k" if salary_min is not None else None
    hi = f"{salary_max // 1000}k" if salary_max is not None else None
    return "$" + (f"{lo}-{hi}" if lo and hi else (lo or hi or ""))


def clamp_text(
    text: str,
    *,
    lines: int = 2,
    body_class: str = "rationale",
    pre: bool = False,
    min_chars: int = 90,
    preview_words: int | None = None,
) -> str:
    """Render a native <details> preview with either line or word limits.

    Short text is rendered plain so a "more" cue never appears on content that
    already fits. ``<details>``/``<summary>`` survive Streamlit's HTML sanitizer,
    giving an in-place expand with no script or rerun.
    """
    safe = escape(text)
    pre_cls = " xt-pre" if pre else ""
    if preview_words is not None:
        words = text.split()
        if len(words) <= preview_words:
            return f'<div class="{body_class}{pre_cls}">{safe}</div>'
        preview = escape(" ".join(words[:preview_words]) + "...")
        # The full copy lives in the <details> BODY (after </summary>), not the
        # summary, so a closed <details> hides it natively — no flash of the whole
        # rationale before THEME_CSS loads (it was visible until .xt-full's
        # stylesheet display:none kicked in). The [open] rules still reveal it.
        return (
            '<details class="xt"><summary>'
            f'<div class="{body_class} xt-excerpt{pre_cls}">{preview}</div>'
            '<span class="xt-cue"></span></summary>'
            f'<div class="{body_class} xt-full{pre_cls}">{safe}</div>'
            '</details>'
        )
    if len(text) <= min_chars:
        return f'<div class="{body_class}{pre_cls}">{safe}</div>'
    return (
        '<details class="xt"><summary>'
        f'<div class="{body_class} xt-clamp{pre_cls}" style="--xt-lines:{lines}">{safe}</div>'
        '<span class="xt-cue"></span></summary></details>'
    )


def skill_strip(chips: list[str], *, head: int = 6) -> str:
    """Render skill chips as a one-row preview with a "+N more" expand toggle.

    ``chips`` are pre-rendered chip spans (the caller knows active-filter state).
    With more than ``head``, the surplus is hidden behind a native <details> whose
    "+N" pill reveals the rest inline; otherwise a plain one-row strip is returned.
    """
    if len(chips) <= head:
        return f'<div class="skills">{"".join(chips)}</div>'
    shown, rest = "".join(chips[:head]), "".join(chips[head:])
    extra = len(chips) - head
    return (
        '<details class="xt xt-skills"><summary class="skills-line">'
        f'<span class="skills skills-clip">{shown}</span>'
        f'<span class="chip chip-more" data-n="{extra}"></span></summary>'
        f'<div class="skills skills-rest">{rest}</div></details>'
    )


def meta_line(row) -> str:
    """One null-omitting meta string: salary, seniority, type, industry, recency."""
    parts: list[str] = []
    salary = salary_label(row.salary_min, row.salary_max)
    if salary:
        parts.append(salary)
    if row.seniority:
        parts.append(str(row.seniority).replace("_", " ").title())
    if getattr(row, "employment_type", None):
        parts.append(str(row.employment_type).replace("_", " ").title())
    if getattr(row, "industry", None):
        parts.append(str(row.industry))
    if getattr(row, "posted_at", None) is not None:
        posted = row.posted_at
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        else:
            posted = posted.astimezone(timezone.utc)
        days = max(0, (datetime.now(timezone.utc) - posted).days)
        parts.append("today" if days == 0 else f"{days}d ago")
    return " · ".join(escape(part) for part in parts)


def masthead(kicker: str, title_html: str, subtitle: str) -> None:
    import streamlit as st
    st.markdown(
        f'<div class="masthead"><div class="masthead-kicker">{kicker}</div>'
        f'<h1 class="masthead-title">{title_html}</h1>'
        f'<div class="masthead-sub">{subtitle}</div></div>',
        unsafe_allow_html=True,
    )


def metric_row(metrics: list[tuple[str, str]]) -> None:
    import streamlit as st
    cells = "".join(
        f'<div class="metric"><div class="metric-value">{value}</div>'
        f'<div class="metric-label">{label}</div></div>'
        for label, value in metrics
    )
    st.markdown(f'<div class="metric-row">{cells}</div>', unsafe_allow_html=True)


def empty_state(glyph: str, title: str, body_html: str) -> None:
    import streamlit as st
    st.markdown(
        f'<div class="empty-state"><div class="empty-glyph">{glyph}</div>'
        f'<div class="empty-title">{title}</div>'
        f'<div class="empty-body">{body_html}</div></div>',
        unsafe_allow_html=True,
    )
