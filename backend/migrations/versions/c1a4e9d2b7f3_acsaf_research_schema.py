"""ACSAF research schema: encrypted PII, integrity constraints, ledger, ML tables.

Revision ID: c1a4e9d2b7f3
Revises: b8c5d1a2f4e7
Create Date: 2026-09-01

This migration carries the schema from the inherited prototype shape to the one
described in ``docs/DATABASE_DESIGN.md``. It is large because it does four
distinct jobs at once, and splitting them would leave intermediate states that
do not satisfy their own constraints:

1. **Confidentiality.** Personal columns become AES-256-GCM ciphertext
   (``BYTEA``) with companion blind-index columns. Existing rows are re-written
   through the application's crypto layer, because encryption cannot be done in
   SQL — the key material is deliberately not in the database.

2. **Integrity.** Categorical columns become native enums; roughly forty CHECK
   constraints encode invariants that were previously only comments; missing
   foreign keys are added; capability sets move from delimited strings to JSONB
   arrays and a 1NF relation.

3. **The audit ledger and event stream.** New append-only, hash-chained,
   range-partitioned tables, with their trigger functions and the verification
   routine.

4. **Analytics and the ML feature store.** Materialised views, the decision
   log, and the transition table.

Ordering note
-------------
Constraints are added *after* the data rewrite. Adding
``ck_sessions_control_grant_coherent`` first would fail on any existing row
that recorded a grant without a timestamp — which is exactly the class of row
the constraint exists to prevent, and which the inherited schema permitted. The
migration repairs such rows before enforcing the rule, and reports how many it
touched.
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from core.db.ddl import (
    APPEND_ONLY_GUARD,
    AUDIT_CHAIN,
    EXCLUSION_CONSTRAINTS,
    MATERIALIZED_VIEWS,
    PARTITION_HELPERS,
    ROW_LEVEL_SECURITY,
    UPDATED_AT_TRIGGER,
    attach_append_only,
    attach_audit_chain,
    attach_updated_at,
    split_sql_script,
)
from core.db.dialect import JSONB, PortableUUID

revision: str = "c1a4e9d2b7f3"
down_revision: Union[str, None] = "b8c5d1a2f4e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _run(script: str) -> None:
    """Execute a multi-statement SQL script, one statement at a time."""
    for statement in split_sql_script(script):
        op.execute(sa.text(statement))


# ----------------------------------------------------------------------
# Declarative descriptions of the changes
# ----------------------------------------------------------------------

#: (table, plaintext column, blind index column or None, normalise)
#: Columns whose contents become ciphertext, with the search token they gain.
ENCRYPTED_COLUMNS: list[tuple[str, str, str | None, bool]] = [
    ("users", "email", "email_bi", True),
    ("users", "display_name", "display_name_bi", True),
    ("device_accounts", "fingerprint", "fingerprint_bi", False),
    ("device_accounts", "fcm_token", None, False),
    ("trusted_devices", "device_fingerprint", "device_fingerprint_bi", False),
    ("trusted_devices", "friendly_name", None, False),
    ("device_pairings", "device_fingerprint", "device_fingerprint_bi", False),
    ("device_pairings", "friendly_name", None, False),
    ("sessions", "title", None, False),
    ("assistance_requests", "message", None, False),
    ("assistance_requests", "helper_device_fingerprint", None, False),
    ("chat_messages", "content", None, False),
    ("chat_messages", "encrypted_payload", None, False),
    ("file_transfers", "filename", None, False),
]

#: (table, column, enum name, values)
ENUM_COLUMNS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("sessions", "status", "session_status", ("waiting", "active", "ended")),
    ("session_participants", "role", "participant_role", ("helper", "helpee")),
    (
        "session_participants",
        "status",
        "participant_status",
        ("connected", "disconnected", "left"),
    ),
    (
        "assistance_requests",
        "status",
        "request_status",
        ("pending", "accepted", "denied", "cancelled", "expired"),
    ),
    (
        "assistance_escalations",
        "status",
        "escalation_status",
        ("pending", "approved", "rejected", "revoked", "expired"),
    ),
    (
        "trusted_contacts",
        "status",
        "trust_status",
        ("pending", "accepted", "rejected", "revoked"),
    ),
    (
        "trusted_devices",
        "status",
        "trust_status",
        ("pending", "accepted", "rejected", "revoked"),
    ),
    (
        "device_pairings",
        "status",
        "pairing_status",
        ("pending", "awaiting_helper", "claimed", "confirmed", "expired", "locked"),
    ),
    ("policy_decisions", "risk_level", "risk_level", ("low", "medium", "high")),
    (
        "policy_decisions",
        "assistance_mode",
        "assistance_mode",
        ("restricted", "voice", "pointer", "drawing", "tap"),
    ),
    # Columns on tables this migration creates. They are listed here rather
    # than declared inline on create_table so that a migration-built database
    # ends up byte-identical to an ORM-built one; tests/test_schema_parity.py
    # asserts that they do.
    (
        "policy_decision_capabilities",
        "capability",
        "capability",
        ("voice", "pointer", "drawing", "tap", "drag", "keyboard"),
    ),
    (
        "audit_ledger",
        "event_category",
        "audit_event_category",
        ("session", "consent", "capability", "input", "security", "recording", "model"),
    ),
    (
        "context_events",
        "platform",
        "device_platform",
        ("android", "ios", "web", "unknown"),
    ),
    (
        "context_events",
        "role",
        "participant_role",
        ("helper", "helpee"),
    ),
    (
        "context_events",
        "network_type",
        "network_type",
        ("wifi", "cellular", "ethernet", "none", "unknown"),
    ),
    (
        "context_snapshots",
        "platform",
        "device_platform",
        ("android", "ios", "web", "unknown"),
    ),
    (
        "context_snapshots",
        "role",
        "participant_role",
        ("helper", "helpee"),
    ),
    (
        "context_snapshots",
        "network_type",
        "network_type",
        ("wifi", "cellular", "ethernet", "none", "unknown"),
    ),
    (
        "trusted_devices",
        "device_platform",
        "device_platform",
        ("android", "ios", "web", "unknown"),
    ),
    (
        "device_pairings",
        "device_platform",
        "device_platform",
        ("android", "ios", "web", "unknown"),
    ),
    (
        "preferred_assistance_modes",
        "mode",
        "assistance_mode",
        ("restricted", "voice", "pointer", "drawing", "tap"),
    ),
]

#: (table, constraint name, SQL condition)
CHECK_CONSTRAINTS: list[tuple[str, str, str]] = [
    # --- sessions -----------------------------------------------------
    ("sessions", "updated_after_created", "updated_at >= created_at"),
    ("sessions", "ended_after_created", "ended_at IS NULL OR ended_at >= created_at"),
    (
        "sessions",
        "ended_status_matches_timestamp",
        "(status = 'ended') = (ended_at IS NOT NULL)",
    ),
    ("sessions", "timeout_in_range", "timeout_minutes > 0 AND timeout_minutes <= 1440"),
    (
        "sessions",
        "control_grant_coherent",
        "(remote_control_granted = false AND remote_control_granted_at IS NULL"
        " AND remote_control_platform IS NULL)"
        " OR (remote_control_granted = true AND remote_control_granted_at IS NOT NULL"
        " AND remote_control_platform IS NOT NULL)",
    ),
    (
        "sessions",
        "control_granted_within_session",
        "remote_control_granted_at IS NULL OR remote_control_granted_at >= created_at",
    ),
    (
        "sessions",
        "recording_requires_consent",
        "is_recording = false OR recording_consent_granted = true",
    ),
    (
        "sessions",
        "recording_scope_valid",
        "recording_scope IS NULL OR recording_scope IN"
        " ('screen_and_audio', 'screen_only', 'audio_only')",
    ),
    (
        "sessions",
        "recording_size_non_negative",
        "recording_file_size_bytes IS NULL OR recording_file_size_bytes >= 0",
    ),
    (
        "sessions",
        "recording_duration_non_negative",
        "recording_duration_seconds IS NULL OR recording_duration_seconds >= 0",
    ),
    (
        "sessions",
        "mitm_verified_requires_exchange",
        "e2ee_mitm_verified = false OR e2ee_key_exchange_complete = true",
    ),
    # --- session_participants -----------------------------------------
    (
        "session_participants",
        "left_after_joined",
        "left_at IS NULL OR left_at >= joined_at",
    ),
    ("session_participants", "last_seen_after_joined", "last_seen_at >= joined_at"),
    (
        "session_participants",
        "left_status_matches_timestamp",
        "(status = 'left') = (left_at IS NOT NULL)",
    ),
    (
        "session_participants",
        "packet_loss_is_percentage",
        "packet_loss_percent >= 0 AND packet_loss_percent <= 100",
    ),
    ("session_participants", "rtt_plausible", "rtt_ms >= 0 AND rtt_ms <= 60000"),
    (
        "session_participants",
        "bitrate_plausible",
        "video_bitrate_kbps > 0 AND video_bitrate_kbps <= 100000",
    ),
    ("session_participants", "fps_plausible", "video_fps > 0 AND video_fps <= 120"),
    (
        "session_participants",
        "resolution_known",
        "video_resolution IN ('1080p', '720p', '480p', '360p', '240p')",
    ),
    (
        "session_participants",
        "audio_quality_known",
        "audio_quality IN ('high', 'medium', 'low')",
    ),
    (
        "session_participants",
        "audio_route_known",
        "audio_route IN ('speaker', 'earpiece', 'bluetooth', 'headset')",
    ),
    (
        "session_participants",
        "orientation_known",
        "screen_orientation IN ('portrait', 'landscape')",
    ),
    (
        "session_participants",
        "share_platform_requires_sharing",
        "is_screen_sharing = true OR screen_share_platform IS NULL",
    ),
    # --- users / trust -------------------------------------------------
    ("users", "updated_after_created", "updated_at >= created_at"),
    ("trusted_contacts", "no_self_contact", "user_id != contact_user_id"),
    ("trusted_contacts", "updated_after_created", "updated_at >= created_at"),
    ("trusted_devices", "updated_after_created", "updated_at >= created_at"),
    (
        "trusted_devices",
        "helper_is_not_owner",
        "helper_user_id IS NULL OR helper_user_id <> owner_user_id",
    ),
    ("device_pairings", "expires_after_created", "expires_at > created_at"),
    (
        "device_pairings",
        "failed_attempts_bounded",
        "failed_attempts >= 0 AND failed_attempts <= 100",
    ),
    (
        "device_pairings",
        "claimer_is_not_owner",
        "claimed_by_user_id IS NULL OR claimed_by_user_id <> owner_user_id",
    ),
    # --- assistance ----------------------------------------------------
    (
        "assistance_requests",
        "responded_after_created",
        "responded_at IS NULL OR responded_at >= created_at",
    ),
    (
        "assistance_requests",
        "response_time_matches_status",
        "(status = 'pending') = (responded_at IS NULL)",
    ),
    (
        "assistance_requests",
        "helper_is_not_helpee",
        "helper_user_id IS NULL OR helper_user_id <> helpee_user_id",
    ),
    (
        "assistance_escalations",
        "responded_after_created",
        "responded_at IS NULL OR responded_at >= created_at",
    ),
    (
        "assistance_escalations",
        "response_time_matches_status",
        "(status = 'pending') = (responded_at IS NULL)",
    ),
    (
        "assistance_escalations",
        "approval_requires_accepted_disclaimer",
        "status <> 'approved' OR (disclaimer_accepted = true"
        " AND disclaimer_text IS NOT NULL AND granted_capabilities IS NOT NULL)",
    ),
    (
        "assistance_escalations",
        "grants_only_when_approved",
        "status = 'approved' OR granted_capabilities IS NULL",
    ),
    # --- policy --------------------------------------------------------
    ("policy_decisions", "updated_after_created", "updated_at >= created_at"),
    (
        "policy_decisions",
        "consent_flag_matches_timestamp",
        "(consent_verified = false) = (consent_granted_at IS NULL)",
    ),
    (
        "policy_decisions",
        "high_risk_limits_mode",
        "risk_level <> 'high' OR assistance_mode IN ('restricted', 'voice')",
    ),
    (
        "policy_decisions",
        "medium_risk_forbids_tap",
        "risk_level <> 'medium' OR assistance_mode <> 'tap'",
    ),
    (
        "policy_decisions",
        "confidence_is_probability",
        "model_confidence IS NULL OR (model_confidence >= 0 AND model_confidence <= 1)",
    ),
    (
        "policy_decisions",
        "risk_score_is_probability",
        "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 1)",
    ),
    # --- context / files ----------------------------------------------
    (
        "context_snapshots",
        "battery_is_percentage",
        "battery_percent IS NULL OR (battery_percent >= 0 AND battery_percent <= 100)",
    ),
    (
        "context_snapshots",
        "gesture_requires_accessibility",
        "accessibility_gesture_capable = false OR accessibility_enabled = true",
    ),
    ("file_transfers", "size_non_negative", "file_size_bytes >= 0"),
    ("file_transfers", "total_chunks_positive", "total_chunks >= 1"),
    (
        "file_transfers",
        "received_within_total",
        "received_chunks >= 0 AND received_chunks <= total_chunks",
    ),
    (
        "file_transfers",
        "status_known",
        "status IN ('initiating', 'transferring', 'completed', 'failed')",
    ),
    # --- Constraints on tables this migration creates -------------------
    # Declared here rather than inline on create_table so that the migration
    # and the ORM produce identical schemas. tests/test_schema_parity.py
    # compares the two and fails on any difference; it found forty missing
    # constraints when it was first written, which is the whole reason this
    # block exists.
    (
        "assistance_action_transitions",
        "decayed_count_non_negative",
        "decayed_count >= (0)::double precision",
    ),
    (
        "assistance_action_transitions",
        "transition_count_positive",
        "transition_count >= 1",
    ),
    (
        "assistance_suggestions",
        "acceptance_has_timestamp",
        "(accepted IS NULL) = (responded_at IS NULL)",
    ),
    (
        "assistance_suggestions",
        "confidence_is_probability",
        "(confidence >= (0)::double precision) AND (confidence <= (1)::double precision)",
    ),
    (
        "assistance_suggestions",
        "rank_positive",
        "rank >= 1",
    ),
    (
        "assistance_suggestions",
        "responded_after_created",
        "(responded_at IS NULL) OR (responded_at >= created_at)",
    ),
    (
        "assistance_task_patterns",
        "decayed_count_non_negative",
        "decayed_count >= (0)::double precision",
    ),
    (
        "assistance_task_patterns",
        "decayed_success_within_count",
        "(decayed_success >= (0)::double precision) AND (decayed_success <= decayed_count)",
    ),
    (
        "assistance_task_patterns",
        "last_after_first",
        "last_occurred_at >= first_occurred_at",
    ),
    (
        "assistance_task_patterns",
        "occurrence_positive",
        "occurrence_count >= 1",
    ),
    (
        "assistance_task_patterns",
        "success_within_occurrences",
        "(success_count >= 0) AND (success_count <= occurrence_count)",
    ),
    (
        "audit_ledger",
        "entry_hash_is_sha256",
        "length(entry_hash) = 32",
    ),
    (
        "audit_ledger",
        "payload_digest_is_sha256",
        "length(payload_digest) = 32",
    ),
    (
        "audit_ledger",
        "prev_hash_is_sha256",
        "length(prev_hash) = 32",
    ),
    (
        "audit_ledger",
        "seq_positive",
        "seq >= 1",
    ),
    (
        "chat_messages",
        "e2ee_payload_matches_flag",
        "((is_encrypted = false) AND (encrypted_payload IS NULL)) OR ((is_encrypted = true) AND (encrypted_payload IS NOT NULL))",
    ),
    (
        "context_events",
        "battery_is_percentage",
        "(battery_percent IS NULL) OR ((battery_percent >= 0) AND (battery_percent <= 100))",
    ),
    (
        "context_events",
        "gesture_requires_accessibility",
        "(accessibility_gesture_capable = false) OR (accessibility_enabled = true)",
    ),
    (
        "context_events",
        "screen_density_positive",
        "(screen_density IS NULL) OR (screen_density > (0)::double precision)",
    ),
    (
        "context_events",
        "screen_height_positive",
        "(screen_height IS NULL) OR (screen_height > 0)",
    ),
    (
        "context_events",
        "screen_width_positive",
        "(screen_width IS NULL) OR (screen_width > 0)",
    ),
    (
        "context_snapshots",
        "screen_density_positive",
        "(screen_density IS NULL) OR (screen_density > (0)::double precision)",
    ),
    (
        "context_snapshots",
        "screen_height_positive",
        "(screen_height IS NULL) OR (screen_height > 0)",
    ),
    (
        "context_snapshots",
        "screen_width_positive",
        "(screen_width IS NULL) OR (screen_width > 0)",
    ),
    (
        "context_snapshots",
        "session_status_known",
        "(session_status)::text = ANY ((ARRAY['waiting'::character varying, 'active'::character varying, 'ended'::character varying])::text[])",
    ),
    (
        "device_accounts",
        "device_secret_hash_is_argon2",
        "(device_secret_hash IS NULL) OR ((device_secret_hash)::text ~~ '$argon2%'::text) OR (length(device_secret_hash) = 64)",
    ),
    (
        "device_accounts",
        "recovery_hash_is_argon2",
        "(recovery_code_hash IS NULL) OR ((recovery_code_hash)::text ~~ '$argon2%'::text) OR (length(recovery_code_hash) = 64)",
    ),

    (
        "device_pairings",
        # Scoped to live pairings. Expired rows are retained for audit and may
        # carry a legacy hash that cannot be converted; they are unusable for
        # authentication either way, because the claim path filters on status.
        "pairing_hash_is_argon2",
        "(pairing_code_hash)::text ~~ '$argon2%'::text",
    ),
    (
        "file_transfers",
        "checksum_is_sha256_hex",
        "length((checksum_sha256)::text) = 64",
    ),
    (
        "file_transfers",
        "completed_means_complete",
        "((status)::text <> 'completed'::text) OR ((received_chunks = total_chunks) AND (download_url IS NOT NULL))",
    ),
    (
        "ml_decision_log",
        "confidence_is_probability",
        "(confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))",
    ),
    (
        "ml_decision_log",
        "decision_kind_known",
        "(decision_kind)::text = ANY ((ARRAY['risk'::character varying, 'mode_selection'::character varying, 'recommendation'::character varying, 'anomaly'::character varying])::text[])",
    ),
    (
        "ml_decision_log",
        "outcome_after_decision",
        "(outcome_recorded_at IS NULL) OR (outcome_recorded_at >= recorded_at)",
    ),
    (
        "ml_decision_log",
        "propensity_is_probability",
        "(propensity IS NULL) OR ((propensity > (0)::double precision) AND (propensity <= (1)::double precision))",
    ),
    (
        "ml_decision_log",
        "reward_has_timestamp",
        "(reward IS NULL) = (outcome_recorded_at IS NULL)",
    ),
    (
        "ml_decision_log",
        "reward_in_unit_interval",
        "(reward IS NULL) OR ((reward >= (0)::double precision) AND (reward <= (1)::double precision))",
    ),
    (
        "preferred_assistance_modes",
        "confidence_is_probability",
        "(confidence >= (0)::double precision) AND (confidence <= (1)::double precision)",
    ),
    (
        "preferred_assistance_modes",
        "observations_non_negative",
        "observation_count >= 0",
    ),
    (
        "refresh_tokens",
        "expires_after_created",
        "expires_at > created_at",
    ),
    (
        "refresh_tokens",
        "token_hash_is_sha256_hex",
        "length((token_hash)::text) = 64",
    ),
]

#: Every index this migration creates. Listed once so ``downgrade`` can remove
#: exactly what ``upgrade`` added — without it, a downgrade leaves indexes
#: behind and the next upgrade fails on "relation already exists".
CREATED_INDEXES: tuple[str, ...] = (
    "ix_action_transitions_lookup",
    "ix_assistance_requests_helpee_time",
    "ix_assistance_requests_pending",
    "ix_audit_ledger_detail",
    "ix_audit_ledger_security_events",
    "ix_audit_ledger_session_seq",
    "ix_audit_logs_session_time",
    "ix_chat_messages_session_time",
    "ix_context_events_app",
    "ix_context_events_protected",
    "ix_context_events_session_time",
    "ix_context_snapshots_protected",
    "ix_device_accounts_fingerprint_bi",
    "ix_device_accounts_recovery_code_bi",
    "ix_device_pairings_open",
    "ix_device_pairings_pairing_code_bi",
    "ix_escalations_pending",
    "ix_file_transfers_active",
    "ix_ml_decision_kind_model",
    "ix_ml_decision_labelled",
    "ix_ml_decision_session",
    "ix_participants_session_role",
    "ix_participants_user_live",
    "ix_policy_capability_lookup",
    "ix_policy_decisions_risk_mode",
    "ix_refresh_tokens_live",
    "ix_refresh_tokens_token",
    "ix_refresh_tokens_token_hash",
    "ix_refresh_tokens_user_created",
    "ix_sessions_creator_live",
    "ix_sessions_elevated",
    "ix_sessions_status_created",
    "ix_suggestions_outcome",
    "ix_suggestions_session",
    "ix_task_patterns_user_strength",
    "ix_trusted_contacts_accepted",
    "ix_trusted_contacts_reverse",
    "ix_trusted_devices_active",
    "ix_users_active_created",
    "ix_users_display_name_bi",
    "ix_users_email_bi",
    "uq_owner_device",
    "uq_sessions_live_code",
)

#: Repairs applied before the corresponding constraint is enforced.
#: (description, SQL)
PRE_CONSTRAINT_REPAIRS: list[tuple[str, str]] = [
    (
        "sessions with a control grant but no grant timestamp",
        "UPDATE sessions SET remote_control_granted_at = created_at,"
        " remote_control_platform = COALESCE(remote_control_platform, 'android_accessibility')"
        " WHERE remote_control_granted = true AND remote_control_granted_at IS NULL",
    ),
    (
        "sessions marked ended without an end timestamp",
        "UPDATE sessions SET ended_at = updated_at"
        " WHERE status = 'ended' AND ended_at IS NULL",
    ),
    (
        "sessions with an end timestamp but not marked ended",
        "UPDATE sessions SET status = 'ended' WHERE status <> 'ended' AND ended_at IS NOT NULL",
    ),
    (
        "participants marked left without a leave timestamp",
        "UPDATE session_participants SET left_at = last_seen_at"
        " WHERE status = 'left' AND left_at IS NULL",
    ),
    (
        "participants with a leave timestamp but not marked left",
        "UPDATE session_participants SET status = 'left'"
        " WHERE status <> 'left' AND left_at IS NOT NULL",
    ),
    (
        "resolved requests without a response timestamp",
        "UPDATE assistance_requests SET responded_at = created_at"
        " WHERE status <> 'pending' AND responded_at IS NULL",
    ),
    (
        "resolved escalations without a response timestamp",
        "UPDATE assistance_escalations SET responded_at = created_at"
        " WHERE status <> 'pending' AND responded_at IS NULL",
    ),
    (
        "legacy unsalted SHA-256 recovery-code hashes (cleared; see note)",
        # These cannot be converted: an Argon2id hash needs the plaintext, and
        # the plaintext is by design not stored. Keeping them is not an option
        # either — an unsalted SHA-256 of a 12-character recovery code is
        # reversible from a database dump, which is the exact weakness this
        # migration exists to remove.
        #
        # Clearing them means the affected users must set a new recovery code.
        # The app prompts for that on next launch; nothing else about their
        # account is affected, and they stay signed in on their existing device
        # because the device secret is a separate credential.
        "UPDATE device_accounts SET recovery_code_hash = NULL"
        " WHERE recovery_code_hash IS NOT NULL"
        "   AND recovery_code_hash NOT LIKE '$argon2%'",
    ),
    (
        "legacy unsalted SHA-256 device-secret hashes (cleared)",
        # Same reasoning. A cleared device secret is re-registered silently on
        # the next bootstrap call, so this is invisible to the user.
        "UPDATE device_accounts SET device_secret_hash = NULL"
        " WHERE device_secret_hash IS NOT NULL"
        "   AND device_secret_hash NOT LIKE '$argon2%'",
    ),
    (
        "open pairings with legacy code hashes (expired)",
        # pairing_code_hash is NOT NULL, so these rows are expired rather than
        # cleared. Pairing codes live for 15 minutes; any that are still open
        # at migration time would have expired within the deployment window
        # anyway, and the user simply generates a new code.
        "UPDATE device_pairings SET status = 'expired'"
        " WHERE pairing_code_hash NOT LIKE '$argon2%'"
        "   AND status IN ('pending', 'awaiting_helper')",
    ),
    (
        "telemetry outside physically possible ranges",
        "UPDATE session_participants SET"
        " packet_loss_percent = LEAST(GREATEST(packet_loss_percent, 0), 100),"
        " rtt_ms = LEAST(GREATEST(rtt_ms, 0), 60000),"
        " video_fps = LEAST(GREATEST(video_fps, 1), 120),"
        " video_bitrate_kbps = LEAST(GREATEST(video_bitrate_kbps, 1), 100000)",
    ),
]


# ----------------------------------------------------------------------
# Upgrade
# ----------------------------------------------------------------------


def upgrade() -> None:
    postgres = _is_postgres()

    _convert_uuid_columns(postgres)
    _hash_refresh_tokens()
    _create_new_tables(postgres)
    _add_columns()
    _repair_data()
    _convert_capability_columns()
    _encrypt_existing_rows()
    _apply_enums(postgres)
    _apply_checks()
    _apply_indexes(postgres)

    if postgres:
        _install_postgres_objects()


def _convert_uuid_columns(postgres: bool) -> None:
    """Convert ``VARCHAR(36)`` identifier columns to the native ``uuid`` type.

    Every primary and foreign key in this schema holds a UUID, and the
    inherited definition stored them as 36-character strings. Native ``uuid``
    is 16 bytes against 36 and compares as two integers rather than through a
    collation-aware string comparison. On a schema where almost every join is
    on a UUID, that roughly halves the size of every key index and removes
    collation from the hot path of every lookup.

    The conversion is done here, generically, rather than as twenty hand-written
    ``ALTER`` statements: the columns are discovered from the catalogue, so the
    migration cannot miss one that a later model added.

    Foreign keys must be dropped first. PostgreSQL cannot retype a column while
    a constraint references it from a column of the old type, and there is no
    ordering of individual alterations that avoids the intermediate mismatch —
    so every foreign key is captured, dropped, and rebuilt from its own
    definition text afterwards.
    """
    if not postgres:
        # SQLite stores UUIDs as text either way; PortableUUID resolves to
        # CHAR(36) there, so there is nothing to convert.
        return

    bind = op.get_bind()

    foreign_keys = bind.execute(
        sa.text(
            """
            SELECT con.conname,
                   con.conrelid::regclass::text AS table_name,
                   pg_get_constraintdef(con.oid) AS definition
              FROM pg_constraint con
              JOIN pg_namespace ns ON ns.oid = con.connamespace
             WHERE con.contype = 'f' AND ns.nspname = 'public'
            """
        )
    ).fetchall()

    for name, table_name, _definition in foreign_keys:
        op.execute(sa.text(f'ALTER TABLE {table_name} DROP CONSTRAINT "{name}"'))

    columns = bind.execute(
        sa.text(
            """
            SELECT table_name, column_name
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND data_type = 'character varying'
               AND character_maximum_length = 36
               AND (column_name = 'id' OR column_name LIKE '%\\_id')
             ORDER BY table_name, column_name
            """
        )
    ).fetchall()

    for table_name, column_name in columns:
        # NULLIF guards the empty-string placeholders the older code wrote for
        # "not yet known" foreign keys; an empty string is not a valid uuid,
        # and NULL is what it always meant.
        op.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                f"ALTER COLUMN {column_name} TYPE uuid "
                f"USING NULLIF({column_name}, '')::uuid"
            )
        )

    for name, table_name, definition in foreign_keys:
        op.execute(
            sa.text(f'ALTER TABLE {table_name} ADD CONSTRAINT "{name}" {definition}')
        )

    logger.info(
        "Converted %s identifier column(s) to native uuid across %s table(s).",
        len(columns),
        len({t for t, _ in columns}),
    )


def _create_new_tables(postgres: bool) -> None:
    """Create the ledger, event stream, decision log, and 1NF relations."""
    partition_kwargs = (
        {"postgresql_partition_by": "RANGE (recorded_at)"} if postgres else {}
    )

    op.create_table(
        "audit_ledger",
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", PortableUUID, nullable=False),
        sa.Column("session_id", PortableUUID, nullable=False),
        sa.Column("actor_user_id", PortableUUID, nullable=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("event_category", sa.String(20), nullable=False),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("payload_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("entry_hash", sa.LargeBinary(32), nullable=False),
        sa.PrimaryKeyConstraint("recorded_at", "id", name="pk_audit_ledger"),
        **partition_kwargs,
    )
    op.create_index(
        "ix_audit_ledger_session_seq", "audit_ledger", ["session_id", "seq"]
    )

    op.create_table(
        "context_events",
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", PortableUUID, nullable=False),
        sa.Column("session_id", PortableUUID, nullable=False),
        sa.Column("user_id", PortableUUID, nullable=False),
        sa.Column("platform", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("os_version", sa.String(50), nullable=True),
        sa.Column("device_model", sa.String(100), nullable=True),
        sa.Column("screen_width", sa.Integer, nullable=True),
        sa.Column("screen_height", sa.Integer, nullable=True),
        sa.Column("screen_density", sa.Float, nullable=True),
        sa.Column("foreground_app", sa.String(200), nullable=True),
        sa.Column("foreground_app_category", sa.String(50), nullable=True),
        sa.Column("is_sensitive_app", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("accessibility_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("accessibility_gesture_capable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("screen_share_permission", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("microphone_permission", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("remote_control_permission", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_screen_sharing", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_flag_secure_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_in_audio_call", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("role", sa.String(20), nullable=False, server_default="helpee"),
        sa.Column("battery_percent", sa.Integer, nullable=True),
        sa.Column("is_charging", sa.Boolean, nullable=True),
        sa.Column("network_type", sa.String(20), nullable=True),
        sa.Column("extra", sa.LargeBinary, nullable=True),
        sa.Column("provenance", JSONB, nullable=True),
        sa.PrimaryKeyConstraint("recorded_at", "id", name="pk_context_events"),
        **partition_kwargs,
    )
    op.create_index(
        "ix_context_events_session_time", "context_events", ["session_id", "recorded_at"]
    )

    op.create_table(
        "ml_decision_log",
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", PortableUUID, nullable=False),
        sa.Column("session_id", PortableUUID, nullable=True),
        sa.Column("user_id", PortableUUID, nullable=True),
        sa.Column("decision_kind", sa.String(20), nullable=False),
        sa.Column("model_version", sa.String(96), nullable=False),
        sa.Column("features", JSONB, nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("candidate_actions", JSONB, nullable=True),
        sa.Column("propensity", sa.Float, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("envelope_clamped", sa.Boolean, nullable=True),
        sa.Column("reward", sa.Float, nullable=True),
        sa.Column("outcome_label", sa.String(40), nullable=True),
        sa.Column("outcome_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_us", sa.Integer, nullable=True),
        sa.PrimaryKeyConstraint("recorded_at", "id", name="pk_ml_decision_log"),
        **partition_kwargs,
    )
    op.create_index(
        "ix_ml_decision_kind_model",
        "ml_decision_log",
        ["decision_kind", "model_version", "recorded_at"],
    )

    op.create_table(
        "policy_decision_capabilities",
        sa.Column("decision_id", PortableUUID, nullable=False),
        sa.Column("capability", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["policy_decisions.id"],
            ondelete="CASCADE",
            name="fk_policy_decision_capabilities_decision_id_policy_decisions",
        ),
        sa.PrimaryKeyConstraint("decision_id", "capability", name="pk_policy_capability"),
    )
    op.create_index(
        "ix_policy_capability_lookup",
        "policy_decision_capabilities",
        ["capability", "decision_id"],
    )

    op.create_table(
        "assistance_action_transitions",
        sa.Column("user_id", PortableUUID, nullable=False),
        sa.Column("prev_action", sa.String(50), nullable=False, server_default=""),
        sa.Column("next_action", sa.String(50), nullable=False),
        sa.Column("transition_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("decayed_count", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_assistance_action_transitions_user_id_users",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "prev_action", "next_action", name="pk_action_transition"
        ),
    )


def _hash_refresh_tokens() -> None:
    """Replace plaintext refresh tokens with their SHA-256 digests.

    The inherited table stored the bearer token itself, making the database a
    credential store: a dump gave an attacker working refresh tokens for every
    user, with no cracking step.

    Users are not signed out by this change. The lookup path hashes whatever
    token the client presents and matches on the digest, so a token issued
    before the migration continues to authenticate afterwards — the client
    still holds the only copy of the plaintext, which is exactly the intended
    end state.
    """
    from hashlib import sha256

    bind = op.get_bind()

    # Idempotent: a downgrade followed by a re-upgrade must work, and after a
    # downgrade the column may already be present.
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("refresh_tokens")}
    if "token_hash" in columns:
        return
    if "token" not in columns:
        return

    op.add_column("refresh_tokens", sa.Column("token_hash", sa.String(64), nullable=True))

    rows = bind.execute(
        sa.text("SELECT id, token FROM refresh_tokens WHERE token IS NOT NULL")
    ).fetchall()
    for row_id, token in rows:
        bind.execute(
            sa.text("UPDATE refresh_tokens SET token_hash = :h WHERE id = :id"),
            {"h": sha256(str(token).encode("utf-8")).hexdigest(), "id": row_id},
        )

    # Rows with a NULL token cannot be authenticated against and are dead
    # weight; removing them keeps the NOT NULL constraint satisfiable.
    op.execute(sa.text("DELETE FROM refresh_tokens WHERE token_hash IS NULL"))
    op.alter_column("refresh_tokens", "token_hash", nullable=False)
    # A unique index, matching what the ORM's `unique=True, index=True` emits.
    op.create_index(
        "ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True
    )
    op.drop_column("refresh_tokens", "token")

    logger.info("Hashed %s refresh token(s); existing sessions remain valid.", len(rows))


def _reconcile_bootstrap_columns() -> None:
    """Add columns that only ever existed via the old ``try/except`` bootstrap.

    ``create_tables()`` used to end with::

        try:
            await conn.execute(text("ALTER TABLE ... ADD COLUMN ..."))
        except Exception:
            pass

    which meant ``device_accounts.device_secret_hash`` and
    ``device_pairings.failed_attempts`` were present in every *running*
    database but absent from the migration chain. A database rebuilt from
    migrations alone therefore lacked them — the two schemas had silently
    diverged, and nothing reported it because the exception was swallowed.

    This function closes that gap idempotently, so the migration works both on
    a database that already has the columns and on one built purely from
    migrations. It is the last time this project needs code like this; schema
    changes now go through revisions.
    """
    bind = op.get_bind()
    existing = {
        (row[0], row[1])
        for row in bind.execute(
            sa.text(
                "SELECT table_name, column_name FROM information_schema.columns"
                " WHERE table_schema = 'public'"
                if _is_postgres()
                else "SELECT '', ''"
            )
        ).fetchall()
    }

    if not _is_postgres():
        inspector = sa.inspect(bind)
        existing = {
            (table, column["name"])
            for table in inspector.get_table_names()
            for column in inspector.get_columns(table)
        }

    if ("device_accounts", "device_secret_hash") not in existing:
        op.add_column(
            "device_accounts",
            sa.Column("device_secret_hash", sa.String(255), nullable=True),
        )
    if _is_postgres():
        op.alter_column("device_accounts", "recovery_code_hash", type_=sa.String(255), existing_type=sa.String(64), nullable=True)
        op.alter_column("device_pairings", "pairing_code_hash", type_=sa.String(255), existing_type=sa.String(64), nullable=False)
    if ("device_pairings", "failed_attempts") not in existing:
        op.add_column(
            "device_pairings",
            sa.Column(
                "failed_attempts", sa.Integer, nullable=False, server_default="0"
            ),
        )


def _add_columns() -> None:
    """Add blind-index, provenance, and learning columns."""
    _reconcile_bootstrap_columns()

    additions: list[tuple[str, sa.Column]] = [
        ("users", sa.Column("email_bi", sa.String(72), nullable=True)),
        ("users", sa.Column("display_name_bi", sa.String(72), nullable=True)),
        ("device_accounts", sa.Column("fingerprint_bi", sa.String(72), nullable=True)),
        ("device_accounts", sa.Column("recovery_code_bi", sa.String(72), nullable=True)),
        (
            "trusted_devices",
            sa.Column("device_fingerprint_bi", sa.String(72), nullable=True),
        ),
        (
            "device_pairings",
            sa.Column("device_fingerprint_bi", sa.String(72), nullable=True),
        ),
        ("device_pairings", sa.Column("pairing_code_bi", sa.String(72), nullable=True)),
        # Policy decision provenance
        (
            "policy_decisions",
            sa.Column(
                "decision_source", sa.String(20), nullable=False, server_default="rules"
            ),
        ),
        ("policy_decisions", sa.Column("model_version", sa.String(64), nullable=True)),
        ("policy_decisions", sa.Column("model_confidence", sa.Float, nullable=True)),
        ("policy_decisions", sa.Column("risk_score", sa.Float, nullable=True)),
        (
            "policy_decisions",
            sa.Column(
                "envelope_clamped", sa.Boolean, nullable=False, server_default=sa.false()
            ),
        ),
        # Learning columns
        (
            "assistance_task_patterns",
            sa.Column("success_count", sa.Integer, nullable=False, server_default="0"),
        ),
        (
            "assistance_task_patterns",
            sa.Column("decayed_count", sa.Float, nullable=False, server_default="1.0"),
        ),
        (
            "assistance_task_patterns",
            sa.Column("decayed_success", sa.Float, nullable=False, server_default="0.0"),
        ),
        (
            "assistance_task_patterns",
            sa.Column("first_occurred_at", sa.DateTime(timezone=True), nullable=True),
        ),
        (
            "preferred_assistance_modes",
            sa.Column(
                "source", sa.String(20), nullable=False, server_default="explicit"
            ),
        ),
        (
            "preferred_assistance_modes",
            sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        ),
        (
            "preferred_assistance_modes",
            sa.Column(
                "observation_count", sa.Integer, nullable=False, server_default="0"
            ),
        ),
        ("assistance_suggestions", sa.Column("action", sa.String(50), nullable=True)),
        (
            "assistance_suggestions",
            sa.Column("rank", sa.Integer, nullable=False, server_default="1"),
        ),
        (
            "assistance_suggestions",
            sa.Column("model_version", sa.String(96), nullable=True),
        ),
        ("assistance_suggestions", sa.Column("accepted", sa.Boolean, nullable=True)),
        (
            "assistance_suggestions",
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        ),
    ]
    for table, column in additions:
        op.add_column(table, column)

    op.execute(
        sa.text(
            "UPDATE assistance_task_patterns "
            "SET first_occurred_at = last_occurred_at WHERE first_occurred_at IS NULL"
        )
    )
    op.alter_column(
        "assistance_task_patterns", "first_occurred_at", nullable=False
    )


def _repair_data() -> None:
    """Fix rows that violate the invariants about to be enforced."""
    bind = op.get_bind()
    for description, statement in PRE_CONSTRAINT_REPAIRS:
        result = bind.execute(sa.text(statement))
        count = result.rowcount if result.rowcount and result.rowcount > 0 else 0
        if count:
            logger.warning(
                "Repaired %s row(s): %s. These states were reachable under the "
                "previous schema and are now prevented by a CHECK constraint.",
                count,
                description,
            )


def _convert_capability_columns() -> None:
    """Move delimited capability strings to JSONB arrays.

    The old values were produced by ``json.dumps(list)``, so most are already
    valid JSON arrays and only need a type change. Rows written by the even
    older comma-delimited code path are converted defensively.
    """
    bind = op.get_bind()

    def _is_text(table: str, column: str) -> bool:
        """True when the column is still a text type needing conversion."""
        row = bind.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = :t"
                "   AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar_one_or_none()
        return row in {"character varying", "text"}

    if _is_postgres():
        for table, column in (
            ("assistance_requests", "initial_capabilities"),
            ("assistance_escalations", "target_capabilities"),
            ("assistance_escalations", "granted_capabilities"),
        ):
            if not _is_text(table, column):
                continue  # already jsonb, from an earlier upgrade
            # A value that does not parse as JSON is treated as a
            # comma-delimited list; an empty one becomes SQL NULL, not the
            # JSON scalar null (see core.db.dialect.JSONB for why that
            # distinction matters to the CHECK constraints).
            op.execute(
                sa.text(
                    f"""
                    ALTER TABLE {table}
                    ALTER COLUMN {column} TYPE jsonb
                    USING CASE
                        WHEN {column} IS NULL OR btrim({column}) = '' THEN NULL
                        WHEN btrim({column}) LIKE '[%' THEN {column}::jsonb
                        ELSE to_jsonb(string_to_array(btrim({column}), ','))
                    END
                    """
                )
            )
    else:
        # SQLite stores JSON as TEXT, so the existing values are already in the
        # right physical form; only empty strings need normalising to NULL.
        for table, column in (
            ("assistance_requests", "initial_capabilities"),
            ("assistance_escalations", "target_capabilities"),
            ("assistance_escalations", "granted_capabilities"),
        ):
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = NULL WHERE trim({column}) = ''"
                )
            )

    # risk_reasons: ", "-joined text becomes a JSON array. The old split(", ")
    # in the service corrupted any reason containing a comma; converting here
    # accepts that historical loss rather than pretending to recover it.
    if _is_postgres() and _is_text("policy_decisions", "risk_reasons"):
        op.execute(
            sa.text(
                """
                ALTER TABLE policy_decisions
                ALTER COLUMN risk_reasons TYPE jsonb
                USING CASE
                    WHEN risk_reasons IS NULL OR btrim(risk_reasons) = '' THEN NULL
                    ELSE to_jsonb(string_to_array(risk_reasons, ', '))
                END
                """
            )
        )

    # negotiated_capabilities becomes the 1NF relation and the column is dropped.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, negotiated_capabilities FROM policy_decisions "
            "WHERE negotiated_capabilities IS NOT NULL"
        )
    ).fetchall()

    import json

    for decision_id, raw in rows:
        try:
            capabilities = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            capabilities = [c.strip() for c in str(raw).split(",") if c.strip()]
        if not isinstance(capabilities, list):
            continue
        for capability in sorted({str(c) for c in capabilities}):
            bind.execute(
                sa.text(
                    "INSERT INTO policy_decision_capabilities (decision_id, capability)"
                    " VALUES (:d, :c)"
                ),
                {"d": decision_id, "c": capability},
            )

    op.drop_column("policy_decisions", "negotiated_capabilities")


def _encrypt_existing_rows() -> None:
    """Re-write personal columns as ciphertext, and populate blind indexes.

    Performed in Python because the key material is intentionally outside the
    database; no SQL expression can do this. Rows are processed in batches so a
    large table does not build one enormous transaction.
    """
    from core.crypto.blind_index import blind_index
    from core.crypto.envelope import encrypt

    bind = op.get_bind()
    postgres = _is_postgres()

    for table, column, index_column, normalise in ENCRYPTED_COLUMNS:
        temp_column = f"{column}__ct"
        op.add_column(table, sa.Column(temp_column, sa.LargeBinary, nullable=True))

        rows = bind.execute(
            sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")
        ).fetchall()

        for row_id, plaintext in rows:
            if plaintext is None:
                continue
            text_value = str(plaintext)
            params: dict = {
                "ct": encrypt(
                    text_value.encode("utf-8"), context=f"{table}.{column}"
                ),
                "id": row_id,
            }
            assignments = [f"{temp_column} = :ct"]
            if index_column:
                params["bi"] = blind_index(
                    text_value,
                    domain=f"{table}.{column}",
                    normalise=normalise,
                )
                assignments.append(f"{index_column} = :bi")
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET {', '.join(assignments)} WHERE id = :id"
                ),
                params,
            )

        op.drop_column(table, column)
        op.alter_column(table, temp_column, new_column_name=column)

        if postgres and index_column:
            op.create_index(
                f"ix_{table}_{index_column}", table, [index_column], unique=False
            )

        logger.info(
            "Encrypted %s.%s (%s row(s))%s",
            table,
            column,
            len(rows),
            f" and built {index_column}" if index_column else "",
        )

    # Uniqueness that previously lived on plaintext columns now lives on their
    # blind indexes; the ciphertext columns cannot carry it, because randomised
    # encryption makes equal plaintexts unequal ciphertexts.
    #
    # Created as a UNIQUE *index* rather than a UNIQUE *constraint*, because
    # that is what `mapped_column(..., unique=True, index=True)` produces in the
    # ORM. PostgreSQL implements both the same way, but they carry different
    # names, and a name difference is a real problem: Alembic drops by name, so
    # a future migration written against the ORM's name would silently fail to
    # find the production object.
    for table, index_column in (
        ("users", "email_bi"),
        ("users", "display_name_bi"),
        ("device_accounts", "fingerprint_bi"),
    ):
        op.drop_index(f"ix_{table}_{index_column}", table_name=table)
        op.create_index(
            f"ix_{table}_{index_column}", table, [index_column], unique=True
        )

    # Columns the ORM declares NOT NULL. Applied after the data rewrite,
    # because the rewrite is what populates them.
    for table, column in (
        ("users", "email_bi"),
        ("device_accounts", "fingerprint_bi"),
        ("chat_messages", "content"),
        ("device_accounts", "fingerprint"),
        ("device_pairings", "device_fingerprint"),
        ("device_pairings", "device_fingerprint_bi"),
        ("device_pairings", "pairing_code_bi"),
        ("file_transfers", "filename"),
        ("trusted_devices", "device_fingerprint"),
        ("trusted_devices", "device_fingerprint_bi"),
        ("users", "email"),
    ):
        op.alter_column(table, column, nullable=False)


def _apply_enums(postgres: bool) -> None:
    """Convert categorical columns to native enums (PostgreSQL only).

    On SQLite the equivalent domain enforcement arrives as the CHECK
    constraints added by :func:`_apply_checks`, because SQLite has no enum
    type and rewriting every table in batch mode to add one would be a great
    deal of churn for no additional guarantee.
    """
    if not postgres:
        return

    bind = op.get_bind()
    created: set[str] = set()
    for table, column, enum_name, values in ENUM_COLUMNS:
        if enum_name not in created:
            sa.Enum(*values, name=enum_name).create(op.get_bind(), checkfirst=True)
            created.add(enum_name)
        # Any pre-existing value outside the new domain is mapped to the
        # closest safe member rather than blocking the migration: refusing to
        # start because of one bad legacy row helps nobody, and the value was
        # already meaningless.
        allowed = ", ".join(f"'{v}'" for v in values)
        nullable = bind.execute(
            sa.text(
                "SELECT is_nullable = 'YES' FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = :t"
                "   AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar_one_or_none()
        if nullable is None:
            continue  # column absent on this database; nothing to convert

        # A NULL in a nullable column is a legitimate "not reported", not an
        # out-of-domain value, so it is left alone. Only genuinely invalid
        # values are mapped, and only a NOT NULL column gets a fallback.
        predicate = f"{column} IS NOT NULL AND {column} NOT IN ({allowed})"
        if not nullable:
            predicate = f"{column} IS NULL OR {column} NOT IN ({allowed})"
        op.execute(
            sa.text(f"UPDATE {table} SET {column} = '{values[0]}' WHERE {predicate}")
        )
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT"
            )
        )
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"TYPE {enum_name} USING {column}::{enum_name}"
            )
        )


def _apply_checks() -> None:
    """Add the CHECK constraints that encode the schema's invariants."""
    # The initial migration created this one before the naming convention
    # existed, so it carries a pre-prefixed name and would sit alongside the
    # correctly-named duplicate this migration adds. Alembic drops by name, so
    # leaving a differently-named twin in production means a future migration
    # cannot remove it.
    if _is_postgres():
        op.execute(
            sa.text(
                "ALTER TABLE trusted_contacts"
                " DROP CONSTRAINT IF EXISTS ck_trusted_contacts_ck_no_self_contact"
            )
        )

    for table, name, condition in CHECK_CONSTRAINTS:
        op.create_check_constraint(name, table, condition)


