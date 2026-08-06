# API Specification — AssistMe (Phase 1)

## Base URL

```
http://localhost:8000
```

## Common Response Format

### Success Response
```json
{
  "field": "value"
}
```

### Error Response
```json
{
  "detail": "Error description"
}
```

### Validation Error (422)
```json
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Health

### `GET /health`

Health check endpoint.

**Response:** `200 OK`
```json
{
  "status": "ok"
}
```

---

## Authentication

### `POST /auth/register`

Register a new user account.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "SecureP@ss1",
  "display_name": "John Doe"
}
```

**Password requirements:**
- Minimum 8 characters
- At least one uppercase letter
- At least one digit

**Response:** `201 Created`
```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "a1b2c3d4...",
  "token_type": "bearer"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| `400` | `"Email already registered"` |
| `422` | Validation errors (invalid email, weak password) |

---

### `POST /auth/login`

Authenticate with credentials.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "SecureP@ss1"
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "a1b2c3d4...",
  "token_type": "bearer"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| `401` | `"Invalid email or password"` |

---

### `POST /auth/refresh`

Refresh an expired access token.

**Request Body:**
```json
{
  "refresh_token": "a1b2c3d4..."
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| `401` | `"Invalid or expired refresh token"` |

---

### `POST /auth/logout`

Revoke the current refresh token.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "refresh_token": "a1b2c3d4..."
}
```

**Response:** `200 OK`
```json
{
  "detail": "Successfully logged out"
}
```

---

## Users

### `GET /users/me`

Get current user profile.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "John Doe",
  "is_active": true,
  "created_at": "2026-08-06T12:00:00Z"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| `401` | `"Not authenticated"` |

---

### `PATCH /users/me`

Update current user profile.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body (all fields optional):**
```json
{
  "display_name": "New Name"
}
```

**Response:** `200 OK` — Updated user object

---

## Trusted Contacts

### `POST /contacts/`

Send a contact request.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "contact_email": "friend@example.com"
}
```

**Response:** `201 Created`
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "contact_user_id": "uuid",
  "status": "pending",
  "created_at": "2026-08-06T12:00:00Z"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| `400` | `"Cannot add yourself as a contact"` |
| `400` | `"Contact request already exists"` |
| `404` | `"User not found"` |

---

### `GET /contacts/`

List all contacts for the current user.

**Headers:** `Authorization: Bearer <access_token>`

**Query Parameters:**
- `status` (optional): Filter by `pending`, `accepted`, `rejected`

**Response:** `200 OK`
```json
[
  {
    "id": "uuid",
    "contact_email": "friend@example.com",
    "contact_display_name": "Friend",
    "status": "accepted",
    "created_at": "2026-08-06T12:00:00Z"
  }
]
```

---

### `PATCH /contacts/{contact_id}`

Accept or reject a contact request.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "status": "accepted"
}
```

**Response:** `200 OK` — Updated contact object

**Errors:**
| Status | Detail |
|--------|--------|
| `403` | `"Not authorized to modify this contact request"` |
| `404` | `"Contact request not found"` |

---

### `DELETE /contacts/{contact_id}`

Remove a trusted contact.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `204 No Content`

---

## Sessions (Phase 2)

### `POST /sessions/`

Create a new assistance session.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "title": "Help with device settings",
  "timeout_minutes": 30
}
```

**Response:** `201 Created`
```json
{
  "id": "uuid",
  "creator_id": "uuid",
  "status": "waiting",
  "title": "Help with device settings",
  "session_code": "ABC123",
  "timeout_minutes": 30,
  "created_at": "2026-08-06T12:00:00Z",
  "updated_at": "2026-08-06T12:00:00Z",
  "ended_at": null,
  "participants": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "role": "helper",
      "status": "connected",
      "joined_at": "2026-08-06T12:00:00Z",
      "last_seen_at": "2026-08-06T12:00:00Z"
    }
  ]
}
```

---

### `POST /sessions/join`

Join a session using a session code.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "session_code": "ABC123"
}
```

**Response:** `200 OK` (returns updated Session object with new participant)

---

### `GET /sessions/`

List sessions for the current user.

**Headers:** `Authorization: Bearer <access_token>`

**Query Parameters:**
- `status` (optional): `waiting`, `active`, `ended`

**Response:** `200 OK`

---

### `GET /sessions/{session_id}`

Get details of a specific session.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/leave`

Leave a session voluntarily.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/end`

End a session (creator only).

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

### `POST /sessions/recover`

Recover a disconnected session.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "session_id": "uuid"
}
```

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/heartbeat`

Send a heartbeat signal for a session.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `204 No Content`

---

### WebSocket Endpoint: `ws://localhost:8000/ws/session/{session_id}?token=<JWT>`

Real-time session events stream.
- Inbound: `{"type": "heartbeat"}`, `{"type": "leave"}`
- Outbound: `user_joined`, `user_left`, `user_disconnected`, `user_reconnected`, `session_ended`, `heartbeat_ack`

---

## Authentication Headers

All authenticated endpoints require:
```
Authorization: Bearer <access_token>
```

Access tokens are JWT with the following claims:
- `sub` — user ID (UUID)
- `exp` — expiration timestamp
- `iat` — issued-at timestamp

Access token lifetime: **30 minutes**
Refresh token lifetime: **7 days**
