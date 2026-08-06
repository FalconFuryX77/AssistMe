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
- Inbound: `heartbeat`, `leave`, `signal_offer`, `signal_answer`, `signal_ice_candidate`, `screen_share_start`, `screen_share_stop`, `screen_share_orientation`, `screen_share_security_event`
- Outbound: `user_joined`, `user_left`, `user_disconnected`, `user_reconnected`, `session_ended`, `heartbeat_ack`, `signal_offer`, `signal_answer`, `signal_ice_candidate`, `screen_share_start`, `screen_share_stop`, `screen_share_orientation`, `screen_share_security_event`

---

## Screen Sharing (Phase 4)

### `POST /sessions/{session_id}/screen-share/start`

Start screen sharing stream (Android MediaProjection / iOS ReplayKit).

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "platform": "android",
  "orientation": "portrait",
  "width": 1080,
  "height": 1920,
  "fps": 30
}
```

**Response:** `200 OK`
```json
{
  "is_screen_sharing": true,
  "platform": "android",
  "is_flag_secure_active": false,
  "screen_orientation": "portrait",
  "participant_user_id": "uuid"
}
```

---

### `POST /sessions/{session_id}/screen-share/stop`

Stop screen sharing stream.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "reason": "user_stopped"
}
```

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/screen-share/orientation`

Update screen share orientation.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "orientation": "landscape"
}
```

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/screen-share/security-event`

Report FLAG_SECURE, protected app, or backgrounding events.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "event_type": "flag_secure_enabled",
  "detail": "Sensitive window active"
}
```

**Response:** `200 OK`

---

### `GET /sessions/{session_id}/screen-share/status`

Get current screen share status for a session.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

## Voice Communication (Phase 5)

### `POST /sessions/{session_id}/audio/start`

Start audio call stream participation.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "is_muted": false,
  "audio_route": "speaker"
}
```

**Response:** `200 OK`
```json
{
  "is_in_audio_call": true,
  "is_audio_muted": false,
  "audio_route": "speaker",
  "audio_quality": "high",
  "participant_user_id": "uuid"
}
```

---

### `POST /sessions/{session_id}/audio/stop`

Stop audio call stream participation.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/audio/mute`

Toggle microphone mute state.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "is_muted": true
}
```

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/audio/route`

Change audio output routing (speaker, earpiece, bluetooth, headset).

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "audio_route": "bluetooth"
}
```

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/audio/degradation`

Report network degradation and adjust audio quality level.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "quality_level": "low",
  "packet_loss": 15.2
}
```

**Response:** `200 OK`

---

### `GET /sessions/{session_id}/audio/status`

Get active voice communication status for session participant.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

## Remote Control Protocol (Phase 6)

### `POST /sessions/{session_id}/remote-control/grant`

Grant remote control permission to the session helper.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "platform": "android_accessibility"
}
```

**Response:** `200 OK`
```json
{
  "session_id": "uuid",
  "remote_control_granted": true,
  "remote_control_granted_at": "2026-08-06T12:00:00Z",
  "remote_control_platform": "android_accessibility"
}
```

---

### `POST /sessions/{session_id}/remote-control/revoke`

Instantly revoke remote control permission.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/remote-control/input`

Dispatch remote gesture or hardware key injection event (Tap, Drag, Long Press, Gestures, Key Events).

**Headers:** `Authorization: Bearer <access_token>`

**Request Body (Tap Example):**
```json
{
  "event_type": "tap",
  "x": 540.0,
  "y": 960.0,
  "normalized_x": 0.5,
  "normalized_y": 0.5
}
```

**Request Body (Drag Example):**
```json
{
  "event_type": "drag",
  "x": 100.0,
  "y": 800.0,
  "end_x": 100.0,
  "end_y": 200.0,
  "duration_ms": 400
}
```

**Request Body (Key Event Example):**
```json
{
  "event_type": "key_event",
  "key_code": "back"
}
```

**Response:** `200 OK`

---

### `GET /sessions/{session_id}/remote-control/status`

Get remote control permission status.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

## Adaptive Streaming & Optimization (Phase 7)

### `POST /sessions/{session_id}/streaming/adapt`

Manually set video stream resolution, bitrate, or frame rate parameters.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "video_resolution": "1080p",
  "video_bitrate_kbps": 3000,
  "video_fps": 60
}
```