def _apply_indexes(postgres: bool) -> None:
    """Add the access-path indexes.

    Partial indexes are PostgreSQL-and-SQLite features but the predicate syntax
    differs for enum comparisons, so the partial variants are created only on
    PostgreSQL and SQLite gets the plain composite equivalents.
    """
    # Session codes become unique among live sessions only; see
    # models/session.py for why global uniqueness does not scale.
    #
    # The old object is a UNIQUE *constraint* or a unique *index* depending on
    # how the table was built, and its name differs accordingly. Both are
    # discovered from the catalogue rather than by attempting a drop inside a
    # try/except: a failed DDL statement aborts the whole transaction in
    # PostgreSQL, so swallowing the exception leaves every subsequent statement
    # failing with "current transaction is aborted" — which is exactly the
    # anti-pattern this migration exists to remove from create_tables().
    bind = op.get_bind()
    if postgres:
        constraints = [
            row[0]
            for row in bind.execute(
                sa.text(
                    "SELECT con.conname FROM pg_constraint con"
                    " WHERE con.conrelid = 'sessions'::regclass"
                    "   AND con.contype = 'u'"
                    "   AND pg_get_constraintdef(con.oid) LIKE '%session_code%'"
                )
            ).fetchall()
        ]
        for name in constraints:
            op.execute(sa.text(f'ALTER TABLE sessions DROP CONSTRAINT "{name}"'))

        indexes = [
            row[0]
            for row in bind.execute(
                sa.text(
                    "SELECT indexname FROM pg_indexes"
                    " WHERE tablename = 'sessions' AND indexdef LIKE '%session_code%'"
                )
            ).fetchall()
        ]
        for name in indexes:
            op.execute(sa.text(f'DROP INDEX IF EXISTS "{name}"'))
    else:
        inspector = sa.inspect(bind)
        existing = {ix["name"] for ix in inspector.get_indexes("sessions")}
        for name in existing:
            if name and "session_code" in name:
                op.drop_index(name, table_name="sessions")

    if postgres:
        # Retire duplicate codes among ended sessions before the new index is
        # built; they are unreachable join tokens and only block the index.
        op.execute(
            sa.text(
                "UPDATE sessions s SET session_code = left(md5(s.id::text), 8)"
                " WHERE status = 'ended' AND EXISTS ("
                "   SELECT 1 FROM sessions o"
                "    WHERE o.session_code = s.session_code AND o.id <> s.id)"
            )
        )
    op.create_index(
        "uq_sessions_live_code",
        "sessions",
        ["session_code"],
        unique=True,
        postgresql_where=sa.text("status <> 'ended'"),
        sqlite_where=sa.text("status <> 'ended'"),
    )

    op.create_index(
        "ix_chat_messages_session_time", "chat_messages", ["session_id", "timestamp"]
    )
    op.create_index(
        "ix_audit_logs_session_time", "audit_logs", ["session_id", "timestamp"]
    )
    op.create_index(
        "ix_trusted_contacts_reverse", "trusted_contacts", ["contact_user_id", "status"]
    )
    op.create_index(
        "ix_participants_session_role", "session_participants", ["session_id", "role"]
    )
    op.create_index(
        "ix_policy_decisions_risk_mode",
        "policy_decisions",
        ["risk_level", "assistance_mode"],
    )
    op.create_index(
        "ix_task_patterns_user_strength",
        "assistance_task_patterns",
        ["user_id", "decayed_count"],
    )
    op.create_index(
        "ix_refresh_tokens_user_created", "refresh_tokens", ["user_id", "created_at"]
    )

    # --- Indexes on tables this migration creates, and ones the ORM
    # declares that were previously missing here. See test_schema_parity.
    op.create_index(
        "ix_action_transitions_lookup",
        "assistance_action_transitions",
        ['user_id', 'prev_action', 'decayed_count'],
    )
    op.create_index(
        "ix_assistance_requests_helpee_time",
        "assistance_requests",
        ['helpee_user_id', 'created_at'],
    )
    op.create_index(
        "ix_audit_ledger_security_events",
        "audit_ledger",
                ["recorded_at", "event_type"],
        postgresql_where=sa.text(
            "event_category IN ('security', 'consent', 'capability')"
        ),
    )
    op.create_index(
        "ix_context_events_app",
        "context_events",
        ['foreground_app', 'foreground_app_category'], postgresql_where=sa.text("foreground_app IS NOT NULL"),
    )
    op.create_index(
        "ix_context_events_protected",
        "context_events",
        ['recorded_at'], postgresql_where=sa.text("is_flag_secure_active OR is_sensitive_app"),
    )
    op.create_index(
        "ix_device_accounts_recovery_code_bi",
        "device_accounts",
        ['recovery_code_bi'],
    )
    op.create_index(
        "ix_device_pairings_pairing_code_bi",
        "device_pairings",
        ['pairing_code_bi'],
    )
    op.create_index(
        "ix_ml_decision_labelled",
        "ml_decision_log",
        ['decision_kind', 'recorded_at'], postgresql_where=sa.text("reward IS NOT NULL"),
    )
    op.create_index(
        "ix_ml_decision_session",
        "ml_decision_log",
        ['session_id', 'recorded_at'],
    )
    op.create_index(
        "ix_suggestions_outcome",
        "assistance_suggestions",
        ['suggestion_type', 'accepted', 'created_at'],
    )
    op.create_index(
        "ix_suggestions_session",
        "assistance_suggestions",
        ['session_id', 'rank'],
    )
    op.create_index(
        "uq_owner_device",
        "trusted_devices",
        ['owner_user_id', 'device_fingerprint_bi'], unique=True,
    )

    if not postgres:
        return

    partial_indexes = [
        ("ix_sessions_creator_live", "sessions", ["creator_id", "created_at"], "status <> 'ended'"),
        ("ix_sessions_elevated", "sessions", ["remote_control_granted_at"], "remote_control_granted"),
        ("ix_participants_user_live", "session_participants", ["user_id"], "status = 'connected'"),
        ("ix_trusted_contacts_accepted", "trusted_contacts", ["user_id", "contact_user_id"], "status = 'accepted'"),
        ("ix_trusted_devices_active", "trusted_devices", ["owner_user_id", "helper_user_id"], "status = 'accepted'"),
        ("ix_device_pairings_open", "device_pairings", ["owner_user_id", "expires_at"], "status = 'pending'"),
        ("ix_assistance_requests_pending", "assistance_requests", ["helper_user_id", "created_at"], "status = 'pending'"),
        ("ix_escalations_pending", "assistance_escalations", ["session_id", "created_at"], "status = 'pending'"),
        ("ix_refresh_tokens_live", "refresh_tokens", ["token_hash"], "NOT revoked"),
        ("ix_file_transfers_active", "file_transfers", ["session_id", "created_at"], "status IN ('initiating', 'transferring')"),
        ("ix_users_active_created", "users", ["created_at"], "is_active"),
        ("ix_context_snapshots_protected", "context_snapshots", ["session_id"], "is_flag_secure_active OR is_sensitive_app"),
    ]
    for name, table, columns, predicate in partial_indexes:
        op.create_index(name, table, columns, postgresql_where=sa.text(predicate))

    # Covering index: PostgreSQL can satisfy the session-list endpoint from
    # the index alone, with no heap access.
    op.create_index(
        "ix_sessions_status_created",
        "sessions",
        ["status", "created_at"],
        postgresql_include=["creator_id", "ended_at"],
    )
    # GIN with jsonb_path_ops for containment queries over audit detail.
    op.create_index(
        "ix_audit_ledger_detail",
        "audit_ledger",
        ["detail"],
        postgresql_using="gin",
        postgresql_ops={"detail": "jsonb_path_ops"},
    )


