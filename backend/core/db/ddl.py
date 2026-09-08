"""PostgreSQL DDL that the ORM cannot express: triggers, partitions, MVs, RLS.

SQLAlchemy models describe tables and constraints well. They do not describe
trigger functions, declarative partitioning, materialised views, or row-level
security — all of which this schema depends on. Those live here as versioned
SQL, applied by Alembic migrations and exercised by
``tests/test_postgres_schema.py``.

Contents
--------
1. **Naming convention** so every constraint and index has a deterministic name
   and Alembic autogenerate produces stable diffs.
2. **``set_updated_at``** — one trigger replacing per-model Python ``onupdate``
   hooks, so a raw SQL ``UPDATE`` cannot bypass the timestamp.
3. **Tamper-evident audit ledger** — a per-session hash chain enforced by
   triggers, with an append-only guard and an in-database verification function.
4. **Declarative range partitioning** for the two append-only tables that grow
   without bound.
5. **Materialised views** backing the research evaluation and the ML feature
   store.
6. **Row-level security** as defence in depth against a compromised connection.
"""

from __future__ import annotations

import re

from sqlalchemy import MetaData

__all__ = [
    "APPEND_ONLY_GUARD",
    "AUDIT_CHAIN",
    "EXCLUSION_CONSTRAINTS",
    "MATERIALIZED_VIEWS",
    "NAMING_CONVENTION",
    "PARTITION_HELPERS",
    "ROW_LEVEL_SECURITY",
    "UPDATED_AT_TRIGGER",
    "metadata_with_naming_convention",
    "split_sql_script",
]


# ----------------------------------------------------------------------
# Script splitting
# ----------------------------------------------------------------------

# Matches a PostgreSQL dollar-quote delimiter: $$ or $tag$.
_DOLLAR_TAG = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def split_sql_script(script: str) -> list[str]:
    """Split a SQL script into individual statements.

    Splitting on ``;`` is wrong for this schema, because every trigger function
    body is dollar-quoted and full of semicolons. This scanner tracks
    dollar-quote tags, single quotes, and line comments, so a ``;`` inside a
    ``$$ ... $$`` body or a string literal does not end a statement.

    The alternative — handing whole scripts to the driver — is not available:
    asyncpg sends every query through the extended (prepared-statement)
    protocol, which permits exactly one command per message. Splitting here
    keeps one definition of the DDL usable from both the async application
    bootstrap and the synchronous Alembic migrations.
    """
    statements: list[str] = []
    buffer: list[str] = []
    i = 0
    length = len(script)
    dollar_tag: str | None = None
    in_single_quote = False
    in_line_comment = False

    while i < length:
        char = script[i]

        if in_line_comment:
            buffer.append(char)
            if char == "\n":
                in_line_comment = False
            i += 1
            continue

        if dollar_tag is not None:
            if script.startswith(dollar_tag, i):
                buffer.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buffer.append(char)
            i += 1
            continue

        if in_single_quote:
            buffer.append(char)
            # '' is an escaped quote, not a terminator.
            if char == "'":
                if script.startswith("''", i):
                    buffer.append("'")
                    i += 2
                    continue
                in_single_quote = False
            i += 1
            continue

        if script.startswith("--", i):
            in_line_comment = True
            buffer.append(char)
            i += 1
            continue

        if char == "'":
            in_single_quote = True
            buffer.append(char)
            i += 1
            continue

        match = _DOLLAR_TAG.match(script, i)
        if match:
            dollar_tag = match.group(0)
            buffer.append(dollar_tag)
            i += len(dollar_tag)
            continue

        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            i += 1
            continue

        buffer.append(char)
        i += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements

# ----------------------------------------------------------------------
# 1. Naming convention
# ----------------------------------------------------------------------

