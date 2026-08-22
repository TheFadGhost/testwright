# DESIGN.md

## Point of view

Testwright is a careful, conservative tool. It is closer to a code formatter than
to an assistant: it scans, it proposes, it proves each proposal by running it, and
it tells you exactly what it did — including what it threw away and why. It never
modifies an existing file, never writes anything without an explicit flag, never
emits a test its verification loop could not execute, and never reports a coverage
number without naming the method that measured it. A CLI does not need more than
that. Everything below exists to serve that register; where a feature would make
the tool louder instead of more trustworthy, the feature loses.

The most important interface is not the terminal — it is the generated test file,
which another developer will read and judge. Generated code is treated as a design
deliverable with the same rigour as the CLI.

---

## The generated test

### Anatomy

- **One file per source module**, placed according to the repository's detected
  layout (adjacent `tests/test_<name>.py`, or mirrored tree; `__tests__/`,
  `<name>.test.js` / `<name>.spec.js` for JavaScript).
- **Naming pattern**
  - Python: `test_<function>` for the primary case, `test_<function>_<scenario>`
    for edge cases. Scenario words are drawn from the inputs used:
    `test_divide_rejects_zero_divisor`. Methods: `test_<Class>_<method>`.
  - JavaScript: `describe('<module>')` containing `it('<scenario>')`; scenario
    sentences read like `returns the quotient for two integers`.
- **Arrangement**: arrange–act–assert with blank lines between phases. Arrange is
  inline literals; no shared mutable state between tests. If the repository's own
  tests use fixtures/setup idioms for equivalent work, Testwright matches them.
- **Comment policy**: no comments. A module-level docstring of one line is emitted
  when the target repo's tests have one (`"""Tests for pkg.module."""`). Comments
  must never restate what the code does. No TODOs anywhere, ever.
- **One assertion concept per test**: one call under test, one property asserted.
  Related input/output pairs are separate tests, not loops over cases inside one
  test body (loops hide which case failed).
- **Edge-case grouping**: edge cases become additional named tests of the same
  function, ordered after the primary case: happy path first, then boundaries,
  then error behaviour.
- **Hard bans in generated code** (checked before emission, violations discard):
  - no TODO/FIXME/XXX markers
  - no placeholder assertions (`assertTrue(True)`, `expect(true).toBe(true)`,
    `pass` as an assertion)
  - no commented-out code
  - no assertions that cannot fail (comparing an expression to itself, comparing
    two literals)

### Characterization honesty

