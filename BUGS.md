# AssistMe bug log

Bugs found while integrating Clicky and testing the guide + on-device AI flow
end to end (branch `feature/clicky-offline-guides`, 2026-10-29/30).

Test setup used: two emulators on one PC (helpee: Android 14 / API 34, helper:
Android 16 / API 36, both x86_64), an isolated backend on port 8100 with its own
SQLite file, debug APK. Emulators **cannot run Gemma or Whisper** (the AI
engine ships for 64-bit ARM only), so the AI calls themselves still need a real
phone. Everything else below was exercised on the emulators.

Status key: **FIXED** (in this branch, verified), **OPEN** (still needs work),
**SUSPECTED** (seen, root cause not proven).

---

## FIXED

### B1. Call transcript never reached the AI (any phone, any Android version)
- **Where:** `assistance_flow_coordinator.dart` (`_handleGuideAudioCaptureCommand`, `_offerLocalGuideSave`).
- **What:** Call audio was recorded on the **helpee's** phone. At hang-up the helpee
  deleted it (`_stopGuideAudioCapture(discard: widget.isHelpee)` + `_deletePendingGuideAudio()`),
  and the helper's save dialog was opened with `audioRecordings: const []`. So
  "Transcribe call locally" never appeared and Gemma only ever saw typed notes.
- **Fix:** the helper's phone records (its mic = helper, its call playback = helpee),
  after the helpee consents. Helpee revoke/mute/disconnect still stops it; revoke
  discards it. The recordings are handed to the save dialog, which deletes them.
  Consent text updated to say where the audio is kept.
- **Verified:** helper cache shows `…-mic.mp4` and `…-remote.mp4` growing; helpee has
  none; save dialog shows "Transcribe call locally"; files deleted after save.

### B2. "Add redacted step to guide" (capture moment) button permanently disabled
- **Where:** `mobile_workspace_screen.dart` (was line 262).
- **What:** `onPressed: _flowCoordinatorKey.currentState?.captureGuideStep` is read on
  the first build, when the coordinator state does not exist yet, so `onPressed` was
  `null` for the whole call unless something else rebuilt the screen.
- **Fix:** `onPressed: () => _flowCoordinatorKey.currentState?.captureGuideStep()`.
- **Verified:** button turns green and captures a frame.

### B3. Red error screen after "Add step" (`'_dependents.isEmpty': is not true`)
- **Where:** `_requestGuideStepDetails` in `assistance_flow_coordinator.dart`.
- **What:** the step dialog's text controllers were disposed in `finally` right after
  `showDialog` returned, while the dialog was still animating closed.
  Debug builds crash to a red screen; release behaviour is undefined.
- **Fix:** new `guide_step_details_dialog.dart` owns and disposes its controllers.
- **Verified:** step added without error on the second run.

### B4. AI failed on some phones with only "Local generation failed"
- **Cause (confirmed from the build):** `libLiteRtLm.so` (Gemma) and the Whisper backend
  ship for `arm64-v8a` only. Flutter also packages `armeabi-v7a`, so the app installs
  and calls work on a 32-bit Android phone, but the AI has no engine there. Gemma 4
  E2B also needs several GB of RAM, and generation was always forced onto the GPU.
- **Fix:** `local_ai_device_support.dart` (native `com.assistme/local_ai_device`
  channel: ABI actually loaded, LiteRT library present, RAM, free space, Android
  version) decides full / text-only / unsupported and says why. The AI service:
  - shrinks screenshots and the context window on lower-RAM phones;
  - stays on the CPU after a GPU load ever kills the app;
  - releases the model after each batch;
  - shows a specific error message instead of a generic one.
- **Verified on emulator:** shows "This is an emulator (x86_64)…" in Settings, in the
  save dialog and on Transcribe. **Not verified:** a real Gemma run on a real phone.

### B16. Release builds said "AI engine is not installed" on 64-bit phones
- **Where:** `MainActivity.localAiDeviceInfo()` (added with B4).
- **What:** the check looked for `libLiteRtLm.so` in the app's native-library
  folder. Release builds use `extractNativeLibs=false`, so Android loads the
  library straight from the APK and the folder is empty. Galaxy M34
  (arm64-v8a, Android 16) was wrongly told the AI could not run.
