# Implementation status

Updated: 2026-10-13

## Repository and environment

- Repository identity: `origin` is `https://github.com/JongHyun070105/comtus-ai.git`.
- Started from clean `main` at `b3dec2a13a1071f6f8f8ddf43955e70141def2a3`; implementation branch: `feat/ranking-ai-foundation`.
- Environment: arm64, macOS 27.0, Swift 6.4, Python 3.14.6, uv 0.11.7, SQLite 3.53.4.
- `git fetch --dry-run origin` passed; one primary worktree was present.
- No game process or screenshot fixture was present. Screen Recording preflight was false and did not trigger a permission prompt.

## Implemented and locally exercised

- Dependency-free Python package with separate card master/owned instance models, role-specific player snapshots, ordinal potential/pitch grades, source labels, OCR v1 adapter, team-state fingerprints, mode-aware rule scaffolding, and calibrated-metric functions that require labeled actual results.
- SQLite migrations v1–v2 with foreign keys, account-scoped identities, append-only player/team snapshots and OCR corrections, evidence provenance, idempotent ingestion, and cross-account result guards.
- Samsung reference seed with only the task-provided OVR 86.6, set deck 121, position-training level 99/+0.7, and player names. It is explicitly `USER_PROVIDED_REFERENCE`, not OCR or a measured single-mode roster.
- 5×5 matchup matrix and all 120 one-to-one pitcher assignments, stable tie reporting, missing-data handling, baseline comparison, and JSON reason/rule/confidence fields. Scores are labeled `HEURISTIC_SCORE`; probabilities are not calibrated.
- CLI for `doctor`, database init/reference seed, capture list/once/OCR, roster show/diff, matchup analyze/optimize, report, and Python tests.
- Swift package source for ScreenCaptureKit window discovery/frame capture, Vision OCR to v1 JSON, normalized active-panel regions, explicit unknown screen classification, player-vs-page arrow semantics, and latency percentile instrumentation.
- Architecture, external-source review, macOS API notes, blocker/test/handoff records, README, and machine-readable schemas.

## Verification state

- Python unit and synthetic end-to-end suite: 27 tests pass.
- CLI doctor/database migration/reference idempotency/roster diff/synthetic matchup/report commands pass against the local SQLite database (schema v2).
- Swift 6.4 optimized (`-O`) core library and CLI compile directly against the installed macOS 27 SDK; release CLI doctor passes and window listing correctly reports `SKIP` without screen-recording consent. The XCTest module compiles. A synthetic Swift smoke harness passes OCR (`TEST 123`), observation JSON/confidence/ROI behavior, page navigation, and latency-statistics checks.
- Reproducible, dependency-free 5×5 heuristic optimizer benchmark ran on Apple M1 Pro/macOS 27, Python 3.14.6: 5 warm-ups, 50 equivalent outputs, median 0.1403 ms, p95 0.1955 ms. It measures synthetic CPU assignment only, not capture/OCR.
- SwiftPM `swift test` could not evaluate its manifest because the host sandbox rejected `sandbox-exec` with `sandbox_apply: Operation not permitted`. No sandbox bypass was used; see [test results](TEST_RESULTS.md).

## Not verified or not available

- Live game window discovery, capture, and game-screen OCR: no game process/image; screen recording permission is not granted.
- Korean OCR accuracy, actual active-panel bounds, and game screen-state profiles: require local game screenshots.
- Current empirical/official values for skills, potentials, training, synergy, mode modifiers, opponent ratings, and win/score formulas: not established by available evidence.
- Actual match results, trained/calibrated win model, real win rate, and capture/ML hardware benchmarks: no qualifying data or live frames.
- Initial implementation checkpoint `81b4320f5df08d7a95124eb87f3545950738dfbd` was pushed to `origin/feat/ranking-ai-foundation`; the remote ref was read back and matched. A follow-up documentation checkpoint records this verification.

## Checkpoint

The feature branch contains a verified remote implementation checkpoint. The working branch and any follow-up documentation checkpoint are reported in the final Git status; do not mark live capture or probability-model verification complete based on synthetic tests.
