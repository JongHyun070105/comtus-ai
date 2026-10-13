from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any

from ..fingerprint import canonical_json, fingerprint
from ..models import EvidenceSource, validate_confidence


SCHEMA_VERSION = 4

INITIAL_SCHEMA = r"""
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    account_key TEXT NOT NULL UNIQUE,
    team_name TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE research_sources (
    id INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('SCREEN_CAPTURE_VERIFIED','USER_PROVIDED_REFERENCE','MANUAL_TRANSCRIPTION','COMMUNITY_RESEARCH','OFFICIAL_RULE','SYNTHETIC_TEST','UNKNOWN')),
    title TEXT NOT NULL,
    url TEXT,
    license_note TEXT,
    observed_at TEXT,
    version TEXT,
    content_sha256 TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX research_source_identity ON research_sources(COALESCE(url, ''), title, COALESCE(version, ''));
CREATE TABLE card_masters (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    team_name TEXT,
    card_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (card_type IN ('SEASON','LIVE','SIGNATURE','IMPACT','GOLDEN_GLOVE','NATIONAL_TEAM','LIVE_ALLSTAR','FA_IMPACT','FA_SIGNATURE','OTHER','UNKNOWN')),
    season_year INTEGER,
    source_id INTEGER REFERENCES research_sources(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX card_master_identity ON card_masters(canonical_name, COALESCE(team_name, ''), card_type, COALESCE(season_year, -1));
CREATE TABLE card_instances (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    card_master_id INTEGER NOT NULL REFERENCES card_masters(id) ON DELETE RESTRICT,
    instance_key TEXT NOT NULL,
    stars INTEGER CHECK (stars IS NULL OR stars BETWEEN 1 AND 5),
    live_version TEXT,
    enhancement INTEGER CHECK (enhancement IS NULL OR enhancement >= 0),
    roster_role TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, instance_key),
    UNIQUE(id, account_id)
);
CREATE TABLE player_snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    card_instance_id INTEGER NOT NULL,
    observed_at TEXT,
    game_version TEXT,
    mode TEXT,
    rules_version TEXT,
    source_type TEXT NOT NULL CHECK (source_type IN ('SCREEN_CAPTURE_VERIFIED','USER_PROVIDED_REFERENCE','MANUAL_TRANSCRIPTION','COMMUNITY_RESEARCH','OFFICIAL_RULE','SYNTHETIC_TEST','UNKNOWN')),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    snapshot_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(card_instance_id, account_id) REFERENCES card_instances(id, account_id) ON DELETE RESTRICT,
    UNIQUE(card_instance_id, snapshot_hash),
    UNIQUE(id, card_instance_id)
);
CREATE TABLE player_skills (
    id INTEGER PRIMARY KEY,
    player_snapshot_id INTEGER NOT NULL REFERENCES player_snapshots(id) ON DELETE RESTRICT,
    slot INTEGER NOT NULL CHECK (slot >= 1),
    skill_name TEXT NOT NULL,
    level INTEGER,
    source_type TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    UNIQUE(player_snapshot_id, slot)
);
CREATE TABLE player_potentials (
    id INTEGER PRIMARY KEY,
    player_snapshot_id INTEGER NOT NULL REFERENCES player_snapshots(id) ON DELETE RESTRICT,
    potential_name TEXT NOT NULL,
    grade TEXT,
    trained INTEGER CHECK (trained IS NULL OR trained IN (0,1)),
    source_type TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    UNIQUE(player_snapshot_id, potential_name)
);
CREATE TABLE player_pitch_grades (
    id INTEGER PRIMARY KEY,
    player_snapshot_id INTEGER NOT NULL REFERENCES player_snapshots(id) ON DELETE RESTRICT,
    pitch_name TEXT NOT NULL,
    grade TEXT,
    source_type TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    UNIQUE(player_snapshot_id, pitch_name)
);
CREATE TABLE player_zones (
    id INTEGER PRIMARY KEY,
    player_snapshot_id INTEGER NOT NULL REFERENCES player_snapshots(id) ON DELETE RESTRICT,
    row_index INTEGER NOT NULL CHECK (row_index BETWEEN 0 AND 2),
    column_index INTEGER NOT NULL CHECK (column_index BETWEEN 0 AND 2),
    zone_type TEXT,
    value REAL,
    source_type TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    UNIQUE(player_snapshot_id, row_index, column_index)
);
CREATE TABLE team_snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    snapshot_kind TEXT NOT NULL,
    observed_at TEXT,
    game_version TEXT,
    mode TEXT,
    rules_version TEXT,
    source_type TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    roster_fingerprint TEXT NOT NULL,
    team_ovr REAL,
    set_deck_points REAL,
    position_training_total INTEGER,
    position_training_ovr_contribution REAL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, roster_fingerprint),
    UNIQUE(id, account_id)
);
CREATE TABLE team_lineups (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    team_snapshot_id INTEGER NOT NULL,
    lineup_type TEXT NOT NULL CHECK (lineup_type IN ('CurrentRoster','RankingAttackLineup','RankingDefenseLineup','MatchBatchSnapshot')),
    slot TEXT NOT NULL,
    card_instance_id INTEGER NOT NULL,
    player_snapshot_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(team_snapshot_id, account_id) REFERENCES team_snapshots(id, account_id) ON DELETE RESTRICT,
    FOREIGN KEY(card_instance_id, account_id) REFERENCES card_instances(id, account_id) ON DELETE RESTRICT,
    FOREIGN KEY(player_snapshot_id, card_instance_id) REFERENCES player_snapshots(id, card_instance_id) ON DELETE RESTRICT,
    UNIQUE(team_snapshot_id, lineup_type, slot),
    UNIQUE(team_snapshot_id, lineup_type, card_instance_id)
);
CREATE TABLE position_training (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    team_snapshot_id INTEGER NOT NULL,
    slot TEXT NOT NULL,
    level INTEGER CHECK (level IS NULL OR level BETWEEN 0 AND 20),
    attribute_bonuses_json TEXT NOT NULL DEFAULT '{}',
    skill_bonus_state TEXT CHECK (skill_bonus_state IN ('LOCKED','UNLOCKED','UNKNOWN')),
    source_type TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    FOREIGN KEY(team_snapshot_id, account_id) REFERENCES team_snapshots(id, account_id) ON DELETE RESTRICT,
    UNIQUE(team_snapshot_id, slot)
);
CREATE TABLE mode_modifiers (
    id INTEGER PRIMARY KEY,
    modifier_key TEXT NOT NULL,
    mode TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    source_id INTEGER REFERENCES research_sources(id) ON DELETE RESTRICT,
    source_type TEXT NOT NULL,
    requires_raw_stats INTEGER NOT NULL DEFAULT 1 CHECK (requires_raw_stats IN (0,1)),
    condition_json TEXT NOT NULL,
    effect_json TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    UNIQUE(modifier_key, mode, rules_version)
);
CREATE TABLE game_rules (
    id INTEGER PRIMARY KEY,
    rule_key TEXT NOT NULL,
    mode TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    source_id INTEGER REFERENCES research_sources(id) ON DELETE RESTRICT,
    source_type TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    rule_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(rule_key, mode, rules_version)
);
CREATE TABLE opponent_snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    opponent_key TEXT,
    observed_at TEXT,
    game_version TEXT,
    mode TEXT,
    rules_version TEXT,
    source_type TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    snapshot_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, snapshot_hash),
    UNIQUE(id, account_id)
);
CREATE TABLE match_batches (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    team_snapshot_id INTEGER NOT NULL,
    batch_key TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'RANKING_CHALLENGE',
    rules_version TEXT,
    observed_at TEXT,
    source_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(team_snapshot_id, account_id) REFERENCES team_snapshots(id, account_id) ON DELETE RESTRICT,
    UNIQUE(account_id, batch_key),
    UNIQUE(id, account_id)
);
CREATE TABLE model_versions (
    id INTEGER PRIMARY KEY,
    model_family TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('CANDIDATE','CHAMPION','CHALLENGER','RETIRED','HEURISTIC')),
    dataset_fingerprint TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(model_family, version)
);
CREATE UNIQUE INDEX one_champion_per_family ON model_versions(model_family) WHERE status = 'CHAMPION';
CREATE TABLE match_predictions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    opponent_snapshot_id INTEGER,
    model_version_id INTEGER REFERENCES model_versions(id) ON DELETE RESTRICT,
    recommended_pitcher_card_instance_id INTEGER REFERENCES card_instances(id) ON DELETE RESTRICT,
    score_type TEXT NOT NULL CHECK (score_type IN ('HEURISTIC_SCORE','CALIBRATED_PROBABILITY','UNKNOWN')),
    predicted_score REAL,
    predicted_win_probability REAL CHECK (predicted_win_probability IS NULL OR (predicted_win_probability BETWEEN 0 AND 1)),
    input_fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(batch_id, account_id) REFERENCES match_batches(id, account_id) ON DELETE RESTRICT,
    FOREIGN KEY(opponent_snapshot_id, account_id) REFERENCES opponent_snapshots(id, account_id) ON DELETE RESTRICT,
    UNIQUE(batch_id, opponent_snapshot_id, input_fingerprint)
);
CREATE TABLE match_results (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    batch_id INTEGER REFERENCES match_batches(id) ON DELETE RESTRICT,
    match_key TEXT NOT NULL,
    team_snapshot_id INTEGER REFERENCES team_snapshots(id) ON DELETE RESTRICT,
    opponent_snapshot_id INTEGER REFERENCES opponent_snapshots(id) ON DELETE RESTRICT,
    model_version_id INTEGER REFERENCES model_versions(id) ON DELETE RESTRICT,
    recommended_pitcher_card_instance_id INTEGER REFERENCES card_instances(id) ON DELETE RESTRICT,
    actual_starting_pitcher_card_instance_id INTEGER REFERENCES card_instances(id) ON DELETE RESTRICT,
    predicted_score REAL,
    predicted_win_probability REAL CHECK (predicted_win_probability IS NULL OR (predicted_win_probability BETWEEN 0 AND 1)),
    actual_score REAL,
    opponent_score REAL,
    result TEXT CHECK (result IS NULL OR result IN ('WIN','LOSS','DRAW','UNKNOWN')),
    observed_at TEXT,
    evidence_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(account_id, match_key)
);
CREATE TABLE capture_evidence (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    sha256 TEXT NOT NULL UNIQUE,
    local_path TEXT,
    media_type TEXT,
    source_type TEXT NOT NULL,
    captured_at TEXT,
    game_version TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE ocr_observations (
    id INTEGER PRIMARY KEY,
    evidence_id INTEGER NOT NULL REFERENCES capture_evidence(id) ON DELETE RESTRICT,
    field TEXT,
    text TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    bbox_json TEXT NOT NULL,
    source_type TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE ocr_corrections (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES ocr_observations(id) ON DELETE RESTRICT,
    corrected_text TEXT NOT NULL,
    reason TEXT,
    corrected_by TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE screen_observations (
    id INTEGER PRIMARY KEY,
    evidence_id INTEGER NOT NULL REFERENCES capture_evidence(id) ON DELETE RESTRICT,
    screen_state TEXT NOT NULL CHECK (screen_state IN ('RANKING_LOBBY','PITCHER_ORDER','OPPONENT_LINEUP','OPPONENT_STARTING_PITCHER_DETAIL','PLAYER_DETAIL_BATTER','PLAYER_DETAIL_PITCHER','TEAM_ROSTER','SYNERGY','POSITION_TRAINING','UNKNOWN')),
    status TEXT NOT NULL CHECK (status IN ('VERIFIED','CANDIDATE','UNKNOWN')),
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    profile_version TEXT NOT NULL,
    anchor_indices_json TEXT NOT NULL,
    panel_layout_json TEXT,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(evidence_id, profile_version)
);
CREATE TABLE ocr_field_candidates (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES ocr_observations(id) ON DELETE RESTRICT,
    field_key TEXT NOT NULL,
    value_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('CANDIDATE','LOW_CONFIDENCE','AMBIGUOUS','UNKNOWN')),
    confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    source_type TEXT NOT NULL CHECK (source_type IN ('SCREEN_CAPTURE_VERIFIED','USER_PROVIDED_REFERENCE','MANUAL_TRANSCRIPTION','COMMUNITY_RESEARCH','OFFICIAL_RULE','SYNTHETIC_TEST','UNKNOWN')),
    derivation_version TEXT NOT NULL,
    context_json TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(observation_id, field_key, derivation_version, dedupe_key)
);
CREATE TABLE match_result_evidence (
    match_result_id INTEGER NOT NULL REFERENCES match_results(id) ON DELETE RESTRICT,
    evidence_id INTEGER NOT NULL REFERENCES capture_evidence(id) ON DELETE RESTRICT,
    PRIMARY KEY(match_result_id, evidence_id)
);
"""