- **Fix:** `hasNativeLibrary()` also looks for `lib/<abi>/libLiteRtLm.so` inside the
  installed APK files.
- **Verified on the Galaxy M34:** "Reads screenshots and transcripts · arm64-v8a ·
  5.3 GB RAM", Download models enabled.

### B17. Gemma download always failed ("The model download did not finish")
- **Where:** `LocalGuideAiService.installModel` (`.fromHuggingFace(repo)` with no file).
- **What:** without a file name the plugin first fetches
  `…/resolve/main/litertlm_manifest.json`. `litert-community/gemma-4-E2B-it-litert-lm`
  is public and not gated, but it ships **no manifest** (HTTP 404), so every
  install failed before any download started, on every network. The error was
  then shown as the generic "did not finish".
- **Fix:** download `gemma-4-E2B-it.litertlm` (2,588,147,712 bytes) explicitly,
  pinned to commit `1caa527c1e88b55f046fcd8d2b4265606680663d`. Download errors now
  include the first line of the real reason. Whisper URLs were checked and work.
- **Verified on the Galaxy M34 (Wi-Fi):** Gemma 4 downloaded in ~12 min, then
  Whisper; "Test on this phone" → `Gemma works on this phone (GPU). Loaded in 48 s,
  answered in 6 s`, output `TITLE: Open Settings / ACTION: Tap "Settings"`.
  Android's low-memory killer closed two other apps during the load; AssistMe
  survived. Note: the model is released after each batch, so every "Improve
  steps" press pays the ~48 s load again.

### B5. Steps without a screenshot could not be made or synced
- **Fix:** "Add a written step" and "Write steps from the transcript" in the save
  dialog. The store saves steps with no image; the sync sends `has_image: false`.
- **Verified:** written step synced to helpee, and Clicky walked it to "All done".

### B6. 2.6 GB Gemma download only started at hang-up
- **Fix:** Settings → "On-device guide AI": shows support status, downloads Gemma +
  Whisper ahead of time, and "Test on this phone" runs a short self-test.

### B15. Helper stuck on "Waiting for the other device to share…" (start-up race)
- **Where:** `assistance_flow_coordinator.dart` (`_bootstrap`, `startScreenShare`,
  `_handleRealtimeConnected`).
- **What:** `_bootstrap()` starts the signaling socket and media setup in
  parallel. If media finishes first, the helpee's auto-start calls
  `startScreenShare()`, which refuses because the socket is not open yet. When
  the socket opens a few ms later, `_handleRealtimeConnected` returns early
  because `_bootstrapping` is still true. Nothing retries, so the helpee never
  shows the capture prompt and the helper waits forever. Timing-only, so it can
  happen on any phone or network. Likely the cause of the handover's P0 "helper
  shows Waiting… while sharing never starts" reports.
- **Evidence:** helpee log `00:52:35.391 refusing to start screen share because
  signaling websocket is disconnected` then `00:52:35.475 websocket connected …
  shareActive=false bootstrapping=true`; 2 of 14 relay-test calls failed this way.
- **Fix:** remember that the share was waiting for signaling and start it from
  `_handleRealtimeConnected`; guard `startScreenShare` against running twice.
  Verification results are in `YET_TO_FIX.md`.

### B7. Helper's audio button said "…on the other phone"
- **Fix:** now "Start/Stop recording guide audio" (`mobile_voice_control_bar.dart`).

---

## OPEN

### B8. Sessions left "active" forever when an app dies mid-call (FIXED in code)
- **Evidence:** `SessionService.check_and_expire_sessions()` (`backend/api/services/session_service.py:591`)
  is never called anywhere. After the apps were killed mid-call, the backend log
  shows four connections polling `GET /sessions/a493e69b-…` every second, and the
  session stayed `active` until it was ended by hand in the test DB.
- **Real installs:** yes. An app crash (for example out of memory while Gemma runs),
  battery death, swipe-away or loss of network during a call leaves the same state.
