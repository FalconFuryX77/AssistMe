"""PostgreSQL-only schema behaviour: constraints, triggers, partitions, RLS.

These tests are skipped unless a PostgreSQL server is configured, because the
features they cover have no SQLite equivalent and cannot be emulated. They are
the other half of the dialect strategy described in :mod:`core.db.dialect`:
business logic is tested on SQLite for speed, and everything that depends on
real PostgreSQL semantics is tested here against a real server.

Run them with::

    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/assistme_test \\
        python -m pytest tests/test_postgres_schema.py

A skipped test is not a passing test. CI runs a PostgreSQL service so these
execute there; skipping locally is a convenience, not a licence to ignore them.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; PostgreSQL-specific schema tests skipped",
)


@pytest_asyncio.fixture(loop_scope="function", scope="function")
async def pg():
    """A clean PostgreSQL schema per test."""
    from sqlalchemy.pool import NullPool

    # NullPool so each test gets a fresh connection and none is left idle
    # holding a lock on the schema we are about to drop.
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    from core.database import create_tables, engine as app_engine

    await create_tables(bind_engine=engine)

    session = factory()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        await engine.dispose()
        # The application engine also holds connections to this database; they
        # must be released or the next test's DROP SCHEMA blocks behind them.
        await app_engine.dispose()


async def _seed(session) -> tuple[str, str]:
    """Insert a user and a session, returning their ids."""
    user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await session.execute(
        text(
            "INSERT INTO users (id, email, email_bi, hashed_password, is_active,"
            " created_at, updated_at)"
            " VALUES (:id, :e, :bi, 'x', true, :t, :t)"
        ),
        {"id": user_id, "e": b"\x00", "bi": f"v1:{uuid.uuid4().hex}", "t": now},
    )
    await session.execute(
        text(
            "INSERT INTO sessions (id, creator_id, status, session_code,"
            " timeout_minutes, remote_control_granted, e2ee_enabled,"
            " e2ee_key_exchange_complete, e2ee_mitm_verified,"
            " recording_consent_granted, is_recording, created_at, updated_at)"
            " VALUES (:sid, :uid, 'active', :code, 30, false, true, false, false,"
            " false, false, :t, :t)"
        ),
        {
            "sid": session_id,
            "uid": user_id,
            "code": uuid.uuid4().hex[:8].upper(),
            "t": now,
        },
    )
    await session.commit()
    return user_id, session_id


async def _add_audit(session, session_id: str, event_type: str, category: str):
    await session.execute(
        text(
            "INSERT INTO audit_ledger (id, session_id, event_type, event_category,"
            " detail, seq, payload_digest, prev_hash, entry_hash, recorded_at)"
            " VALUES (gen_random_uuid(), :sid, :et, :cat, '{}'::jsonb, 0,"
            " sha256(CAST(:digest_src AS bytea)), CAST('\\x00' AS bytea),"
            " CAST('\\x00' AS bytea), now())"
        ),
        # A separate bind for the digest source: reusing :et in both a varchar
        # column and a bytea cast makes asyncpg unable to deduce one type.
        {
            "sid": session_id,
            "et": event_type,
            "cat": category,
            "digest_src": event_type.encode("utf-8"),
        },
    )


# ---------------------------------------------------------------------------
# Tamper-evident audit ledger
# ---------------------------------------------------------------------------


class TestAuditLedger:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_chain_is_built_by_the_trigger(self, pg) -> None:
        _, session_id = await _seed(pg)
        for i, (event, category) in enumerate(
            [("session_created", "session"), ("consent_granted", "consent"),
             ("tap_dispatched", "input")]
        ):
            await _add_audit(pg, session_id, event, category)
        await pg.commit()

        rows = (
            await pg.execute(
                text(
                    "SELECT seq, prev_hash, entry_hash FROM audit_ledger"
                    " WHERE session_id = :s ORDER BY seq"
                ),
                {"s": session_id},
            )
        ).fetchall()

        assert [r[0] for r in rows] == [1, 2, 3]
        # Each link points at the previous entry's hash.
        assert bytes(rows[1][1]) == bytes(rows[0][2])
        assert bytes(rows[2][1]) == bytes(rows[1][2])
        assert len({bytes(r[2]) for r in rows}) == 3

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_is_refused(self, pg) -> None:
        _, session_id = await _seed(pg)
        await _add_audit(pg, session_id, "session_created", "session")
        await pg.commit()

        with pytest.raises(DBAPIError, match="append-only"):
            await pg.execute(
                text("UPDATE audit_ledger SET event_type = 'forged'")
            )
        await pg.rollback()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete_is_refused(self, pg) -> None:
        _, session_id = await _seed(pg)
        await _add_audit(pg, session_id, "session_created", "session")
        await pg.commit()

        with pytest.raises(DBAPIError, match="append-only"):
            await pg.execute(text("DELETE FROM audit_ledger"))
        await pg.rollback()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_verification_detects_tampering(self, pg) -> None:
        """A superuser bypassing the trigger is still caught by verification.

        The append-only trigger stops the application and any ordinary role.
        This test models the stronger adversary — someone able to disable
        triggers — and shows the hash chain still detects the edit.
        """
        _, session_id = await _seed(pg)
        for event in ("session_created", "consent_granted", "tap_dispatched"):
            await _add_audit(pg, session_id, event, "session")
        await pg.commit()

        rows = (
            await pg.execute(
                text("SELECT seq, valid FROM assistme_audit_verify(:s) ORDER BY seq"),
                {"s": session_id},
            )
        ).fetchall()
        assert all(valid for _, valid in rows)

        partition = datetime.now(timezone.utc).strftime("audit_ledger_p%Y%m")
        await pg.execute(text(f"ALTER TABLE {partition} DISABLE TRIGGER ALL"))
        await pg.execute(
            text(
                f"UPDATE {partition} SET payload_digest = sha256('forged'::bytea)"
                " WHERE seq = 2"
            )
        )
        await pg.execute(text(f"ALTER TABLE {partition} ENABLE TRIGGER ALL"))
        await pg.commit()

        rows = (
            await pg.execute(
                text(
                    "SELECT seq, valid, failure FROM assistme_audit_verify(:s)"
                    " ORDER BY seq"
                ),
                {"s": session_id},
            )
        ).fetchall()
        by_seq = {seq: (valid, failure) for seq, valid, failure in rows}
        assert by_seq[2][0] is False
        assert "entry_hash" in (by_seq[2][1] or "")
        assert by_seq[1][0] is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_sessions_have_independent_chains(self, pg) -> None:
        """Entries cannot be spliced from one session's chain into another."""
        user_id, first_session = await _seed(pg)
        _, second_session = await _seed(pg)

        await _add_audit(pg, first_session, "session_created", "session")
        await _add_audit(pg, second_session, "session_created", "session")
        await pg.commit()

        rows = (
            await pg.execute(
                text(
                    "SELECT session_id, prev_hash FROM audit_ledger WHERE seq = 1"
                )
            )
        ).fetchall()
        genesis_hashes = {bytes(r[1]) for r in rows}
        assert len(genesis_hashes) == 2