IMMUTABLE_TABLES = (
    "player_snapshots", "player_skills", "player_potentials", "player_pitch_grades",
    "player_zones", "team_snapshots", "team_lineups", "position_training",
    "opponent_snapshots", "match_batches", "match_predictions", "match_results",
    "capture_evidence", "ocr_observations", "ocr_corrections", "screen_observations",
    "ocr_field_candidates", "match_result_evidence",
)

MIGRATION_2 = (
    "CREATE INDEX IF NOT EXISTS idx_match_results_account_observed ON match_results(account_id, observed_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_match_prediction_identity ON match_predictions(batch_id, COALESCE(opponent_snapshot_id, -1), COALESCE(model_version_id, -1), input_fingerprint)",
    """CREATE TRIGGER match_prediction_account_guard BEFORE INSERT ON match_predictions BEGIN
       SELECT CASE WHEN NEW.recommended_pitcher_card_instance_id IS NOT NULL AND NOT EXISTS
         (SELECT 1 FROM card_instances WHERE id=NEW.recommended_pitcher_card_instance_id AND account_id=NEW.account_id)
         THEN RAISE(ABORT, 'prediction pitcher account mismatch') END;
       SELECT CASE WHEN NEW.opponent_snapshot_id IS NOT NULL AND NOT EXISTS
         (SELECT 1 FROM opponent_snapshots WHERE id=NEW.opponent_snapshot_id AND account_id=NEW.account_id)
         THEN RAISE(ABORT, 'prediction opponent account mismatch') END;
       END""",
    """CREATE TRIGGER match_result_account_guard BEFORE INSERT ON match_results BEGIN
       SELECT CASE WHEN NEW.batch_id IS NOT NULL AND NOT EXISTS
         (SELECT 1 FROM match_batches WHERE id=NEW.batch_id AND account_id=NEW.account_id)
         THEN RAISE(ABORT, 'result batch account mismatch') END;
       SELECT CASE WHEN NEW.team_snapshot_id IS NOT NULL AND NOT EXISTS
         (SELECT 1 FROM team_snapshots WHERE id=NEW.team_snapshot_id AND account_id=NEW.account_id)
         THEN RAISE(ABORT, 'result team snapshot account mismatch') END;
       SELECT CASE WHEN NEW.opponent_snapshot_id IS NOT NULL AND NOT EXISTS
         (SELECT 1 FROM opponent_snapshots WHERE id=NEW.opponent_snapshot_id AND account_id=NEW.account_id)
         THEN RAISE(ABORT, 'result opponent account mismatch') END;
       SELECT CASE WHEN NEW.recommended_pitcher_card_instance_id IS NOT NULL AND NOT EXISTS
         (SELECT 1 FROM card_instances WHERE id=NEW.recommended_pitcher_card_instance_id AND account_id=NEW.account_id)
         THEN RAISE(ABORT, 'result recommended pitcher account mismatch') END;
       SELECT CASE WHEN NEW.actual_starting_pitcher_card_instance_id IS NOT NULL AND NOT EXISTS
         (SELECT 1 FROM card_instances WHERE id=NEW.actual_starting_pitcher_card_instance_id AND account_id=NEW.account_id)
         THEN RAISE(ABORT, 'result actual pitcher account mismatch') END;
       SELECT CASE WHEN NEW.evidence_id IS NOT NULL AND NOT EXISTS
         (SELECT 1 FROM capture_evidence WHERE id=NEW.evidence_id AND account_id=NEW.account_id)
         THEN RAISE(ABORT, 'result evidence account mismatch') END;
       END""",
    """CREATE TRIGGER match_result_evidence_account_guard BEFORE INSERT ON match_result_evidence BEGIN
       SELECT CASE WHEN NOT EXISTS (
         SELECT 1 FROM match_results m JOIN capture_evidence e ON e.id=NEW.evidence_id
         WHERE m.id=NEW.match_result_id AND m.account_id=e.account_id)
         THEN RAISE(ABORT, 'match result evidence account mismatch') END;
       END""",
)

