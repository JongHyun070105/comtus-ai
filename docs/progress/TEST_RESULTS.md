# Test results

Updated: 2026-10-13. `EXEC PASS` denotes an executed command; compiled-but-not-executed XCTest cases are not counted as passing tests.

## v0.2.2 current validation — 2026-10-13

### EXEC PASS

- Python full suite: `PYTHONPATH=packages/python/src .venv/bin/python -m unittest discover -s packages/python/tests -v` ran 81 tests; all 81 passed. This adds exact process/bundle filtering, larger-terminal exclusion, ambiguity refusal, PID replacement, small-number/page/player changes, animated-frame dedup, image-to-OCR evidence, verified partial snapshot, and unverified-field refusal coverage.
- Read-only real capture: ScreenCaptureKit matched only process `V26` with bundle `com.com2us.futurecpb.ios.apple.global.normal`, PID 81562, window ID 82657. The selected game window was 810×1112pt; a larger iTerm2 window was not eligible. PID and bundle identity are checked again in the actual capture call.
- Latest `capture session --preserve-images --max-polls 4`: `EXEC_PASS`, 4 polls/frames, 1 OCR frame, 2 duplicate frames, 0 ambiguous polls, 0 failures, 88 OCR observations, and 7 field candidates. Capture p50/p95 379.4/396.6 ms; OCR p50/p95 770.7/770.7 ms; process+child CPU 61.4%; 8 missed polls. These timings measure this host's capture/OCR work, not game FPS.
- Direct image review: the screen is the pitcher-order overview, `PITCHER_ORDER:CANDIDATE` at 0.5 confidence. `후라도'26`, LIVE V2, five stars, and +5 are overview-only candidates. The visible `100*` is not confirmed as OVR. No requested pitcher-detail page, stats, skills, potential, or pitch grades were captured.
- Local SQLite schema v4 now contains 20 capture records, 1,835 OCR observations, 20 screen observations, 144 field candidates, 16 private images, and 2 append-only correction rows. `PRAGMA integrity_check` is `ok`; foreign-key violations: 0. The local verified player snapshot count remains 0; card masters and account card instances remain 0. The earlier 9 captures/843 OCR observations were retained.
- Verified partial-snapshot API tests pass with two verified image-backed pages and one confirmed field; replaying the same evidence is idempotent. A `CANDIDATE` field and direct generic `SCREEN_CAPTURE_VERIFIED` promotion are rejected. This is synthetic test evidence, not a real Hurado snapshot. No schema migration was needed.
- `git diff --check` passes. Private PNGs and the SQLite database remain under Git-ignored `data/` paths.

### STATIC / SKIP / BLOCKED

- **BLOCKED — SwiftPM/XCTest:** `swift test --package-path apps/mac-capture -c release` stops before manifest evaluation with `sandbox-exec: sandbox_apply: Operation not permitted`. No bypass was used for the test gate; XCTest did not execute. The capture CLI's built-in source-matched Swift compiler fallback enabled the separately requested read-only capture, but is not counted as an XCTest pass.
- **NEEDS USER ACTION — actual player detail:** the current visible page is the pitcher-order overview. Automatic game UI input remains disabled, so the user must open pitcher-detail pages 1–3 before actual field verification can continue. Until then: verified fields 0; player snapshots 0; visible card facts stay `CANDIDATE`; OVR/stats/skills/potential/pitches stay `UNKNOWN`.
- Korean OCR accuracy remains `NOT_VERIFIABLE`; no labeled detail-page ground truth is available.

## Historical — v0.2.1 actual-image pipeline — 2026-10-13

### EXEC PASS

