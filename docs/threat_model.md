# Threat Model — AssistMe (Phase 1: Authentication)

## Scope

This threat model covers the authentication, user management, and trusted contacts features implemented in Phase 1.

---

## Assets

| Asset | Sensitivity | Description |
|-------|------------|-------------|
| User credentials | **Critical** | Email + password combinations |
| JWT access tokens | **High** | Bearer tokens for API access |
| Refresh tokens | **High** | Long-lived tokens for session continuity |
| User PII | **Medium** | Email addresses, display names |
| Contact relationships | **Medium** | Social graph of trusted contacts |

---

## Threat Categories (STRIDE)

### 1. Spoofing — Identity Attacks

| Threat | Risk | Mitigation |
|--------|------|------------|
| Credential stuffing | High | Rate limiting on login endpoint, account lockout after N failures |
| Brute force password | High | bcrypt with high cost factor (12 rounds), minimum password complexity |
| Token theft (XSS) | High | Short-lived access tokens (30 min), httpOnly cookies for web |
| Session hijacking | Medium | Refresh token rotation, bind tokens to device fingerprint (future) |

### 2. Tampering — Data Modification

| Threat | Risk | Mitigation |
|--------|------|------------|
| JWT modification | High | HMAC-SHA256 signing with server-side secret key |
| SQL injection | High | SQLAlchemy ORM (parameterized queries), Pydantic validation |
| Parameter tampering | Medium | Pydantic schema validation on all inputs |

### 3. Repudiation — Deniability

| Threat | Risk | Mitigation |
|--------|------|------------|
| Denied actions | Low | Audit logging (Phase 10), timestamps on all records |

### 4. Information Disclosure

| Threat | Risk | Mitigation |
|--------|------|------------|
| Password exposure in logs | High | Never log passwords, hash before storage |
| User enumeration via registration | Medium | Generic error messages ("Invalid email or password") |
| Token leakage in URLs | Medium | Use POST for token operations, never pass tokens in query strings |
| Error stack traces | Low | Disable debug mode in production, custom error handlers |

### 5. Denial of Service

| Threat | Risk | Mitigation |
|--------|------|------------|
| Registration spam | Medium | Rate limiting on registration endpoint |
| Token refresh flooding | Medium | Rate limiting, one active refresh token per session |
| Large payload attacks | Low | Request size limits via FastAPI/uvicorn |

### 6. Elevation of Privilege

| Threat | Risk | Mitigation |
|--------|------|------------|
| Accessing other users' data | High | All queries scoped to authenticated user's ID |
| Modifying others' contact requests | Medium | Ownership check on all contact operations |
| Accessing admin functions | Low | No admin functions in Phase 1; role-based access in future |

---

## Security Controls Summary

| Control | Implementation |
|---------|---------------|
| Password hashing | bcrypt via passlib, 12 rounds |
| Token signing | HMAC-SHA256 via python-jose |
| Input validation | Pydantic models on all endpoints |
| SQL injection prevention | SQLAlchemy ORM (no raw queries) |
| CORS | Restrict origins in production |
| Rate limiting | To be added (SlowAPI or custom middleware) |
| HTTPS | Enforced at deployment level (Phase 17) |

---

## Risk Acceptance

The following risks are **accepted for Phase 1** and will be addressed in later phases:

- **Rate limiting**: Full implementation deferred to Phase 14 (Security Testing)
- **Device binding**: Token-to-device binding deferred to Phase 9 (Policy Engine)
- **Account lockout**: Deferred to Phase 14
- **CORS configuration**: Deferred to Phase 12 (Frontend) / Phase 17 (Deployment)
