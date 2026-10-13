# Blockers and skips

## v0.2 OCR and navigation continuation — 2026-10-13

- **NOT_VERIFIABLE — player extraction / OCR accuracy:** existing OCR rows have no original images for ground truth; parsed name/year/OVR/enhancement values remain null due confidence 0.5. No real card or player snapshot was promoted.
- **CANDIDATE — pitcher-order screen:** four local frames match title, instructional text, and bottom actions; minimum anchor confidence is 0.5. The classifier does not authorize navigation from candidate frames.
- **UNKNOWN / SKIP — all other requested screens and panel bounds:** no separate local examples verify their anchors, central panel, or side previews.
- **EXEC PASS — simulated navigation only:** mock state transitions, unexpected-screen stop, explicit start, user-input pause, emergency stop, depth/retry limits, and coordinate mapping are covered by Python tests.
- **BLOCKED — real game UI input:** the applicable Korean V26 policy did not establish permission. Apple Accessibility/CGEvent capability is not publisher permission; no input implementation or live click was performed.
- **BLOCKED — SwiftPM build/test runner:** standard SwiftPM manifest evaluation is rejected by the host sandbox. The source-matched direct Swift 6.4 compiler fallback and CLI doctor pass; XCTest did not execute.
- **SKIP — fresh actual screen/latency:** a fresh read-only window listing found no V26 window. Historical local captures remain in the private database.

## Earlier implementation stage (historical; superseded by v0.2 continuation)

- **EXEC PASS — live capture and OCR:** Screen Recording permission is true. A fresh window listing matched `process_name=V26` and a non-empty title; capture, Korean Vision OCR, and local SQLite persistence passed. Original screenshots were deleted after processing.
- **BLOCKED — SwiftPM test runner:** manifest evaluation still fails with `sandbox-exec: sandbox_apply: Operation not permitted`. Direct optimized compilation and runtime checks passed.
- **BLOCKED — lineup/player-detail recognizers:** only a Ranking Challenge screen was captured. That title is recognized from its validated top-center anchor; lineup-detail and player-detail states remain `UNKNOWN` until their screens are collected in read-only captures.
- **NOT AVAILABLE — official/empirical game formulas and model validation:** no verified rule dataset or actual match-result labels were collected.

## Current environment-bound skips

The entries below describe the earlier checkpoint and are superseded for live capture by the current-task result above.

- **SKIP — game screen integration:** no Com2uS Baseball V26 process was found and no fixture image exists in this checkout.
- **SKIP — ScreenCaptureKit live access:** `CGPreflightScreenCaptureAccess()` returned `false`; code must not prompt or bypass the normal macOS consent path.
- **SKIP — actual-game OCR accuracy and active panel geometry:** no user screenshot was available to verify Korean player/stat recognition or central ROI dimensions.
- **SKIP — measured Mac capture/ML benchmark:** no real-game frame source was available; synthetic test timing is not hardware/game performance evidence.
- **NOT AVAILABLE — official/empirical game formulas:** the implementation keeps source and rule version fields but does not invent skill, potential, training, synergy, win-probability or score effects.
- **NOT AVAILABLE — model validation:** there are no actual match results; prediction metrics must report no labeled results.
- **BLOCKED — SwiftPM test runner:** manifest evaluation is rejected by the host sandbox (`sandbox-exec: sandbox_apply: Operation not permitted`). Direct Swift compilation, XCTest module compilation, and the synthetic OCR smoke harness passed; no sandbox bypass was attempted.
- **BLOCKED — standard SwiftPM build command in this host:** SwiftPM manifest evaluation hits the same sandbox restriction. A direct Swift 6.4 optimized compile of the core library and CLI succeeded as an alternate build check.

These skips do not block offline schema, parser, optimizer, CLI, or synthetic integration work.
