# Implementation status

Updated: 2026-10-13

## Current task run — 2026-10-13

- Branch remains `feat/ranking-ai-foundation`; the pre-existing `WindowListResponse` JSON crash hotfix is preserved.
- Screen Recording preflight is true. After activating the already-running V26 app, fresh ScreenCaptureKit enumeration matched a visible window by both `process_name=V26` and non-empty `title` (810×1112 pt).
- Direct optimized Swift 6.4 Release compilation passed. The initial capture attempt exposed `CGS_REQUIRE_INIT`; initializing AppKit on the main actor fixed capture, and the fresh window was captured and OCRed at 1620×2224 px.
- Swift Vision JSON parses in Python. `--screen-state` is passed through; `source="vision"` maps to evidence source `UNKNOWN`, while an explicit evidence provenance is used for persistence.
- `capture ocr --store` saved four actual captured frames (364 OCR observations total) to the ignored local SQLite database. Reprocessing one exact frame inserted 0 additional observations (91 deduplicated); all temporary PNGs were deleted after processing.
- A single real screen anchor supports `RANKING_LOBBY`. Lineup-detail and player-detail screens were not collected and continue to classify as `UNKNOWN`.
- Python suite: 28/28 tests passed, including a real Swift Vision → Python CLI/parser → temporary SQLite integration test.
- SwiftPM `swift test` remains blocked before manifest execution by host `sandbox-exec` (`sandbox_apply: Operation not permitted`). Direct Release compilation and a classifier smoke harness are used as alternate executed checks.

## Repository and environment

- Repository identity: `origin` is `https://github.com/JongHyun070105/comtus-ai.git`.
- Started from clean `main` at `b3dec2a13a1071f6f8f8ddf43955e70141def2a3`; implementation branch: `feat/ranking-ai-foundation`.
- Environment: arm64, macOS 27.0, Swift 6.4, Python 3.14.6, uv 0.11.7, SQLite 3.53.4.
- `git fetch --dry-run origin` passed; one primary worktree was present.
- The prior checkpoint below had no game process or screenshot fixture and Screen Recording preflight was false. The current run above supersedes that live-capture status.

## Implemented and locally exercised

- Dependency-free Python package with separate card master/owned instance models, role-specific player snapshots, ordinal potential/pitch grades, source labels, OCR v1 adapter, team-state fingerprints, mode-aware rule scaffolding, and calibrated-metric functions that require labeled actual results.
- SQLite migrations v1–v2 with foreign keys, account-scoped identities, append-only player/team snapshots and OCR corrections, evidence provenance, idempotent ingestion, and cross-account result guards.
- Samsung reference seed with only the task-provided OVR 86.6, set deck 121, position-training level 99/+0.7, and player names. It is explicitly `USER_PROVIDED_REFERENCE`, not OCR or a measured single-mode roster.
- 5×5 matchup matrix and all 120 one-to-one pitcher assignments, stable tie reporting, missing-data handling, baseline comparison, and JSON reason/rule/confidence fields. Scores are labeled `HEURISTIC_SCORE`; probabilities are not calibrated.
- CLI for `doctor`, database init/reference seed, capture list/once/OCR, roster show/diff, matchup analyze/optimize, report, and Python tests.
- Swift package source for ScreenCaptureKit window discovery/frame capture, Vision OCR to v1 JSON, normalized active-panel regions, a narrow real-capture Ranking Challenge title profile with UNKNOWN fallback, player-vs-page arrow semantics, and latency percentile instrumentation.
- Architecture, external-source review, macOS API notes, blocker/test/handoff records, README, and machine-readable schemas.

## Prior verification checkpoint (historical)

- Python unit and synthetic end-to-end suite: 27 tests pass.
- CLI doctor/database migration/reference idempotency/roster diff/synthetic matchup/report commands pass against the local SQLite database (schema v2).
- Swift 6.4 optimized (`-O`) core library and CLI compile directly against the installed macOS 27 SDK; release CLI doctor passes and window listing correctly reports `SKIP` without screen-recording consent. The XCTest module compiles. A synthetic Swift smoke harness passes OCR (`TEST 123`), observation JSON/confidence/ROI behavior, page navigation, and latency-statistics checks.
- Reproducible, dependency-free 5×5 heuristic optimizer benchmark ran on Apple M1 Pro/macOS 27, Python 3.14.6: 5 warm-ups, 50 equivalent outputs, median 0.1403 ms, p95 0.1955 ms. It measures synthetic CPU assignment only, not capture/OCR.
- SwiftPM `swift test` could not evaluate its manifest because the host sandbox rejected `sandbox-exec` with `sandbox_apply: Operation not permitted`. No sandbox bypass was used; see [test results](TEST_RESULTS.md).

## Remaining not verified or unavailable

- Lineup-detail and player-detail OCR/state profiles and active-panel bounds: those screens were not part of the available read-only captures.
- Current empirical/official values for skills, potentials, training, synergy, mode modifiers, opponent ratings, and win/score formulas: not established by available evidence.
- Actual match results, trained/calibrated win model, real win rate, and capture/ML hardware benchmarks: no qualifying data or live frames.
- Initial implementation checkpoint `81b4320f5df08d7a95124eb87f3545950738dfbd` was pushed to `origin/feat/ranking-ai-foundation`; the remote ref was read back and matched. A follow-up documentation checkpoint records this verification.

## Checkpoint

The feature branch contains a verified remote implementation checkpoint. The working branch and any follow-up documentation checkpoint are reported in the final Git status; do not mark live capture or probability-model verification complete based on synthetic tests.
