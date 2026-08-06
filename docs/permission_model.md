# Permission Model — AssistMe

## Overview

AssistMe uses a role-based access control (RBAC) model combined with resource ownership checks. In Phase 1, there is a single role (`user`). Future phases will introduce additional roles as the platform evolves.

---

## Roles

| Role | Description | Introduced In |
|------|-------------|---------------|
| `user` | Standard authenticated user | Phase 1 |
| `admin` | Platform administrator | Future |
| `helper` | Active assistance provider in a session | Phase 2 |
| `helpee` | User receiving assistance in a session | Phase 2 |

---

## Permission Matrix — Phase 1

### Public Endpoints (No Authentication Required)

| Endpoint | Method | Access |
|----------|--------|--------|
| `/health` | GET | Public |
| `/auth/register` | POST | Public |
| `/auth/login` | POST | Public |

### Authenticated Endpoints

| Endpoint | Method | Required Role | Ownership Check |
|----------|--------|---------------|-----------------|
| `/auth/refresh` | POST | `user` | Token must belong to user |
| `/auth/logout` | POST | `user` | Token must belong to user |
| `/users/me` | GET | `user` | Self only |
| `/users/me` | PATCH | `user` | Self only |
| `/contacts/` | POST | `user` | — |
| `/contacts/` | GET | `user` | Returns only user's contacts |
| `/contacts/{id}` | PATCH | `user` | Must be the contact recipient |
| `/contacts/{id}` | DELETE | `user` | Must be participant in the contact |

---

## Authentication Flow

```
Client                          Server
  |                               |
  |-- POST /auth/login ---------->|
  |                               |-- Verify credentials
  |                               |-- Generate JWT (access_token)
  |                               |-- Generate refresh_token
  |<-- { access_token, refresh }--|
  |                               |
  |-- GET /users/me ------------->|
  |   Authorization: Bearer JWT   |-- Decode JWT
  |                               |-- Extract user_id from `sub`
  |                               |-- Query user by ID
  |<-- { user profile } ---------|
  |                               |
  |-- POST /auth/refresh -------->|
  |   { refresh_token }          |-- Validate refresh token
  |                               |-- Generate new access_token
  |<-- { new access_token } -----|
```

---

## Ownership Rules

1. **User profile**: Users can only read/modify their own profile (`/users/me`).
2. **Contact requests**: 
   - Any user can send a request to another user.
   - Only the **recipient** can accept/reject a request.
   - Either party can delete (remove) the contact.
3. **Refresh tokens**: A user can only refresh/revoke their own tokens.

---

## Future Permission Extensions

- **Phase 2**: Session roles (helper/helpee) with session-scoped permissions
- **Phase 7**: Accessibility control permissions (device-level)
- **Phase 9**: Policy engine will dynamically compute permissions based on context
- **Phase 10**: Audit log access (admin-only)
