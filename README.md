# AssistMe

AssistMe is a device-first, one-tap remote assistance app for an older adult
and a trusted family member or friend. The live product path is deliberately
small: pair trusted devices, tap a person to ring them, share the helpee's
screen and voice, draw guidance, and request touch control only with explicit
helpee approval.

## Repository layout

- `backend/` — FastAPI, SQLAlchemy, device identity, pairing, help calls, WebRTC signaling, and native-control authorization
- `mobile/` — Flutter Android/iOS client, WebRTC media, drawing overlay, FCM ring notifications, and Android accessibility bridge
- `deploy/` — Docker Compose deployment with PostgreSQL, Redis, coturn, and ingress services
- `docs/` — vision, architecture, threat-model, and progress notes

## Local backend

```powershell
cd backend
python -m venv ..\.venv
..\.venv\Scripts\pip.exe install -r requirements.txt
..\.venv\Scripts\python.exe -m pytest tests/test_vision_contract.py tests/test_device_first_e2e.py -q
..\.venv\Scripts\python.exe -m uvicorn app:app --reload
```

The development backend uses SQLite by default. Docker deployment uses
PostgreSQL and Redis:

```powershell
docker compose -f deploy/docker-compose.yml up --build
```

## Flutter client

```powershell
cd mobile
flutter pub get
flutter analyze --no-fatal-infos
flutter test
flutter run --dart-define=DEFAULT_SERVER_URL=http://10.0.2.2:8000
```

`10.0.2.2` is the Android-emulator address for the host machine. For a
physical phone, use the computer's LAN address; release builds must use a
stable HTTPS URL. Flutter/Dart must be installed to run these checks.

## Security notes

FCM credentials are runtime-only. For the Compose deployment, place a
service-account JSON at the git-ignored `backend/firebase-service-account.json`
path; Compose mounts it read-only at `/run/secrets/firebase-service-account.json`.
Other deployments should mount the credential and set `FIREBASE_SERVICE_ACCOUNT`
to that path. The Docker build excludes credential files. If the runtime file is
absent, push notifications are skipped. Google disabled a service key after
public exposure; rotate or delete it in Google Cloud.

The current handoff and verification status is recorded in
[`docs/PROJECT_PROGRESS.md`](docs/PROJECT_PROGRESS.md).