MIGRATION_3 = (
    """CREATE TABLE IF NOT EXISTS screen_observations (
       id INTEGER PRIMARY KEY,
       evidence_id INTEGER NOT NULL REFERENCES capture_evidence(id) ON DELETE RESTRICT,
       screen_state TEXT NOT NULL CHECK (screen_state IN ('RANKING_LOBBY','PITCHER_ORDER','OPPONENT_LINEUP','OPPONENT_STARTING_PITCHER_DETAIL','PLAYER_DETAIL_BATTER','PLAYER_DETAIL_PITCHER','TEAM_ROSTER','SYNERGY','POSITION_TRAINING','UNKNOWN')),
       status TEXT NOT NULL CHECK (status IN ('VERIFIED','CANDIDATE','UNKNOWN')),
       confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
       profile_version TEXT NOT NULL,
       anchor_indices_json TEXT NOT NULL,
       panel_layout_json TEXT,
       dedupe_key TEXT NOT NULL UNIQUE,
       created_at TEXT NOT NULL,
       UNIQUE(evidence_id, profile_version)
       )""",
    """CREATE TABLE IF NOT EXISTS ocr_field_candidates (
       id INTEGER PRIMARY KEY,
       observation_id INTEGER NOT NULL REFERENCES ocr_observations(id) ON DELETE RESTRICT,
       field_key TEXT NOT NULL,
       value_json TEXT,
       status TEXT NOT NULL CHECK (status IN ('CANDIDATE','LOW_CONFIDENCE','AMBIGUOUS','UNKNOWN')),
       confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
       source_type TEXT NOT NULL CHECK (source_type IN ('SCREEN_CAPTURE_VERIFIED','USER_PROVIDED_REFERENCE','MANUAL_TRANSCRIPTION','COMMUNITY_RESEARCH','OFFICIAL_RULE','SYNTHETIC_TEST','UNKNOWN')),
       derivation_version TEXT NOT NULL,
       context_json TEXT NOT NULL,
       dedupe_key TEXT NOT NULL UNIQUE,
       created_at TEXT NOT NULL,
       UNIQUE(observation_id, field_key, derivation_version, dedupe_key)
       )""",
    """CREATE TRIGGER IF NOT EXISTS immutable_screen_observations_update BEFORE UPDATE ON screen_observations BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END""",
    """CREATE TRIGGER IF NOT EXISTS immutable_screen_observations_delete BEFORE DELETE ON screen_observations BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END""",
    """CREATE TRIGGER IF NOT EXISTS immutable_ocr_field_candidates_update BEFORE UPDATE ON ocr_field_candidates BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END""",
    """CREATE TRIGGER IF NOT EXISTS immutable_ocr_field_candidates_delete BEFORE DELETE ON ocr_field_candidates BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END""",
)

