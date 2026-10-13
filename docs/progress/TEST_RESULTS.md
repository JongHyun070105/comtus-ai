# Test results

Updated: 2026-10-13. `EXEC PASS` denotes an executed command; compiled-but-not-executed XCTest cases are not counted as passing tests.

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
