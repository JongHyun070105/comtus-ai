# Foundation design and evidence boundaries

## Data path

```text
ScreenCaptureKit frame or synthetic fixture
  -> Vision observations (schema v1, normalized frame coordinates)
  -> Python OCR adapter and manual correction journal
  -> account-scoped immutable SQLite snapshots
  -> explicit rules / caller-provided matchup scores
  -> 120-permutation assignment report (HEURISTIC_SCORE)
  -> actual result tables for future offline evaluation
```

Swift emits JSON only; no RPC service is introduced. The Swift library contracts include `FrameSource`, `FrameProcessor`, `ScreenRegion`, `ObjectObservation`, `InferenceEngine`, and `LatencyProfiler`. Latency samples are separated by stage and expose p50/p95/p99 and missed-frame count.

## Identity and history

- `card_masters` identify a player/card edition; `card_instances` hold an account's independent stars, season, LIVE version, enhancement, role, and identity key.
- `player_snapshots` preserve observed states and deduplicate identical normalized payloads. Team fingerprints include roster payload, OVR, set deck, training, mode, game version, and rule version; OVR alone is not identity.
- `team_lineups` distinguish current roster, ranking attack/defense and match-batch snapshots while preserving the actual card slot.
- Evidence and snapshots are append-only at the SQLite layer. OCR edits add rows to `ocr_corrections`; the original observation remains intact.
- Foreign keys are enabled per connection. Snapshot identity is account-scoped; cards from another account cannot be attached to a saved player's snapshot.
- The reference seed is deliberately not an account capture. It records only facts supplied in the task and leaves mode/time/confidence and unreported player fields unknown.

## Rule firewall

Rule rows carry mode, source type, source link, rules version, confidence, conditions, effects, and validity range. Current engine behavior:

1. Only the matching mode and explicitly declared condition are evaluated.
2. A declared effect is applied only when caller-provided base stats are explicitly marked as excluding modifiers.
3. `True` or `None` for “stats already include modifier” skips arithmetic and preserves a reason.
4. The engine does not assign numerical values to skills or potentials without a sourced rule row.
5. Rotation scores are not probabilities and no candidate assignment becomes a match result.

The task's observed synergy examples can be stored as reference evidence, but their group membership/version and whether UI stats already include the modifier still require verification.

## Rotation objective

The optimizer accepts five unique card-instance IDs and five unique opponent IDs. It enumerates all 120 permutations, ranks candidates by known matchup coverage first and supplied score sum second, returns every tied optimum, and keeps a deterministic recommendation. Missing data is `null`, never a win. The output lists omitted rules, reflected inputs, a model label, completeness, and `probability_calibrated=false`.

## Matching screen panels

No screenshot or measured panel bounds was present in the checkout. The Swift OCR API therefore accepts an explicit normalized active-panel ROI and maps crop-relative Vision boxes back to full-frame coordinates. The screen classifier returns `UNKNOWN` until a profile is supported by real screen examples. Top detail arrows are represented as player navigation; bottom arrows change the information page. Only pages 1–3 have a data model in this version.

## Stored tables

Migrations create: `schema_migrations`, `accounts`, `card_masters`, `card_instances`, `player_snapshots`, `player_skills`, `player_potentials`, `player_pitch_grades`, `player_zones`, `team_snapshots`, `team_lineups`, `position_training`, `mode_modifiers`, `game_rules`, `research_sources`, `opponent_snapshots`, `match_batches`, `match_predictions`, `match_results`, `capture_evidence`, `ocr_observations`, `ocr_corrections`, and `model_versions`. `match_result_evidence` joins a result to its supporting capture files. Migration 2 adds match-result source provenance and insert-time account-consistency guards. Synthetic outcomes remain stored as `SYNTHETIC_TEST` and are excluded from the report's real-result count.

## Next data needed

1. User-permitted, local sample screenshots to measure active panel ROI and verify window/OCR behavior.
2. Source-backed skill, potential, set-deck, training, synergy, and mode rules with version and licensing notes.
3. Actual, user-recorded match results tied to exact team/opponent/rule/model snapshots.
4. A dataset large enough to compare baseline vs candidate and assess Brier score, log loss, calibration, score error, and drift.
