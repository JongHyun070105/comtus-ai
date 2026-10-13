# Foundation design and evidence boundaries

## Data path

```text
ScreenCaptureKit frame or synthetic fixture
  -> Vision observations (schema v1, normalized frame coordinates)
  -> Python multi-anchor screen classifier and OCR field candidates
  -> explicit panel/player/page context gate
  -> account-scoped immutable SQLite snapshots
  -> explicit rules / caller-provided matchup scores
  -> 120-permutation assignment report (HEURISTIC_SCORE)
  -> actual result tables for future offline evaluation
```

Swift emits JSON only; no RPC service is introduced. The Swift library contracts include `FrameSource`, `FrameProcessor`, `ScreenRegion`, `ObjectObservation`, `InferenceEngine`, and `LatencyProfiler`. Latency samples are separated by stage and expose p50/p95/p99 and missed-frame count.

The read-only capture session enumerates visible V26 windows, captures without sending UI input, and compares a downsampled visual signature so small animation does not force OCR on every poll. It runs Vision after the configured stable samples, deduplicates processed frames, and reports capture/OCR latency, CPU use, and missed polls. Screen classification disagreement fails closed to `UNKNOWN`.

## Identity and history

- `card_masters` identify a player/card edition; `card_instances` hold an account's independent stars, season, LIVE version, enhancement, role, and identity key.
- `player_snapshots` preserve observed states and deduplicate identical normalized payloads. Team fingerprints include roster payload, OVR, set deck, training, mode, game version, and rule version; OVR alone is not identity.
- `team_lineups` distinguish current roster, ranking attack/defense and match-batch snapshots while preserving the actual card slot.
- Evidence and snapshots are append-only at the SQLite layer. OCR edits add rows to `ocr_corrections`; the original observation remains intact.
- `screen_observations` and `ocr_field_candidates` retain detector/parser version, anchor/token references, confidence, source, panel role, and unresolved reasons. Candidate fields do not become player snapshots until screen, player, page, active panel, and card-instance identity are separately verified.
- Optional source PNGs live under ignored `data/private-fixtures/`, are SHA-256 linked to capture evidence, and use 0700 directory / 0600 file permissions. Capture time, pixel dimensions, screen state, OCR engine version, extraction ROI, and OCR JSON are stored with the asset. The default total image limit is 1 GiB. Removing a PNG marks the linked asset `DELETED` while preserving OCR/evidence history.
- The OCR parser treats name/year, card type, stars, enhancement, and labelled OVR as separate fields. It uses the minimum OCR confidence of contributing tokens and leaves the value null below the configured threshold. A detected player name never creates an owned card instance key by itself.
- Two-digit season years resolve only inside the configured KBO season window relative to a reference year. Unresolvable text and candidate years remain attached to `UNRESOLVED`; the current season is never substituted for a missing card year.
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

## Screen profiles and panels

The only local multi-anchor profile is the pitcher-order change panel: its title and instruction must appear in the captured upper-center bounds, and the `원래대로` and `저장` actions must appear at opposite bottom sides. Four legacy v1 frames and five current v2 captures match this profile, but their minimum OCR confidence is 0.5, so persisted results remain `PITCHER_ORDER:CANDIDATE` and cannot authorize navigation. A lone `랭킹 챌린지` title is not enough to distinguish the lobby from a modal over that lobby. All other requested screens remain `UNKNOWN` until their separate screen captures establish anchors and placement.

`PanelLayout` requires explicit measured bounds for the central active panel and both side previews. No default thirds or active-player area is inferred. A token outside the active region remains a preview or unscoped candidate. `PlayerPageTracker` keeps screen, player key, and page as separate values, clears pending fields on unexpected transitions, and permits a player-field commit only for a verified detail screen, verified player/page, and active panel.

`NavigationPlanner` uses only a caller-supplied transition graph; it does not guess game menu routes. `SimulatedNavigator` has only a mock adapter. Explicit start, verified pre/post screens, user-input pause, emergency stop, route-depth/retry limits, and an allowlist of read-only navigation intents are checked. No CGEvent or Accessibility action adapter is implemented.

## Stored tables

Migrations create: `schema_migrations`, `accounts`, `card_masters`, `card_instances`, `player_snapshots`, `player_skills`, `player_potentials`, `player_pitch_grades`, `player_zones`, `team_snapshots`, `team_lineups`, `position_training`, `mode_modifiers`, `game_rules`, `research_sources`, `opponent_snapshots`, `match_batches`, `match_predictions`, `match_results`, `capture_evidence`, `ocr_observations`, `ocr_corrections`, `screen_observations`, `ocr_field_candidates`, `private_fixture_assets`, `capture_session_frames`, and `model_versions`. `match_result_evidence` joins a result to its supporting capture files. Migration 2 adds match-result source provenance and insert-time account-consistency guards. Migration 3 adds immutable screen decisions and versioned field candidates without rewriting prior OCR rows. Migration 4 aligns Swift/Python screen states, adds `VERIFIED` and `UNRESOLVED` candidate statuses, and tracks private images and capture-session processing without deleting prior evidence. Synthetic outcomes remain stored as `SYNTHETIC_TEST` and are excluded from the report's real-result count.

## Next data needed

1. Separate read-only local captures of lineup, batter/pitcher detail pages, synergy, and position training to validate screen anchors and panel bounds.
2. Source-backed skill, potential, set-deck, training, synergy, and mode rules with version and licensing notes.
3. Actual, user-recorded match results tied to exact team/opponent/rule/model snapshots.
4. A dataset large enough to compare baseline vs candidate and assess Brier score, log loss, calibration, score error, and drift.
