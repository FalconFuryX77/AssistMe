# AssistMe v1.1.0 - PostgreSQL Production Migration & Calling Stability Release

AssistMe v1.1.0 represents a major milestone in production readiness and real-time calling reliability. This release transitions the backend infrastructure to PostgreSQL with comprehensive ACSAF security architecture, hardens authentication token persistence, resolves real-time calling and media-engine edge cases, and delivers an enhanced, lag-free user experience.

---

## 🌟 Highlights & Key Improvements

### 🗄️ 1. PostgreSQL Production Migration & Cryptographic Hardening
- **PostgreSQL Database Engine**: Migrated the core database to PostgreSQL with zero breaking changes, maintaining full backwards compatibility across all REST and WebSocket interfaces.
- **Envelope Encryption**: Field-level encryption using AES-256-GCM (`backend/core/crypto/envelope.py`) protecting sensitive records at rest with versioned Key Encryption Keys (KEKs).
- **Blind Indexing**: Searchable encrypted identifiers via HMAC-SHA256 blind indexing (`backend/core/crypto/blind_index.py`), preventing plain-text leakage while enabling fast queries.
- **Cryptographic Audit Ledger**: Tamper-evident, hash-chained ledger (`backend/core/crypto/hashing.py`) ensuring full traceability of security-critical actions and policy decisions.
- **Online Key Rotation**: Seamless cryptographic key rotation mechanisms without downtime or database re-initialization.

### 🔑 2. Token Lifecycle & User Identity Persistence
- **Sliding Refresh Window**: Restored the 30-day sliding validity window for refresh tokens in `auth_service.py`, eliminating false token-theft triggers that previously invalidated active user sessions.
- **Dual Token Refresh**: Updated `AccessTokenResponse` and `api_client.dart` to return and store new refresh tokens upon rotation.
- **Transparent Device Re-Bootstrap**: Mobile client automatically recovers session authentication via cryptographically stored `deviceSecret` upon encountering expired or invalidated tokens, preventing unexpected logouts or onboarding resets.
- **Multi-Attribute Identity Check**: `main.dart` and `home_screen.dart` check `accessToken`, `refreshToken`, `deviceSecret`, and `displayName` to ensure returning users are never dropped back to the "Welcome to AssistMe" screen.

### 🎙️ 3. Instant Bidirectional Voice Audio
- **Immediate Microphone Activation**: Both helper and helpee automatically start local microphones (`startMicOnly()`) from second 1 upon entering a session.
- **Initial Audio Negotiation**: Automated audio-only WebRTC offer creation ensures users can talk immediately without waiting for screen sharing to begin.
- **Voice Service Hardening**: Backend `voice_service.py` automatically sets `is_in_audio_call = True` on mute/unmute and route changes, preventing `400 Bad Request` exceptions.

### 📺 4. Permanent Screen Sharing Controls
- **Dedicated Toggle Button**: Replaced the ephemeral floating green icon with a permanent, accessible **Start Sharing / Stop Sharing** button in the helpee workspace.
- **State Synchronization**: Integrated `screenSharingSink` between the WebRTC media engine and the Flutter UI layer, providing accurate real-time feedback on stream status.
- **Stream Recovery**: Clean handling of Android MediaProjection capture intents with seamless renegotiation over WebRTC peer connections.

### 🚪 5. Call Teardown & Elimination of Black Screen
- **Navigation Double-Pop Guard**: Added `isLocalLeave` tracking in `assistance_flow_coordinator.dart` and re-entrancy pop guards in `mobile_workspace_screen.dart`, ensuring `MobileWorkspaceScreen` is popped exactly once and preserving `HomeScreen`.
- **Synchronized Auto-Exit**: Ending a call on either device automatically broadcasts a `session_ended` event to the peer, cleanly dismissing overlays, stopping media tracks, and returning both participants to the home screen.

---

## 📦 Release Assets
- **Mobile APK**: `AssistMe-v1.1.0.apk` (Android 7.0+ / API 24+)
- **Backend**: FastAPI with PostgreSQL 16+ & ACSAF Security Suite
