# Handoff: next development steps

1. Read `docs/progress/IMPLEMENTATION_STATUS.md`, `TEST_RESULTS.md`, and `BLOCKERS.md`; confirm branch and current HEAD before continuing.
2. When a V26 window is available, capture read-only examples for the ranking lobby, both lineups, opponent starter, batter/pitcher pages 1–3, synergy, and position training. Keep each screen state `UNKNOWN` or `CANDIDATE` until independent anchors and layout are verified.
3. Measure central active panel and left/right preview bounds from those actual frames. Keep original images and minimum correction crops under ignored local `data/` paths; do not commit OCR text or private frames.
4. Reassess Korean OCR accuracy using image-backed ground truth, then tune the field confidence threshold with a held-out local fixture set. Do not promote preview fields or unresolved card instances.
5. Obtain game- and region-specific publisher policy for any proposed UI input before implementing an Accessibility/CGEvent adapter. Until then use mock navigation only.
6. If the host later permits SwiftPM manifest evaluation, run the full XCTest suite; direct optimized compilation and smoke execution do not replace it.
7. Verify and source rules for skills, potentials, set deck, training, synergy, and mode effects before entering numeric modifiers. Keep community estimates distinct from official rules.
8. Add actual result data only after user collection, then validate baseline/challenger metrics offline. Never synthesize match outcomes as training truth.
