# Clicky in AssistMe: "Use Clicky" on saved guides

## Feasibility summary

| Question | Answer |
|---|---|
| Can the Clicky repo be dropped into AssistMe? | **No.** Clicky is a macOS menu-bar app (Swift, AppKit, ScreenCaptureKit, CGEvent taps). None of it runs on Android or iOS, and AssistMe is a Flutter phone app. |
| Can Clicky's *idea* run in AssistMe? | **Yes, on Android.** AssistMe already ships an accessibility service that can read on-screen labels and draw overlays. That's everything Clicky needs. |
| iOS? | **Not possible.** iOS does not allow an app to read or draw over other apps. The button is hidden on iOS. |
| Cloud AI like the original Clicky? | **Not used.** Clicky sends screenshots to Claude through a Cloudflare Worker. AssistMe promises guides stay encrypted on-device, so this port matches buttons using the accessibility tree, entirely on the phone. |

## What the user sees

1. They open a saved guide (My Step Guides → a guide) and tap **Use Clicky**.
2. The first time only, a dialog explains why Clicky needs AssistMe's accessibility
   service and opens Settings.
3. AssistMe goes to the home screen. A floating **Clicky card** shows and reads aloud the
   current step. A **blue pointer** flies to the control the step mentions and pulses around it.
4. When the user taps that control, Clicky notices, says "Nice! ✓" and moves to the next step.
   **Back**, **Next**, mute and **✕** are always on the card.
5. After the last step, Clicky says "All done" and closes itself.

Clicky only points. It never taps for the user.

## How it works

```
GuideDetailScreen ─ Use Clicky ─▶ ClickyBridge (Dart, channel com.assistme/clicky)
                                    │  step titles + instructions only (no images/transcript)
                                    ▼
MainActivity ─▶ AssistMeAccessibilityService.startClickyGuide()
                                    ▼
                          ClickyGuideController
                 ├─ ClickyTargetMatcher   which label each step means, and scoring of on-screen labels
                 ├─ accessibility tree    labels + bounds of what's visible (password fields skipped)
                 ├─ TYPE_ACCESSIBILITY_OVERLAY windows: Clicky card + pointer layer
                 ├─ TYPE_VIEW_CLICKED     detects that the user tapped the target and advances
                 └─ Android TextToSpeech  on-device voice (auto-muted when TalkBack is on)
```

**Matching a step to a button.** For each step, Clicky extracts target labels in order:
- Quoted text first: `Tap "Wi-Fi"`, `Open 'Display'`.
- Otherwise action phrases: `Open Settings, then tap the Wi-Fi option` gives `Settings`, `Wi-Fi`.
- Menu paths are split: `Go to Settings > Connections > Wi-Fi`.
- Otherwise a specific step title (not "Step 3").

Labels are compared ignoring case, punctuation and simple plurals, and scripts like
Devanagari keep their vowel marks. Tappable matches win over plain text, so a page header that
repeats an earlier word doesn't steal the pointer.

**Tip for guide writers.** Put the exact on-screen words in quotes ("Tap \"Wi-Fi\"") and
Clicky will point reliably.

## Safety and privacy

- Text-only payload. Screenshots and transcripts never leave the encrypted guide store.
- No network calls and no cloud model.
- Password fields are never read.
- On sensitive screens (banking, wallets, password managers, permission prompts), Clicky
  hides the pointer. It reuses the existing `isSensitiveWindowFocused` check.
- Clicky's own window events are ignored, so they can't clear that sensitive-screen latch.
- If a help call starts, the annotation overlay stops Clicky first, and Clicky refuses to
  start during a call. The two never overlap.
- Accessibility overlays don't need the "draw over apps" permission, and Android 12+ never
  blocks the user's taps through them.

## Files

New:
- `mobile/android/app/src/main/kotlin/com/assistme/clicky/ClickyTargetMatcher.kt`: pure Kotlin, unit tested
- `mobile/android/app/src/main/kotlin/com/assistme/clicky/ClickyGuideController.kt`
- `mobile/android/app/src/test/kotlin/com/assistme/clicky/ClickyTargetMatcherTest.kt`
- `mobile/lib/core/platform/clicky_bridge.dart`
- `mobile/test/clicky_bridge_test.dart`

