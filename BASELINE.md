# BASELINE.md — regression baseline on the committed corpus

Quality is measured by running the tool end to end against every repository in
`tests/fixtures/repos` and comparing: tests generated, tests discarded (with
reasons), coverage delta (with method), and mutation-validated share. A change
that increases tests generated while lowering the mutation-validated share is a
regression and must be reverted.

Command form (from the repository root):

```
PYTHONPATH=src python -m testwright generate tests/fixtures/repos/<repo> \
    --execute --mutate --json --report out.json
```

(The JavaScript corpus runs without `--mutate`; mutation validation currently
supports Python targets only.)

## Baseline recorded 2026-08-23 (v1.0.0 candidate, post-audit)

### py_pytest_app (Python, pytest, packaged)

- functions targeted 4; tests generated 6, all 6 mutation-validated (100%)
- tests discarded 5: two `prorate` characterization cases discarded as weak
  (they survived every applied mutant — reported, not emitted), plus three
  overwrite refusals because `tests/test_split.py` already exists
- coverage delta: `payroll/tax.py` executed lines 0 -> 12
  (method: coverage.py line coverage over repository sources; existing suite vs
  existing suite plus generated tests)
- generated imports are narrowed to kept tests only (no dead imports), unittest
  files gain the repo's `unittest.main()` guard idiom

### py_unittest_app (Python, unittest, flat layout)

- functions targeted 4; tests generated 2 (`geom3d.py`), both mutation-validated
- discard reasons: adjacent `test_geom.py` already exists for covered module
  (safety refusal); generated file carries blank lines between methods and the
  `if __name__ == "__main__": unittest.main()` guard matching the repo idiom
- coverage delta: `geom3d.py` executed lines 0 -> 5 (same method as above)

### js_jest_app (JavaScript, Jest, __tests__ layout)

- functions targeted 5; tests generated 6 into `src/__tests__/stats.test.js`,
  verified by jest from the target's own node_modules:
  happy paths for mean/sumAll/variance, error paths (`mean([])` /
  `variance([])` throw RangeError) as `toThrow(RangeError)`, and a
  `toBeCloseTo(x, 10)` tolerance assertion for non-exact floats
- discard reasons: existing `src/__tests__/math.test.js` refuses overwrite for
  `math.js` targets (safety refusal)
- coverage delta: not measured (no standard JS coverage tool wired in this version)

## Notes

- Mutation validation applies up to four text-level mutants per function
  (comparison inversion, ordering tightening, +/- swap, boolean flip, integer
  bump) to a full shadow copy of the repository and requires the test to fail.
- Probe reprs must round-trip through `ast.literal_eval` before they are
  embedded in an assertion; anything else (objects, memory addresses) is skipped.
- The corpus consists of small original programs written for this project.

## Update rule

Any change that legitimately improves these numbers re-records them here with a
date. Any change that moves generation/discards without improving the
mutation-validated share is treated as a regression.
