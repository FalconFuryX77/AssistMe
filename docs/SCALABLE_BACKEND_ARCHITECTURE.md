# Scalable Backend Architecture

## Goals

AssistMe should scale horizontally without changing application code or
rebuilding clients for every environment. The backend therefore treats the
runtime environment as configuration and keeps the API process stateless.

## Runtime topology

```text
Mobile clients
    │ HTTPS + WSS (stable public DNS)
    ▼
TLS edge / load balancer
    ├── FastAPI API replicas (stateless)
    ├── PostgreSQL (managed, backed up)
    ├── Redis (future: rate limits, presence, pub/sub)
    ├── Object storage (future: files, recordings)
    └── Coturn cluster (WebRTC media relay)
```

The API is not the media path. WebRTC carries audio/video/data, while the API
handles identity, authorization, session negotiation, durable state, and
signaling. WebSocket state must be moved to Redis pub/sub before running more
than one replica.

## Configuration contract

All deployment-specific values are injected through environment variables or
secret-manager references. Important values include:

- `APP_ENV`, `APP_VERSION`, and `LOG_LEVEL`
- `DATABASE_URL`, `DB_POOL_SIZE`, and `DB_MAX_OVERFLOW`
- `SECRET_KEY` and token lifetimes
- `ALLOWED_ORIGINS`
- `PUBLIC_API_BASE_URL`, `PUBLIC_WS_BASE_URL`, `PUBLIC_STUN_URLS`, and
  `PUBLIC_TURN_URL`

Production rejects the development JWT secret and does not auto-create tables.
Use a migration job (Alembic should be the next database-infrastructure task)
before deploying API replicas.

## Deployment commands

For Docker Compose, create `deploy/.env` from `deploy/.env.example`, provide a
real `SECRET_KEY` and public URLs, then run:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up --build -d
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
```

The `migrate` one-shot service runs `alembic upgrade head` before the API
starts. For Kubernetes, build and publish the backend image, apply the
configuration/secrets, run `backend-migration-job.yaml`, wait for completion,
and then roll out `backend-deployment.yaml`.

For testing physical phones on the same trusted LAN, use the separate local
override so the phones can connect directly to the API over HTTP:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml -f deploy/docker-compose.local.yml up -d
```

Set the mobile server address to `http://<PC-LAN-IP>:8000`. Do not use this
override on an internet-facing host; production clients should use a stable
HTTPS domain with a trusted certificate through the edge gateway.

For clients on different networks, deploy a named public edge. A supported
option is a Cloudflare Tunnel with a stable hostname, configured in Cloudflare
to route to `http://backend:8000` and started with the `public-edge` Compose
profile:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml --profile public-edge up -d
```

Build the mobile release with that stable hostname, for example
`--dart-define=DEFAULT_SERVER_URL=https://api.example.com`. WebRTC also needs
an internet-reachable TURN service. Use a public Coturn host with its UDP/TCP
ports and relay range forwarded, or configure `METERED_API_KEY`; a TURN server
bound only to a home/LAN address cannot connect users on unrelated networks.

## Health and rollout behavior

- `/health/live` only verifies that the process is alive.
- `/health/ready` verifies the database connection and is used for traffic
  admission.
- `/health` remains as a compatibility endpoint for existing tooling.

This distinction prevents a broken database from receiving traffic and avoids
restarting a healthy process merely because a dependency is temporarily down.

## Client endpoint strategy

The mobile source contains no shared tunnel hostname. A release pipeline
injects the stable endpoint with `--dart-define=DEFAULT_SERVER_URL=...`; local
builds can set it through the same mechanism or use the in-app server settings.
This is configuration, not application logic, and lets development, staging,
and production use separate endpoints without source edits.

## Recommended next infrastructure increments

1. Add Alembic migrations and a one-shot migration deployment/job.
2. Add Redis-backed rate limiting and WebSocket fan-out.
3. Move file/recording payloads to object storage with signed URLs.
4. Add structured JSON logs, OpenTelemetry traces, and metrics.
5. Store secrets in a managed secret manager and rotate JWT signing keys.
6. Replace single-node Coturn with region-aware relays and health checks.
