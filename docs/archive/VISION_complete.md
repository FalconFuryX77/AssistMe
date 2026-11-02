# AssistMe — Product Vision & System Flow

> Living document. Updated as understanding deepens. Last updated: 2026-08-26

---

## 1. What This Is

**AssistMe is a one-tap remote assistance app for elderly people, built around screen sharing + voice.**

An elderly person (helpee) and their trusted family member (helper) each install the app. When the elderly person is stuck on something — a setting, WhatsApp, a confusing dialog — they tap **one button**, pick a trusted person, and that person's phone rings. When accepted, the helper **sees the elderly person's actual live screen**, **talks to them over voice**, and can **draw on the screen** to point things out. If the elderly person grants it, the helper can also **tap and swipe on their screen remotely**.

**Core principle: the elderly person does as little as possible.** Every flow is designed so the person receiving help never types, never remembers codes, never configures anything.

**Not in scope:** video calls (no faces), group sessions, chat-with-strangers, accounts/passwords/logins.

---

## 2. The Users

| Role | Who | What they do |
|---|---|---|
| **Helpee** (elderly) | Parent, grandparent | Tap "I need help" → tap a person → talk. That's it. |
| **Helper** | Adult child, trusted friend | Accepts rings, sees screen, guides by voice + drawing, optionally gets touch control. Also manages all setup. |

Both roles live in **every install** — role is a per-session choice, not a per-device identity. Any phone can be a helper for one person and a helpee for another.

**Constraints:**
- One helper serves **one helpee at a time** (they can only look at one screen).
- One helpee can have **multiple helpers** (son, daughter, etc.).
- Helper must **approve once** when added — prevents strangers spamming elderly people.

---

## 3. Identity — No Accounts, Ever

There is **no email, no password, no login screen**. The install itself is the identity.

- On first launch the app silently registers the device (a stable fingerprint) with the backend and receives a session token. The user only sees: **"What should we call you?"** — one text field.
- The app then shows a **recovery code once** — 12 characters, shown a single time, stored hashed server-side.
- Every future app open goes straight to Home. Tokens refresh automatically; the user never sees an auth screen again.

**Two-secret model:**

| Secret | Purpose | Rules |
|---|---|---|
| **Recovery code** | Root of identity. Reclaims everything after reinstall/phone loss. | Never shared. Shown once. Hashed server-side. Rate-limited reclaim. |
| **Device fingerprint** | Silent per-install identity used for auth. | Stable across restarts. Rebindable via recovery code. |

**Reinstall flow:** new install → "Reinstalling? I have a recovery code" → enter code → same identity, same trusted people. (Rotation/dormancy hardening is specced but not yet built — see §9.)

---

## 4. Trust — The Mutual Contact List

Trust is **device-to-device**, Gmail-"trust this device" style. Both phones end up with each other in their lists.

**Pairing flow (helper does the work):**
1. Helpee's phone: **Trusted people → Show my code** → big 6-digit code appears (valid 15 min).
2. Helpee reads it aloud to the helper (usually over a phone call).
3. Helper's phone: **Trusted people → I have a code** → types it → taps **Send request**.
4. Helpee's phone pops: *"Son's Phone wants to help you — Allow?"* → one tap **Allow**.
5. Done. Helper appears in helpee's list; helpee appears in helper's "people I help" list. **Mutual.**

**Security gates:** the 6-digit code is short-lived; the helper must approve being added (anti-spam); revoking a person is one tap on the owner's list.

---

## 5. The Core Loop — Requesting Help

### Helpee side (dead simple)
```
Home
┌──────────────────────────┐
│        Hi, Grandma       │
│  ┌────────────────────┐  │
│  │    I NEED HELP     │  │
│  └────────────────────┘  │
│  ┌────────────────────┐  │
│  │  I'M HELPING       │  │
│  └────────────────────┘  │
└──────────────────────────┘
```
1. Tap **I NEED HELP**.
2. Trusted people appear as big contact cards.
3. Tap a person → optional message ("my WhatsApp won't open") or just **Just ring**.
4. "Calling Son…" spinner. Cancel anytime.