- Python full suite: `PYTHONPATH=packages/python/src .venv/bin/python -m unittest discover -s packages/python/tests -v` ran 72 tests; all 72 passed, including the existing Swift Vision synthetic integration. The original 53 tests remain present; the suite now has 19 additional regression/integration tests.
- Direct Swift build: `.venv/bin/comtus-ai doctor` attempted SwiftPM first, then compiled the current source-hash-matched Release core and CLI with Swift 6.4 `swiftc -O`. The direct binary manifest matched the current Swift source and binary SHA-256. ScreenCaptureKit, Vision, and Screen Recording permission were available.
- Swift/Python screen contract: shared fixture regression passed; a real captured pitcher-order screen classified identically in both implementations (`screen_profile_match=true`). Unverified profiles remain `UNKNOWN`.
- Actual V26 window: read-only `capture list` found the visible `컴프야V26` window at 810×1112 points. No game input was sent.
- Actual read-only capture session: latest run used 5 polls at 0.5 seconds, saw the V26 window on all 5 polls, captured 5 frames, waited for a stable visual signature, OCRed 1 frame, skipped 3 duplicates, and reported 2 missed polls. Capture p50/p95 were 354.9/369.0 ms; OCR p50/p95 were 795.3/795.3 ms; measured process+child CPU was 44.9%. No capture/OCR failures or classifier mismatches occurred.
- Actual selected-card capture: full-frame OCR plus one measured card ROI was stored as image evidence. The screen is `PITCHER_ORDER:CANDIDATE` at confidence 0.5. The card's name/year and visible edition details are stored as manual `CANDIDATE` fields; OCR corrections are append-only. The local image-vs-text report is `data/private-fixtures/verification-report.md` and is git-ignored.
- Private image retention: 5 PNGs are linked to SQLite evidence. Every file SHA-256 matched its DB value; every file is mode 0600 under a mode 0700 directory. Capture time, dimensions, screen state, OCR version, ROI, and OCR JSON are linked. The local store has a 1 GiB cap.
- SQLite: schema v3→v4 migration passed after creating mode-0600 backup `data/local-db-backups/comtus-ai-pre-v4-20261013.sqlite3` (SHA-256 `6bacb2c7f1b459eb112f5a8d9acfbb9ba942dcf0817a0d5c6fe05777c8665aa8`). Existing evidence counts were preserved: 4 captures, 364 OCR observations, 4 screen observations, 46 field candidates. After live collection, v4 contains 9 captures, 843 OCR observations, 9 screen observations, 71 field candidates, and 2 correction rows. `PRAGMA integrity_check` returned `ok`; foreign-key violations: 0.
- Data status: 8 manual image-backed candidates are recorded for one selected starter card; 25 field candidates now link to preserved images and 46 historical candidates have no remaining PNG. There are 0 verified player snapshots and 0 card masters/instances. No historical image was assumed to exist.
- `git diff --check`, Python `compileall`, and `comtus-ai db init` passed. The migration/init is idempotent at schema v4.

### STATIC / SKIP / BLOCKED

- **BLOCKED — SwiftPM/XCTest:** `swift test --package-path apps/mac-capture -c release` still fails before manifest evaluation with `sandbox-exec: sandbox_apply: Operation not permitted`. No sandbox bypass was used. The XCTest target did not execute; Python's shared screen-contract regression passed.
- **NEEDS USER ACTION — player-detail verification:** the visible screen is the pitcher-order overview, not a player-detail page. The selected card's name/year, LIVE V2 type, five stars, +5 enhancement, and `100*` display are only `CANDIDATE`. `100*` is not promoted to pitcher OVR because this overview has no explicit OVR label. Stats, skills, potential, and pitches remain `UNKNOWN`; verified player count is 0. The minimum next step is for the user to open the first starter's pitcher-detail screen while `comtus-ai capture session --preserve-images` runs.
- Korean OCR accuracy and v0.2 accuracy delta are `NOT_VERIFIABLE`: there is no labeled ground-truth image set. No accuracy/error-rate claim is made.
- Actual game input remains absent. The capture session only reads the V26 window and never clicks, consumes game currency, or starts a match.

## v0.2 OCR and navigation continuation — 2026-10-13

### EXEC PASS

