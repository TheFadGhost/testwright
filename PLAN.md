# PLAN.md

Feature ideation for Testwright. Every candidate below was judged against three tests:

1. Does it serve the core purpose of increasing **meaningful** test coverage?
2. Can it be finished to the same quality bar as the committed features?
3. Does it avoid expanding scope into a second product (a refactoring tool, a
   static-analysis lint suite, a coverage-hosting service, a review bot)?

## Accepted

These are first-class FEATURES under the same loop and audit as the committed set.

- **Interactive review-and-accept flow** — a per-test accept/skip gate over the
  diff; directly raises meaningful coverage and is an extension of the write path.
- **CI mode with machine-readable output and meaningful exit codes** — the same
  tool run headless; JSON output plus documented exit codes let teams gate on results.
- **Sensible default exclusions** (vendored code, generated code, migrations,
  build output) — stops wasted generation on noise; user-overridable via config.
- **Helpful errors when the test command cannot be found** — names what was
  looked for, what was detected, and the next step.
- **`--explain` showing why a function was prioritized** — surfaces the already-
  computed ranking components (complexity, fan-in, API surface, recency, coverage).
- **Incremental mode (`--changed`)** — restricts work to files changed in git;
  focuses effort where regressions live without changing the pipeline.
- **Resumable scan cache** — content-hash keyed manifest so large repositories do
  not re-analyze unchanged files; pure infrastructure.
- **Generated-files manifest with safe cleanup (`testwright clean`)** — removes
  only files Testwright wrote, tracked by hash in `.testwright-manifest.json`;
  deepens the safety story instead of widening scope.

## Rejected

- **Watch mode** — fails 1 and 2: continuous regeneration adds watcher/debounce
  complexity with near-zero extra meaningful coverage for a batch task.
- **Auto-fixing source code to be more testable** — fails 1 and 3: edits production
  code (violates the never-modify promise); that is a refactoring tool.
- **Documentation generation** — fails 1 and 3: zero coverage impact; docs tool is
  a second product.
- **IDE plugins** — fails 2 and 3: multi-editor surface cannot reach the quality
  bar and turns the CLI into a distribution platform.
- **Parallel shard execution of target tests** — fails 2: cross-process isolation
  flakiness threatens the "never emit an unverified test" guarantee.
- **Server/daemon mode** — fails 3: persistent-service operations far beyond a CLI.
- **Posting PR comments** — fails 3: forge APIs and auth drift make it a review
  bot; CI-mode JSON already carries the data out.
- **Severity scores exported to dashboards** — fails 3: metrics hosting is the
  coverage-hosting service in embryo.
- **Coverage-threshold policy enforcement/gating** — fails 3: governance-over-time
  is a different product; users can gate on the JSON output themselves.
- **Rewriting or upgrading existing weak tests** — fails 1 and 3: modifies existing
  files (safety violation) and is test-suite refactoring, not gap filling.
- **Flaky-test detection and quarantine tracking** — fails 3: test-health platform,
  adjacent but distinct from generating missing tests.
- **Telemetry/analytics** — fails 1: adds nothing to coverage and burdens trust in
  a safety-positioned tool.

## Release plan

- v0.1.0 — verified passing generated tests for one language (Python/pytest) on the
  committed corpus, end to end.
- minor bump per added language or major subsystem (JavaScript analyzer + Jest path).
- v1.0.0 only after a clean fresh-eyes audit (see AUDIT.md).

## Regression baseline

Quality is measured on the committed corpus (tests/fixtures/repos): tests generated,
tests discarded (with reasons), coverage delta (method stated wherever a number
appears), and mutation-kill rate. A change that increases tests generated while
lowering the mutation-kill rate is a regression and is reverted. Baseline numbers
live in BASELINE.md and are re-recorded whenever they legitimately improve.