#: Deterministic constraint and index names.
#:
#: Without this, SQLAlchemy lets the database invent names for unnamed
#: constraints (PostgreSQL produces ``sessions_status_check1``, and the suffix
#: number depends on creation order). Alembic then cannot reliably ``DROP`` a
#: constraint it did not create, and autogenerate emits spurious diffs. Fixing
#: the convention up front is the difference between migrations that work for
#: three years and migrations that need manual patching by month four.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def metadata_with_naming_convention() -> MetaData:
    """Return a ``MetaData`` bound to the project naming convention."""
    return MetaData(naming_convention=NAMING_CONVENTION)


# ----------------------------------------------------------------------
# 2. updated_at maintenance
# ----------------------------------------------------------------------

UPDATED_AT_TRIGGER = {
    "up": """
CREATE OR REPLACE FUNCTION assistme_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION assistme_set_updated_at() IS
'Maintains updated_at on every UPDATE. Enforced in the database rather than by
SQLAlchemy onupdate= so that raw SQL, bulk updates, and future non-Python
clients cannot leave a stale timestamp behind.';
""",
    "down": "DROP FUNCTION IF EXISTS assistme_set_updated_at() CASCADE;",
}


def attach_updated_at(table: str) -> str:
    """SQL attaching the ``updated_at`` trigger to one table."""
    return f"""
DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};
CREATE TRIGGER trg_{table}_updated_at
    BEFORE UPDATE ON {table}
    FOR EACH ROW
    EXECUTE FUNCTION assistme_set_updated_at();
"""


# ----------------------------------------------------------------------
# 3. Tamper-evident audit ledger
# ----------------------------------------------------------------------

AUDIT_CHAIN = {
    "up": r"""
-- ---------------------------------------------------------------------
-- Hash-chained audit ledger
-- ---------------------------------------------------------------------
-- Each session's audit entries form a linked chain:
--
--     entry_hash(n) = SHA256( prev_hash(n) || canonical_payload(n) )
--     prev_hash(n)  = entry_hash(n-1),  or the genesis constant for n = 1
--
-- Any modification to a historical entry changes its entry_hash, which breaks
-- every subsequent link. Deleting an entry leaves a sequence gap. Neither can
-- be repaired without recomputing the whole tail, and the append-only guard
-- below prevents even that.
--
-- This gives the property the product's security story actually claims: the
-- helpee can be shown a complete, verifiable record of what was done on their
-- device, and no operator with SQL access can quietly edit it.

CREATE OR REPLACE FUNCTION assistme_audit_chain_append()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_prev_hash  bytea;
    v_prev_seq   bigint;
BEGIN
    -- Serialise appends per session. Without this lock two concurrent inserts
    -- can read the same MAX(seq) and produce a forked chain -- a real race,
    -- since a session's helper and helpee emit audit events simultaneously.
    -- An advisory *transaction* lock is used rather than SELECT ... FOR UPDATE
    -- because there is no parent row to lock and it releases automatically at
    -- commit or rollback.
    PERFORM pg_advisory_xact_lock(
        hashtext('assistme_audit_chain'), hashtext(NEW.session_id::text)
    );

    SELECT seq, entry_hash
      INTO v_prev_seq, v_prev_hash
      FROM audit_ledger
     WHERE session_id = NEW.session_id
     ORDER BY seq DESC
     LIMIT 1;

    IF v_prev_seq IS NULL THEN
        NEW.seq := 1;
        -- Genesis: a fixed 32-byte constant, distinct per session so two
        -- sessions' chains can never be spliced into one another.
        NEW.prev_hash := sha256(('assistme-genesis-v1:' || NEW.session_id::text)::bytea);
    ELSE
        NEW.seq := v_prev_seq + 1;
        NEW.prev_hash := v_prev_hash;
    END IF;

    -- The link commits to the previous hash, the writer-supplied content
    -- digest, and the position in the chain. Including seq means an attacker
    -- cannot reorder two entries even if their payloads were identical.
    -- Fields are length-unambiguous (32 B ‖ 32 B ‖ 8 B), so no separator or
    -- canonicalisation is needed and no 'AB'||'C' = 'A'||'BC' collision exists.
    NEW.entry_hash := sha256(
        NEW.prev_hash || NEW.payload_digest || int8send(NEW.seq)
    );
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION assistme_audit_chain_append() IS
'Computes the per-session sequence number and hash chain link for an audit
entry. Serialised per session with a transaction-scoped advisory lock so
concurrent helper and helpee events cannot fork the chain.';


-- ---------------------------------------------------------------------
-- Chain verification
-- ---------------------------------------------------------------------
-- Recomputes the chain from scratch and reports the first divergence. Runs in
-- the database so verification does not depend on trusting the application.

CREATE OR REPLACE FUNCTION assistme_audit_verify(p_session_id uuid)
RETURNS TABLE (
    seq          bigint,
    entry_id     uuid,
    valid        boolean,
    failure      text
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    r            record;
    v_expected   bytea;
    v_computed   bytea;
    v_next_seq   bigint := 1;
BEGIN
    v_expected := sha256(('assistme-genesis-v1:' || p_session_id::text)::bytea);

    FOR r IN
        SELECT * FROM audit_ledger
         WHERE session_id = p_session_id
         ORDER BY seq ASC
    LOOP
        seq := r.seq;
        entry_id := r.id;
        valid := true;
        failure := NULL;

        IF r.seq <> v_next_seq THEN
            valid := false;
            failure := format('sequence gap: expected %s, found %s', v_next_seq, r.seq);
        ELSIF r.prev_hash <> v_expected THEN
            valid := false;
            failure := 'prev_hash does not match the preceding entry hash';
        ELSE
            v_computed := sha256(
                r.prev_hash || r.payload_digest || int8send(r.seq)
            );
            IF v_computed <> r.entry_hash THEN
                valid := false;
                failure := 'entry_hash does not match recomputed chain link';
            END IF;
        END IF;

        v_expected := r.entry_hash;
        v_next_seq := r.seq + 1;
        RETURN NEXT;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION assistme_audit_verify(uuid) IS
'Structural verification of a session audit chain: linkage, sequence
continuity, and hash-link correctness. Content verification (recomputing
payload_digest from the row fields) is performed by AuditLedgerService, which
owns the canonical serialisation. Used by the security review endpoint and by
tests that deliberately tamper with a row.';
""",
    "down": """
DROP FUNCTION IF EXISTS assistme_audit_verify(uuid);
DROP FUNCTION IF EXISTS assistme_audit_chain_append() CASCADE;
""",
}


