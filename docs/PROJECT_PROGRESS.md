# AssistMe progress

## Current baseline

- Working branch: `codex/restore-80e5e0a`
- Source baseline: `80e5e0a4f7e83d63d83a4db56a1cecb186c23697`
- The later `codex/codebase-cleanup-vision-alignment` branch was inspected for context only. It is not merged or cherry-picked.
- Product direction: device-first, two-person help between an older adult and a trusted helper. Email/password login, group collaboration, chat/files, and a web client are outside the current product path.

## Implemented product path

### Identity and trust

- A device fingerprint bootstraps an invisible account; the user chooses a display name once.
- A one-time recovery code supports reinstall/device-loss reclaim.
- Setup-code pairing is owner-generated, helper-claimed, then owner-approved.
- Trusted-device and helping lists expose the actual paired display names.
- Device bootstrap, recovery, pairing, and help-call attempts have IP-based sliding-window limits.

### One-tap help

- The helpee taps a trusted helper device; the backend forms the pair session and rings the helper over the persistent device WebSocket and optional FCM.
- Pending calls are durable and reloadable after a closed-app launch.
- Accept/deny responses are routed back to the caller.
- An outgoing call can be cancelled server-side; the helper is notified and cannot accept the cancelled request.
- A helper already serving another connected or reconnecting helpee is rejected with a conflict.

### Live workspace

- WebRTC signaling, screen-share lifecycle, two-way microphone audio, recovery/reconnect, shared normalized drawing, and Android annotation overlay are wired.
- Helper controls include overlay drawing by default and a separate explicit touch-control escalation.
- Touch control requires helpee approval and a risk disclaimer, is restricted to the helper role, is validated at the REST and WebSocket gateways, and can be revoked immediately by the helpee.
- Native Android accessibility input uses normalized coordinates and the overlay has a helpee-owned panic/clear control.
- Workspace voice and phase controls can be dragged away from the remote target.
- Drawing coordinates are mapped to the contained 9:16 video rectangle so letterboxing does not shift marks or touch targets.

## Verification

Passed locally on 2026-08-26 with Python 3.12:

```text
python -m compileall -q backend       PASS
pytest tests/test_vision_contract.py tests/test_device_first_e2e.py -q
6 passed
```

The repository also contains an older broad test suite for the removed
email/password, web, chat/file, and multi-party roadmap. Running that suite
produces failures because those tests expect routes intentionally absent from
the device-first app. It is not the acceptance gate for this product path.

Flutter/Dart was not installed on the development machine, so `flutter
analyze` and `flutter test` still need to run in CI or on a Flutter-equipped
machine. GitHub Actions now runs the focused backend tests, backend compile,
Flutter dependency resolution, analysis, and Flutter tests.

## Security follow-up

- The inherited exact-base history tracked `backend/firebase-service-account.json`.
- It has been removed from the working tree and added to ignore rules; FCM now requires an explicit runtime `FIREBASE_SERVICE_ACCOUNT` path.
- Because the key remains in Git history, the Firebase service-account key must be revoked and replaced. Removing the file in a new commit does not rewrite old history.
- Production deployment should use a strong `SECRET_KEY`, explicit allowed origins, HTTPS/WSS, Redis-backed rate-limit counters, and a mounted Firebase credential if FCM is enabled.

## Next validation step

Install Flutter and run:

```powershell
cd mobile
flutter pub get
flutter analyze --no-fatal-infos
flutter test
```

Then exercise two real Android devices (or an emulator plus a device) for
pairing, closed-app ring notification, screen capture, voice, drawing,
escalation, panic/revoke, and reconnect behavior. WebRTC/native media cannot
be fully verified by the backend-only test environment.