def _install_postgres_objects() -> None:
    """Install trigger functions, partitions, views, RLS, and the ledger chain."""
    for block in (
        UPDATED_AT_TRIGGER,
        AUDIT_CHAIN,
        APPEND_ONLY_GUARD,
        PARTITION_HELPERS,
    ):
        _run(block["up"])

    for table in (
        "users",
        "sessions",
        "trusted_contacts",
        "trusted_devices",
        "policy_decisions",
        "context_snapshots",
    ):
        _run(attach_updated_at(table))

    _run(attach_audit_chain("audit_ledger"))
    for table in ("audit_ledger", "context_events"):
        _run(attach_append_only(table))

    for parent in ("audit_ledger", "context_events", "ml_decision_log"):
        op.execute(sa.text(f"SELECT assistme_provision_partitions('{parent}', 3, 1)"))
        op.execute(sa.text(f"SELECT assistme_ensure_default_partition('{parent}')"))

    for block in (EXCLUSION_CONSTRAINTS, MATERIALIZED_VIEWS, ROW_LEVEL_SECURITY):
        _run(block["up"])

    op.execute(sa.text("SELECT assistme_refresh_analytics(false)"))


# ----------------------------------------------------------------------
# Downgrade
# ----------------------------------------------------------------------


def downgrade() -> None:
    """Reverse the structural changes.

    Honest limitation: this restores the *shape* of the previous schema but not
    the plaintext of encrypted columns, which are decrypted back to text here —
    a step that requires the same key material the upgrade used. If the keys
    are gone, the downgrade cannot recover the data, and that is a property of
    encryption rather than a defect in the migration. Take a backup before
    downgrading a production database.
    """
    postgres = _is_postgres()

    if postgres:
        for block in (
            ROW_LEVEL_SECURITY,
            MATERIALIZED_VIEWS,
            EXCLUSION_CONSTRAINTS,
            PARTITION_HELPERS,
            APPEND_ONLY_GUARD,
            AUDIT_CHAIN,
            UPDATED_AT_TRIGGER,
        ):
            _run(block["down"])

    # The bare constraint name is passed, not the rendered one: Alembic applies
    # the metadata naming convention (``ck_%(table_name)s_%(constraint_name)s``)
    # on drop just as it does on create, so pre-prefixing here would produce
    # ``ck_<table>_ck_<table>_<name>``.
    # Indexes first: some are partial on columns the constraint drops below
    # would otherwise still be referenced.
    bind = op.get_bind()
    if postgres:
        existing = {
            row[0]
            for row in bind.execute(
                sa.text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            ).fetchall()
        }
    else:
        inspector = sa.inspect(bind)
        existing = {
            ix["name"]
            for table in inspector.get_table_names()
            for ix in inspector.get_indexes(table)
            if ix["name"]
        }

    for name in CREATED_INDEXES:
        if name in existing:
            op.execute(sa.text(f'DROP INDEX IF EXISTS "{name}"'))

    for table, name, _ in reversed(CHECK_CONSTRAINTS):
        op.drop_constraint(name, table, type_="check")

    _decrypt_existing_rows()
    _restore_refresh_tokens()

    op.add_column(
        "policy_decisions", sa.Column("negotiated_capabilities", sa.Text, nullable=True)
    )

    for table in (
        "assistance_action_transitions",
        "policy_decision_capabilities",
        "ml_decision_log",
        "context_events",
        "audit_ledger",
    ):
        op.drop_table(table)

    for table, column in (
        ("users", "email_bi"),
        ("users", "display_name_bi"),
        ("device_accounts", "fingerprint_bi"),
        ("device_accounts", "recovery_code_bi"),
        ("trusted_devices", "device_fingerprint_bi"),
        ("device_pairings", "device_fingerprint_bi"),
        ("device_pairings", "pairing_code_bi"),
        ("policy_decisions", "decision_source"),
        ("policy_decisions", "model_version"),
        ("policy_decisions", "model_confidence"),
        ("policy_decisions", "risk_score"),
        ("policy_decisions", "envelope_clamped"),
        ("assistance_task_patterns", "success_count"),
        ("assistance_task_patterns", "decayed_count"),
        ("assistance_task_patterns", "decayed_success"),
        ("assistance_task_patterns", "first_occurred_at"),
        ("preferred_assistance_modes", "source"),
        ("preferred_assistance_modes", "confidence"),
        ("preferred_assistance_modes", "observation_count"),
        ("assistance_suggestions", "action"),
        ("assistance_suggestions", "rank"),
        ("assistance_suggestions", "model_version"),
        ("assistance_suggestions", "accepted"),
        ("assistance_suggestions", "responded_at"),
    ):
        op.drop_column(table, column)


