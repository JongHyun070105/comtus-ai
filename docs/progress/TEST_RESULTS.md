# Test results

Updated: 2026-10-13. `EXEC PASS` denotes an executed command; compiled-but-not-executed XCTest cases are not counted as passing tests.

## Current task run — 2026-10-13

### EXEC PASS

- `PYTHONPATH=packages/python/src .venv/bin/python -m unittest discover -s packages/python/tests -v`: 28/28 passed; the prior 27 tests remain, with one Swift→Python→SQLite integration test added.
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