### Helper side (rings anywhere)
- **App open:** full-screen popup — who + message + **Accept / Can't right now**.
- **App closed:** **FCM push notification** with the same info; tapping it opens the app straight into the popup.
- **Missed it entirely:** on next app open, the pending request is fetched from the server and shown. A request is never lost.
- Re-ringing while one is pending is idempotent (no dead-end errors).

### Accept → live session
Accept drops **both phones straight into the live session**. No codes, no rooms, no join screens. The session forms silently server-side.

---

## 6. The Live Session — The Actual Product

```
┌─────────────────────────────┐
│                             │
│   HELPER'S PHONE            │
│   ┌─────────────────────┐   │
│   │                     │   │
│   │  LIVE VIEW OF THE   │   │
│   │  HELPEE'S SCREEN    │   │
│   │  (with red drawing  │   │
│   │   overlay)          │   │
│   │                     │   │
│   └─────────────────────┘   │
│    [mic]      [hang up]     │
└─────────────────────────────┘

┌─────────────────────────────┐
│   HELPEE'S PHONE            │
│   (their normal screen,     │
│    with helper's red        │
│    annotations on top —     │
│    visible but not          │
│    touchable)               │
│    [panic stop]             │
└─────────────────────────────┘
```

**Three capabilities, in escalation order:**

1. **See** — helper watches a live WebRTC video of the helpee's screen (Android MediaProjection → WebRTC video track). *This is the core product.*
2. **Speak** — two-way WebRTC voice, mandatory from day one. No phone-call integration, no WhatsApp, in-app only.
3. **Draw** — both sides can annotate. Helper draws on the live screen video and strokes appear on the helpee's screen; **helpee can also draw back** (to point at what they mean). Overlay is visible to both but not touchable as app UI. Strokes support basic pen colors (black, blue, green, red, yellow, orange, etc.), can be set to **persist until erased** or to **auto-fade after a short time** so they never permanently block the screen. Either side can **clear all with one tap**, use an **eraser**, and **undo/redo**. Annotations **never block the panic stop button** — the panic control sits above the drawing layer and is always tappable, and the helper can never interact with that button or any in-app settings on the helpee's phone.

**Escalation (Phase B) — staged, explicit, and always the helpee's choice:**
- **Level 1 — Annotate only:** helper can draw (above). No touch control.
- **Level 2 — Full control:** helpee grants **tap + swipe + scroll + typing** control. Either the helper can *ask* for it or the helpee can *offer* it — both paths show the same clear risk screen before anything is granted.
- Requires an **Accessibility Service** on the helpee's phone (one-time enable, guided).
- Hard-gated: only acts during an active, token-verified session.
- **One-tap panic stop** on the helpee's screen kills all control instantly.
- Persistent visible indicator while any elevated control is granted (security by user awareness — the helpee always sees that a session/control is active). Auto-timeout is **not default**; it can be enabled as an option in the helpee's settings, but is disabled by default.

**Session UI (deliberately minimal, clearly labelled in plain language):**
- Helper: live screen video + movable (mic toggle + hang up) dock + movable (annotate dock + permission escalation button + they should be able to turn draw mode on and off) 
- Helpee: their normal life + overlay + panic stop (always on top, never obscurable).
- No E2EE dashboards, no "zeroize" buttons, no technical jargon anywhere. **Every critical decision — especially privilege escalation — shows a plain-language screen explaining exactly what will happen and the risks, before the helpee confirms.** The key selling point is that the helpee is always kept safe through **user awareness and a security-first workflow**.
- **Either side can hang up and it ends for both**, with a persistent meeting indicator visible for as long as the session is active (security by user awareness).

---

## 7. Infrastructure