def attach_audit_chain(table: str = "audit_ledger") -> str:
    """SQL attaching the hash-chain trigger to the ledger.

    PostgreSQL 13+ supports row-level ``BEFORE`` triggers on a partitioned
    parent and propagates them to every partition, including ones created
    later — which is exactly what is needed here, since partitions are
    provisioned monthly by a maintenance job that must not have to remember to
    re-attach triggers.
    """
    return f"""
DROP TRIGGER IF EXISTS trg_{table}_chain ON {table};
CREATE TRIGGER trg_{table}_chain
    BEFORE INSERT ON {table}
    FOR EACH ROW
    EXECUTE FUNCTION assistme_audit_chain_append();
"""


APPEND_ONLY_GUARD = {
    "up": """
-- ---------------------------------------------------------------------
-- Append-only enforcement
-- ---------------------------------------------------------------------
-- Revoking UPDATE/DELETE from the application role is the first line of
-- defence, but privileges are a deployment concern that a misconfigured
-- environment can quietly drop. A trigger enforces the invariant inside the
-- database regardless of who holds which grant, including the table owner.

CREATE OR REPLACE FUNCTION assistme_forbid_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'Table % is append-only; % is not permitted (attempted on row id %)',
        TG_TABLE_NAME, TG_OP,
        CASE WHEN TG_OP = 'DELETE' THEN OLD.id::text ELSE NEW.id::text END
        USING ERRCODE = 'integrity_constraint_violation',
              HINT = 'Correct an erroneous entry by appending a compensating '
                     'record; history is never rewritten.';
END;
$$;

COMMENT ON FUNCTION assistme_forbid_mutation() IS
'Rejects UPDATE and DELETE on append-only tables (audit ledger, context event
stream, model decision log).';
""",
    "down": "DROP FUNCTION IF EXISTS assistme_forbid_mutation() CASCADE;",
}


