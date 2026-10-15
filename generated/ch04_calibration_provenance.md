# CAL-01 v4 provenance

Data class: `illustrative_constructed`. Every source row and generated table row carries this label.

- Scope: constructed, held-out-style binary outcomes for one illustrative action class and one version bundle
- Claim boundary: method mechanics only; no production model, threshold, action class, or operational effect is validated
- Authoritative input: `fixtures/ch04/CAL-01/synthetic_smoke.csv`
- Input SHA-256: `b6e914b2a3482236b8356a1c7cfb52dd5815e34008351face95b047572a661fc`
- Generator SHA-256: `dd4095891311069d3aa7ba7e82f3eed810a09d0417544878971d91799df6b492`
- Independent unit rule: at most one row per `incident_group_id` and `action_class`
- Eligible rows in this fixture: 254
- Adjudicated binary rows: 254
- Indeterminate rows: 0
- Excluded rows: 0
- Bin convention: `[0.50,0.60)`, `[0.60,0.70)`, `[0.70,0.80)`, `[0.80,0.90)`, `[0.90,0.95)`, `[0.95,1.00]`
- Bin counts in that order: 40, 55, 80, 62, 10, 7
- Interval: two-sided 95% Wilson score interval, `z=1.959963984540054`
- Illustrative boundaries: 0.70 and 0.90; neither is a recommendation
- Decision rule: a bin is uncertified when its interval crosses the nearest illustrative boundary; no sample-count minimum certifies a bin
- Version rule: pooling across action classes or model/calibrator versions is rejected
- Runtime used for release artifacts: CPython 3.12.13
- Dependency versions: Python standard library from CPython 3.12.13; no third-party package
- Exact command: `cd companion && make calibration`

The fixture contains no indeterminate or excluded examples. The zero counts above describe this constructed input; the lab does not silently remove either outcome class from a larger population.