Changed:
- `guide_detail_screen.dart`: **Use Clicky** button, first-run enable dialog, status messages
- `AssistMeAccessibilityService.kt`: hosts Clicky, forwards events, stops it on unbind/destroy
- `AssistMeAnnotationOverlayService.kt`: a help call stops Clicky
- `MainActivity.kt`: `com.assistme/clicky` channel (`start`, `stop`, `isActive`)
- `accessibility_service_config.xml`: adds `typeViewClicked|typeViewScrolled`
- `AndroidManifest.xml`: TTS `<queries>` entry (needed on Android 11+)
- `strings.xml`: accessibility description now mentions Clicky (honest consent text)
- `app/build.gradle.kts`: `testImplementation("junit:junit:4.13.2")`

## Verifying

```bash
cd mobile
flutter pub get
flutter analyze --no-fatal-infos
flutter test test/clicky_bridge_test.dart
cd android && ./gradlew :app:testDebugUnitTest --tests "com.assistme.clicky.*"
```

Manual check on a real Android phone (Android 11+):
1. Save a guide with steps like `Open "Settings"`, `Tap "Network & internet"`, `Tap "Internet"`.
2. Open it and tap **Use Clicky**. Enable the service when asked, come back, and Clicky starts.
3. Confirm the pointer lands on Settings. Tap it, and the card should advance.
4. Open a banking app. The pointer should hide.
5. Start a help call. Clicky should close.
6. Turn the accessibility service off while Clicky is open. The card should disappear.
7. With TalkBack on, Clicky should start muted.

## Known limits / next steps

- Vague steps ("fix the settings") have no label to point at. Clicky shows the step and
  waits for **Next**. A future fallback could ask the on-device Gemma model (already in
  the app) to choose among the *visible labels*, still fully on-device.
- Icon-only buttons without accessibility labels can't be found.
- English action verbs are recognised. Other languages work through quotes or titles.

## Offline feasibility (helper not available)

**Use case.** The helper and helpee solve a task together on a call. The helper curates the
guide (screenshots, redaction, written steps) and it syncs to both phones when the call ends.
Later, when the helper can't be reached, the helpee opens that guide and taps **Use Clicky**
to be walked through the same steps again.

**Verdict: feasible offline on Android, and shipped that way.** No part of the replay needs
the backend, the internet or a cloud model.

| Part of the replay | Needs network? | Why |
|---|---|---|
| Opening the app | No | `main.dart` picks `/home` from the identity in secure storage. Contacts may fail to load, but the **My Step Guides** button is always in the app bar. |
| Listing and opening a guide | No | `MyGuidesScreen` reads `LocalGuideStore`, the encrypted on-device store. |
| Matching steps to buttons | No | `ClickyTargetMatcher` is pure Kotlin. It reads the accessibility tree on the phone. |
| Card and pointer | No | `TYPE_ACCESSIBILITY_OVERLAY` windows owned by AssistMe's accessibility service. |
| Reading steps aloud | Usually no | Android's own TTS engine. Most phones ship offline voice data for the system language. If none is installed, Clicky stays silent and the card still shows the text. |
| Getting the guide onto the phone | **Yes, once** | The guide arrives during the call (session signaling plus data channel). After it is saved it can be replayed with no connection. |

**What was deliberately not used.** The original Clicky sends screenshots to Claude through a
Cloudflare Worker. An online mode like that isn't needed for this use case, and it would break
AssistMe's promise that guides stay encrypted on the phone. Don't add it without a product
decision and a consent screen.

**What makes replay work well.** Clicky points reliably when a step names the on-screen
label in quotes. To encourage that while the guide is being made:
- The helper's "Write this guide step" dialog shows a quoted example and a tip
  (`assistance_flow_coordinator.dart`).
- The end-of-call review dialog repeats the tip (`local_guide_save_dialog.dart`).
- The on-device Gemma draft prompt asks for exact labels in double quotes
  (`local_guide_ai_service.dart`).

**Limits to keep in mind when replaying offline.**
- If the target app changed its layout or wording since the call, Clicky can't find the label.
  It says what it's looking for and the user can tap **Next**.
- Steps that only exist as screenshots (no written instruction naming a control) can be shown
  but not pointed at.
- iOS can't do this. The button is hidden there; the normal step viewer still works offline.
- Clicky and a live help call never run together, so connecting to a helper later is unaffected.
