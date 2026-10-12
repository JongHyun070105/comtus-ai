# Blockers and skips

## Current environment-bound skips

- **SKIP — game screen integration:** no Com2uS Baseball V26 process was found and no fixture image exists in this checkout.
- **SKIP — ScreenCaptureKit live access:** `CGPreflightScreenCaptureAccess()` returned `false`; code must not prompt or bypass the normal macOS consent path.
- **SKIP — actual-game OCR accuracy and active panel geometry:** no user screenshot was available to verify Korean player/stat recognition or central ROI dimensions.
- **SKIP — measured Mac capture/ML benchmark:** no real-game frame source was available; synthetic test timing is not hardware/game performance evidence.
- **NOT AVAILABLE — official/empirical game formulas:** the implementation keeps source and rule version fields but does not invent skill, potential, training, synergy, win-probability or score effects.
- **NOT AVAILABLE — model validation:** there are no actual match results; prediction metrics must report no labeled results.
- **BLOCKED — SwiftPM test runner:** manifest evaluation is rejected by the host sandbox (`sandbox-exec: sandbox_apply: Operation not permitted`). Direct Swift compilation, XCTest module compilation, and the synthetic OCR smoke harness passed; no sandbox bypass was attempted.
- **BLOCKED — standard SwiftPM build command in this host:** SwiftPM manifest evaluation hits the same sandbox restriction. A direct Swift 6.4 optimized compile of the core library and CLI succeeded as an alternate build check.

These skips do not block offline schema, parser, optimizer, CLI, or synthetic integration work.
