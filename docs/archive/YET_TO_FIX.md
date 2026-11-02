# Yet to fix

Working list, highest priority first. Details and evidence for each item are in
`docs/BUGS.md`. Tick items off here as they are fixed and verified on real phones.

## Must do before the demo

- [ ] **Run the AI on a real 64-bit phone.** Settings → On-device guide AI →
      Download models → Test on this phone. Record backend (GPU/CPU), load time
      and answer time for each phone you will demo on. Emulators cannot run it.
- [ ] **Check each demo phone's CPU type:**
      `adb shell getprop ro.product.cpu.abilist`. If `arm64-v8a` is missing, that
      phone cannot run Gemma or Whisper; make it the helpee, since the AI runs on the helper.
- [ ] **B8 – expire stale sessions** (backend): call `check_and_expire_sessions`
      on a timer and end sessions whose participants stopped heartbeating.
      Re-test: force-stop the app mid-call, reopen, call again.
- [ ] **TURN relay test** (see below) on two different networks with the real
      endpoint: 10 calls in a row, each must show `localCandidateType: relay`
      and rising `videoFramesDecoded`.

- [ ] **B15 on real phones**: confirm the share-start race fix (helpee log line
      `starting the screen share that was waiting for it` shows when it triggers).
- [ ] **B13** make a Metered failure visible (backend log + client warning) and
      fall back to a reachable `PUBLIC_TURN_URL` instead of silently going STUN-only.

## Should do

- [ ] **B14** decide: drop the self-hosted coturn, or deploy it on a public-IP host
      (`EXTERNAL_IP`, open ports, `PUBLIC_TURN_URL`).

- [ ] **B10** keep the last remote frame visible / force periodic keyframes so the
      helper never sees black on a static helpee screen.
- [ ] **B9** keep the helpee's floating AssistMe toolbar out of guide screenshots.
- [ ] **B12** retry syncing a guide that was saved while the other phone was gone.
- [ ] **B11** Clicky card: allow moving it, or shrink it when not pointing.

## Later

- [ ] Gemma fallback for vague steps in Clicky (choose among visible labels).
- [ ] iOS: Clicky is impossible; the step viewer works. Decide what iOS shows.

## TURN relay test notes

- Build a relay-only APK for testing: it connects **only** through TURN, so a
  call that works proves the relay path:

  ```
  flutter build apk --release --dart-define=DEFAULT_SERVER_URL=<your https endpoint> --dart-define=FORCE_TURN_RELAY=true
  ```

  Install it on both phones, one on Wi-Fi and one on mobile data, and make 10
  calls. Normal builds (no flag) are unchanged and still prefer direct paths.
- What to collect per call: both phones' `[AssistMe][MEDIA] transport=` lines
  (candidate types, `videoFramesDecoded`), and the backend's session-WebSocket
  accept/reject lines (`authentication_failed`, `not_participant`, …).
### Emulator relay-only results (2026-10-30)

Setup: Android 14 helpee + Android 16 helper emulators, each behind its own
emulator NAT on one PC; isolated test backend handing out the same Metered TURN
servers as the live backend (`turn:in.relay.metered.ca:80/443`,
`turns:…:443`); `FORCE_TURN_RELAY=true`, so no direct path was allowed.

| Batch | Build | Calls | Connected over relay with video | Failed |
|---|---|---|---|---|
| 1 | before B15 fix | 4 valid | 3 | 1: helpee never got the share prompt (B15) |
| 2 | before B15 fix | 6 | 5 | 1: same as above (B15) |
| 3 | **with B15 fix** | 8 | **8** | 0 |

- Every call that reached WebRTC selected `relay → relay` over UDP, 14–54 ms
  round trip, decoded video, and ICE never failed.
- Every failure was B15, before WebRTC started. Batch 3 had none, but the race
  is timing-dependent, so 8 clean calls are strong evidence, not proof.
- **Not covered:** real phones, real mobile data, TCP/TLS TURN only (UDP blocked),
  your ngrok endpoint. Run the relay-only build on your two phones (one on Wi-Fi,
  one on mobile data) for 10 calls, and keep the logs of any failure.
