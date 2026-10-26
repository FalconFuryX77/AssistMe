# AssistMe progress

## Current baseline

- Working branch: `main`
- The GitHub default branch is `main`.
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

Latest focused checks passed locally:

```text
pytest tests/test_guides.py tests/test_webrtc.py tests/test_internet_connectivity.py -q
33 passed
flutter test --no-pub
2 passed
dart analyze [changed mobile files]
No issues found
```

The repository also contains an older broad test suite for the removed
email/password, web, chat/file, and multi-party roadmap. Running that suite
produces failures because those tests expect routes intentionally absent from
the device-first app. It is not the acceptance gate for this product path.

The installed SDK is Flutter 3.38.5 / Dart 3.10.4. GitHub Actions uses the
current stable Flutter channel and runs backend checks, dependency resolution,
analysis, and Flutter tests.

## Security follow-up

- Google identified the historical `backend/firebase-service-account.json` service-account credential associated with project `assistme-8332b`.
- The file is absent from the current tree and all fetched Git branches/tags scanned locally. The commit in Google's alert is not present in the local object database after the prior history cleanup.
- Confirm in Google Cloud that the reported service-account key is disabled/deleted; source cleanup cannot revoke a cloud credential or erase copies held by forks/caches.
- `mobile/android/app/google-services.json` contains a Firebase client configuration key. It is delivered to the app by design; restrict its API usage and Android app identity in Google Cloud/Firebase. It is not the service-account private key identified in the alert.
- Production deployment should use a strong `SECRET_KEY`, explicit allowed origins, HTTPS/WSS, Redis-backed rate-limit counters, and a mounted Firebase credential if FCM is enabled.

## Current guide and network follow-up

- Guide screenshots are captured in memory only. Repeated visual frames are deduplicated, memory is bounded by a byte budget, and screenshots are no longer uploaded automatically at call end.
- Guide APIs reject new image uploads, hide legacy image URLs, and the new database migration clears previously stored guide screenshots when applied.
- The legacy cloud MiMo/OpenRouter synthesis route is disabled and its backend settings/deployment variables are removed. The local Gemma 4 guide generator, local transcription, sensitive-text masking, and local guide persistence are not implemented yet.
- Current Flutter LiteRT-LM packages require Flutter 3.44/Dart 3.12 and Android API 30. The installed local SDK is older, so integrate Gemma only after the app/toolchain minimums and target-device support are decided and CI can build it.
- Annotation previews now use a separate unordered, short-lived data channel; committed strokes and control messages remain reliable. WebRTC can balance resolution and frame rate under congestion, and debug builds log selected relay type, RTT, jitter, loss, and receive FPS without IP addresses.
- Metered credential retrieval is asynchronous and bounded. Static `PUBLIC_TURN_URL` accepts a comma-separated list, including a TURN/TLS TCP 443 relay for restrictive networks. The public endpoint still needs to be configured and tested from the actual college Wi-Fi; code changes alone cannot make an unreachable relay pass the firewall.
- If ICE negotiation fails while TURN is configured, the mobile clients now make one TURN-only retry and renegotiate; regular ICE remains the first choice for latency. This recovery still needs a two-device test on the actual campus network.

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