**Response:** `200 OK`
```json
{
  "video_resolution": "1080p",
  "video_bitrate_kbps": 3000,
  "video_fps": 60,
  "rtt_ms": 35.0,
  "packet_loss_percent": 0.5,
  "auto_adapted": false,
  "participant_user_id": "uuid"
}
```

---

### `POST /sessions/{session_id}/streaming/metrics`

Report client network constraint metrics (RTT, jitter, packet loss) and trigger automated video quality adaptation.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "rtt_ms": 150.0,
  "jitter_ms": 12.0,
  "packet_loss_percent": 3.0,
  "available_bandwidth_kbps": 2000
}
```

**Response:** `200 OK`

---

### `GET /sessions/{session_id}/streaming/config`

Get current WebRTC video streaming quality configuration for participant.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

## End-to-End Encryption (Phase 8)

### `POST /sessions/{session_id}/e2ee/keys/exchange`

Exchange E2EE identity keys, signed prekeys, and ephemeral ratchet keys for WebRTC Insertable Streams.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "identity_key": "pub_identity_key_abc123",
  "signed_prekey": "pub_signed_prekey_def456",
  "ephemeral_key": "pub_ephemeral_key_ghi789",
  "algorithm": "Signal_DoubleRatchet_AES256_GCM"
}
```

**Response:** `200 OK`
```json
{
  "session_id": "uuid",
  "e2ee_enabled": true,
  "key_exchange_complete": true,
  "fingerprint": "a1b2c3d4e5f6...",
  "is_mitm_verified": false
}
```

---

### `POST /sessions/{session_id}/e2ee/keys/rotate`

Rotate Double Ratchet ephemeral keys for forward secrecy.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "new_ephemeral_key": "new_ephemeral_key_999",
  "ratchet_counter": 1
}
```

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/e2ee/verify`

Verify SAS (Short Authentication String) / Safety Number fingerprint to detect and block MITM attacks.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "safety_number_fingerprint": "a1b2c3d4e5f6...",
  "is_verified_by_user": true
}
```

**Response:** `200 OK`

---

### `GET /sessions/{session_id}/e2ee/status`

Get active E2EE status, safety number fingerprint, and MITM verification state.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

## Session Recording & Audit Trails (Phase 9)

### `POST /sessions/{session_id}/recording/consent`

Update session recording consent state and scope.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "consent_granted": true,
  "recording_scope": "screen_and_audio"
}
```

**Response:** `200 OK`
```json
{
  "session_id": "uuid",
  "is_recording": false,
  "consent_granted": true,
  "recording_scope": "screen_and_audio",
  "recording_url": null,
  "file_size_bytes": null,
  "duration_seconds": null
}
```

---

### `POST /sessions/{session_id}/recording/start`

Initiate session recording stream (requires `consent_granted == true`).

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "storage_provider": "local_encrypted"
}
```

**Response:** `200 OK`

---

### `POST /sessions/{session_id}/recording/stop`

Stop active session recording and save storage metadata.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "file_url": "https://storage.assistme.internal/recordings/rec_123.mp4",
  "file_size_bytes": 15420000,
  "duration_seconds": 180
}
```

**Response:** `200 OK`

---

### `GET /sessions/{session_id}/recording/status`

Get recording status and metadata for session.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`

---

### `GET /sessions/{session_id}/audit-trail`

Retrieve structured privacy compliance audit logs for session.

**Headers:** `Authorization: Bearer <access_token>`

**Response:** `200 OK`
```json
{
  "session_id": "uuid",
  "total_events": 2,
  "events": [
    {
      "id": "uuid",
      "session_id": "uuid",
      "user_id": "uuid",
      "event_type": "recording_consent_updated",
      "detail": "Consent: true, Scope: screen_and_audio",
      "timestamp": "2026-08-06T12:00:00Z"
    }
  ]
}
```

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