| Piece | Choice | Status |
|---|---|---|
| Backend | FastAPI + SQLite, REST + WebSockets | ✅ built |
| Signaling | Existing session WebSocket (`signal_offer/answer/ice_candidate`) | ✅ built |
| Ring channel | Persistent per-device WebSocket (`/ws/device`) + FCM fallback | ✅ built |
| Push | **FCM** — Firebase project `assistme-8332b`; service account on backend; wake-up-ping discipline (minimal payload, details fetched over our API) | ✅ wired |
| NAT traversal | **Metered.ca TURN** (`assistme.metered.live`), short-lived REST creds, cached 10 min | ✅ wired |
| Screen capture | flutter_webrtc `getDisplayMedia` → MediaProjection consent | ✅ built, needs live verification |
| Voice | WebRTC mic track both directions | ✅ built, needs live verification |
| Storage | SharedPreferences (identity must survive restarts); encrypted storage later | ✅ built |

**Network requirement:** must work **over the internet, from anywhere** — helpee at home on Wi-Fi, helper at work on different Wi-Fi or mobile data. Never same-network-only.

---

## 8. Security Posture (agreed decisions)

- **Media:** end-to-end encrypted by WebRTC (DTLS-SRTP) regardless of TURN. TURN sees only ciphertext.
- **Chat/voice-notes (future):** server-readable in v1 — deliberate, disclosed trade-off.
- **Recovery code:** 12+ chars, hashed, shown once, rate-limited reclaim (rotation + reclaim-alerts-to-contacts are specced, not yet built).
- **Trust-add:** always requires helper's one-time consent (anti-spam/phishing).
- **Accessibility service:** hard-gated to active sessions, panic stop, visible indicator.
- **FCM:** minimal payloads only.
- **Screen capture:** full-screen disclosure ("your helper sees everything on screen"); Android 14+ single-app sharing as progressive enhancement later.
- **Known gap:** rate limiting on claim/approve/reclaim endpoints — not yet implemented.

---

## 9. Build Status

### ✅ Working / built
- Device-first identity + recovery code + reclaim UI
- Mutual trust pairing (setup-code flow)
- One-tap help call: ring → accept → auto-formed session
- Live WebSocket ring + FCM push + missed-request inbox + idempotent re-ring
- WebRTC pipeline (capture, mic, offer/answer, ICE) with Metered TURN
- Session screen: live video viewport, mic + hang-up only
- Auto token refresh (401 → refresh → retry)

### 🔧 Built but unverified live
- Actual screen-share video between the two physical phones
- Two-way voice audio
- Helper drawing → helpee overlay (stroke relay exists; helper-side draw input not yet wired to the video view)

### 📋 Specced, not built
- Escalation to touch control (Accessibility Service, panic stop)
- Deny-with-reason shown to helpee
- Voice notes on requests
- Rich notification (expandable, playable voice note)
- Recovery-code rotation + dormant trust + reclaim alerts to contacts
- Rate limiting on security-sensitive endpoints
- Android 14+ partial screen sharing
- Encrypted storage (currently SharedPreferences)

---

## 10. The Test That Defines "Done"

> **Grandma, at home on her Wi-Fi, taps one button. Her son, at work on office Wi-Fi, gets a notification, taps Accept, sees her screen, says "tap the green button", draws a circle around it — and she taps it. Done.**

Every design decision above serves that sentence.

---

## 11. Engineering & Deployment Requirements Added During Implementation

The following requirements were added during implementation discussions and are part of the product direction even when they are not visible in the original 2026-08-23 vision.

### 11.1 Scalable backend architecture

The backend must be designed for scalability and maintainability rather than relying on hardcoded development values or temporary infrastructure.

- Configuration must be environment-driven; development, local-device, staging, and production configuration must remain separable.
- Production secrets must not be hardcoded into source code.
- Database schema changes must use migrations rather than automatic table creation in production.
- Database connectivity should use connection pooling and explicit readiness/health checks.
- The backend should expose separate liveness and readiness health checks so infrastructure can determine whether the process is alive and whether it is actually ready to serve traffic.
- Backend functionality should remain modular, with domain-specific routers/services rather than accumulating functionality in a single backend module.
- Temporary LAN addresses, emulator hosts, tunnel URLs, and other development endpoints must not become application defaults.
- The architecture should be suitable for deployment behind a stable API endpoint/reverse proxy rather than depending on a developer machine's IP address.

