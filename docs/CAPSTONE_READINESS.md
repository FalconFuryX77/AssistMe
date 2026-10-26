# Capstone Readiness: Local Guides and Restricted-Network Calls

Updated 2026-10-26.

## Current status

- The legacy cloud guide endpoint is disabled. Mobile screenshots are no longer
  uploaded when a call ends, and the backend rejects new guide image uploads.
- Screenshots are captured in memory on each participant's device when a step
  is bookmarked or annotation settles. They are deduplicated and bounded by a
  byte budget, then discarded with the session. There is no persistent local
  guide yet, and no transcript is collected.
- Live audio and screen video still travel to the other call participant over
  WebRTC as part of assistance. The local-only guarantee applies to the future
  guide-generation path; it does not hide a shared screen from the helper.
- Preview annotations use a separate lossy channel with bounded queuing, while
  completed strokes use the reliable channel. ICE diagnostics report transport
  metrics without candidate IP addresses. Failed ICE now gets one TURN-only
  retry if relay credentials were supplied.

## Gemma 4 feasibility and constraints

Gemma 4 E2B can run locally and accept both images and audio. The published
LiteRT-LM bundle is about 2.6 GB; multimodal inference is recommended for
devices with at least 8 GB RAM. Published fast timings are from flagship phones
and should not be assumed for the capstone handset. Flutter integration is
community-maintained. Its current LiteRT package requires Android API 30 or
newer and 64-bit ARM, and iOS 15 or newer. AssistMe currently uses Flutter
3.38.5 locally, so model integration also requires a Flutter toolchain upgrade.

These constraints make Gemma 4 a good privacy-aligned prototype for the demo
phone, but not a universally available feature across older devices. Keep the
model optional, show the model download size and progress, and do not download
it during a call. The initial model download needs internet; inference and
guide creation can then work offline. Do not fall back to cloud inference.

## Recommended guide workflow

1. Generate the guide on the helpee's phone, where the original screen exists.
   Keep screenshots, audio chunks, and model prompts on that device.
2. Prefer explicit bookmarks for meaningful steps. The current automatic
   capture after every settled drawing can still save near-duplicate or
   context-free screens even with perceptual deduplication.
3. Add explicit, opt-in on-device transcription of the helper's instructions.
   AssistMe currently streams call audio but does not create a transcript.
   Keep only the text needed for the guide; discard raw audio after processing.
4. Give Gemma the nearby bookmarked screenshot and corresponding transcript
   segment, not the entire call. Ask for a concise action, visible evidence,
   and uncertainty. Never let the model invent taps or labels that are not
   visible in the screenshot or stated in the transcript.
5. Let the helpee review and edit generated steps before saving. Clearly mark
   model-generated content and allow deleting a step or the whole guide.
6. Persist guides only on-device. Exclude guide files from OS cloud backup,
   apply platform file protection, and provide a delete-all control. Do not
   reuse the cloud guide API for screenshots or transcript text.

For screenshot privacy, local inference means the screenshot is not sent to an
LLM provider. A local OCR pass can identify likely passwords, email addresses,
phone numbers, and account identifiers; blur those regions in the saved guide
image and allow a user to inspect the result. OCR is imperfect, so use a
pre-generation review step and a visible pause/delete control instead of
promising automatic detection will catch every secret.

## Restricted-network call plan

1. Configure a reachable TURN/TLS service at TCP 443 with valid credentials.
   A TURN server cannot share the same public IP:443 binding with Nginx; use a
   managed relay hostname or a separate relay IP.
2. Keep direct ICE as the first attempt for low latency. If it fails and TURN
   is advertised, the client now makes one relay-only retry and renegotiates.
3. Test two phones on the actual college Wi-Fi, then compare with mobile data.
   Confirm debug metrics show `localCandidateType: relay` on the campus test.
   If no relay candidate appears, verify DNS, TCP 443 reachability, TURN/TLS
   certificate, username/password, and provider credential expiry.
4. Record setup success, time to first video/audio, RTT, jitter, and packet loss
   for direct and relayed calls. A relay fixes reachability; it can increase
   media latency because traffic takes an additional route.
5. Test annotation drawing while video is active. Preview updates may be
   dropped under congestion by design; completed strokes must still arrive
   reliably and must not appear after a newer committed stroke.

## Remaining implementation and acceptance work

- Upgrade and pin the Flutter toolchain supported by the selected LiteRT
  package, then add a local Gemma model manager and an explicit download flow.
- Build the on-device transcript-to-guide pipeline and local guide library;
  confirm no screenshot, transcript, or prompt is sent to AssistMe's backend.
- Add local OCR redaction and a review screen, then test it with synthetic
  passwords, email addresses, phone numbers, and account IDs.
- Run a long call on the capstone device and measure memory, heat, battery,
  model latency, and output quality. The 2.6 GB bundle and memory use may make
  Gemma 4 E2B unsuitable on lower-memory phones.
- Run the two-device campus Wi-Fi test with a real TURN/TLS 443 provider. The
  code change alone cannot confirm that the relay endpoint is reachable.
- Apply database migration `e5b7a2d91c40` in deployed environments to purge
  legacy guide image URLs from existing guide rows.
- The repository scan found no remaining service-account JSON/private key in
  reachable Git history. The exposed Google key shown in the alert was a
  service-account key in project `assistme-8332b`; Google said it was
  restricting that credential. Verify in Cloud Console that it is disabled or
  deleted before making the repository public. GitHub's secret-scanning alerts
  endpoint was unavailable for this repository, so it did not provide a second
  independent scan result.