MIGRATION_4 = (
    """CREATE TABLE screen_observations_v4 (
       id INTEGER PRIMARY KEY,
       evidence_id INTEGER NOT NULL REFERENCES capture_evidence(id) ON DELETE RESTRICT,
       screen_state TEXT NOT NULL CHECK (screen_state IN ('HOME','RANKING_LOBBY','PITCHER_ORDER','OPPONENT_LINEUP','OPPONENT_STARTING_PITCHER_DETAIL','PLAYER_DETAIL_BATTER','PLAYER_DETAIL_PITCHER','TEAM_ROSTER','SYNERGY','POSITION_TRAINING','MATCH_RESULT','UNKNOWN')),
       status TEXT NOT NULL CHECK (status IN ('VERIFIED','CANDIDATE','UNKNOWN')),
       confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
       profile_version TEXT NOT NULL,
       anchor_indices_json TEXT NOT NULL,
       panel_layout_json TEXT,
       dedupe_key TEXT NOT NULL UNIQUE,
       created_at TEXT NOT NULL,
       UNIQUE(evidence_id, profile_version)
       )""",
    """INSERT INTO screen_observations_v4(id,evidence_id,screen_state,status,confidence,profile_version,
       anchor_indices_json,panel_layout_json,dedupe_key,created_at)
       SELECT id,evidence_id,screen_state,status,confidence,profile_version,anchor_indices_json,
       panel_layout_json,dedupe_key,created_at FROM screen_observations""",
    "DROP TABLE screen_observations",
    "ALTER TABLE screen_observations_v4 RENAME TO screen_observations",
    """CREATE TABLE ocr_field_candidates_v4 (
       id INTEGER PRIMARY KEY,
       observation_id INTEGER NOT NULL REFERENCES ocr_observations(id) ON DELETE RESTRICT,
       field_key TEXT NOT NULL,
       value_json TEXT,
       status TEXT NOT NULL CHECK (status IN ('VERIFIED','CANDIDATE','LOW_CONFIDENCE','AMBIGUOUS','UNKNOWN','UNRESOLVED')),
       confidence REAL CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
       source_type TEXT NOT NULL CHECK (source_type IN ('SCREEN_CAPTURE_VERIFIED','USER_PROVIDED_REFERENCE','MANUAL_TRANSCRIPTION','COMMUNITY_RESEARCH','OFFICIAL_RULE','SYNTHETIC_TEST','UNKNOWN')),
       derivation_version TEXT NOT NULL,
       context_json TEXT NOT NULL,
       dedupe_key TEXT NOT NULL UNIQUE,
       created_at TEXT NOT NULL,
       UNIQUE(observation_id, field_key, derivation_version, dedupe_key)
       )""",
    """INSERT INTO ocr_field_candidates_v4(id,observation_id,field_key,value_json,status,confidence,
       source_type,derivation_version,context_json,dedupe_key,created_at)
       SELECT id,observation_id,field_key,value_json,status,confidence,source_type,derivation_version,
       context_json,dedupe_key,created_at FROM ocr_field_candidates""",
    "DROP TABLE ocr_field_candidates",
    "ALTER TABLE ocr_field_candidates_v4 RENAME TO ocr_field_candidates",
    "CREATE TRIGGER immutable_screen_observations_update BEFORE UPDATE ON screen_observations BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END",
    "CREATE TRIGGER immutable_screen_observations_delete BEFORE DELETE ON screen_observations BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END",
    "CREATE TRIGGER immutable_ocr_field_candidates_update BEFORE UPDATE ON ocr_field_candidates BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END",
    "CREATE TRIGGER immutable_ocr_field_candidates_delete BEFORE DELETE ON ocr_field_candidates BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END",
    """CREATE TABLE private_fixture_assets (
       evidence_id INTEGER PRIMARY KEY REFERENCES capture_evidence(id) ON DELETE RESTRICT,
       relative_path TEXT NOT NULL UNIQUE,
       sha256 TEXT NOT NULL UNIQUE,
       byte_size INTEGER NOT NULL CHECK (byte_size > 0),
       captured_at TEXT NOT NULL,
       window_size_json TEXT NOT NULL,
       screen_state TEXT NOT NULL CHECK (screen_state IN ('HOME','RANKING_LOBBY','PITCHER_ORDER','OPPONENT_LINEUP','OPPONENT_STARTING_PITCHER_DETAIL','PLAYER_DETAIL_BATTER','PLAYER_DETAIL_PITCHER','TEAM_ROSTER','SYNERGY','POSITION_TRAINING','MATCH_RESULT','UNKNOWN')),
       ocr_engine_version TEXT NOT NULL,
       roi_json TEXT,
       ocr_document_json TEXT NOT NULL,
       status TEXT NOT NULL CHECK (status IN ('PRESENT','DELETING','DELETED')),
       deleted_at TEXT,
       created_at TEXT NOT NULL
       )""",
    """CREATE TABLE capture_session_frames (
       evidence_id INTEGER NOT NULL REFERENCES capture_evidence(id) ON DELETE RESTRICT,
       profile_version TEXT NOT NULL,
       status TEXT NOT NULL CHECK (status IN ('PROCESSING','COMPLETE')),
       started_at TEXT NOT NULL,
       completed_at TEXT,
       PRIMARY KEY(evidence_id,profile_version)
       )""",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialize(self) -> int:
        self.connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
        current = self.connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"database schema {current} is newer than this package supports ({SCHEMA_VERSION})")
        if current < 1:
            try:
                self.connection.executescript("BEGIN IMMEDIATE;\n" + INITIAL_SCHEMA)
                for table in IMMUTABLE_TABLES:
                    for operation in ("UPDATE", "DELETE"):
                        trigger = f"immutable_{table}_{operation.lower()}"
                        self.connection.execute(
                            f"CREATE TRIGGER {trigger} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable evidence row'); END"
                        )
                self.connection.execute(
                    "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                    (1, "initial_analysis_schema", utc_now()),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            current = 1
        if current < 2:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(match_results)")}
                if "source_type" not in columns:
                    self.connection.execute(
                        "ALTER TABLE match_results ADD COLUMN source_type TEXT NOT NULL DEFAULT 'UNKNOWN' "
                        "CHECK(source_type IN ('SCREEN_CAPTURE_VERIFIED','USER_PROVIDED_REFERENCE','MANUAL_TRANSCRIPTION','COMMUNITY_RESEARCH','OFFICIAL_RULE','SYNTHETIC_TEST','UNKNOWN'))"
                    )
                for statement in MIGRATION_2:
                    self.connection.execute(statement)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                    (2, "result_provenance_and_account_guards", utc_now()),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            current = 2
        if current < 3:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                for statement in MIGRATION_3:
                    self.connection.execute(statement)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                    (3, "ocr_field_candidates_and_screen_observations", utc_now()),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            current = 3
        if current < 4:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                for statement in MIGRATION_4:
                    self.connection.execute(statement)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                    (4, "year_resolution_screen_parity_and_private_fixture_lifecycle", utc_now()),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
        return SCHEMA_VERSION

    def schema_version(self) -> int:
        row = self.connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
        return int(row[0])

    def ensure_account(self, account_key: str, team_name: str | None = None) -> int:
        self.connection.execute(
            "INSERT INTO accounts(account_key,team_name,created_at) VALUES(?,?,?) ON CONFLICT(account_key) DO NOTHING",
            (account_key, team_name, utc_now()),
        )
        row = self.connection.execute("SELECT id FROM accounts WHERE account_key = ?", (account_key,)).fetchone()
        assert row is not None
        self.connection.commit()
        return int(row[0])

    def save_team_snapshot(self, *, account_id: int, snapshot_kind: str, payload: dict[str, Any], source_type: EvidenceSource | str,
                           team_ovr: float | None = None, set_deck_points: float | None = None,
                           position_training_total: int | None = None, position_training_ovr_contribution: float | None = None,
                           observed_at: str | None = None, mode: str | None = None, rules_version: str | None = None,
                           confidence: float | None = None, game_version: str | None = None) -> tuple[int, bool]:
        validate_confidence(confidence)
        payload_json = canonical_json(payload)
        state = {
            "snapshot_kind": snapshot_kind, "payload": payload, "team_ovr": team_ovr,
            "set_deck_points": set_deck_points, "position_training_total": position_training_total,
            "position_training_ovr_contribution": position_training_ovr_contribution,
            "mode": mode, "rules_version": rules_version, "game_version": game_version,
        }
        state_hash = fingerprint(state)
        existing = self.connection.execute(
            "SELECT id FROM team_snapshots WHERE account_id=? AND roster_fingerprint=?", (account_id, state_hash)
        ).fetchone()
        if existing:
            return int(existing[0]), False
        cursor = self.connection.execute(
            """INSERT INTO team_snapshots(account_id,snapshot_kind,observed_at,game_version,mode,rules_version,source_type,
            confidence,roster_fingerprint,team_ovr,set_deck_points,position_training_total,position_training_ovr_contribution,
            payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (account_id, snapshot_kind, observed_at, game_version, mode, rules_version, str(source_type), confidence,
             state_hash, team_ovr, set_deck_points, position_training_total, position_training_ovr_contribution,
             payload_json, utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid), True

    def save_player_snapshot(self, *, account_id: int, card_instance_id: int, payload: dict[str, Any], source_type: EvidenceSource | str,
                             confidence: float | None = None, observed_at: str | None = None, mode: str | None = None,
                             rules_version: str | None = None, game_version: str | None = None) -> tuple[int, bool]:
        if str(source_type) == EvidenceSource.SCREEN_CAPTURE_VERIFIED.value:
            raise ValueError("verified capture snapshots must use save_verified_player_snapshot with image and field proofs")
        return self._save_player_snapshot(
            account_id=account_id, card_instance_id=card_instance_id, payload=payload, source_type=source_type,
            confidence=confidence, observed_at=observed_at, mode=mode, rules_version=rules_version,
            game_version=game_version,
        )

    def save_verified_player_snapshot(
        self, *, account_id: int, card_instance_id: int, payload: dict[str, Any], identity: dict[str, Any],
        page_proofs: list[dict[str, Any]], field_proofs: dict[str, dict[str, Any]],
        confidence: float | None = None, observed_at: str | None = None, mode: str | None = None,
        rules_version: str | None = None, game_version: str | None = None,
        manual_review: list[str] | None = None, contradictions: list[str] | None = None,
    ) -> tuple[int, bool]:
        """Persist a partial capture snapshot only after image-backed identity and field review."""
        validate_confidence(confidence)
        if not payload or set(payload) != set(field_proofs):
            raise ValueError("snapshot payload must contain only explicitly verified fields")
        if manual_review or contradictions:
            raise ValueError("manual-review or contradictory fields cannot be promoted")
        if identity.get("status") != "VERIFIED" or identity.get("reviewed_from_image") is not True:
            raise ValueError("player and card identity must be reviewed and VERIFIED against an image")
        player_key = identity.get("player_key")
        if not isinstance(player_key, str) or not player_key.strip():
            raise ValueError("verified identity requires a stable player key")
        canonical_name = identity.get("canonical_name")
        season_year = identity.get("season_year")
        card_type = identity.get("card_type")
        if (not isinstance(canonical_name, str) or not canonical_name.strip()
                or not isinstance(season_year, int) or season_year < 1900
                or not isinstance(card_type, str) or card_type in ("", "UNKNOWN")):
            raise ValueError("verified player identity requires a known name, season, and card type")
        master = self.connection.execute(
            """SELECT cm.canonical_name,cm.season_year,cm.card_type,ci.stars,ci.live_version,ci.enhancement
               FROM card_instances ci JOIN card_masters cm ON cm.id=ci.card_master_id
               WHERE ci.id=? AND ci.account_id=?""", (card_instance_id, account_id),
        ).fetchone()
        if master is None:
            raise sqlite3.IntegrityError("card instance does not belong to the requested account")
        for key in ("canonical_name", "season_year", "card_type"):
            if identity.get(key) != master[key]:
                raise ValueError(f"verified {key} does not match the card master")
        for key in ("stars", "live_version", "enhancement"):
            if key in identity and identity[key] != master[key]:
                raise ValueError(f"verified {key} does not match the card instance")

        if len(page_proofs) < 2:
            raise ValueError("player identity must match across at least two detail pages")
        page_by_number: dict[int, dict[str, Any]] = {}
        evidence_ids: set[int] = set()
        screen_ids: set[int] = set()
        for proof in page_proofs:
            page = proof.get("page")
            if (proof.get("status") != "VERIFIED" or proof.get("reviewed_from_image") is not True
                    or proof.get("player_key") != player_key
                    or proof.get("canonical_name") != identity["canonical_name"]
                    or page not in (1, 2, 3) or page in page_by_number):
                raise ValueError("detail-page proofs must verify one player on distinct pages 1...3")
            evidence_id = int(proof["evidence_id"])
            screen_id = int(proof["screen_observation_id"])
            if evidence_id in evidence_ids or screen_id in screen_ids:
                raise ValueError("each verified page requires its own image and screen observation")
            screen = self.connection.execute(
                "SELECT evidence_id,screen_state,status,panel_layout_json FROM screen_observations WHERE id=?",
                (screen_id,),
            ).fetchone()
            if (screen is None or int(screen["evidence_id"]) != evidence_id
                    or screen["screen_state"] != "PLAYER_DETAIL_PITCHER" or screen["status"] != "VERIFIED"):
                raise ValueError("page proof must link to a verified pitcher-detail screen")
            active_panel = json.loads(screen["panel_layout_json"] or "{}").get("active")
            if not isinstance(active_panel, list) or len(active_panel) != 4:
                raise ValueError("verified pitcher page must have a measured active panel")
            panel_x, panel_y, panel_width, panel_height = active_panel
            if (any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in active_panel)
                    or panel_x < 0 or panel_y < 0 or panel_width <= 0 or panel_height <= 0
                    or panel_x + panel_width > 1 or panel_y + panel_height > 1):
                raise ValueError("active panel bounds must be a valid normalized image region")
            self._require_preserved_capture(evidence_id)
            identity_observation_id = int(proof["identity_observation_id"])
            identity_observation = self.connection.execute(
                "SELECT evidence_id,text,bbox_json,source_type,confidence FROM ocr_observations WHERE id=?",
                (identity_observation_id,),
            ).fetchone()
            year = str(season_year)
            short_year = f"'{season_year % 100:02d}"
            curly_short_year = f"’{season_year % 100:02d}"
            if (identity_observation is None or int(identity_observation["evidence_id"]) != evidence_id
                    or identity_observation["source_type"] != EvidenceSource.SCREEN_CAPTURE_VERIFIED.value
                    or identity_observation["confidence"] is None or identity_observation["confidence"] < 0.85
                    or canonical_name not in identity_observation["text"]
                    or not any(marker in identity_observation["text"]
                               for marker in (year, short_year, curly_short_year))
                    or not self._bbox_inside_panel(identity_observation["bbox_json"], active_panel)):
                raise ValueError("each detail page must link to an image-backed player name and season observation")
            page_by_number[page] = {**proof, "evidence_id": evidence_id, "screen_observation_id": screen_id,
                                    "identity_observation_id": identity_observation_id,
                                    "active_panel": active_panel}
            evidence_ids.add(evidence_id)
            screen_ids.add(screen_id)

        if "_verification" in payload:
            raise ValueError("_verification is reserved for capture provenance")
        verified_fields: dict[str, dict[str, Any]] = {}
        corrections: list[tuple[int, str, str, str]] = []
        for field_key, proof in field_proofs.items():
            if proof.get("status") != "VERIFIED" or proof.get("reviewed_from_image") is not True:
                raise ValueError(f"field {field_key} must be explicitly verified against its image")
            if "value" not in proof or proof["value"] is None or payload[field_key] != proof["value"]:
                raise ValueError(f"field {field_key} must store only its verified non-empty value")
            validate_confidence(proof.get("confidence"))
            if proof.get("confidence") is None:
                raise ValueError(f"field {field_key} requires a recorded confidence")
            page = proof.get("page")
            page_proof = page_by_number.get(page)
            if (page_proof is None or proof.get("player_key") != player_key
                    or proof.get("panel_role") != "ACTIVE"
                    or int(proof.get("evidence_id", -1)) != page_proof["evidence_id"]
                    or int(proof.get("screen_observation_id", -1)) != page_proof["screen_observation_id"]):
                raise ValueError(f"field {field_key} must belong to the verified active player panel")
            observation_id = int(proof["observation_id"])
            observation = self.connection.execute(
                "SELECT evidence_id,text,bbox_json,source_type FROM ocr_observations WHERE id=?",
                (observation_id,),
            ).fetchone()
            if (observation is None or int(observation["evidence_id"]) != page_proof["evidence_id"]
                    or observation["source_type"] != EvidenceSource.SCREEN_CAPTURE_VERIFIED.value
                    or proof.get("ocr_text") != observation["text"]):
                raise ValueError(f"field {field_key} must link to the reviewed OCR observation")
            if not self._bbox_inside_panel(observation["bbox_json"], page_proof["active_panel"]):
                raise ValueError(f"field {field_key} falls outside the active panel")
            correction_reason = proof.get("correction_reason")
            corrected_by = proof.get("corrected_by")
            if str(proof["value"]) != observation["text"]:
                if not isinstance(correction_reason, str) or not correction_reason.strip() or not isinstance(corrected_by, str) or not corrected_by.strip():
                    raise ValueError(f"field {field_key} needs a recorded reason and reviewer for manual correction")
                corrections.append((observation_id, str(proof["value"]), correction_reason, corrected_by))
            verified_fields[field_key] = {
                "value": proof["value"], "confidence": proof.get("confidence"),
                "evidence_id": page_proof["evidence_id"], "observation_id": observation_id,
                "screen_observation_id": page_proof["screen_observation_id"], "page": page,
                "player_key": player_key, "panel_role": "ACTIVE", "ocr_text": observation["text"],
            }

        stored_payload = dict(payload)
        stored_payload["_verification"] = {
            "status": "VERIFIED", "player_key": player_key,
            "identity": {key: identity[key] for key in
                         ("canonical_name", "season_year", "card_type", "stars", "live_version", "enhancement")
                         if key in identity},
            "page_proofs": [{key: page_by_number[page][key] for key in
                             ("page", "player_key", "canonical_name", "evidence_id", "screen_observation_id",
                              "identity_observation_id")}
                            for page in sorted(page_by_number)],
            "field_proofs": verified_fields,
        }
        for observation_id, corrected_text, reason, corrected_by in corrections:
            exists = self.connection.execute(
                "SELECT 1 FROM ocr_corrections WHERE observation_id=? AND corrected_text=? AND reason=? AND corrected_by=?",
                (observation_id, corrected_text, reason, corrected_by),
            ).fetchone()
            if exists is None:
                self.connection.execute(
                    "INSERT INTO ocr_corrections(observation_id,corrected_text,reason,corrected_by,created_at) VALUES(?,?,?,?,?)",
                    (observation_id, corrected_text, reason, corrected_by, utc_now()),
                )
        try:
            result = self._save_player_snapshot(
                account_id=account_id, card_instance_id=card_instance_id, payload=stored_payload,
                source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED, confidence=confidence,
                observed_at=observed_at, mode=mode, rules_version=rules_version, game_version=game_version,
            )
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def _require_preserved_capture(self, evidence_id: int) -> None:
        row = self.connection.execute(
            """SELECT e.sha256,e.source_type,e.media_type,a.relative_path,a.sha256 AS asset_sha256,a.status
               FROM capture_evidence e JOIN private_fixture_assets a ON a.evidence_id=e.id WHERE e.id=?""",
            (evidence_id,),
        ).fetchone()
        if (row is None or row["source_type"] != EvidenceSource.SCREEN_CAPTURE_VERIFIED.value
                or row["media_type"] != "image/png" or row["status"] != "PRESENT"
                or row["sha256"] != row["asset_sha256"]):
            raise ValueError("verified snapshots require a preserved original PNG linked to the evidence ID")
        relative_path = Path(row["relative_path"])
        root = self.path.parent.parent.resolve()
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("private image path is outside the project evidence root")
        image_path = (root / relative_path).resolve()
        if root not in image_path.parents or image_path.is_symlink() or not image_path.is_file():
            raise ValueError("preserved original image is missing or outside the evidence root")
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("preserved original image SHA-256 does not match the evidence record")

    @staticmethod
    def _bbox_inside_panel(bbox_json: str, panel: list[float]) -> bool:
        x, y, width, height = json.loads(bbox_json)
        panel_x, panel_y, panel_width, panel_height = panel
        return (x >= panel_x and y >= panel_y and x + width <= panel_x + panel_width
                and y + height <= panel_y + panel_height)

    def _save_player_snapshot(self, *, account_id: int, card_instance_id: int, payload: dict[str, Any], source_type: EvidenceSource | str,
                              confidence: float | None = None, observed_at: str | None = None, mode: str | None = None,
                              rules_version: str | None = None, game_version: str | None = None) -> tuple[int, bool]:
        validate_confidence(confidence)
        owner = self.connection.execute("SELECT account_id FROM card_instances WHERE id=?", (card_instance_id,)).fetchone()
        if owner is None or int(owner[0]) != account_id:
            raise sqlite3.IntegrityError("card instance does not belong to the requested account")
        payload_json = canonical_json(payload)
        state_hash = fingerprint({"payload": payload, "mode": mode, "rules_version": rules_version, "game_version": game_version})
        existing = self.connection.execute(
            "SELECT id FROM player_snapshots WHERE card_instance_id=? AND snapshot_hash=?", (card_instance_id, state_hash)
        ).fetchone()
        if existing:
            return int(existing[0]), False
        cursor = self.connection.execute(
            """INSERT INTO player_snapshots(account_id,card_instance_id,observed_at,game_version,mode,rules_version,source_type,
            confidence,snapshot_hash,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (account_id, card_instance_id, observed_at, game_version, mode, rules_version, str(source_type), confidence,
             state_hash, payload_json, utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid), True

    def save_ocr_observation(self, *, evidence_id: int, field: str | None, text: str, confidence: float | None,
                             bbox: list[float], source_type: EvidenceSource | str, schema_version: int = 1) -> tuple[int, bool]:
        validate_confidence(confidence)
        key = fingerprint({"evidence_id": evidence_id, "field": field, "text": text, "bbox": bbox, "schema_version": schema_version})
        self.connection.execute(
            """INSERT INTO ocr_observations(evidence_id,field,text,confidence,bbox_json,source_type,schema_version,dedupe_key,created_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(dedupe_key) DO NOTHING""",
            (evidence_id, field, text, confidence, canonical_json(bbox), str(source_type), schema_version, key, utc_now()),
        )
        row = self.connection.execute("SELECT id FROM ocr_observations WHERE dedupe_key=?", (key,)).fetchone()
        assert row is not None
        inserted = self.connection.execute("SELECT changes()").fetchone()[0] == 1
        self.connection.commit()
        return int(row[0]), inserted

    def save_screen_observation(self, *, evidence_id: int, screen_state: str, status: str,
                                confidence: float | None, profile_version: str,
                                anchor_indices: list[int], panel_layout: dict[str, Any] | None = None) -> tuple[int, bool]:
        validate_confidence(confidence)
        content = {"evidence_id": evidence_id, "screen_state": screen_state, "status": status,
                   "confidence": confidence, "profile_version": profile_version,
                   "anchor_indices": anchor_indices, "panel_layout": panel_layout}
        key = fingerprint(content)
        existing = self.connection.execute(
            "SELECT id,screen_state,status,confidence,anchor_indices_json,panel_layout_json FROM screen_observations WHERE evidence_id=? AND profile_version=?",
            (evidence_id, profile_version),
        ).fetchone()
        anchors_json = canonical_json(anchor_indices)
        panel_json = None if panel_layout is None else canonical_json(panel_layout)
        if existing:
            current = tuple(existing[name] for name in ("screen_state", "status", "confidence", "anchor_indices_json", "panel_layout_json"))
            expected = (screen_state, status, confidence, anchors_json, panel_json)
            if current != expected:
                raise sqlite3.IntegrityError("screen classification already exists with different data for this detector version")
            return int(existing["id"]), False
        cursor = self.connection.execute(
            """INSERT INTO screen_observations(evidence_id,screen_state,status,confidence,profile_version,
            anchor_indices_json,panel_layout_json,dedupe_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (evidence_id, screen_state, status, confidence, profile_version, anchors_json, panel_json, key, utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid), True

    def save_ocr_field_candidate(self, *, observation_id: int, field_key: str, value: Any,
                                 status: str, confidence: float | None, source_type: EvidenceSource | str,
                                 derivation_version: str, context: dict[str, Any]) -> tuple[int, bool]:
        validate_confidence(confidence)
        source = EvidenceSource(source_type)
        value_json = None if value is None else canonical_json(value)
        context_json = canonical_json(context)
        key = fingerprint({"observation_id": observation_id, "field_key": field_key, "value_json": value_json,
                           "status": status, "confidence": confidence, "source_type": source.value,
                           "derivation_version": derivation_version, "context_json": context_json})
        self.connection.execute(
            """INSERT INTO ocr_field_candidates(observation_id,field_key,value_json,status,confidence,source_type,
            derivation_version,context_json,dedupe_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(dedupe_key) DO NOTHING""",
            (observation_id, field_key, value_json, status, confidence, source.value, derivation_version,
             context_json, key, utc_now()),
        )
        row = self.connection.execute("SELECT id FROM ocr_field_candidates WHERE dedupe_key=?", (key,)).fetchone()
        assert row is not None
        inserted = self.connection.execute("SELECT changes()").fetchone()[0] == 1
        self.connection.commit()
        return int(row[0]), inserted

    def save_capture_evidence(self, *, sha256: str, source_type: EvidenceSource | str,
                              media_type: str = "image/png") -> tuple[int, bool]:
        source = EvidenceSource(source_type)
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256.lower()):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        existing = self.connection.execute(
            "SELECT id,source_type,media_type FROM capture_evidence WHERE sha256=?", (sha256.lower(),)
        ).fetchone()
        if existing:
            if existing["source_type"] != source.value or existing["media_type"] != media_type:
                raise sqlite3.IntegrityError("capture hash already exists with different provenance")
            return int(existing["id"]), False
        cursor = self.connection.execute(
            """INSERT INTO capture_evidence(sha256,media_type,source_type,created_at)
            VALUES(?,?,?,?)""",
            (sha256.lower(), media_type, source.value, utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid), True

    def capture_frame_is_processed(self, *, sha256: str, profile_version: str) -> bool:
        row = self.connection.execute(
            """SELECT f.status FROM capture_evidence e JOIN capture_session_frames f ON f.evidence_id=e.id
               WHERE e.sha256=? AND f.profile_version=?""",
            (sha256.lower(), profile_version),
        ).fetchone()
        if row is not None:
            return row["status"] == "COMPLETE"
        return self.connection.execute(
            """SELECT 1 FROM capture_evidence e JOIN screen_observations s ON s.evidence_id=e.id
               WHERE e.sha256=? AND s.profile_version=? LIMIT 1""",
            (sha256.lower(), profile_version),
        ).fetchone() is not None

    def mark_capture_frame_processing(self, *, evidence_id: int, profile_version: str, complete: bool) -> None:
        status = "COMPLETE" if complete else "PROCESSING"
        self.connection.execute(
            """INSERT INTO capture_session_frames(evidence_id,profile_version,status,started_at,completed_at)
               VALUES(?,?,?,?,?) ON CONFLICT(evidence_id,profile_version) DO UPDATE SET
               status=excluded.status,completed_at=excluded.completed_at""",
            (evidence_id, profile_version, status, utc_now(), utc_now() if complete else None),
        )
        self.connection.commit()

    def record_ocr_correction(self, observation_id: int, corrected_text: str, *, reason: str | None = None,
                              corrected_by: str | None = None) -> int:
        cursor = self.connection.execute(
            "INSERT INTO ocr_corrections(observation_id,corrected_text,reason,corrected_by,created_at) VALUES(?,?,?,?,?)",
            (observation_id, corrected_text, reason, corrected_by, utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def create_match_batch(self, *, account_id: int, team_snapshot_id: int, batch_key: str,
                           rules_version: str | None, observed_at: str | None = None,
                           source_type: EvidenceSource | str = EvidenceSource.UNKNOWN,
                           payload: dict[str, Any] | None = None) -> tuple[int, bool]:
        payload = payload or {}
        encoded = canonical_json(payload)
        existing = self.connection.execute(
            "SELECT id,team_snapshot_id,rules_version,observed_at,source_type,payload_json FROM match_batches WHERE account_id=? AND batch_key=?",
            (account_id, batch_key),
        ).fetchone()
        expected = (team_snapshot_id, rules_version, observed_at, str(source_type), encoded)
        if existing:
            current = tuple(existing[key] for key in ("team_snapshot_id", "rules_version", "observed_at", "source_type", "payload_json"))
            if current != expected:
                raise sqlite3.IntegrityError("batch key already exists with different snapshot data")
            return int(existing["id"]), False
        cursor = self.connection.execute(
            """INSERT INTO match_batches(account_id,team_snapshot_id,batch_key,rules_version,observed_at,source_type,payload_json,created_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (account_id, team_snapshot_id, batch_key, rules_version, observed_at, str(source_type), encoded, utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid), True

    def record_match_prediction(self, *, account_id: int, batch_id: int, opponent_snapshot_id: int | None,
                                model_version_id: int | None, recommended_pitcher_card_instance_id: int | None,
                                score_type: str, predicted_score: float | None, predicted_win_probability: float | None,
                                payload: dict[str, Any] | None = None) -> tuple[int, bool]:
        if score_type == "HEURISTIC_SCORE" and predicted_win_probability is not None:
            raise ValueError("heuristic scores cannot be stored as calibrated win probabilities")
        if score_type == "CALIBRATED_PROBABILITY" and (predicted_win_probability is None or model_version_id is None):
            raise ValueError("calibrated probabilities require both a probability and a model version")
        validate_confidence(predicted_win_probability)
        payload_json = canonical_json(payload or {})
        content = {"account_id": account_id, "batch_id": batch_id, "opponent_snapshot_id": opponent_snapshot_id,
                   "model_version_id": model_version_id, "recommended_pitcher_card_instance_id": recommended_pitcher_card_instance_id,
                   "score_type": score_type, "predicted_score": predicted_score,
                   "predicted_win_probability": predicted_win_probability, "payload": payload or {}}
        input_hash = fingerprint(content)
        existing = self.connection.execute(
            """SELECT id FROM match_predictions WHERE batch_id=? AND opponent_snapshot_id IS ? AND input_fingerprint=?""",
            (batch_id, opponent_snapshot_id, input_hash),
        ).fetchone()
        if existing:
            return int(existing[0]), False
        cursor = self.connection.execute(
            """INSERT INTO match_predictions(account_id,batch_id,opponent_snapshot_id,model_version_id,
            recommended_pitcher_card_instance_id,score_type,predicted_score,predicted_win_probability,input_fingerprint,payload_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (account_id, batch_id, opponent_snapshot_id, model_version_id, recommended_pitcher_card_instance_id,
             score_type, predicted_score, predicted_win_probability, input_hash, payload_json, utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid), True

    def record_match_result(self, *, account_id: int, match_key: str, source_type: EvidenceSource | str,
                            batch_id: int | None = None, team_snapshot_id: int | None = None,
                            opponent_snapshot_id: int | None = None, model_version_id: int | None = None,
                            recommended_pitcher_card_instance_id: int | None = None,
                            actual_starting_pitcher_card_instance_id: int | None = None,
                            predicted_score: float | None = None, predicted_win_probability: float | None = None,
                            actual_score: float | None = None, opponent_score: float | None = None,
                            result: str | None = None, observed_at: str | None = None, evidence_id: int | None = None,
                            payload: dict[str, Any] | None = None) -> tuple[int, bool]:
        validate_confidence(predicted_win_probability)
        source = str(source_type)
        payload_json = canonical_json(payload or {})
        fields = (account_id, batch_id, match_key, team_snapshot_id, opponent_snapshot_id, model_version_id,
                  recommended_pitcher_card_instance_id, actual_starting_pitcher_card_instance_id,
                  predicted_score, predicted_win_probability, actual_score, opponent_score, result,
                  source, observed_at, evidence_id, payload_json)
        existing = self.connection.execute(
            """SELECT account_id,batch_id,match_key,team_snapshot_id,opponent_snapshot_id,model_version_id,
            recommended_pitcher_card_instance_id,actual_starting_pitcher_card_instance_id,predicted_score,
            predicted_win_probability,actual_score,opponent_score,result,source_type,observed_at,evidence_id,payload_json
            FROM match_results WHERE account_id=? AND match_key=?""",
            (account_id, match_key),
        ).fetchone()
        if existing:
            if tuple(existing) != fields:
                raise sqlite3.IntegrityError("match key already exists with different result evidence")
            return int(self.connection.execute("SELECT id FROM match_results WHERE account_id=? AND match_key=?", (account_id, match_key)).fetchone()[0]), False
        cursor = self.connection.execute(
            """INSERT INTO match_results(account_id,batch_id,match_key,team_snapshot_id,opponent_snapshot_id,model_version_id,
            recommended_pitcher_card_instance_id,actual_starting_pitcher_card_instance_id,predicted_score,predicted_win_probability,
            actual_score,opponent_score,result,source_type,observed_at,evidence_id,payload_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*fields[:-1], fields[-1], utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid), True

    def counts(self) -> dict[str, int]:
        names = ("accounts", "card_masters", "card_instances", "player_snapshots", "team_snapshots", "opponent_snapshots", "match_predictions", "match_results", "capture_evidence", "ocr_observations", "ocr_corrections", "screen_observations", "ocr_field_candidates", "model_versions")
        result = {name: int(self.connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) for name in names}
        result["validated_match_results"] = int(self.connection.execute(
            "SELECT COUNT(*) FROM match_results WHERE source_type IN ('SCREEN_CAPTURE_VERIFIED','USER_PROVIDED_REFERENCE','MANUAL_TRANSCRIPTION')"
        ).fetchone()[0])
        result["synthetic_match_results"] = int(self.connection.execute(
            "SELECT COUNT(*) FROM match_results WHERE source_type='SYNTHETIC_TEST'"
        ).fetchone()[0])
        return result


def default_database_path(repo_root: Path) -> Path:
    return repo_root / "data" / "comtus-ai.sqlite3"
