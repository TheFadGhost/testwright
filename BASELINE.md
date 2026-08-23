# BASELINE.md — regression baseline on the committed corpus

Quality is measured by running the tool end to end against every repository in
`tests/fixtures/repos` and comparing: tests generated, tests discarded (with
reasons), coverage delta (with method), and mutation-kill outcome. A change that
increases tests generated while lowering the mutation-validated share is a
regression and must be reverted.

Command form (from the repository root):

```
PYTHONPATH=src python -m testwright generate tests/fixtures/repos/<repo> \
    --execute --mutate --json --report out.json
```

## Baseline recorded 2026-08-23 (v1.0.0 candidate)

### py_pytest_app (Python, pytest, packaged)

- ranked targets: 4 relevant; functions targeted 4
- tests generated: 6, all mutation-validated (mutation-kill rate 6/6 = 100% of
  emitted tests detected at least one applied mutant)
- tests discarded: 2 weak (`prorate` characterization cases survived all five
  mutator kinds; discarded rather than emitted), plus overwrite refusals for
  `split.py::round_to_cents` because `tests/test_split.py` already exists
- coverage delta: `payroll/tax.py` executed lines 0 -> 12
  (method: coverage.py line coverage over repository sources; existing suite vs
  existing suite plus generated tests)

### py_unittest_app (Python, unittest, flat layout)

- functions targeted 4; tests generated 2 (`geom3d.py`), both mutation-validated
- discard reasons: adjacent `test_geom.py` already exists, so nothing may be
  written for the covered module (safety refusal, reported)
- coverage delta: `geom3d.py` executed lines 0 -> 5 (same method as above)

### js_jest_app (JavaScript, Jest, __tests__ layout)

- functions targeted 6; tests generated 4 into `src/__tests__/stats.test.js`,
  verified by running jest from the target's own node_modules
- discard reasons: existing `src/__tests__/math.test.js` refuses overwrite for
  `math.js` targets (safety refusal)
- coverage delta: not measured (no standard JS coverage tool wired in this version)

## Notes

- Mutation validation applies up to four text-level mutants per function
  (comparison inversion, ordering tightening, +/- swap, boolean flip, integer
  bump) to a full shadow copy of the repository and requires the test to fail.
- The corpus consists of small original programs written for this project.

## Update rule

Any change that legitimately improves these numbers re-records them here with a
date. Any change that moves generation/discards without improving the
mutation-validated share is treated as a regression.