### 11.2 Internet-first connectivity

AssistMe is not a LAN-only application.

- A helpee and helper must be able to use the application while connected to completely different networks, including home Wi-Fi, office Wi-Fi, and mobile data.
- Local LAN connectivity may remain useful for development/testing, but it must be an override rather than the product's fundamental networking model.
- Production connectivity must use a stable public HTTPS backend/API endpoint.
- NAT traversal must be supported through a publicly reachable TURN service or equivalent managed TURN infrastructure.
- The client must not expose server addresses, deployment paths, tunnel URLs, or networking configuration to ordinary users.
- Changing backend/server settings must not be part of the first-page/onboarding experience.

### 11.3 User-facing onboarding must stay simple

The user should not be burdened with infrastructure configuration.

- The first page should not display the server address.
- The first page should not expose a server-settings control or server-settings dialog.
- Server configuration belongs to the build/deployment configuration, not to normal user interaction.
- Technical infrastructure details should never be presented to the elderly user merely because the app is running against a local or remote backend.

### 11.4 Reliable help-request state

A help request must remain reliable even when a real-time event is missed.

- The request lifecycle must have a durable server-side state.
- WebSocket events are a real-time delivery mechanism, not the sole source of truth.
- If a WebSocket event is missed, the receiving device must be able to recover the pending request from the backend.
- A request must not become permanently stuck because one real-time event was lost.
- Repeated/rerun requests while an earlier request is pending should be handled idempotently rather than producing dead-end states.
- A connection/request attempt must eventually resolve to an appropriate state rather than leaving the user indefinitely on a loading screen.
- Failure should produce a clear retry path rather than an unexplained technical error.

### 11.5 Correct helper/helpee session roles

The live-session responsibilities must follow the product model in this document.

- **The helpee is the device whose screen is shared.**
- **The helper is the device that receives/views the helpee's screen.**
- The helper must never be presented with a "Start screen sharing" action for the helpee's screen.
- Android's MediaProjection/screen-capture consent must be initiated on the **helpee device**.
- The helper should not need to approve an Android screen-capture prompt for the helpee's device.
- After MediaProjection approval, the helpee application must remain in a stable session state; the app must not appear to crash, disappear, or abandon the session while the capture service runs.
- The helper must actually receive and display the resulting WebRTC screen stream.
- The Android capture service/activity lifecycle must be treated as part of the session architecture, not as an isolated screen-sharing button.

### 11.6 Notifications are part of the product flow

WebSocket events alone are insufficient for user-facing notifications.

When a helpee requests help:

- The helper should receive an actual device notification when the app is backgrounded or closed.
- The notification should identify who is requesting help and, when applicable, include the request message.
- Tapping the notification should bring the helper directly into the appropriate incoming-help UI.
- When the app is already open, the request should still be represented by a clear incoming-call/request UI.
- The notification and in-app request should represent the same server-side request rather than creating separate independent states.
- If the helper misses the notification/request entirely, the pending-request recovery behaviour described in §5 must still apply.
- The same notification/state model should be used consistently rather than treating an in-app WebSocket event as a substitute for a device notification.

### 11.7 Human-readable names must be used throughout the call flow

The application should use the trusted contact's actual chosen name rather than internal/device-oriented labels.

- Avoid labels such as **"My Device"** in user-facing call states.
- The helpee should see language such as **"Connecting to <contact name>…"** rather than **"Calling My Device…"**.
- Contact names supplied by the backend must propagate correctly through the request, ringing, acceptance, and live-session UI.
- User-facing terminology should describe people and actions, not internal device IDs or implementation concepts.

### 11.8 Error handling must preserve the actual failure meaning

The mobile client must not turn backend failures into misleading parsing errors.

