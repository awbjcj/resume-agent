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

**Post-fix table (fill in after Task 9, or write "skipped — within budget"):**