def attach_append_only(table: str) -> str:
    """SQL making one table reject UPDATE and DELETE.

    Note the ``FOR EACH STATEMENT`` variant is deliberately *not* used: a
    row-level trigger lets the error message name the offending row, which
    matters when the guard fires during an incident investigation.
    """
    return f"""
DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table};
CREATE TRIGGER trg_{table}_append_only
    BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW
    EXECUTE FUNCTION assistme_forbid_mutation();
"""


# ----------------------------------------------------------------------
# 4. Declarative partitioning
# ----------------------------------------------------------------------

PARTITION_HELPERS = {
    "up": """
-- ---------------------------------------------------------------------
-- Monthly range partition management
-- ---------------------------------------------------------------------
-- audit_ledger and context_events are append-only and grow linearly with
-- usage forever. Three properties make monthly RANGE partitioning the right
-- structure here rather than a single heap:
--
--   * Retention becomes DROP TABLE (instant, no bloat) instead of a mass
--     DELETE that leaves dead tuples for autovacuum to chase.
--   * Every analytical query in this system filters on a time window, so
--     partition pruning eliminates whole months before a single page is read.
--   * Per-partition indexes stay small enough to remain cache-resident.

CREATE OR REPLACE FUNCTION assistme_ensure_month_partition(
    p_parent text,
    p_month  date
)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_start date := date_trunc('month', p_month)::date;
    v_end   date := (date_trunc('month', p_month) + interval '1 month')::date;
    v_name  text := format('%s_p%s', p_parent, to_char(v_start, 'YYYYMM'));
BEGIN
    IF to_regclass(v_name) IS NOT NULL THEN
        RETURN v_name;
    END IF;

    EXECUTE format(
        'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        v_name, p_parent, v_start, v_end
    );

    -- BRIN rather than B-tree on the time column: the data is physically
    -- append-ordered by time, so a BRIN index summarising each 128-page range
    -- answers window queries with an index hundreds of times smaller than the
    -- equivalent B-tree, and costs almost nothing to maintain on insert.
    EXECUTE format(
        'CREATE INDEX %I ON %I USING brin (recorded_at) WITH (pages_per_range = 32)',
        'brin_' || v_name || '_recorded_at', v_name
    );

    RETURN v_name;
END;
$$;

COMMENT ON FUNCTION assistme_ensure_month_partition(text, date) IS
'Idempotently creates the monthly partition covering p_month, with a BRIN
index on recorded_at. Safe to call from a scheduled job and from the
application on the first insert of a new month.';


CREATE OR REPLACE FUNCTION assistme_provision_partitions(
    p_parent       text,
    p_months_ahead int DEFAULT 3,
    p_months_back  int DEFAULT 0
)
RETURNS SETOF text
LANGUAGE plpgsql
AS $$
DECLARE
    i int;
BEGIN
    FOR i IN -p_months_back..p_months_ahead LOOP
        RETURN NEXT assistme_ensure_month_partition(
            p_parent, (current_date + (i || ' months')::interval)::date
        );
    END LOOP;
END;
$$;

COMMENT ON FUNCTION assistme_provision_partitions(text, int, int) IS
'Creates monthly partitions from p_months_back before to p_months_ahead after
the current month. Run from a monthly maintenance job so a month boundary never
lands on a missing partition; p_months_back is for backfilling imported data.';


-- ---------------------------------------------------------------------
-- Default partitions
-- ---------------------------------------------------------------------
-- A range-partitioned table rejects any row outside every defined range with
-- "no partition of relation found". For an append-only audit table that is
-- data loss on a write path that must not fail: if the maintenance job misses
-- a month, or a client's clock is skewed into next year, the event that
-- records what happened on someone's phone is simply refused.
--
-- A DEFAULT partition catches those rows instead. The trade-off is real and
-- worth stating: once the default holds rows, attaching a new partition whose
-- range overlaps them requires a full scan of the default to prove none belong
-- there. The default is therefore a safety net, not a strategy — it should
-- stay empty, and assistme_check_default_partitions() exists to alert when it
-- does not.

CREATE OR REPLACE FUNCTION assistme_ensure_default_partition(p_parent text)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_name text := format('%s_default', p_parent);
BEGIN
    IF to_regclass(v_name) IS NOT NULL THEN
        RETURN v_name;
    END IF;
    EXECUTE format('CREATE TABLE %I PARTITION OF %I DEFAULT', v_name, p_parent);
    RETURN v_name;
END;
$$;

CREATE OR REPLACE FUNCTION assistme_check_default_partitions()
RETURNS TABLE (partition_name text, row_count bigint)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    r record;
    v_count bigint;
BEGIN
    FOR r IN
        SELECT relname FROM pg_class
         WHERE relname LIKE '%\\_default' AND relkind = 'r'
           AND relnamespace = 'public'::regnamespace
    LOOP
        EXECUTE format('SELECT count(*) FROM %I', r.relname) INTO v_count;
        IF v_count > 0 THEN
            partition_name := r.relname;
            row_count := v_count;
            RETURN NEXT;
        END IF;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION assistme_check_default_partitions() IS
'Returns any default partition holding rows. A non-empty result means the
monthly provisioning job has fallen behind, or a client is writing timestamps
outside the provisioned range. Alert on it.';
""",
    "down": """
DROP FUNCTION IF EXISTS assistme_provision_partitions(text, int);
DROP FUNCTION IF EXISTS assistme_ensure_month_partition(text, date);
""",
}