- Server errors may be structured JSON or plain text during failures, and the client must handle both safely.
- A plain-text backend error must not surface to the user as an unrelated JSON `FormatException`.
- User-facing errors should explain what failed and provide an appropriate recovery action where possible.
- Backend logs should retain the technical error details needed for debugging without exposing those details unnecessarily to the user.

### 11.9 Deployment and infrastructure must be production-oriented

The project should be deployable without changing application logic for every environment.

- Local development may use Docker Compose and a LAN override.
- Production should use a stable public endpoint, trusted TLS, production secrets, and publicly reachable TURN infrastructure.
- Reverse proxies/API gateways should be supported as part of the deployment architecture.
- Infrastructure health checks should be suitable for container/orchestrator probes.
- The application should be able to move from local development to a real internet deployment without rewriting core application behaviour.

### 11.10 The complete end-to-end flow must be verified, not just individual components

A feature is not considered complete merely because the corresponding code exists or unit tests pass.

The critical physical-device flow must be tested end to end:

**Helpee requests help → helper receives device notification → helper opens/accepts request → both devices enter the session → helpee grants screen capture → helpee's screen is streamed → helper sees it → voice works → drawing works → optional control works when explicitly granted → either side can end the session.**

Testing must specifically cover:

- App open
- App backgrounded
- App closed
- Missed WebSocket events
- Missed push notifications
- Android MediaProjection approval
- Android activity/service lifecycle after approval
- Two different networks
- Wi-Fi ↔ mobile-data combinations
- Temporary network interruption and recovery
- Correct helper/helpee role assignment
- Correct contact-name propagation
- Backend/API failure responses

The system should be considered broken if any individual component appears to work in isolation while this end-to-end flow fails.

---

## 12. Interaction, Session-Recovery & Helper Workspace Requirements

These requirements were explicitly raised during physical-device testing and must be treated as product requirements, not optional polish.

### 12.1 Control and Guide modes must coexist

Privilege escalation does not end annotation capability.

- After Phase 3/full control has been granted, the helper must be able to switch between:
  - **Control mode** — interact with the helpee's device.
  - **Guide/annotation mode** — draw annotations on the helpee's screen.
- Switching to Guide mode must not revoke or destroy the already-approved control privilege.
- The helper must be able to guide the helpee visually while retaining the ability to return to control.
- The helper must be able to switch modes repeatedly during one session.

### 12.2 Annotation must be genuinely live

Annotations are part of the real-time assistance experience.

- A stroke must begin appearing remotely while it is being drawn, rather than waiting until the user's finger is lifted.
- Live annotation previews must reach both:
  - the helper's local representation, and
  - the helpee's actual external screen overlay.
- Annotation updates must be coalesced/throttled where necessary to prevent stale frames, but must remain responsive.
- Changing annotation properties such as color or thickness must be reflected consistently in the actual remote overlay, not merely in the helper's UI.
- The system should minimize latency between drawing and visible remote feedback.

### 12.3 Annotation controls

The annotation UI should remain deliberately simple.

- Use **one pen control**, not separate thin-pen and thick-pen tools.
- Pencil/pen thickness should be controlled with a slider.
- Color should be selectable independently from thickness.
- The selected color and thickness must apply consistently to annotations.
- Retain an eraser.
- Provide Clear All on both sides where appropriate.
- Do not duplicate Clear All controls unnecessarily.
- The helpee's annotation controls must not be exposed as interactive controls to the helper.

### 12.4 Helpee overlay is independent of the app UI

The helpee should not have to keep AssistMe open merely to see guidance.

- The helper's annotations must appear on top of the helpee's normal phone usage.
- The helpee must be able to continue using their phone normally while the guidance overlay is visible.
- The annotation overlay itself is not an interactive AssistMe surface.
- The helper must never be able to interact with the helpee's panic/exit control.
- The helpee must retain a private, always-available way to clear annotations and terminate the assistance session.

### 12.5 Panic/exit control

The helpee must always retain an independent escape path.

