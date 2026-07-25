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

## After

| Board | Page | p50 | p95 | Payload | `jdText` | Facets |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| shortlist | 1 | 15.2 | 18.5 | 37,326 | 0 | 330 |
| shortlist | 7 (last) | 7.6 | 9.4 | 25,153 | 0 | 4 |
| triage | 1 | 46.5 | 52.5 | 14,129 | 0 | 65 |
| triage | 14 (last) | 28.3 | 30.3 | 4,836 | 0 | 4 |
| pipeline | 1 | 88.3 | 108.7 | 53,248 | 0 | 444 |
| pipeline | 40 (last) | 39.6 | 45.5 | 53,086 | 0 | 4 |

Pipeline page 1 is about 13.8 times faster and its payload is 84% smaller.
Later pages no longer calculate or return facets, so pipeline page 40 is faster
than page 1 rather than paying a whole-board projection cost. The repeatable
Windows measurement does not meet the plan's aspirational 50 ms page-1 target;
profiling attributes most of the remaining page-1 time to exact 12-facet
aggregation rather than page selection.
