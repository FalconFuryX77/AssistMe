# Cloud Deployment – Run AssistMe Over the Internet

> Local `192.168.1.39:8000` works only on same Wi-Fi. This guide puts the backend on a public HTTPS/WSS endpoint so helpee at home and helper at office/mobile data can connect via `coturn` + `Metered` TURN.

## 1. What Changes vs Local

| Local | Cloud |
|---|---|
| `DEFAULT_SERVER_URL=http://192.168.1.39:8000` | `https://api.yourdomain.com` |
| `STUN=stun.l.google.com` + `TURN=turn:coturn:3478` (LAN) | `TURN=turn:coturn.yourdomain.com:3478` + `METERED` fallback |
| SQLite `assistme.db` | Managed Postgres + Redis |
| `ALLOWED_ORIGINS=*` | `https://yourdomain.com` |
| No TLS | `nginx` 443 with certs or Cloudflare Tunnel |

## 2. Prepare `deploy/.env`

Copy `deploy/.env.example` → `deploy/.env` and set:

```
APP_ENV=production
SECRET_KEY=<32+ random, never commit>
DATABASE_URL=postgresql+asyncpg://assistme:STRONG_PASS@db:5432/assistmedb   # or Neon/Supabase/RDS
REDIS_URL=redis://:PASS@redis:6379/0
ALLOWED_ORIGINS=https://yourdomain.com
PUBLIC_API_BASE_URL=https://api.yourdomain.com
PUBLIC_WS_BASE_URL=wss://api.yourdomain.com
PUBLIC_TURN_URL=turn:coturn.yourdomain.com:3478
TURN_USERNAME=assistme_turn_user
TURN_CREDENTIAL=<strong>
EXTERNAL_IP=<your public IP or empty if behind NAT>
METERED_API_KEY=<from metered.ca>  # fallback when users on different NATs
METERED_DOMAIN=assistme.metered.live
```

## 3. Option A – VPS with Docker Compose ( simplest )

1. Buy VPS (Hetzner DO Lightsail, 2 vCPU, 2GB), point `A api.yourdomain.com → VPS IP`, `turn.yourdomain.com → same IP`.
2. `scp -r . user@VPS:/opt/assistme`
3. On VPS:
```bash
cd /opt/assistme/deploy
docker compose build backend
docker compose run --rm migrate  # runs alembic upgrade head (or `migrate` service)
docker compose up -d   # backend, db, redis, coturn, nginx
# check
docker compose ps
curl https://api.yourdomain.com/health/ready
```
4. TLS: put `fullchain.pem`/`privkey.pem` in `deploy/nginx/certs/` or use `certbot` on host, `nginx` already mounts `./nginx` . Or use `CLOUDFLARED_TUNNEL_TOKEN` – set token and `docker compose --profile tunnel up -d` (no public IP needed).

## 4. Option B – Cloudflare Tunnel (no open ports)

1. Create Tunnel in Cloudflare Zero Trust, copy token.
2. `deploy/.env` set `CLOUDFLARED_TUNNEL_TOKEN=<token>`, keep `PUBLIC_*` as above.
3. `docker compose --profile tunnel up -d` – `cloudflared` exposes `api.yourdomain.com` via Tunnel.

## 5. Mobile Build for Cloud

```
flutter build apk --release --dart-define=DEFAULT_SERVER_URL=https://api.yourdomain.com
# or for iOS same
```

Install that APK – now helpee home Wi-Fi and helper office Wi-Fi both hit `https://api...` over internet, WebRTC via `coturn` + `Metered`.

## 6. Verify

- `curl https://api.yourdomain.com/health/ready` → `{"status":"ok"}`
- `curl https://api.yourdomain.com/health/ready` from phone browser via mobile data
- Two phones different networks: helpee `I need help` → helper gets `FCM` + `incoming_call` → accept → screen share appears

## 7. Ongoing

- `docker compose logs -f backend` for 403609 etc.
- `alembic` migrations are in `backend/migrations` – never use `AUTO_CREATE_TABLES=true` in production.
- Rotate `SECRET_KEY` via k8s secret or `deploy/.env` (restart backend).

See `deploy/README.md` and `SCALABLE_BACKEND_ARCHITECTURE.md` for k8s variant.