- **Fix (backend code + tests; not yet deployed):** every worker runs
  `run_session_sweeper` (started in `app.py` lifespan). Every 30 s it stamps
  `last_seen_at` for the session sockets that worker holds, then
  `SessionService.expire_abandoned_sessions` ends waiting/active sessions with no
  stamp for 5 min (the existing reconnect grace). This covers crashed or dead
  phones, phones that never opened the socket, and grace timers lost on a backend
  restart. Clients already stop polling once a session reads `ended`.
- **Second bug found and fixed here:** the backend runs `--workers 4`, and the
  5-minute grace timer lives in the worker where the socket dropped. A phone that
  reconnected through another worker never cancelled it, so the call was ended
  5 minutes later while still in progress. `terminate_on_disconnect` now does
  nothing if the participant is `connected` again in the database.
- `check_and_expire_sessions` (ends any call 60 min after it *started*) is still
  deliberately unused: it would cut long but healthy calls.

### B9. Guide screenshots include the helpee's own AssistMe toolbar
- **Evidence:** the saved guide image shows the floating "Draw / STOP" overlay bar.
- **Fix (written and compiling, NOT yet verified on a device):** the toolbar window and its
  colour/thickness pickers use `FLAG_SECURE`, so screen sharing shows a blank (black)
  area instead of the buttons. Helper gestures pass through it:
  `AssistMeAccessibilityService.dispatchInput` makes the toolbar `FLAG_NOT_TOUCHABLE`
  (`AssistMeAnnotationOverlayService.beginRemoteGesture/endRemoteGesture`), waits
  60 ms, injects the gesture, then restores it. The helpee's own touches are unchanged.
- **To verify:** in a call, (1) the helper sees a black box where the toolbar is;
  (2) with control approved, a helper tap on that box hits the app underneath and
  does NOT trigger STOP; (3) the helpee can still tap STOP / Draw. Watch for OEMs
  (Samsung, ColorOS) that black out the whole capture when a secure window shows.

### B10. Helper sees a black screen until the helpee's screen changes
- **Evidence:** call 2: ICE connected, `videoFramesDecoded: 1`, then 0 fps for more
  than 30 s while the helpee sat on a static screen; frames resumed (3, then 12)
  as soon as the helpee's screen changed. Capturing a guide step during that time
  can grab a black frame. Android screen capture only emits frames on change.
- **Fix idea:** keep the last decoded frame on screen (do not clear the renderer),
  and/or have the helpee re-send a keyframe periodically (e.g. a 1-px overlay
  toggle or a periodic `RTCRtpSender` keyframe request) while sharing.
  Related to the handover's P0 "no remote frames" item, which may share this cause.

### B11. Clicky's card swallows swipes that start on it
- **Evidence:** a swipe up for the app drawer that began on the card (bottom of
  screen) did nothing; it only worked from above the card.
- **Fix idea:** make the card smaller when there's no target, or let the user drag
  it, or add a "move card up" button.

### B12. Long AI generation happens while the call is still open
- **What:** by design the helper's save dialog opens before hang-up so the guide
  syncs over the live data channel. Transcription and Gemma can take minutes on a
  phone. If the helpee hangs up meanwhile, the guide is saved only on the helper
  ("other device could not be reached"), with no later retry.
- **Fix (code + unit tests; not yet tested on phones):** delivery no longer depends
  on the call. The helper's phone makes a random key per call and sends it to the
  helpee only over the peer data channel (`guide_frame_sync_key`). If the live
  sync fails, the guide (steps + screenshots) is AES-GCM encrypted on the helper
  and uploaded to the new `/guide-deliveries` API; failed uploads wait in an outbox
  and are retried every 60 s from Home. The helpee's Home checks every 60 s,
  downloads, decrypts, saves and deletes it (skipping it if the live sync already
  delivered that session). The backend only holds ciphertext, for at most 7 days.
- **Deploy:** the live backend needs the new code and migration
  `f6c3b8e1a920_guide_deliveries` (rebuild the backend image, then `alembic upgrade head`).
- **Limit:** if the data channel never opened, the helpee never got the key and
  cannot open a post-call delivery (but then no screenshots were sent either).

