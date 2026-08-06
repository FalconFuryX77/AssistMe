# Architecture Notes — AssistMe

## Design Principles

- **Clean Architecture**: Routers → Schemas → Services → Models → Database
- **SOLID**: Each module has a single responsibility, dependencies are injected
- **API-first**: All features are exposed through RESTful endpoints
- **Testability**: Every layer is independently testable with dependency injection

---

## Project Structure

```
AssistMe/
├── backend/
│   ├── app.py                    # FastAPI application entry point
│   ├── requirements.txt          # Python dependencies
│   ├── core/                     # Cross-cutting concerns
│   │   ├── config.py             # Environment settings
│   │   ├── database.py           # SQLAlchemy engine & session
│   │   └── security.py           # JWT, password hashing
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── refresh_token.py
│   │   └── trusted_contact.py
│   ├── api/
│   │   ├── dependencies.py       # Shared FastAPI dependencies (auth, DB)
│   │   ├── routers/              # Route handlers (thin layer)
│   │   │   ├── health.py
│   │   │   ├── auth/
│   │   │   │   └── auth.py
│   │   │   ├── contacts.py
│   │   │   └── users.py
│   │   ├── schemas/              # Pydantic request/response models
│   │   │   ├── auth.py
│   │   │   ├── contacts.py
│   │   │   ├── health.py
│   │   │   └── users.py
│   │   └── services/             # Business logic
│   │       ├── auth_service.py
│   │       ├── contacts_service.py
│   │       └── health_service.py
│   └── tests/                    # Pytest test suites
│       ├── conftest.py           # Shared fixtures
│       ├── test_auth.py
│       ├── test_contacts.py
│       ├── test_health.py
│       └── test_users.py
├── mobile/                       # React Native client (Phase 12)
│   └── README.md
├── docs/                         # Project documentation
│   ├── PROJECT_PROGRESS.md       # Shared handoff document
│   ├── ARCHITECTURE_NOTES.md     # This file
│   ├── database_schema.md        # Database table definitions
│   ├── api_specification.md      # REST API contracts
│   ├── threat_model.md           # Security threat analysis
│   └── permission_model.md       # RBAC and access control
└── AssistMe_AI_Development_Roadmap.md  # Master roadmap
```

---

## Layer Responsibilities

### Routers (`api/routers/`)
- HTTP endpoint definitions
- Request parsing and response formatting
- Input validation via Pydantic schemas
- No business logic — delegates to services

### Schemas (`api/schemas/`)
- Pydantic models for request validation and response serialization
- Type safety and documentation for the API layer

### Services (`api/services/`)
- Business logic and domain rules
- Database operations via SQLAlchemy models
- Security operations (hashing, token management)

### Models (`models/`)
- SQLAlchemy ORM models
- Database table definitions
- Relationships and constraints

### Core (`core/`)
- Cross-cutting infrastructure: configuration, database, security
- Shared across all features

### Dependencies (`api/dependencies.py`)
- FastAPI dependency injection functions
- `get_db` — database session lifecycle
- `get_current_user` — JWT authentication

---

## Database Strategy

- **Development**: SQLite (via `aiosqlite`) — no external dependencies
- **Production**: PostgreSQL (as specified in roadmap)
- **ORM**: SQLAlchemy 2.0 with async support
- **Migrations**: Alembic (to be configured)

---

## Authentication Architecture

1. User registers/logs in → server validates → returns JWT access token + refresh token
2. Client sends `Authorization: Bearer <token>` on protected requests
3. Server decodes JWT, extracts `sub` (user ID), loads user from DB
4. Access tokens expire after 30 minutes; refresh tokens after 7 days
5. Refresh tokens are stored in DB and can be revoked (logout)