- A clearly visible panic/STOP control must remain above the annotation layer.
- The helper cannot move, press, obscure, or otherwise interact with this control.
- Activating it immediately terminates the active assistance/control path.
- The control must remain available while the helpee is using other applications.
- The purpose is to protect the helpee if the helper behaves unexpectedly or if the helpee simply wants the session to stop.

### 12.6 Helper workspace must remain an in-app workspace

The helper must not lose the controls needed to operate AssistMe.

- The helper workspace must remain inside the AssistMe application.
- Do **not** make the helper's remote screen an uncontrolled fullscreen surface that hides the AssistMe controls.
- The helper's controls must remain visible while connected to a session.
- Android's native navigation area must not make the remote target unusable.
- The helper should be able to see the remote phone's content at a useful, bounded size rather than having the remote viewport consume the entire screen.
- The helper's own controls must not permanently cover important parts of the remote target.

### 12.7 Repositionable helper controls

The helper needs to place controls where they do not obstruct interaction with the remote device.

- The helper control dock should be movable/repositionable.
- A dedicated drag handle or equivalent interaction should make its movement obvious.
- The helper can move the dock away from the portion of the remote screen they need to interact with.
- Moving the dock must not move or alter the remote target.
- Controls should remain reachable after repositioning.
- The remote viewport and helper controls must coexist without forcing the helper to rotate the phone merely to reach the remote target.

### 12.8 Remote touch coordinate mapping

Remote control must map helper input to the correct location on the helpee device.

- Touches must be transformed according to the actual displayed remote-video rectangle.
- Letterboxing, scaling, aspect-ratio differences, and viewport offsets must be accounted for.
- A tap at a point on the helper's displayed remote screen should act at the corresponding point on the helpee's actual screen.
- Coordinate mapping must be tested in both portrait and relevant bounded-viewport layouts.
- The helper's own UI/navigation bars must not introduce a systematic offset.

### 12.9 Reconnect must restore the complete session

A reconnect is not successful merely because a WebSocket reconnects.

- If the helper disconnects accidentally, the helper must be able to reconnect to the existing meeting while it is still within the session's recovery window.
- The helpee must also be able to reconnect to the existing meeting.
- Reconnection must restore/rebuild the WebRTC media path.
- Screen capture and microphone tracks must be restored/re-established as required.
- The remote screen must continue working after reconnect rather than working only on the initial connection.
- Signaling messages required during reconnection must be buffered or otherwise recoverable.
- The session should remain alive for a defined grace period while one side is temporarily disconnected.
- After that grace period, the meeting should automatically terminate.
- Rejoining should be possible by selecting the relevant trusted person's name rather than requiring a new help request where the existing meeting is still recoverable.

### 12.10 Session termination is symmetric

The session state must reflect both participants' actual connection state.

- If the helper exits, backgrounds/force-stops the app in a way that terminates participation, or explicitly leaves, the helpee must not remain indefinitely in a phantom meeting.
- If the helpee leaves, the helper must likewise be informed and the session should end or enter its defined reconnect state.
- Explicit Leave Session must terminate the assistance session cleanly.
- Accidental disconnection should enter the reconnect grace period rather than immediately killing the session.
- Permanent disconnection after the grace period should cleanly close the meeting on both sides.

### 12.11 Screen-share latency is a first-class requirement

The screen stream is the core interaction surface and must be optimized for responsiveness.

- Minimize end-to-end visual latency as far as the network and device allow.
- Optimize capture resolution, frame rate, bitrate, and WebRTC configuration for interactive assistance rather than maximum visual fidelity.
- Do not accept a configuration that makes the screen appear several moments behind the user's actual interaction.
- Annotation/control feedback should remain responsive even when the screen video experiences network pressure.
- Screen-share optimization must not break control input or annotation delivery.
- Any trade-off between resolution and latency should favor a responsive guidance experience.

### 12.12 Phase boundaries must remain consistent with the product model

The phase model is:

- **Phase 1 — See:** helper sees the helpee's screen.
- **Phase 2 — Guide:** annotation only; no remote touch control.
- **Phase 3 — Control:** explicit remote touch/scroll/typing permission.