### B20. Captured screenshots saved on neither phone
- **Cause:** the helper kept a step only after the helpee confirmed it. Any failure
  lost it on both phones: an aggressive 9×8 "duplicate" check (similar screens
  rejected), full-size PNGs over the 2 MB limit, a stale unfinished transfer on
  the helpee blocking every later one, or an ack timeout.
- **Fix (code + tests; not yet tested on phones):** the helper keeps each step first;
  sending to the helpee is best effort; screenshots are shrunk to ≤1280 px;
  helper-chosen steps skip the duplicate check; the helpee replaces stale
  transfers; missing screenshots are resent on save, and a step whose image
  still never arrives is saved as text instead of failing the guide. The helpee
  now waits up to 5 min for the helper to finish.

### B18. "Step 1 of 0" on guides saved with notes only
- **Fix:** the viewer shows "Session notes" for a guide with no steps.

### B19. Helper drawings disappeared behind the notification panel
- **Cause:** the helpee's drawing layer and toolbar were `TYPE_APPLICATION_OVERLAY`
  windows, which Android always draws *below* the notification shade.
- **Fix (compiles; not yet tested on phones):** when AssistMe's accessibility
  service is on, both windows are `TYPE_ACCESSIBILITY_OVERLAY`, which Android draws
  above the shade. Without the service it falls back to the old behaviour.

### B13. TURN depends entirely on Metered; failure silently means "no TURN"
- **Evidence (live backend container, names/hosts only, no secrets read):**
  `TURN_SERVER_URL=turn:coturn:3478` and `STUN_SERVER_1=stun:coturn:3478` use the
  Docker-internal hostname `coturn`, which phones cannot resolve, and
  `PUBLIC_TURN_URL` is empty. `webrtc_service.get_ice_servers()` drops any
  `coturn` URL, so the only TURN source is the Metered API. Right now it returns
  `turn:in.relay.metered.ca:80/443` + `turns:…:443`, so TURN works. If that HTTP
  call fails and there is no cached copy, it returns **STUN only** and the
  only sign is the client log line `ICE configuration has no TURN relay`.
  Cross-network calls then fail, which matches the handover's "works sometimes" reports.
- **Fix idea:** log/alert when Metered fails; return an error (or a static
  `PUBLIC_TURN_URL` fallback) instead of silently going STUN-only; show
  "relay unavailable" in the call UI's diagnostics.

### B14. The local coturn container cannot relay for phones
- **Evidence:** running container has `EXTERNAL_IP=0.0.0.0`, so the relay addresses
  it advertises are unusable, and `turnserver.conf` denies peers in 10/8,
  172.16/12 and 192.168/16, which includes its own container address. ngrok
  cannot carry TURN's UDP either. So the self-hosted coturn is not a working TURN
  path for real phones; only Metered is.
- **Fix idea:** if self-hosted TURN is wanted, run coturn on a host with a public
  IP, set `EXTERNAL_IP` to it, open 3478 + the relay port range, and set
  `PUBLIC_TURN_URL=turn:<public-host>:3478` with the long-term credentials.

---

## SUSPECTED

### S1. Call button appeared to do nothing after an interrupted call
- Seen after the apps were reinstalled mid-call. No `/help/…` request reached the
  backend for several taps; it worked after the stale session (B8) was ended and
  the app restarted, but the Call dialog was also very slow (5–10 s) on the
  emulator. A later batch where "Call" seemed dead turned out to be the helpee's
  late screen-capture prompt covering the app (B15), not the button. Not
  reproduced on its own. Re-check on a phone: force-stop the app mid-call,
  reopen, call again.
- **Related, real:** after a phone restart mid-call, the helpee app rejoined the
  old session by itself and asked to share again (seen once). That is the
  intended recovery, but combined with B8 an abandoned session can be rejoined
  much later.

---

## Notes for testers (not app bugs)

- Running `uiautomator dump` (or any UI Automator tool) makes Android shut down
  every other accessibility service, including AssistMe's, so Clicky disappears.
  Drive Clicky tests with taps and screenshots only.
- Reinstalling the debug APK switched AssistMe's accessibility service off; Clicky
  then asks to turn it on again. Re-check whether a normal update keeps it on.
- Typing into Flutter fields with `adb shell input text` drops characters on these
  emulators, and Gboard may show a stylus tutorial that swallows input.
