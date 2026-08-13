# Job artifact-run lookup baseline (2026-08-12)

## Scope

The Job modal previously filtered and sorted the complete run collection for
each artifact row. The replacement builds one index per immutable run-store
snapshot and performs constant-time artifact lookups from that index.

## Method

- Windows development machine, Node/Vite runtime from `web/node_modules`.
- Synthetic run snapshots of 100, 1,000, and 5,000 records.
- 100 artifact queries per sample.
- The new measurement includes both the one-time index build and all queries.
- These are local directional measurements, not production latency SLOs.

## Results

| Runs | Previous filter/sort queries | Indexed snapshot + queries | Reduction |
| ---: | ---: | ---: | ---: |
| 100 | 2.550 ms | 0.460 ms | 82.0% |
| 1,000 | 23.549 ms | 1.641 ms | 93.0% |
| 5,000 | 203.884 ms | 10.427 ms | 94.9% |

The production build's initial bundle remained effectively flat: 87.33 kB
gzip before and 87.31 kB gzip after.

## Guardrail

`artifact-lifecycle.test.ts` verifies that every consumer receives the same
index object for one store snapshot and a new snapshot receives a new index.
This protects the once-per-snapshot complexity property independently of wall
clock timing.