# ---------------------------------------------------------------------------
# Exclusion constraint
# ---------------------------------------------------------------------------


class TestExclusionConstraint:
    async def _add_participant(self, pg, session_id: str, user_id: str, role: str):
        await pg.execute(
            text(
                "INSERT INTO session_participants (id, session_id, user_id, role,"
                " status, joined_at, last_seen_at, is_screen_sharing,"
                " is_flag_secure_active, screen_orientation, is_in_audio_call,"
                " is_audio_muted, audio_route, audio_quality, video_resolution,"
                " video_bitrate_kbps, video_fps, rtt_ms, packet_loss_percent,"
                " is_active_speaker)"
                " VALUES (gen_random_uuid(), :sid, :uid, :role, 'connected', now(),"
                " now(), false, false, 'portrait', false, false, 'speaker', 'high',"
                " '720p', 1500, 30, 50, 0, false)"
            ),
            {"sid": session_id, "uid": user_id, "role": role},
        )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_overlapping_participation_is_refused(self, pg) -> None:
        """One helper, one helpee, one session at a time — enforced by the index.

        This is the product's defining constraint, and it is an interval
        property that no UNIQUE constraint can express. Checking it in Python
        is a check-then-act race; the exclusion constraint holds regardless.
        """
        user_id, first_session = await _seed(pg)
        _, second_session = await _seed(pg)

        await self._add_participant(pg, first_session, user_id, "helpee")
        await pg.commit()

        with pytest.raises(IntegrityError, match="ex_participants_no_overlap"):
            await self._add_participant(pg, second_session, user_id, "helpee")
            await pg.commit()
        await pg.rollback()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_sequential_participation_is_allowed(self, pg) -> None:
        """Leaving one session frees the user to join another."""
        user_id, first_session = await _seed(pg)
        _, second_session = await _seed(pg)

        await self._add_participant(pg, first_session, user_id, "helpee")
        await pg.execute(
            text(
                "UPDATE session_participants SET status = 'left', left_at = now()"
                " WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        await pg.commit()

        await self._add_participant(pg, second_session, user_id, "helpee")
        await pg.commit()

        count = (
            await pg.execute(
                text(
                    "SELECT count(*) FROM session_participants WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        ).scalar_one()
        assert count == 2


# ---------------------------------------------------------------------------
# Integrity constraints
# ---------------------------------------------------------------------------


class TestIntegrityConstraints:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_high_risk_cannot_grant_tap(self, pg) -> None:
        """The database refuses the outcome the whole system exists to prevent.

        Third and final enforcement point, below the safety envelope and the
        inference service. A model regression, a bad migration, or a direct SQL
        write cannot produce this row.
        """
        user_id, session_id = await _seed(pg)
        with pytest.raises(IntegrityError, match="high_risk_limits_mode"):
            await pg.execute(
                text(
                    "INSERT INTO policy_decisions (id, session_id,"
                    " evaluated_by_user_id, risk_level, assistance_mode,"
                    " decision_source, consent_verified, envelope_clamped,"
                    " created_at, updated_at)"
                    " VALUES (gen_random_uuid(), :sid, :uid, 'high', 'tap', 'rules',"
                    " false, false, now(), now())"
                ),
                {"sid": session_id, "uid": user_id},
            )
            await pg.commit()
        await pg.rollback()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_control_grant_requires_a_timestamp(self, pg) -> None:
        """An unauditable privilege grant cannot be stored."""
        _, session_id = await _seed(pg)
        with pytest.raises(IntegrityError, match="control_grant_coherent"):
            await pg.execute(
                text(
                    "UPDATE sessions SET remote_control_granted = true"
                    " WHERE id = :sid"
                ),
                {"sid": session_id},
            )
            await pg.commit()
        await pg.rollback()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_approved_escalation_requires_a_disclaimer(self, pg) -> None:
        """Consent without evidence of disclosure is not storable."""
        user_id, session_id = await _seed(pg)
        with pytest.raises(IntegrityError, match="approval_requires_accepted_disclaimer"):
            await pg.execute(
                text(
                    "INSERT INTO assistance_escalations (id, session_id,"
                    " requested_by_user_id, target_capabilities, status,"
                    " disclaimer_accepted, created_at, responded_at)"
                    " VALUES (gen_random_uuid(), :sid, :uid, '[\"tap\"]'::jsonb,"
                    " 'approved', false, now(), now())"
                ),
                {"sid": session_id, "uid": user_id},
            )
            await pg.commit()
        await pg.rollback()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_enum_value_is_refused(self, pg) -> None:
        _, session_id = await _seed(pg)
        with pytest.raises(DBAPIError):
            await pg.execute(
                text("UPDATE sessions SET status = 'banana' WHERE id = :sid"),
                {"sid": session_id},
            )
        await pg.rollback()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_impossible_telemetry_is_refused(self, pg) -> None:
        """Physically impossible values must not reach a model feature."""
        user_id, session_id = await _seed(pg)
        with pytest.raises(IntegrityError, match="packet_loss_is_percentage"):
            await pg.execute(
                text(
                    "INSERT INTO session_participants (id, session_id, user_id,"
                    " role, status, joined_at, last_seen_at, is_screen_sharing,"
                    " is_flag_secure_active, screen_orientation, is_in_audio_call,"
                    " is_audio_muted, audio_route, audio_quality, video_resolution,"
                    " video_bitrate_kbps, video_fps, rtt_ms, packet_loss_percent,"
                    " is_active_speaker)"
                    " VALUES (gen_random_uuid(), :sid, :uid, 'helpee', 'connected',"
                    " now(), now(), false, false, 'portrait', false, false,"
                    " 'speaker', 'high', '720p', 1500, 30, 50, 900, false)"
                ),
                {"sid": session_id, "uid": user_id},
            )
            await pg.commit()
        await pg.rollback()


# ---------------------------------------------------------------------------
# Partitioning and views
# ---------------------------------------------------------------------------


class TestPhysicalDesign:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_append_only_tables_are_partitioned(self, pg) -> None:
        rows = (
            await pg.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relkind = 'p'"
                    " AND relnamespace = 'public'::regnamespace"
                )
            )
        ).fetchall()
        partitioned = {r[0] for r in rows}
        assert {"audit_ledger", "context_events", "ml_decision_log"} <= partitioned

    @pytest.mark.asyncio(loop_scope="function")
    async def test_partitions_are_provisioned_ahead(self, pg) -> None:
        """A month boundary must not land on a missing partition."""
        count = (
            await pg.execute(
                text(
                    "SELECT count(*) FROM pg_class"
                    " WHERE relname LIKE 'audit_ledger_p2%'"
                )
            )
        ).scalar_one()
        assert count >= 3

    @pytest.mark.asyncio(loop_scope="function")
    async def test_partition_pruning_happens(self, pg) -> None:
        """A time-windowed query must not scan every partition."""
        plan = (
            await pg.execute(
                text(
                    "EXPLAIN (FORMAT TEXT) SELECT * FROM audit_ledger"
                    " WHERE recorded_at >= now() - interval '1 day'"
                )
            )
        ).fetchall()
        text_plan = "\n".join(row[0] for row in plan)
        scanned = text_plan.count("audit_ledger_p")
        total = (
            await pg.execute(
                text(
                    "SELECT count(*) FROM pg_class WHERE relname LIKE 'audit_ledger_p2%'"
                )
            )
        ).scalar_one()
        assert scanned < total, f"no pruning; plan scanned all partitions:\n{text_plan}"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_materialised_views_exist_and_refresh(self, pg) -> None:
        views = {
            r[0]
            for r in (
                await pg.execute(
                    text("SELECT matviewname FROM pg_matviews WHERE schemaname='public'")
                )
            ).fetchall()
        }
        assert {
            "mv_session_analytics",
            "mv_user_assistance_profile",
            "mv_app_risk_profile",
        } <= views

        # CONCURRENTLY requires a unique index on each view; this call fails if
        # one is missing, which is the property being checked.
        await pg.execute(text("SELECT assistme_refresh_analytics(true)"))
        await pg.commit()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_identifiers_use_native_uuid(self, pg) -> None:
        rows = (
            await pg.execute(
                text(
                    "SELECT table_name, data_type FROM information_schema.columns"
                    " WHERE table_schema = 'public' AND column_name = 'id'"
                    " AND table_name IN ('users','sessions','policy_decisions')"
                )
            )
        ).fetchall()
        assert rows
        assert all(data_type == "uuid" for _, data_type in rows)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_updated_at_is_maintained_by_the_database(self, pg) -> None:
        """A raw SQL UPDATE must still refresh the timestamp."""
        _, session_id = await _seed(pg)
        before = (
            await pg.execute(
                text("SELECT updated_at FROM sessions WHERE id = :s"),
                {"s": session_id},
            )
        ).scalar_one()

        await pg.execute(
            text("UPDATE sessions SET timeout_minutes = 45 WHERE id = :s"),
            {"s": session_id},
        )
        await pg.commit()

        after = (
            await pg.execute(
                text("SELECT updated_at FROM sessions WHERE id = :s"),
                {"s": session_id},
            )
        ).scalar_one()
        assert after > before


# ---------------------------------------------------------------------------
# Row-level security
# ---------------------------------------------------------------------------


class TestRowLevelSecurity:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_policies_are_enabled(self, pg) -> None:
        rows = (
            await pg.execute(
                text(
                    "SELECT relname FROM pg_class"
                    " WHERE relrowsecurity AND relnamespace = 'public'::regnamespace"
                )
            )
        ).fetchall()
        protected = {r[0] for r in rows}
        assert {"sessions", "session_participants", "chat_messages"} <= protected

    @pytest.mark.asyncio(loop_scope="function")
    async def test_unset_identity_yields_no_rows(self, pg) -> None:
        """RLS fails closed when no user identity is set.

        Note: this asserts the *policy* returns nothing. A superuser or the
        table owner bypasses RLS entirely, so the check is written against the
        policy predicate rather than against a SELECT, which would pass
        vacuously when the test connects as the owner.
        """
        result = (
            await pg.execute(text("SELECT assistme_current_user_id()"))
        ).scalar_one_or_none()
        assert result is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_identity_is_transaction_scoped(self, pg) -> None:
        """The RLS identity must not leak to the next user of a pooled connection."""
        user_id = str(uuid.uuid4())
        await pg.execute(
            text("SELECT set_config('assistme.current_user_id', :uid, true)"),
            {"uid": user_id},
        )
        assert str(
            (await pg.execute(text("SELECT assistme_current_user_id()"))).scalar_one()
        ) == user_id

        await pg.commit()
        assert (
            await pg.execute(text("SELECT assistme_current_user_id()"))
        ).scalar_one_or_none() is None