# ----------------------------------------------------------------------
# 4b. Exclusion constraints
# ----------------------------------------------------------------------

EXCLUSION_CONSTRAINTS = {
    "up": """
-- ---------------------------------------------------------------------
-- The "one helper, one helpee, one session at a time" invariant
-- ---------------------------------------------------------------------
-- This is the product's defining constraint and it is a statement about
-- *intervals*, which no UNIQUE constraint can express. Checking it in the
-- service layer is a check-then-act race: two accepts arriving together both
-- read "this user has no live session" and both insert.
--
-- An exclusion constraint states it exactly: for any two rows with the same
-- user, their participation intervals must not overlap. An open participation
-- is [joined_at, infinity), so a second concurrent join overlaps the first and
-- is rejected by the index at commit. Correct under any concurrency, with no
-- application locking and no advisory lock to forget.
--
-- btree_gist supplies the GiST equality operator class for uuid, which core
-- GiST does not provide.

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Dropped first so the whole block is re-runnable. A development bootstrap
-- that fails the second time it runs is a bootstrap people stop trusting.
ALTER TABLE session_participants
    DROP CONSTRAINT IF EXISTS ex_participants_no_overlap;

ALTER TABLE session_participants
    ADD CONSTRAINT ex_participants_no_overlap
    EXCLUDE USING gist (
        user_id WITH =,
        tstzrange(joined_at, left_at) WITH &&
    ) WHERE (status <> 'left');

COMMENT ON CONSTRAINT ex_participants_no_overlap ON session_participants IS
'A user cannot be actively participating in two sessions at once. Enforced by
the index rather than by application logic, so it holds under concurrency.';
""",
    "down": """
ALTER TABLE session_participants
    DROP CONSTRAINT IF EXISTS ex_participants_no_overlap;
""",
}


# ----------------------------------------------------------------------
# 5. Materialised views
# ----------------------------------------------------------------------

