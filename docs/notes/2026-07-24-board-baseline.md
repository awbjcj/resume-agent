# Board Read-Path Baseline — 2026-07-24

Synthetic measurements use `scripts/bench_board.py`, 2,000 file-backed SQLite
jobs, 10 warm repetitions, 50 rows per page, and production-shaped criteria.
Times are milliseconds; payload columns are uncompressed UTF-8 bytes.

| Board | Page | p50 | p95 | Payload | `jdText` | Facets |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| shortlist | 1 | 39.6 | 42.6 | 37,326 | 0 | 330 |
| shortlist | 7 (last) | 38.7 | 41.4 | 25,479 | 0 | 330 |
| triage | 1 | 47.0 | 56.4 | 14,129 | 0 | 65 |
| triage | 14 (last) | 46.6 | 47.6 | 4,897 | 0 | 65 |
| pipeline | 1 | 1,215.4 | 1,608.0 | 337,999 | 304,700 | 444 |
| pipeline | 40 (last) | 1,085.5 | 1,113.4 | 337,967 | 304,700 | 444 |

Command:

```powershell
.venv\Scripts\python.exe scripts\bench_board.py --rows 2000 --repeat 10 --page 1 last
```

The real development Workspace measured at plan authoring contained 2,096 jobs
and 11.7 MB of `jd_text`. Its pipeline page 1 cost 261.6 ms (median 303.5 ms),
page 40 cost 219.2 ms, and the page-1 response was 406.8 KB, including 287.3 KB
of `jdText` and 39.7 KB of facets. The synthetic fixture is intentionally
repeatable rather than numerically identical; its page-depth parity and payload
composition reproduce the same failure mode.

The post-implementation table belongs below this section so before/after
measurements retain the exact fixture and command.
