# Database Schema — AssistMe

## Overview

This document defines the PostgreSQL database schema for the AssistMe platform.
For local development, SQLite is used via SQLAlchemy's database-agnostic ORM layer.

---

## Tables

### `users`

Stores registered user accounts.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `UUID` | PK, default `gen_random_uuid()` | Unique user identifier |
| `email` | `VARCHAR(255)` | UNIQUE, NOT NULL | User's email address |
| `hashed_password` | `VARCHAR(255)` | NOT NULL | bcrypt-hashed password |
| `display_name` | `VARCHAR(100)` | NULL | Optional display name |
| `is_active` | `BOOLEAN` | NOT NULL, default `true` | Account active status |
| `created_at` | `TIMESTAMP` | NOT NULL, default `now()` | Account creation time |
| `updated_at` | `TIMESTAMP` | NOT NULL, default `now()` | Last update time |

**Indexes:**
- `ix_users_email` — unique index on `email`

---

### `refresh_tokens`

Stores JWT refresh tokens for session management.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `UUID` | PK, default `gen_random_uuid()` | Token record identifier |
| `token` | `VARCHAR(255)` | UNIQUE, NOT NULL | The refresh token string |
| `user_id` | `UUID` | FK → `users.id`, NOT NULL | Owner of the token |
| `expires_at` | `TIMESTAMP` | NOT NULL | Token expiration time |
| `revoked` | `BOOLEAN` | NOT NULL, default `false` | Whether token has been revoked |
| `created_at` | `TIMESTAMP` | NOT NULL, default `now()` | Token creation time |

**Indexes:**
- `ix_refresh_tokens_token` — unique index on `token`
- `ix_refresh_tokens_user_id` — index on `user_id`

---

### `trusted_contacts`

Stores trusted contact relationships between users (directional).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `UUID` | PK, default `gen_random_uuid()` | Relationship identifier |
| `user_id` | `UUID` | FK → `users.id`, NOT NULL | The user who initiated |
| `contact_user_id` | `UUID` | FK → `users.id`, NOT NULL | The contact being added |
| `status` | `VARCHAR(20)` | NOT NULL, default `'pending'` | `pending`, `accepted`, `rejected` |
| `created_at` | `TIMESTAMP` | NOT NULL, default `now()` | Request creation time |
| `updated_at` | `TIMESTAMP` | NOT NULL, default `now()` | Last status change |

**Constraints:**
- `UNIQUE(user_id, contact_user_id)` — prevent duplicate requests
- `CHECK(user_id != contact_user_id)` — prevent self-add

**Indexes:**
- `ix_trusted_contacts_user_id` — index on `user_id`
- `ix_trusted_contacts_contact_user_id` — index on `contact_user_id`

---

### `sessions`

Stores assistance sessions between users.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `UUID` | PK, default `gen_random_uuid()` | Session identifier |
| `creator_id` | `UUID` | FK → `users.id`, NOT NULL | User who created the session (helper) |
| `status` | `VARCHAR(20)` | NOT NULL, default `'waiting'` | `waiting`, `active`, `ended` |
| `title` | `VARCHAR(200)` | NULL | Optional session title |
| `session_code` | `VARCHAR(8)` | UNIQUE, NOT NULL | Short code for joining |
| `timeout_minutes` | `INTEGER` | NOT NULL, default `30` | Auto-expire timeout |
| `created_at` | `TIMESTAMP` | NOT NULL, default `now()` | Session creation time |
| `updated_at` | `TIMESTAMP` | NOT NULL, default `now()` | Last update time |
| `ended_at` | `TIMESTAMP` | NULL | When session was ended |

**Indexes:**
- `ix_sessions_creator_id` — index on `creator_id`
- `ix_sessions_status` — index on `status`
- `ix_sessions_session_code` — unique index on `session_code`

---

### `session_participants`

Tracks users participating in sessions with their roles and connection state.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `UUID` | PK, default `gen_random_uuid()` | Participant record ID |
| `session_id` | `UUID` | FK → `sessions.id`, NOT NULL | The session |
| `user_id` | `UUID` | FK → `users.id`, NOT NULL | The participant |
| `role` | `VARCHAR(20)` | NOT NULL | `helper` or `helpee` |
| `status` | `VARCHAR(20)` | NOT NULL, default `'connected'` | `connected`, `disconnected`, `left` |
| `joined_at` | `TIMESTAMP` | NOT NULL, default `now()` | When user joined |
| `left_at` | `TIMESTAMP` | NULL | When user left/disconnected |
| `last_seen_at` | `TIMESTAMP` | NOT NULL, default `now()` | Last heartbeat |

**Constraints:**
- `UNIQUE(session_id, user_id)` — one record per user per session

**Indexes:**
- `ix_session_participants_session_id` — index on `session_id`
- `ix_session_participants_user_id` — index on `user_id`

---

## Future Tables (Phase 10+)

These tables will be added in later phases:

- `audit_logs` — Phase 10 (Audit & Security)
- `consent_logs` — Phase 10
- `assistance_history` — Phase 11 (Intelligent Assistance)

---

## Migration Strategy

- **ORM:** SQLAlchemy 2.0 with async support
- **Migrations:** Alembic (to be configured in Phase 1)
- **Dev database:** SQLite (file-based, no external dependencies)
- **Prod database:** PostgreSQL (as specified in roadmap)