- `PYTHONPATH=packages/python/src .venv/bin/python -m unittest discover -s packages/python/tests -v`: full suite passed, 53/53.
- Synthetic `player-card-ocr.synthetic.json` traversed OCR field parsing, explicit active-panel/player/page verification, account-scoped card identity supplied by the fixture, and SQLite snapshot persistence. The stored snapshot source is `SYNTHETIC_TEST`.
- Existing private local DB migration v2→v3 passed. `db analyze-ocr` processed 4 stored frames / 364 OCR observations and inserted 4 multi-anchor `PITCHER_ORDER:CANDIDATE` rows plus 46 field candidates. A repeat run inserted 0 rows. SQLite `integrity_check` returned `ok`.
- Every actual-DB field candidate is `LOW_CONFIDENCE` with `value_json=NULL`: 11 name, 11 year, 20 opponent-batter OVR, and 4 enhancement candidates. No card masters, card instances, or player snapshots were created.
- Current read-only `capture list` returned `EXEC_PASS` with no V26 window. The earlier 4 captures remain historical local evidence; there was no fresh game capture or OCR latency sample in this continuation.
- `.venv/bin/comtus-ai doctor` passed after standard SwiftPM build was attempted first and blocked at manifest sandbox evaluation. The source-hash-isolated direct Swift 6.4 `swiftc` fallback compiled the current core and CLI; the executable manifest binds both current Swift source SHA-256 and binary SHA-256.

### STATIC / SKIP / BLOCKED

- Real player count remains 0. Korean player/stat OCR accuracy is `NOT_VERIFIABLE`: original frame images are no longer present for ground-truth review, and the remaining tokens are low-confidence.
- The only live-data screen profile is a `PITCHER_ORDER` candidate. Ranking lobby, opposing lineups/details, batter/pitcher pages, team lineup, synergy, and position training remain `UNKNOWN` until separate captures establish anchors and active-panel geometry.
- Navigation, retries, depth limits, pause, emergency stop, wrong-screen halt, and coordinate mapping are verified on synthetic frames only. No real input adapter exists.
- `swift test --package-path apps/mac-capture -c release` remains `BLOCKED` by host `sandbox-exec` manifest evaluation (`sandbox_apply: Operation not permitted`); no sandbox bypass was attempted.
- Com2uS policy for the Korean V26 service and read-only UI automation is `NOT_VERIFIABLE`; actual game input remains `BLOCKED`.

## Earlier implementation stage (historical; superseded by v0.2 continuation)

### EXEC PASS

- `PYTHONPATH=packages/python/src .venv/bin/python -m unittest discover -s packages/python/tests -v`: 28/28 passed at that stage; the current 53-test result is recorded above.
- `.venv/bin/comtus-ai doctor`: Swift ScreenCaptureKit/Vision available and Screen Recording permission true.
- Direct optimized Swift 6.4 `swiftc` build of `MacCaptureCore` and CLI passed after the capture initialization fix. `doctor` and window listing passed with the built binary.
- Actual capture: fresh `capture list` selected the on-screen window by `process_name=V26` plus non-empty `title`; `capture once` and Korean Vision OCR passed at 1620×2224 px.
- Actual SQLite persistence: four `SCREEN_CAPTURE_VERIFIED` frame records and 364 observations were saved locally; replaying one exact frame saved 91 observations once and 0 on the second pass (91 duplicates). Temporary source PNGs were removed. The SQLite database is ignored under `data/` and was not committed.
- Synthetic integration: Swift Vision recognized the fixture text, Python parsed Swift's `source="vision"` JSON, and SQLite retained one capture and its observations across two identical ingest runs.
- Actual state profile: the collected top-center `랭킹 챌린지` title was recognized as `RANKING_LOBBY`; ambiguous/unsupported anchors remain `UNKNOWN`.
- `git diff --check` passed.

### EXEC FAIL (recovered)

- The first live capture exited on CoreGraphics `CGS_REQUIRE_INIT`. Initializing `NSApplication` on the CLI main actor fixed it; subsequent fresh-window capture and OCR passed.

### STATIC

- The Swift XCTest target was not run by XCTest. Standalone test-target typechecking could not load the Xcode XCTest module; the new XCTest assertion remains unverified. The production classifier smoke harness did execute.
- Lineup-detail and player-detail recognition have no collected real screen profiles and deliberately return `UNKNOWN`.

