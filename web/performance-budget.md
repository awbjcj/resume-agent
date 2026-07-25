# Web performance budget

These budgets make regressions visible; the current measurements do not justify
bundle refactoring.

| Surface | Budget | Current baseline |
| --- | ---: | ---: |
| Initial JavaScript | 200 KB gzip | about 132 KB (`index` 86.03 KB + `lib` 45.72 KB) |
| Largest lazy route chunk | 120 KB gzip | `AnalyticsPage` 99.50 KB |
| Board page response | 150 KB | enforced by the pipeline payload regression test |

All routes are already split with `lazy()`. Re-measure these values after adding
a substantial dependency, moving code into the initial route, or expanding a
board response contract.
