# AUDIT.md

Pre-release audits were run with fresh-eyes sub-agents that had not written the
code under review: a dedicated safety audit (write path, sandbox, injection,
resource leaks), a code-quality audit (dead code, duplication, consistency),
and a generated-code quality review that ran the tool on the corpus and judged
the output as a senior reviewer would. Every FEATURE was verified by actually
running the tool; anything not demonstrable was treated as not done.

## Safety audit findings and resolution

| id | severity | finding | resolution |
|----|----------|---------|------------|
| M1 | major | probe `repr()` output interpolated raw into written assertions; a hostile `__repr__` could smuggle code into a test file | fixed: every repr must round-trip through `ast.literal_eval` (`repr_is_comparable`) before it can reach a generated assertion; non-literals are skipped |
| M2 | major | repo file/directory names embedded unescaped in JS string literals (`describe`, `it`, `require`) | fixed: all JS strings emitted via JSON escaping; import/test paths must match a safe-character allowlist or the module is skipped |
| M3 | major | `testwright clean` deleted manifest-listed paths without containment; a tampered manifest could delete outside the tree | fixed: each entry passes the same containment check as the write path; violations are skipped with a warning |
| M4 | major | POSIX timeout killed only the direct child; grandchildren holding pipes could hang the run | fixed: children spawn in their own process group and `killpg` reaps the tree; post-kill pipe drain is itself time-bounded |
| M5 | major | probes/verification compiled target modules inside the target tree, leaving unrecorded `__pycache__` writes | fixed: `PYTHONDONTWRITEBYTECODE=1` set for every spawned process |
| m1-m8 | minor | non-atomic manifest write; coverage suffix matching could return `..` paths; TOCTOU between assembly check and write (final check remains in `write_new_file`); runner substring match (`esbuild-jest`); disclosure gaps (Windows memory not bounded, root-level `pytest.py` shadowing) | fixed or documented: atomic `os.replace` manifest, `..` rejection, exact dependency-name matching, DESIGN/README disclosures |

Verified sound by the audit with no changes needed: no shell interpolation
anywhere (argv lists only), stdin closed and output capped, env scrubbing of
`PYTHONPATH`/`NODE_OPTIONS`/`COVERAGE_FILE`/`PYTEST_ADDOPTS`, triple-layer
overwrite defense ending in an atomic create-only write, containment checks on
every path derived from repository content, fail-closed coverage parsers,
graceful handling of unparseable sources / missing runners / absent git /
absent coverage tooling, temp directories cleaned on success and error paths.

## Code-quality audit findings and resolution

All high/medium findings fixed: dead `runners` invocation layer removed (~100
lines), dead `VerifiedTest` type replaced with the real candidate type,
`GenerationUnit.render()` duplicate removed, unused `probes` parameter removed
from the backend interface, language enable/disable logic rewritten (a config
bug could silently disable Python analysis), `sys.executable` used for all
target-code invocation, shared skip-dir sets unified per module, error types
aligned to the documented exit-code contract (`UsageError` -> 1,
`TargetError` -> 2), inline `__import__` calls removed, leftover scaffolding
(`# __PART__` markers, no-op branches, unused variables) deleted, missing
type annotations added.

## Generated-code review findings and resolution

The reviewer rejected all three sample files; every blocking finding is fixed
and covered by the corpus gates:

- dead imports from discarded candidates -> imports now narrowed to kept tests
  only at assembly time
- unittest methods without separating blank lines (PEP 8 E301) -> fixed
- missing `unittest.main()` guard vs repo idiom -> detected from sibling tests
  and emitted
- ulp-brittle float equality (`0.6666666666666666`) -> automatic tolerance
  matcher (`pytest.approx` / `assertAlmostEqual(places=10)` / `toBeCloseTo(x,10)`)
- error-path behaviour captured by probes but dropped -> raising probes become
  `pytest.raises` / `assertRaises` / `toThrow(ErrorType)` tests when at least
  one normal case survives verification
- JS `it()` naming contradicted DESIGN.md -> DESIGN.md updated to bless the
  call-echo style the repos use (design doc follows reality)
- characterization honesty sentence promised but never printed -> printed in
  both text summary and JSON `note`
- overwrite refusals not counted in `tests_discarded` -> counted
- reports dropped generated file contents -> `content` included in `--json`

Known accepted limitations (documented, deliberate):
- characterization tests pin current behaviour; they cannot know intent
- mutation validation covers Python targets only
- jest + ESM sources are skipped with an explanation rather than mis-generated
- unpackaged nested Python modules are skipped (no reliable import path)

## Stranger test / clean run

- full suite re-run from a clean checkout state: green (37 tests)
- README commands exercised verbatim via `PYTHONPATH=src python -m testwright ...`
  (installing into system site-packages would violate this workspace's folder
  isolation rule; `pip install .` is the documented end-user path)
- `NO_COLOR`, `--no-color`, non-TTY plain mode verified to emit zero ANSI codes
- exit codes verified live: 0 success, 1 usage/config error, 2 target errors