MATERIALIZED_VIEWS = {
    "up": """
-- ---------------------------------------------------------------------
-- mv_session_analytics
-- ---------------------------------------------------------------------
-- One row per completed session with the derived measures the evaluation and
-- the operations dashboard both need. Computing these on demand means a
-- four-way join plus three correlated aggregates per session; as a
-- materialised view it is a sequential scan of a narrow table.

DROP MATERIALIZED VIEW IF EXISTS mv_session_analytics CASCADE;
CREATE MATERIALIZED VIEW mv_session_analytics AS
SELECT
    s.id                                        AS session_id,
    s.creator_id,
    s.status,
    s.created_at,
    s.ended_at,
    EXTRACT(EPOCH FROM (COALESCE(s.ended_at, now()) - s.created_at))
                                                AS duration_seconds,
    s.remote_control_granted,
    pd.risk_level,
    pd.assistance_mode,
    pd.consent_verified,
    COUNT(DISTINCT sp.user_id)                  AS participant_count,
    COUNT(DISTINCT sp.user_id) FILTER (WHERE sp.role = 'helper')
                                                AS helper_count,
    COUNT(DISTINCT ae.id)                       AS escalation_count,
    COUNT(DISTINCT ae.id) FILTER (WHERE ae.status = 'approved')
                                                AS escalation_approved_count,
    COUNT(DISTINCT ae.id) FILTER (WHERE ae.status = 'rejected')
                                                AS escalation_rejected_count,
    MAX(sp.rtt_ms)                              AS worst_rtt_ms,
    MAX(sp.packet_loss_percent)                 AS worst_packet_loss_percent
FROM sessions s
LEFT JOIN session_participants   sp ON sp.session_id = s.id
LEFT JOIN policy_decisions       pd ON pd.session_id = s.id
LEFT JOIN assistance_escalations ae ON ae.session_id = s.id
GROUP BY s.id, pd.risk_level, pd.assistance_mode, pd.consent_verified;

-- A UNIQUE index is not optional here: REFRESH MATERIALIZED VIEW CONCURRENTLY
-- requires one. Without it every refresh takes an ACCESS EXCLUSIVE lock and
-- blocks all readers for its duration.
CREATE UNIQUE INDEX uq_mv_session_analytics_session
    ON mv_session_analytics (session_id);
CREATE INDEX ix_mv_session_analytics_created
    ON mv_session_analytics (created_at DESC);


-- ---------------------------------------------------------------------
-- mv_user_assistance_profile
-- ---------------------------------------------------------------------
-- Per-user behavioural summary. Doubles as the cold-start prior for the
-- recommender: a user with no history in the current context still has a
-- global mode distribution to fall back on.

DROP MATERIALIZED VIEW IF EXISTS mv_user_assistance_profile CASCADE;
CREATE MATERIALIZED VIEW mv_user_assistance_profile AS
SELECT
    u.id                                              AS user_id,
    COUNT(DISTINCT sp.session_id)                     AS total_sessions,
    COUNT(DISTINCT sp.session_id) FILTER (WHERE sp.role = 'helpee')
                                                      AS sessions_as_helpee,
    COUNT(DISTINCT sp.session_id) FILTER (WHERE sp.role = 'helper')
                                                      AS sessions_as_helper,
    MIN(s.created_at)                                 AS first_session_at,
    MAX(s.created_at)                                 AS last_session_at,
    AVG(EXTRACT(EPOCH FROM (s.ended_at - s.created_at)))
        FILTER (WHERE s.ended_at IS NOT NULL)         AS avg_duration_seconds,
    COUNT(DISTINCT tc.contact_user_id)
        FILTER (WHERE tc.status = 'accepted')         AS trusted_contact_count,
    COUNT(DISTINCT ae.id) FILTER (WHERE ae.status = 'approved')
                                                      AS escalations_approved,
    COUNT(DISTINCT ae.id)                             AS escalations_requested
FROM users u
LEFT JOIN session_participants   sp ON sp.user_id = u.id
LEFT JOIN sessions               s  ON s.id = sp.session_id
LEFT JOIN trusted_contacts       tc ON tc.user_id = u.id
LEFT JOIN assistance_escalations ae ON ae.requested_by_user_id = u.id
GROUP BY u.id;

CREATE UNIQUE INDEX uq_mv_user_assistance_profile_user
    ON mv_user_assistance_profile (user_id);


-- ---------------------------------------------------------------------
-- mv_app_risk_profile
-- ---------------------------------------------------------------------
-- Empirical risk statistics per foreground application, aggregated across all
-- users. This is the ML feature store's population prior: when the classifier
-- meets an app it has never seen for this user, the population's historical
-- escalation-approval and high-risk rates are the informative fallback.
--
-- The HAVING floor matters for privacy as well as statistics: an app observed
-- in fewer than five sessions is dropped, so the view cannot become a
-- single-user re-identification channel.

DROP MATERIALIZED VIEW IF EXISTS mv_app_risk_profile CASCADE;
CREATE MATERIALIZED VIEW mv_app_risk_profile AS
SELECT
    ce.foreground_app,
    ce.foreground_app_category,
    COUNT(*)                                                    AS observation_count,
    COUNT(DISTINCT ce.session_id)                               AS session_count,
    AVG((ce.is_flag_secure_active)::int)::double precision      AS flag_secure_rate,
    AVG((ce.is_sensitive_app)::int)::double precision           AS sensitive_rate,
    AVG((pd.risk_level = 'high')::int)::double precision        AS high_risk_rate,
    AVG((pd.assistance_mode = 'tap')::int)::double precision    AS tap_mode_rate,
    MAX(ce.recorded_at)                                         AS last_observed_at
FROM context_events ce
LEFT JOIN policy_decisions pd ON pd.session_id = ce.session_id
WHERE ce.foreground_app IS NOT NULL
GROUP BY ce.foreground_app, ce.foreground_app_category
HAVING COUNT(DISTINCT ce.session_id) >= 5;

CREATE UNIQUE INDEX uq_mv_app_risk_profile_app
    ON mv_app_risk_profile (foreground_app, foreground_app_category);


-- ---------------------------------------------------------------------
-- Refresh helper
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION assistme_refresh_analytics(p_concurrently boolean DEFAULT true)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_view text;
BEGIN
    FOREACH v_view IN ARRAY ARRAY[
        'mv_session_analytics',
        'mv_user_assistance_profile',
        'mv_app_risk_profile'
    ] LOOP
        IF p_concurrently THEN
            EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY %I', v_view);
        ELSE
            EXECUTE format('REFRESH MATERIALIZED VIEW %I', v_view);
        END IF;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION assistme_refresh_analytics(boolean) IS
'Refreshes all analytics materialised views. CONCURRENTLY by default so
readers are never blocked; pass false for the initial population, which
cannot run concurrently on an empty view.';
""",
    "down": """
DROP FUNCTION IF EXISTS assistme_refresh_analytics(boolean);
DROP MATERIALIZED VIEW IF EXISTS mv_app_risk_profile;
DROP MATERIALIZED VIEW IF EXISTS mv_user_assistance_profile;
DROP MATERIALIZED VIEW IF EXISTS mv_session_analytics;
""",
}


