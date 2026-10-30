"""Abandoned-session expiry and multi-worker reconnect safety (bug B8)."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.session_service import SessionService
from models.session import Session
from models.session_participant import SessionParticipant
from tests.test_sessions import _create_session, _register

IDLE = timedelta(minutes=5)


async def _active_session(client: AsyncClient) -> tuple[dict, dict, dict]:
    helper = await _register(client)
    helpee = await _register(client)
    session = await _create_session(client, helper["headers"])
    joined = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    assert joined.status_code == 200
    return helper, helpee, session


async def _age_session(db: AsyncSession, session_id: str, by: timedelta) -> None:
    past = datetime.now(timezone.utc) - by
    await db.execute(update(Session).where(Session.id == session_id).values(created_at=past))
    await db.execute(
        update(SessionParticipant)
        .where(SessionParticipant.session_id == session_id)
        .values(joined_at=past - timedelta(seconds=1), last_seen_at=past)
    )
    await db.commit()


async def _status(db: AsyncSession, session_id: str) -> str:
    db.expire_all()
    return (
        await db.execute(select(Session.status).where(Session.id == session_id))
    ).scalar_one()


@pytest.mark.asyncio(loop_scope="session")
async def test_session_nobody_is_connected_to_is_ended(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, session = await _active_session(client)
    await _age_session(db_session, session["id"], timedelta(minutes=20))

    ended = await SessionService.expire_abandoned_sessions(db_session, IDLE)

    assert session["id"] in ended
    assert await _status(db_session, session["id"]) == "ended"


@pytest.mark.asyncio(loop_scope="session")
async def test_live_socket_stamp_keeps_session_open(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    helper, _, session = await _active_session(client)
    await _age_session(db_session, session["id"], timedelta(minutes=20))
    # One worker still holds the helper's socket and stamps it.
    await SessionService.touch_participants(
        [(session["id"], helper["user"]["id"])], db_session
    )

    ended = await SessionService.expire_abandoned_sessions(db_session, IDLE)

    assert session["id"] not in ended
    assert await _status(db_session, session["id"]) == "active"


@pytest.mark.asyncio(loop_scope="session")
async def test_recent_session_is_not_ended(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, session = await _active_session(client)
    ended = await SessionService.expire_abandoned_sessions(db_session, IDLE)
    assert session["id"] not in ended


@pytest.mark.asyncio(loop_scope="session")
async def test_grace_timer_spares_a_reconnected_participant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    helper, _, session = await _active_session(client)
    user_id = helper["user"]["id"]
    # Socket dropped on worker A, then the phone reconnected through worker B.
    await SessionService.mark_disconnected(session["id"], user_id, db_session)
    await db_session.execute(
        update(SessionParticipant)
        .where(
            SessionParticipant.session_id == session["id"],
            SessionParticipant.user_id == user_id,
        )
        .values(status="connected")
    )
    await db_session.commit()

    result = await SessionService.terminate_on_disconnect(session["id"], user_id, db_session)

    assert result is None
    assert await _status(db_session, session["id"]) == "active"


@pytest.mark.asyncio(loop_scope="session")
async def test_grace_timer_ends_call_when_participant_stays_away(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    helper, _, session = await _active_session(client)
    user_id = helper["user"]["id"]
    await SessionService.mark_disconnected(session["id"], user_id, db_session)

    result = await SessionService.terminate_on_disconnect(session["id"], user_id, db_session)

    assert result is not None
    assert await _status(db_session, session["id"]) == "ended"