The deterministic backend cannot know intended behaviour. It executes the function
once with constructed inputs (only when `--execute` is granted) and pins the
observed result. These are characterization tests: they detect regressions and
kill mutants, and they say so plainly in the summary report ("expected values were
captured from current behaviour"). A function whose probes raise exceptions on
every constructed input is skipped rather than pinned as "always raises".

### Good example (would be emitted)

```python
"""Tests for ledger.split."""

from ledger.split import split_evenly


def test_split_evenly_returns_equal_shares():
    shares = split_evenly(90, 3)

    assert shares == [30, 30, 30]


def test_split_evenly_returns_empty_list_for_zero_people():
    shares = split_evenly(90, 0)

    assert shares == []
```

Why it passes: correct import path from the real module graph; AAA layout;
one assertion concept per test; names state the scenario; nothing to delete.

### Rejected example (and why)

```python
def test_split_evenly():  # TODO: add real cases
    result = split_evenly(90, 3)
    # assert result == [30, 30, 30]
    assert True
```

Rejected for three independent reasons, any one sufficient: contains a TODO;
contains commented-out code; ends in a placeholder assertion that cannot fail.

---

## CLI

```
testwright scan PATH        analyze, correlate coverage, rank untested functions
testwright generate PATH    do everything scan does, then generate + verify tests
testwright clean PATH       remove only files previously written by Testwright
```

Global flags: `--config FILE`, `--no-color`, `--json`, `-v/--verbose`, `-q/--quiet`.

Key `generate` flags:

| flag          | effect                                                        |
|---------------|---------------------------------------------------------------|
| `--top N`     | only the N highest-ranked targets                             |
| `--explain F` | print the full ranking rationale for function F               |
| `--coverage F`| ingest a coverage report (lcov, cobertura, coverage.py JSON)   |
| `--backend`   | `template` (default) or `command:` pointing at an external generator |
| `--execute`   | grant permission to run the target project's code (required for verification) |
| `--write`     | create new test files (requires verified tests; refuses otherwise) |
| `--mutate`    | mutation-validate each surviving test (Python targets)         |
| `--changed`   | restrict to files changed vs the git merge-base                |

Default run (no flags beyond a path): scan, generate candidates, print diff
previews, print summary. Nothing is executed and nothing is written.

Help text states what a command does in plain declarative sentences. No marketing
adjectives, no emoji, no banners, no ASCII art, no "AI-powered" anywhere.

### Exit codes (stable, documented)

| code | meaning                                                        |
|------|----------------------------------------------------------------|
| 0    | success, including runs where every candidate was discarded    |
| 1    | Testwright usage/configuration error                           |
| 2    | failure in the target repository environment (runner missing, suite timeout) |

`--json` output carries `"schema": "testwright.report/1"`; fields are additive only.

### Progress display

Progress is honest about unknown remaining time:

- Phase headers when duration is unknown: `scanning files...`
- Counts once enumeration finishes: `[12/40] analyzing src/payroll/tax.py`
- Verification lines name the subject and verdict: `verify split_evenly ... pass`
- No percentage bars that can stall at 99%. Non-TTY output prints phase
  completions only, one line each.

### Summary report anatomy

Leads with what was discarded, then what was generated, then coverage.

```
Discarded
  payroll/tax.py::prorate      failed verification after repair (AssertionError)
  payroll/tax.py::brackets     meaningless: assertion cannot fail
Generated
  tests/test_tax.py            3 tests (prorate x2, round_to_cents x1)
Coverage delta
  targeted modules line coverage 41% -> 58%
  method: coverage.py branch-off line coverage, measured before and after
```

Every number carries its measurement method or says "not measured".

### Diff preview

Unified-diff format with `---`/`+++` file headers, `@@` hunks, `+`/`-` markers.
Markers are always present; colour is decoration on top, never the sole signal.
Readable without colour by construction.

### Error message shape

```
error: <what went wrong>
  file: <path>            (when applicable)
  function: <name>        (when applicable)
  next step: <actionable instruction>
```

Example:

```
error: could not find a way to run this project's tests
  file: package.json
  next step: install jest (npm install --save-dev jest) or set
    [languages.javascript] test_command in testwright.toml
```

### Colour roles and themes

Colour is proportionate: five roles, one token table, applied centrally — no ANSI
escapes scattered through modules. Two themes plus plain mode.

| token     | dark theme      | light theme     | plain  |
|-----------|-----------------|-----------------|--------|
| accent    | cyan `\x1b[36m` | blue `\x1b[34m` | none   |
| success   | green `\x1b[32m`| green `\x1b[32m`| none   |
| warning   | yellow`\x1b[33m`| yellow`\x1b[33m`| none   |
| error     | red `\x1b[31m`  | red `\x1b[31m`  | none   |
| muted     | white `\x1b[37m`| black `\x1b[30m`| none   |

Diff-add = success, diff-del = error, always paired with `+`/`-` markers. Diff
colours chosen to remain distinguishable under deuteranopia because the markers
carry the information, not the hue.

Colour is enabled only when stdout is a TTY, `NO_COLOR` is unset, and `--no-color`
was not passed. On 16-colour terminals the standard codes above are already the
palette; no 256-colour or truecolour escapes are used.

### Machine-readable mode

`--json` suppresses all human progress output and emits exactly one JSON document
to stdout (logs go to stderr). Schema documented in README and versioned as
`testwright.report/1`.

---

## Architecture note

`analyze -> prioritize -> generate -> verify -> report`. The code model
(`src/testwright/model.py`) is the contract between language analyzers and
generators. Generation backends implement `GeneratorBackend`; verification is
mandatory and sits downstream of every backend, so no backend can emit an
unverified test. The sandbox bounds execution by wall-clock timeout and process
tree kill; on POSIX, address-space rlimits are additionally applied. Running an
unknown repository's test suite executes that repository's code; Testwright says
so wherever it matters.
