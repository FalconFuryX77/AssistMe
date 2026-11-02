# AssistMe v1.2.0

AssistMe now leaves the helpee with something to keep: after a call, the helper's phone turns the session into a private, step-by-step guide, written by AI that runs on the phone itself. **Clicky** then replays that guide offline on the helpee's phone, reading each step aloud and pointing at the button to press. Calls are also much more reliable across networks, Wi-Fi to mobile-data switches and reconnects.

Watch the [2.5-minute explainer](https://github.com/FalconFuryX77/AssistMe/blob/main/docs/media/assistme-explainer.mp4).

## New

- **Private guides from every call.** One tap captures a step during the call, with nothing to type. After the call the helper reviews each screenshot full screen, covers private details with solid blocks (or taps **Skip all**), and the steps are written automatically from the call.
- **On-device AI.** Whisper tiny transcribes the call (only with the helpee's consent, at most 20 minutes, deleted after use) and Gemma 4 E2B drafts the steps. Both run locally through LiteRT and download once, on request. The app checks the phone first and explains clearly when it can't run them.
- **Encrypted guide delivery.** Guides reach the helpee over the call's data channel, or later as AES-GCM ciphertext the server can't read, collected next time the app opens.
- **Clicky.** An offline walkthrough over any app: a floating card speaks each step, and a pointer flies to the control to tap.
  - Steady pointer: it waits for the screen to settle, stays on the target, and glides when the page scrolls.
  - Understands that "Done", "Apply" or "OK" can stand in for "Next", and moves on when you're already ahead.
  - Press-and-hold and swipe steps outline the whole screen.
  - **Back** takes the phone back to the earlier step's screen; **✕** returns to the guide.
  - Falls back to another speech engine when the phone's default refuses (some Samsung phones).
  - Not offered on guides the helper made, since those follow the helpee's phone.

## Improved

- **Calls survive network changes.** Switching between Wi-Fi and mobile data reconnects signaling at once and renegotiates media. A helper who comes back no longer triggers a false "disconnected, auto-leaving" countdown on the helpee.
- **Multi-worker backend.** Call offers reach the other phone whichever backend worker it is connected to; offers for a phone that isn't connected yet are held briefly and replayed.
- **Abandoned calls end by themselves** after five minutes with nobody connected.
- **Drawing accuracy.** Strokes land exactly where the helper drew, including above the notification shade.
- **Helpee toolbar.** Translucent, folds itself away, and never blocks the helper's taps or appears black in the shared screen.
- Faster call exit, reliable re-sharing after the lock screen, and video recovery after reconnects.

All bugs found while testing on real phones, with their causes and fixes, are in [`docs/BUGS.md`](https://github.com/FalconFuryX77/AssistMe/blob/main/docs/BUGS.md).

## Project

- New README, a file-by-file [codebase guide](https://github.com/FalconFuryX77/AssistMe/blob/main/docs/CODEBASE_GUIDE.md), and the explainer video.
- Licensed under the [PolyForm Noncommercial License 1.0.0](https://github.com/FalconFuryX77/AssistMe/blob/main/LICENSE): free for personal, research and educational use; commercial use needs written permission.

## Install

- **Android APK:** `AssistMe-v1.2.0.apk` below, for Android 11 or later. Turn on the AssistMe accessibility service for remote control and Clicky.
- The build points at the author's demo server, which is only online during demos. To run your own, follow the backend steps in the README and set the address under **Settings → Custom Backend Server**.
- On-device AI needs a 64-bit ARM phone with several GB of RAM; models download from Hugging Face on request (about 2.75 GB).
