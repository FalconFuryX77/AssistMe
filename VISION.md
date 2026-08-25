# AssistMe — Product Vision & System Flow

> Living document. Updated as understanding deepens. Last updated: 2026-08-23

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
- Helper: live screen video + mic toggle + hang up. Nothing else.
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
- Helper drawing → helpee overlay (normalized helper-side draw input and stroke relay are wired; needs live verification)

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
