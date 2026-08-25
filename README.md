# Testwright

> **built with ox alpha**
>
> most of this was written in august 2026 during the free preview window of
> [ox alpha](https://openrouter.ai/stealth/ox-alpha), an anonymous stealth model
> that turned up on openrouter for about a week. i set the direction and reviewed
> what came back. the tests are real and they pass — clone it and run them.

Testwright scans a codebase for functions with no test coverage and writes
verified unit tests that match the project's own conventions, for developers
inheriting a repository with a thin test suite.

## Safety model

Read this before running anything:

- Testwright **never modifies or deletes an existing file** in the target
  repository. It only creates new test files.
- It **refuses to overwrite**; a run that would collide with an existing test
  file reports the collision instead of writing.
- **Nothing is written unless you pass `--write`.** Without it, every run is a
  preview.
- With `--execute`, Testwright **runs code from the target repository**: its
  test suite, and one probe call per function under test. Running an unknown
  repository's test suite executes that repository's code. Review what you point
  this tool at. Execution is bounded by a wall-clock timeout (`--timeout`,
  default 120 s) and the whole process tree is killed on expiry; on POSIX an
  address-space rlimit also applies (Windows has no portable equivalent, so
  memory is not bounded there). A repository containing root modules named
  `pytest.py` or `unittest.py` could shadow the real runner during verification.
- Generated tests are emitted only if the verification loop executed them and
  they passed. Failing or meaningless candidates are repaired once or discarded,
  never written.
- A `.testwright-manifest.json` in the target root lists exactly which files
  Testwright created; `testwright clean` removes only those files.

## Install

Requires Python 3.11+ (stdlib only). For coverage deltas, `pip install coverage`
in the environment that also has the target project's runner.

```
git clone https://github.com/TheFadGhost/testwright.git
cd testwright
pip install .
```

## Quick start: dry run first

From inside (or pointing at) the target repository:

```
testwright generate path/to/repo                 # analyze + preview only
testwright generate path/to/repo --execute       # + verify by running its tests
testwright generate path/to/repo --execute --write   # + create new test files
```

Other commands:

```
testwright scan path/to/repo                     # rank untested functions
testwright scan path/to/repo --explain prorate -v # why this function ranks high
testwright clean path/to/repo                    # remove only generated files
```

Useful flags: `--top N`, `--coverage report.info|cobertura.xml|coverage.json`,
`--mutate` (mutation-validate each surviving test), `--changed` (files changed
vs HEAD), `--json` (machine-readable output), `--no-color`.

Generated tests are characterization tests: the deterministic backend executes
each function once with constructed inputs and pins the observed result, so they
detect regressions but do not know intent. Read them like any other diff.

## Supported languages and frameworks

| language   | runners detected      | notes                                        |
|------------|-----------------------|----------------------------------------------|
| Python     | pytest, unittest      | packaged modules and flat root modules        |
| JavaScript | jest, vitest, mocha   | CommonJS verified end to end; ESM+jest skipped with an explanation |

The project's existing test framework is detected from its own configuration
and test imports — never assumed — and generated style follows it (naming,
layout, assertion idiom).

## How prioritization works

Targets are scored 0-100 as `40*complexity + 25*fan-in + 20*public API surface
+ 15*git recency`, restricted to functions whose body lines are uncovered
(from your coverage report via `--coverage`) or, absent a report, functions not
referenced by any existing test. `scan --json` exposes every component;
`--explain NAME -v` prints the arithmetic for a function.

## Configuring a generation backend

The default backend is deterministic and needs no service. To use an external
generator instead, set it in `testwright.toml` at the target root:

```toml
backend = "command"
```

and implement the contract documented in `src/testwright/generate/__init__.py`.
Whatever a backend produces still has to pass the verification loop; no backend
can emit an unverified test through this tool.

## Corpus results (measured, method stated)

Small original repositories live in `tests/fixtures/repos`. Full numbers and
the exact commands are recorded in [BASELINE.md](BASELINE.md); summary at the
v1.0.0 tag, measured as described there:

| repo            | generated | discarded | mutation-validated | coverage delta (method below) |
|-----------------|-----------|-----------|--------------------|-------------------------------|
| py_pytest_app   | 6         | 2 weak + overwrite refusals | 6/6 | payroll/tax.py executed lines 0 -> 12 |
| py_unittest_app | 2         | overwrite refusals          | 2/2 | geom3d.py executed lines 0 -> 5 |
| js_jest_app     | 6         | overwrite refusals          | n/a | not measured |

The JavaScript file includes error-path tests (`toThrow(RangeError)`) and a
`toBeCloseTo` tolerance assertion for non-exact floats.

Coverage delta method: `coverage.py` line coverage over repository sources,
existing suite vs existing suite plus the generated tests. Numbers without this
kind of stated method should not be trusted; Testwright prints the method next
to every number it reports.

## Example run

Terminal capture of a real run on the pytest corpus fixture (dry run):

```
$ testwright generate tests/fixtures/repos/py_pytest_app --execute

Running with --execute will execute code from the target repository.

+ tests/test_tax.py
--- /dev/null
+++ b/tests/test_tax.py
@@ -0,0 +1,9 @@
+"""Tests for payroll.tax."""
+
+from payroll.tax import bracket_rate
+
+
+def test_bracket_rate():
+    result = bracket_rate(1.5)
+
+    assert result == 0.0

Discarded (0)
  nothing was discarded

Generated (1)
  tests/test_tax.py  1 test(s)
    test_bracket_rate

Coverage delta: coverage.py line coverage over repository sources; existing
suite vs existing suite plus generated tests

Dry run: nothing was written. Pass --write to create these files.
```

## Architecture note

Pipeline: `analyze -> prioritize -> generate -> verify -> report`. Language
analyzers produce one shared code model (`src/testwright/model.py`) — the
contract between analyzers and generators. Generation backends implement
`GeneratorBackend`; verification is mandatory downstream of every backend:
candidates are rendered into a temporary shadow directory, executed with the
project's own runner, bisected when a multi-test unit fails, statically screened
for meaningless assertions, and optionally mutation-validated against a shadow
copy of the repository.

## License

MIT — see [LICENSE](LICENSE).