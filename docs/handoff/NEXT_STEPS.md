# Handoff: next development steps

1. Read `docs/progress/IMPLEMENTATION_STATUS.md`, `TEST_RESULTS.md`, and `BLOCKERS.md`; confirm branch and current HEAD before continuing.
2. If the host allows SwiftPM manifest evaluation in a future session, run the package's full `swift test`; direct optimized compilation and classifier smoke checks do not replace the XCTest runner.
3. Collect read-only captures of lineup-detail and batter/pitcher detail screens when available; keep all unverified screen states `UNKNOWN` and never commit account screenshots or OCR text.
4. Measure active detail-panel ROI from those actual screens and verify Korean OCR fields before labeling their recognizers `EXEC PASS`.
5. Verify and source rules for skills, potentials, set deck, training, synergy, and mode effects before entering numeric modifiers. Keep community estimates distinct from official rules.
6. Add actual result data only after user collection, then validate baseline/challenger metrics offline. Never synthesize match outcomes as training truth.
