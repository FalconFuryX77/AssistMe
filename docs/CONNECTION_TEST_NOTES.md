# Two-device connection test

Date: 2026-10-28

## Devices and build

- A069P (`00331663K000635`) and Samsung M346B (`RZCW82DJ4DZ`) both installed and launched the debug APK built from commit `1e66b45`.
- A069P placed a help call to M346B; M346B received and accepted the request.
- A069P granted Android screen-capture consent. M346B received screen video.

## Observed transport

- The live ICE configuration on both devices contained no TURN relay. The app logged `ICE configuration has no TURN relay`.
- The initial session selected a direct UDP host path. M346B reported 10–33 ms RTT, then packet loss rose (44 and 76 packets in diagnostic samples) and incoming video fell to 0 FPS.
- M346B's ICE state changed from connected to disconnected and then failed. The media connection did not remain stable for the full test.
- A new attempt also used STUN-only configuration and later failed. A relay fallback could not run because no TURN server was returned by the backend.
- The remote video was visible within a few seconds after Android's screen-sharing consent was accepted. This was an observation, not a controlled first-frame benchmark.

## What remains

- Configure a public TURN relay in the backend and confirm `/sessions/{id}/ice-servers` returns it. For campus and enterprise firewalls, include a reachable TURN/TLS endpoint over TCP 443. The ngrok HTTP/WebSocket tunnel does not relay WebRTC media.
- Retest on the college network with the selected candidate verified as `relay`, then repeat call, screen-share, audio, and annotation checks. The annotation gesture was not validated after ICE failed; call audio was not audibly verified.
- The direct-path call started, but it was not stable enough to call the overall flow reliable. Preserve ICE state, packet-loss, FPS, and RTT logs during the next run.
- A brief landscape capture showed a Flutter bottom-overflow warning. Verify the call layout in both portrait and landscape during the UI pass.
- A second test with one phone on Wi-Fi and the other on mobile data again returned STUN-only settings. M346B showed 197 ms RTT, packet loss, 0 incoming video FPS, and then ICE failed. The helper saw a blank viewport; audio was not audibly verified on that cross-network attempt.
- The app tried one fresh direct-path offer after ICE failure, then stopped retrying. It could not recover because no TURN relay was configured. Annotations may fall back to WebSocket, which explains why they can still arrive while being noticeably slower.
- Drawing previews now carry stroke IDs and per-stroke sequence numbers; the receiver drops delayed previews after a newer preview or committed stroke. WebSocket fallback previews are coalesced to 10 per second to limit stale TCP backlog.
- The helper viewport now keeps an accessible connection message visible until the first video frame is actually rendered; screen capture status no longer claims the helper can already see video.

## Startup change in this build

The call bootstrap now starts realtime signaling alongside ICE lookup and local media preparation. This removes the avoidable sequential wait between independent setup paths. It does not remove Android's screen-capture consent or the video-track negotiation and first-frame delay.