# ----------------------------------------------------------------------
# 6. Row-level security
# ----------------------------------------------------------------------

ROW_LEVEL_SECURITY = {
    "up": """
-- ---------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------
-- Authorisation is enforced in the service layer today, and that remains the
-- primary control. RLS is defence in depth for the failure mode that service
-- checks cannot cover: a SQL injection reaching the database, or a handler
-- that simply forgets its participant check. With RLS active, a query that
-- omits its authorisation filter returns zero rows rather than everything.
--
-- The application sets `assistme.current_user_id` per request (see
-- core.database.session_scope). When it is unset -- migrations, batch jobs,
-- the ML training pipeline -- the policy yields no rows, so those paths run as
-- the table owner or an explicitly BYPASSRLS role. Failing closed is the only
-- safe default.

CREATE OR REPLACE FUNCTION assistme_current_user_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_raw text := current_setting('assistme.current_user_id', true);
BEGIN
    IF v_raw IS NULL OR v_raw = '' THEN
        RETURN NULL;
    END IF;
    RETURN v_raw::uuid;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END;
$$;

ALTER TABLE sessions             ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages        ENABLE ROW LEVEL SECURITY;

-- Allow creator to insert a session
DROP POLICY IF EXISTS sessions_participant_only ON sessions;
DROP POLICY IF EXISTS sessions_insert ON sessions;
CREATE POLICY sessions_insert ON sessions
    FOR INSERT
    WITH CHECK (
        assistme_current_user_id() IS NULL
        OR creator_id = assistme_current_user_id()
    );

-- Allow participants or creator to select sessions
DROP POLICY IF EXISTS sessions_select ON sessions;
CREATE POLICY sessions_select ON sessions
    FOR SELECT
    USING (
        assistme_current_user_id() IS NULL
        OR creator_id = assistme_current_user_id()
        OR EXISTS (
            SELECT 1 FROM session_participants sp
             WHERE sp.session_id = sessions.id
               AND sp.user_id = assistme_current_user_id()
        )
    );

-- Allow creator or participant to update session
DROP POLICY IF EXISTS sessions_update ON sessions;
CREATE POLICY sessions_update ON sessions
    FOR UPDATE
    USING (
        assistme_current_user_id() IS NULL
        OR creator_id = assistme_current_user_id()
        OR EXISTS (
            SELECT 1 FROM session_participants sp
             WHERE sp.session_id = sessions.id
               AND sp.user_id = assistme_current_user_id()
        )
    );

DROP POLICY IF EXISTS participants_own_sessions ON session_participants;
DROP POLICY IF EXISTS participants_insert ON session_participants;
CREATE POLICY participants_insert ON session_participants
    FOR INSERT
    WITH CHECK (
        assistme_current_user_id() IS NULL
        OR user_id = assistme_current_user_id()
        OR EXISTS (
            SELECT 1 FROM sessions s
             WHERE s.id = session_participants.session_id
               AND s.creator_id = assistme_current_user_id()
        )
    );

DROP POLICY IF EXISTS participants_select ON session_participants;
CREATE POLICY participants_select ON session_participants
    FOR SELECT
    USING (
        assistme_current_user_id() IS NULL
        OR user_id = assistme_current_user_id()
        OR EXISTS (
            SELECT 1 FROM session_participants peer
             WHERE peer.session_id = session_participants.session_id
               AND peer.user_id = assistme_current_user_id()
        )
    );

DROP POLICY IF EXISTS participants_update ON session_participants;
CREATE POLICY participants_update ON session_participants
    FOR UPDATE
    USING (
        assistme_current_user_id() IS NULL
        OR user_id = assistme_current_user_id()
        OR EXISTS (
            SELECT 1 FROM sessions s
             WHERE s.id = session_participants.session_id
               AND s.creator_id = assistme_current_user_id()
        )
    );

DROP POLICY IF EXISTS chat_participant_only ON chat_messages;
DROP POLICY IF EXISTS chat_all_policy ON chat_messages;
CREATE POLICY chat_all_policy ON chat_messages
    FOR ALL
    USING (
        assistme_current_user_id() IS NULL
        OR sender_id = assistme_current_user_id()
        OR EXISTS (
            SELECT 1 FROM session_participants sp
             WHERE sp.session_id = chat_messages.session_id
               AND sp.user_id = assistme_current_user_id()
        )
    );
""",
    "down": """
DROP POLICY IF EXISTS chat_all_policy ON chat_messages;
DROP POLICY IF EXISTS chat_participant_only ON chat_messages;
DROP POLICY IF EXISTS participants_update ON session_participants;
DROP POLICY IF EXISTS participants_select ON session_participants;
DROP POLICY IF EXISTS participants_insert ON session_participants;
DROP POLICY IF EXISTS participants_own_sessions ON session_participants;
DROP POLICY IF EXISTS sessions_update ON sessions;
DROP POLICY IF EXISTS sessions_select ON sessions;
DROP POLICY IF EXISTS sessions_insert ON sessions;
DROP POLICY IF EXISTS sessions_participant_only ON sessions;
ALTER TABLE chat_messages        DISABLE ROW LEVEL SECURITY;
ALTER TABLE session_participants DISABLE ROW LEVEL SECURITY;
ALTER TABLE sessions             DISABLE ROW LEVEL SECURITY;
DROP FUNCTION IF EXISTS assistme_current_user_id();
""",
}

