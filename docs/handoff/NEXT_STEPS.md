# Handoff: next development steps

1. Read `docs/progress/IMPLEMENTATION_STATUS.md`, `TEST_RESULTS.md`, and `BLOCKERS.md`; confirm branch and current HEAD before continuing.
2. If the host allows SwiftPM manifest evaluation in a future session, run the package's full `swift test`; current direct optimized compile and synthetic Vision smoke checks do not replace the XCTest runner.
3. Have the user grant Screen Recording permission through System Settings and provide a sample game screen or open the local game before live capture validation.
4. With a real screenshot, measure the active detail panel ROI and verify Korean OCR fields and state classification before labeling game-screen integration `EXEC PASS`.
5. Verify and source rules for skills, potentials, set deck, training, synergy, and mode effects before entering numeric modifiers. Keep community estimates distinct from official rules.
6. Add actual result data only after user collection, then validate baseline/challenger metrics offline. Never synthesize match outcomes as training truth.
