# Pre-closing market goal-rate challenger

Generated: 2026-08-07T16:47:34.705470+00:00

## Verdict

**PASS** — on the untouched 2023/24–2025/26 seasons, market Poisson deviance was 1.0514 versus 1.0892, goal MAE was 0.9179 versus 0.9331, and clean-sheet Brier was 0.1678 versus 0.1702.

This passes the fixture-probability gate. It remains a shadow challenger until a legal FPL policy replay proves that the improvement converts into points and a deadline-safe current-season feed is present.

## Season-forward evidence

| Season | Source | Poisson deviance | Goal MAE | CS Brier |
|---|---|---:|---:|---:|
| 2019-20 | market | 1.0651 | 0.8726 | 0.1853 |
| 2019-20 | incumbent | 1.1336 | 0.9099 | 0.1885 |
| 2020-21 | market | 1.2363 | 0.9490 | 0.1976 |
| 2020-21 | incumbent | 1.2724 | 0.9547 | 0.2020 |
| 2021-22 | market | 1.1058 | 0.9133 | 0.1797 |
| 2021-22 | incumbent | 1.1543 | 0.9404 | 0.1842 |
| 2022-23 | market | 1.1874 | 0.9488 | 0.1869 |
| 2022-23 | incumbent | 1.2015 | 0.9496 | 0.1893 |
| 2023-24 | market | 1.0461 | 0.9548 | 0.1552 |
| 2023-24 | incumbent | 1.0887 | 0.9745 | 0.1559 |
| 2024-25 | market | 1.0598 | 0.9156 | 0.1708 |
| 2024-25 | incumbent | 1.0912 | 0.9265 | 0.1724 |
| 2025-26 | market | 1.0483 | 0.8833 | 0.1775 |
| 2025-26 | incumbent | 1.0876 | 0.8983 | 0.1822 |

## Information safety and provenance

The source labels non-closing columns as pre-closing odds and says weekend odds are collected Friday afternoons and midweek odds Tuesday afternoons. Only `AvgH`, `AvgD`, `AvgA`, `Avg>2.5` and `Avg<2.5` are used; all columns containing the closing marker `C` are excluded. Prices are de-vigged before two independent-Poisson goal rates are fitted.

Source notes: https://www.football-data.co.uk/notes.txt

This is research evidence, not betting advice. Market availability and timestamp coverage must be verified before every live deadline; missing odds never silently fall back to fabricated values.
