# Board read-path baseline — 2026-07-19

Machine: AMD64 (AMD Ryzen, Family 25) — Windows 11, CPython 3.13.2
Command: `.venv/Scripts/python.exe scripts/bench_board.py`

```
   rows      board   p50 ms   p95 ms
   1000  shortlist     23.4     52.5
   1000     triage     24.7     40.0
   5000  shortlist    133.9    178.4
   5000     triage    123.1    147.2
  10000  shortlist    267.3    302.4
  10000     triage    267.1    302.6
```

**Threshold for Task 9 (deferred jd_text):** proceed only if shortlist or
triage p95 at 5,000 rows exceeds 100 ms. Otherwise skip Task 9 Steps 2-4 and
record "within budget" here.

Result: **exceeded** — shortlist p95 178.4 ms and triage p95 147.2 ms at 5,000
rows are both over the 100 ms budget. Task 9 deferral applied.

**Post-fix table (after Task 9 — `defer(jd_text)` on shortlist/triage/archived list queries):**

```
   rows      board   p50 ms   p95 ms
   1000  shortlist     14.7     29.0
   1000     triage     15.0     24.7
   5000  shortlist     78.9    124.1
   5000     triage     78.0    132.6
  10000  shortlist    176.3    218.9
  10000     triage    159.7    215.3
```

Deferral kept: p95 at 5,000 rows improved for both boards (shortlist
178.4 → 124.1 ms, triage 147.2 → 132.6 ms), and p50 nearly halved. Deferring
the ~4.4 KB `jd_text` column — never shipped by `ShortlistItem`/`TriageItem` —
removes it from every row's hydration. The guard test
(`test_shortlist_and_triage_rows_never_touch_jd_text`) keeps the invariant from
silently regressing into an N+1.