### BLOCKED

- `swift test --package-path apps/mac-capture -c release` is blocked before manifest execution because host `sandbox-exec` returns `sandbox_apply: Operation not permitted`; no bypass was used.

## Prior checkpoint results

## EXEC PASS

- `.venv/bin/python -m comtus_ai test`: 27/27 Python unit and synthetic integration tests passed.
- `.venv/bin/comtus-ai doctor`: reported Python 3.14.6, SQLite 3.53.4, Swift/ScreenCaptureKit/Vision availability, and the current Screen Recording permission state.
- `.venv/bin/comtus-ai db init`: schema migration reached version 2; foreign keys and local evidence counts were reported.
- `.venv/bin/comtus-ai db seed-reference`: reference snapshot inserted once and duplicate invocation was idempotent (`inserted: false`). It reported `screenshots_verified: false`.
- `.venv/bin/comtus-ai roster diff --account reference:samsung-lions`: returned the expected first-snapshot state without inventing a previous roster.
- `.venv/bin/comtus-ai matchup analyze --input tests/fixtures/heuristic-matchup.json`: evaluated 25 supplied scores across 120 one-to-one assignments and labeled output `SYNTHETIC_TEST`, `HEURISTIC_SCORE`, and uncalibrated.
- `.venv/bin/comtus-ai report`: returned zero actual results, `NO_REAL_MATCH_RESULTS`, and `NOT_CALIBRATED`.
- `python scripts/benchmark_core.py`: 5 warm-ups + 50 iterations on Apple M1 Pro/macOS 27/Python 3.14.6; optimizer output was identical every iteration, median 0.1403 ms, p95 0.1955 ms. Scope is only synthetic CPU assignment; no capture/OCR is measured.
- Swift 6.4 optimized (`-O`) direct compilation of `MacCaptureCore` and `mac-capture` CLI passed against the installed macOS 27 SDK. Release CLI doctor passed.
- Swift XCTest target compiled as a module. The XCTest suite runner itself did not execute; see `BLOCKED` below.
- Optimized binary `windows` command returned exit 3 with `SKIP / SCREEN_RECORDING_PERMISSION_DENIED`, as expected; it did not prompt for consent.
- Direct synthetic Swift smoke harness linked to the optimized binary passed: OCR recognized `TEST 123`, emitted one bounded-confidence Vision observation, active-panel ROI/navigation assertions passed, and p50/p95/p99 plus missed-frame statistics were calculated. This is synthetic UI evidence, not a game-screen test or device-performance benchmark.
- `git diff --check` passed before the final documentation update; it will be repeated before checkpointing.
- Git checkpoint `81b4320f5df08d7a95124eb87f3545950738dfbd` was pushed normally to `origin/feat/ranking-ai-foundation`; a fresh `git ls-remote` read returned the same commit ID.

## EXEC FAIL

- No unresolved implementation or test failures remain in the executed checks listed above. Earlier failures encountered during development were fixed and the Python suite was rerun successfully.

## STATIC

- Swift XCTest assertions compile, but the suite was not executed through XCTest.
- Screen-state recognition intentionally returns `UNKNOWN` until real, labeled screen profiles are validated.
- Rule data models support source/mode/version metadata, but unsupported game effects remain unscored.

## SKIP

- Live capture, game-window OCR, Korean stat/player-name accuracy, and ROI calibration: no game process/sample image was available and Screen Recording permission preflight was false.
- Real-match metrics, model calibration, game latency, and Apple Silicon capture/inference benchmark: no verified match/frame dataset was available.

## BLOCKED

- `swift test --package-path apps/mac-capture -c release` failed before manifest execution because macOS `sandbox-exec` returned `sandbox_apply: Operation not permitted`. The sandbox was not disabled or bypassed. Direct source compilation and the synthetic Swift smoke harness were run as independent checks.
- Live capture remains unavailable until normal macOS Screen Recording consent is granted by the user; the CLI does not request or bypass permission.