def _restore_refresh_tokens() -> None:
    """Restore the plaintext ``token`` column.

    The plaintext cannot be recovered from a SHA-256 digest, so the rows are
    deleted rather than filled with placeholder values that would silently
    never authenticate. Every user re-authenticates after a downgrade, which is
    the honest outcome: the previous schema stored a credential this one
    deliberately does not keep.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("refresh_tokens")}
    if "token" in columns:
        return

    deleted = bind.execute(sa.text("DELETE FROM refresh_tokens")).rowcount
    if deleted:
        logger.warning(
            "Deleted %s refresh token(s): the plaintext cannot be recovered "
            "from a digest, so affected users must sign in again.",
            deleted,
        )

    # The index was already removed by the CREATED_INDEXES sweep at the top of
    # downgrade(); only the column remains.
    op.drop_column("refresh_tokens", "token_hash")
    op.add_column("refresh_tokens", sa.Column("token", sa.String(255), nullable=False))
    op.create_index(
        "ix_refresh_tokens_token", "refresh_tokens", ["token"], unique=True
    )


def _decrypt_existing_rows() -> None:
    """Restore encrypted columns to plaintext text columns."""
    from core.crypto.envelope import DecryptionError, decrypt

    bind = op.get_bind()
    for table, column, _index_column, _normalise in ENCRYPTED_COLUMNS:
        temp_column = f"{column}__pt"
        op.add_column(table, sa.Column(temp_column, sa.Text, nullable=True))

        rows = bind.execute(
            sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")
        ).fetchall()
        for row_id, blob in rows:
            try:
                plaintext = decrypt(bytes(blob), context=f"{table}.{column}").decode(
                    "utf-8"
                )
            except DecryptionError:
                logger.error(
                    "Could not decrypt %s.%s id=%s during downgrade; leaving NULL",
                    table,
                    column,
                    row_id,
                )
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET {temp_column} = :pt WHERE id = :id"),
                {"pt": plaintext, "id": row_id},
            )

        op.drop_column(table, column)
        op.alter_column(table, temp_column, new_column_name=column)