Phase 2 must not accidentally include control features.

Phase 3 must not eliminate Phase 2's annotation capability.

The UI should make the currently active mode obvious without making the underlying security state confusing.

---

## 13. Identity, Naming & Trusted-Person Presentation

### 13.1 Display names are real user-facing identifiers

The name entered during onboarding is not merely decorative.

- The chosen name must be used consistently throughout the trusted-person and help-request experience.
- A user should see **the person's chosen name**, not `"My Device"` or another generic device label.
- The name should appear in the I NEED HELP contact list.
- The name should appear when adding/trusting a device.
- The name should appear in incoming/outgoing request states and relevant session/reconnect UI.

### 13.2 Names must be uniquely identifiable

Names function like usernames for the purposes of the product's trusted-device model.

- Two registered identities must not be allowed to use the same display name.
- Uniqueness should be enforced at the database/API boundary, not merely in the client.
- Uniqueness should be case-insensitive so `Dad`, `dad`, and `DAD` cannot represent different identities.
- A database unique index/constraint must enforce the rule reliably under concurrent registration.
- If a chosen name is already taken, the user must receive a clear error and choose another name.

### 13.3 Device identity may supplement, but not replace, the name

Because multiple devices may otherwise be difficult to distinguish, the trusted-person presentation may include a short device/account tag alongside the person's name.

- The person's name remains the primary human-readable identifier.
- A short unique device/account identifier may be shown where needed to distinguish a specific trusted installation.
- Internal device IDs should never replace the person's chosen name in ordinary UI.

---

## 14. Notifications & Incoming Help UX

### 14.1 Incoming help must be surfaced immediately

The helper should not need to reopen AssistMe to discover a request.

- If the helper app is open, an incoming help request must immediately produce the appropriate in-app alert/request UI.
- If the helper app is backgrounded or closed, a device notification must be delivered.
- If the helper is already somewhere inside the app, the request should still interrupt the relevant flow appropriately.
- The helper should never have to close and reopen the app to make an already-received request appear.

### 14.2 Notification delivery is a real feature requirement

FCM is not merely an implementation detail.

- The backend must be capable of sending the notification in the deployed environment.
- The required Firebase Admin SDK/dependencies must be present in the backend deployment.
- Notification failures must be observable in backend logs.
- Notification payloads should remain minimal and the client should retrieve sensitive/request details through the authenticated API as defined by the security model.

---

## 15. Performance & Verification Standard

### 15.1 Verification must cover the actual phones

Passing Flutter tests, static analysis, backend health checks, or an APK build is not enough to declare the product working.

The critical changes must be verified on the two physical Android devices used for the project.

### 15.2 Regression testing is mandatory after UI/transport changes

Any change to WebRTC, WebSocket/Redis signaling, Android MediaProjection, session lifecycle, helper workspace layout, annotation transport, or control mode must re-test the complete end-to-end flow.

At minimum verify:

- Initial help request
- Incoming notification
- Accept
- Screen capture permission
- Live screen
- Voice
- Mute/unmute
- Phase 2 annotation
- External helpee overlay
- Clear All
- Panic STOP
- Phase 3 control approval
- Touch coordinate accuracy
- Swipe/scroll
- Switching Control ↔ Guide
- Helper disconnect/reconnect
- Helpee disconnect/reconnect
- Session timeout
- Session termination from either side
- Re-entry to an existing recoverable meeting
- Cross-network operation
- Background/closed-app notification behaviour
- User/contact name propagation

### 15.3 Do not remove working UI while fixing an unrelated problem

The helper workspace and its controls are core functionality.

- A fix for fullscreen, coordinate mapping, latency, or control mode must not remove the helper's existing controls.
- Any UI simplification must preserve the ability to perform every existing required action.
- If a change causes the helper to lose the screen, controls, annotation tools, or interaction capability, it is a regression and must be reverted/fixed before the change is considered complete.
