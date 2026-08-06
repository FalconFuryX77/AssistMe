# Project Progress Log

## Purpose

This document is the shared handoff file for the AssistMe project. It should be updated after each meaningful change so the other contributor can continue from the latest state.

---

## Current Status: Phase 1 COMPLETE ✅

**Last updated:** 2026-08-06T16:41Z
**Last contributor:** Agent Session (via Antigravity)
**All tests passing:** 33/33

---

## Completed Phases

### Phase 0 — Architecture & Planning ✅

**Commit:** `59b0bdf` — "Phase 0: Complete architecture docs, DB schema, API spec, threat model, permission model"

Completed:
- `docs/database_schema.md` — Full schema for `users`, `refresh_tokens`, `trusted_contacts`
- `docs/api_specification.md` — REST API contracts for all Phase 1 endpoints
- `docs/threat_model.md` — STRIDE-based security analysis
- `docs/permission_model.md` — RBAC roles, permission matrix, ownership rules
- `docs/ARCHITECTURE_NOTES.md` — Complete folder structure, layer responsibilities
- Deleted `backend/main.py` (was dead code — duplicate of health endpoint)

### Phase 1 — Authentication & Trusted Contacts ✅

**Commit:** `901b0dc` — "Phase 1: Full authentication, JWT, trusted contacts, user management — 33 tests passing"

#### What was built:

**Core Infrastructure (`backend/core/`):**
- `config.py` — Environment-based settings (SECRET_KEY, DATABASE_URL, JWT expiry)
- `security.py` — bcrypt password hashing (direct, not passlib), JWT creation/verification via python-jose, refresh token generation
- `database.py` — Async SQLAlchemy engine + session factory, SQLite for dev

**Database Models (`backend/models/`):**
- `user.py` — User: UUID PK, email (unique), hashed_password, display_name, is_active, timestamps
- `refresh_token.py` — RefreshToken: FK→users, expiration, revocation flag
- `trusted_contact.py` — TrustedContact: FK→users (both sides), status, unique constraint, self-add check

**Auth API (`backend/api/routers/auth/auth.py`):**
- `POST /auth/register` — 201, duplicate email check, password validation (8+ chars, uppercase, digit)
- `POST /auth/login` — Credential verification with bcrypt
- `POST /auth/refresh` — New access token from valid refresh token
- `POST /auth/logout` — Revoke refresh token

**Contacts API (`backend/api/routers/contacts.py`):**
- `POST /contacts/` — Send request by email, checks: self-add, duplicate, user exists
- `GET /contacts/` — List with optional `?status=` filter, enriched with contact details
- `PATCH /contacts/{id}` — Accept/reject (recipient only)
- `DELETE /contacts/{id}` — Remove (either party)

**Users API (`backend/api/routers/users.py`):**
- `GET /users/me` — Get authenticated user's profile
- `PATCH /users/me` — Update display_name

**Auth Middleware (`backend/api/dependencies.py`):**
- `get_current_user` — JWT → user lookup dependency via HTTPBearer

**Test Suite (33 tests):**
- `test_auth.py` — 15 tests: register (valid, duplicate, invalid email, 3 weak password cases), login (success, wrong pass, nonexistent), token refresh (valid, invalid), logout with revocation, security (invalid JWT, missing header, SQL injection)
- `test_contacts.py` — 13 tests: create (success, self-add, duplicate, nonexistent), list (all, filtered), accept, reject, wrong user, invalid status, delete, not found, auth required
- `test_users.py` — 4 tests: get profile, update display name, unauthorized access (GET, PATCH)
- `test_health.py` — 1 test: health check

#### Key technical decisions:
- **bcrypt direct** (not passlib): passlib 1.7.4 is incompatible with bcrypt 5.x on Python 3.13
- **SQLite for dev**: No need for PostgreSQL during development. SQLAlchemy makes the switch seamless.
- **In-memory SQLite for tests**: Each test session gets a fresh database
- **Async throughout**: All endpoints, services, and DB operations are async

#### Dependencies added:
```
sqlalchemy[asyncio]==2.0.35
aiosqlite==0.20.0
python-jose[cryptography]==3.3.0
bcrypt==5.0.0
python-dotenv==1.0.1
pytest-asyncio==0.24.0
```

---

## What's Next: Phase 2 — Session Management

Per the roadmap, the next phase implements:
- Session creation (helper initiates, helpee joins)
- Join/leave session
- Session recovery (reconnection after network loss)
- Timeouts (idle session cleanup)
- Session lifecycle management

### Recommended approach:
1. Create `models/session.py` and `models/session_participant.py`
2. Add session schemas, service, and router
3. Add WebSocket support for real-time session state
4. Tests: lost network, duplicate joins, expired sessions, concurrent requests

### Files that will need changes:
- `docs/database_schema.md` — Add `sessions` and `session_participants` tables
- `backend/models/` — New session models
- `backend/api/` — New session router, schemas, service
- `backend/app.py` — Include session router
- `backend/requirements.txt` — May need additional WebSocket deps

---

## Architecture Quick Reference

```
backend/
├── app.py                        # FastAPI entry point (lifespan creates tables)
├── core/
│   ├── config.py                 # Settings (env-based)
│   ├── database.py               # SQLAlchemy async engine
│   └── security.py               # bcrypt + JWT
├── models/                       # ORM models
│   ├── user.py
│   ├── refresh_token.py
│   └── trusted_contact.py
├── api/
│   ├── dependencies.py           # get_current_user, get_db
│   ├── routers/                  # HTTP handlers
│   ├── schemas/                  # Pydantic models
│   └── services/                 # Business logic
└── tests/                        # Pytest async test suite
    └── conftest.py               # Shared fixtures
```

## How to run

```bash
# Install dependencies
pip install -r backend/requirements.txt

# Run server (from backend/)
uvicorn app:app --reload

# Run tests (from backend/)
python -m pytest tests/ -v
```

---

## Notes for the next contributor

- Keep this file updated after each milestone.
- Record decisions, blockers, and completed work here.
- Prefer small, reviewable commits.
- Run `python -m pytest tests/ -v` before pushing — all tests must pass.
- The golden rule: **no phase begins until the current phase is fully validated.**
