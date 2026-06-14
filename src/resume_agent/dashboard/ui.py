"""Broadsheet design system: theme CSS, palette, and pure HTML helpers.

All functions here are pure (no Streamlit calls at import or call time) so the
module imports cleanly and the helpers are unit-testable without a server.
"""

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600;6..72,700&family=IBM+Plex+Mono:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
  --paper:#f4f1ea; --paper-2:#efeae0; --ink:#16130f; --muted:#6c6253;
  --oxblood:#8c2f1f; --rule:rgba(22,19,15,0.16);
}

.stApp { background: var(--paper); color: var(--ink); }
.block-container { padding-top: 2.2rem; max-width: 2400px; }

html, body, [class*="css"], .stMarkdown, p, li, label,
.stTextInput input, .stSelectbox div, .stDataFrame, table {
  font-family: 'IBM Plex Sans', -apple-system, sans-serif;
}
h1, h2, h3, h4, .card-title, .nameplate, .empty-title {
  font-family: 'Newsreader', Georgia, serif !important; letter-spacing: -0.01em;
}

/* ── Masthead / nameplate ─────────────────────────────────────── */
.nameplate { font-family:'Newsreader',serif; font-size: 1.7rem; font-weight: 700; margin-bottom: 1rem; }
.masthead { margin: 0 0 1.6rem 0; padding-bottom: 1.0rem; border-bottom: 2px solid var(--ink); }
.masthead-kicker {
  font-family:'IBM Plex Mono', monospace; font-size: 0.72rem; letter-spacing: 0.34em;
  text-transform: uppercase; color: var(--oxblood); margin-bottom: 0.5rem;
}
.masthead-title { font-size: clamp(2.2rem, 2.4vw, 3.0rem); font-weight: 700; line-height: 1.02; margin: 0; color: var(--ink); }
.masthead-title .dot { color: var(--oxblood); }
.masthead-sub { color: var(--muted); margin-top: 0.5rem; font-size: 1.0rem; max-width: 70ch; }

/* ── Metric strip ─────────────────────────────────────────────── */
.metric-row { display:flex; gap: 1.0rem; margin: 0.4rem 0 1.6rem 0; flex-wrap: wrap; }
.metric { flex:1; min-width: 150px; background: var(--paper-2); border:1px solid var(--rule); border-radius: 4px; padding: 1.0rem 1.2rem; }
.metric-value { font-family:'Newsreader', serif; font-size: clamp(1.8rem, 1.8vw, 2.4rem); font-weight: 700; color: var(--ink); line-height:1; }
.metric-label { font-family:'IBM Plex Mono', monospace; font-size: 0.66rem; letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted); margin-top: 0.45rem; }

/* ── Responsive card grid (the 4K fill) ───────────────────────── */
/* Keyed st.container(key="cardgrid_…") emits a stable .st-key-cardgrid…
   class on the real DOM node; its child vertical block holds the cards. */
[class*="st-key-cardgrid"] > div[data-testid="stVerticalBlock"] {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: clamp(0.8rem, 1vw, 1.4rem);
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

.card-title { font-size: 1.32rem; font-weight: 600; color: var(--ink); margin: 0; }
.card-meta { color: var(--muted); font-size: 0.92rem; margin-top: 0.15rem; }
.rationale { color: #3f382e; font-size: 0.95rem; line-height: 1.5; margin-top: 0.5rem; border-left: 2px solid var(--oxblood); padding-left: 0.8rem; }
.rail-head { font-family:'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.24em; font-size: 0.74rem; color: var(--muted); margin: 1.5rem 0 0.4rem; display:flex; align-items:center; gap: 0.7rem; }
.rail-head::after { content:""; flex:1; height:1px; background: var(--rule); }

/* ── Cards (Streamlit bordered containers) ────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--paper-2); border: 1px solid var(--rule) !important; border-radius: 6px;
  box-shadow: 0 1px 0 rgba(22,19,15,0.04); transition: border-color .18s ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: var(--oxblood) !important; }

/* ── Buttons ──────────────────────────────────────────────────── */
.stButton > button { font-family:'IBM Plex Mono', monospace; font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; border-radius: 3px; border: 1px solid var(--oxblood); background: var(--oxblood); color: var(--paper); font-weight: 600; padding: 0.45rem 1.1rem; transition: all .15s ease; }
.stButton > button:hover { background: #75271a; border-color:#75271a; }
.stDownloadButton > button { font-family:'IBM Plex Mono', monospace; font-size: 0.74rem; letter-spacing: 0.06em; border-radius: 3px; background: transparent; color: var(--ink); border: 1px solid var(--rule); }
.stDownloadButton > button:hover { border-color: var(--oxblood); color: var(--oxblood); }

/* ── Sidebar ──────────────────────────────────────────────────── */
[data-testid="stSidebar"] { background: var(--paper-2); border-right: 2px solid var(--ink); }
[data-testid="stSidebar"] .stRadio label { font-family:'IBM Plex Sans'; }

/* ── Inputs / tables / expander (re-themed for paper) ─────────── */
.stTextInput input, .stSelectbox [data-baseweb="select"] > div { background: #fff !important; border-color: var(--rule) !important; border-radius: 3px !important; color: var(--ink) !important; }
[data-testid="stExpander"] summary { font-family:'IBM Plex Mono', monospace; font-size: 0.76rem; letter-spacing: 0.06em; color: var(--muted); }
table { border-collapse: collapse; }
thead th { font-family:'IBM Plex Mono', monospace !important; font-size: 0.7rem !important; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted) !important; border-bottom: 2px solid var(--ink) !important; }
tbody td { border-bottom: 1px solid var(--rule) !important; }

/* ── Focus visibility (keyboard a11y) ─────────────────────────── */
.stButton > button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.stTextInput input:focus-visible, .stSelectbox [data-baseweb="select"] > div:focus-within { border-color: var(--oxblood) !important; box-shadow: 0 0 0 2px color-mix(in srgb, var(--oxblood) 30%, transparent) !important; }

/* ── Empty states ─────────────────────────────────────────────── */
.empty-state { text-align:center; padding: 3.4rem 1.2rem; border: 1px dashed var(--rule); border-radius: 6px; margin-top: 0.4rem; background: var(--paper-2); }
.empty-glyph { font-family:'Newsreader', serif; font-size: 2.6rem; color: var(--oxblood); opacity: .9; line-height: 1; }
.empty-title { font-size: 1.34rem; color: var(--ink); margin-top: .5rem; }
.empty-body { color: var(--muted); font-size: .96rem; margin-top: .45rem; }
.empty-body code { font-family:'IBM Plex Mono', monospace; font-size: .85em; color: var(--ink); background: #fff; border: 1px solid var(--rule); border-radius: 3px; padding: .1rem .42rem; }

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
