/// Mobile WebRTC PeerConnection & MediaStream Engine Wrapper.
///
/// Real implementation on top of flutter_webrtc:
///  - RTCPeerConnection configured with STUN/TURN servers fetched from the
///    backend (`/sessions/{id}/ice-servers`).
///  - Screen capture via `getDisplayMedia` (Android MediaProjection consent +
///    flutter_webrtc's foreground service).
///  - Two-way microphone audio via `getUserMedia`.
///  - SDP offer/answer and trickle ICE exposed as plain maps so the session
///    controller can relay them through RealtimeService (`signal_offer`,
///    `signal_answer`, `signal_ice_candidate`).
library;

import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:permission_handler/permission_handler.dart';

enum WebRTCEngineState {
  uninitialized,
  initializing,
  connected,
  disconnected,
  failed,
}

class WebRTCEngine {
  WebRTCEngineState _state = WebRTCEngineState.uninitialized;
  bool _isScreenSharing = false;
  bool _isAudioMuted = false;

  RTCPeerConnection? _pc;
  MediaStream? _micStream;
  MediaStream? _screenStream;

  /// Remote media (helper's mic / helpee sees nothing video-side) arrives here.
  void Function(MediaStream stream)? onRemoteStream;

  /// Trickle ICE candidates generated locally; relay to the remote peer.
  void Function(Map<String, dynamic> candidate)? onLocalCandidate;

  /// Peer connection state transitions for UI status display.
  void Function(WebRTCEngineState state)? onStateChanged;

  WebRTCEngineState get state => _state;
  bool get isScreenSharing => _isScreenSharing;
  bool get isAudioMuted => _isAudioMuted;
  RTCPeerConnection? get peerConnection => _pc;

  Future<void> initialize({required List<Map<String, dynamic>> iceServers}) async {
    if (_pc != null) return;
    _setState(WebRTCEngineState.initializing);
    try {
      _pc = await createPeerConnection(
        {
          'iceServers': iceServers,
          'sdpSemantics': 'unified-plan',
        },
        {
          'mandatory': {},
          'optional': [
            {'DtlsSrtpKeyAgreement': true},
          ],
        },
      );

      _pc!.onIceCandidate = (candidate) {
        onLocalCandidate?.call(candidate.toMap());
      };
      _pc!.onTrack = (event) {
        if (event.streams.isNotEmpty) {
          onRemoteStream?.call(event.streams.first);
        }
      };
      _pc!.onConnectionState = (state) {
        switch (state) {
          case RTCPeerConnectionState.RTCPeerConnectionStateConnected:
            _setState(WebRTCEngineState.connected);
            break;
          case RTCPeerConnectionState.RTCPeerConnectionStateFailed:
            _setState(WebRTCEngineState.failed);
            break;
          case RTCPeerConnectionState.RTCPeerConnectionStateClosed:
          case RTCPeerConnectionState.RTCPeerConnectionStateDisconnected:
            _setState(WebRTCEngineState.disconnected);
            break;
          default:
            break;
        }
      };

      _setState(WebRTCEngineState.connected);
    } catch (e) {
      _setState(WebRTCEngineState.failed);
      rethrow;
    }
  }

  // ---------------------------------------------------------------------------
  // Local media
  // ---------------------------------------------------------------------------

  /// Start sharing this device's screen (helpee side).
  ///
  /// Triggers the Android MediaProjection consent dialog via flutter_webrtc's
  /// native pipeline, then attaches the screen video track + microphone to the
  /// peer connection.
  Future<void> startScreenCapture({String platform = 'android'}) async {
    if (_pc == null) {
      throw StateError('initialize() must be called before startScreenCapture()');
    }
    await _ensurePermissions();

    final screen = await navigator.mediaDevices.getDisplayMedia({
      'video': true,
      // System/internal audio capture is only reliable on Android 10+ and is
      // not needed while the mic carries the elderly person's voice.
      'audio': false,
    });
    _screenStream = screen;

    for (final track in screen.getVideoTracks()) {
      await _pc!.addTrack(track, screen);
    }
    _isScreenSharing = true;

    await _addMicrophone();
  }

  /// Join with microphone only (helper side — receives video, sends voice).
  Future<void> startMicOnly() async {
    if (_pc == null) {
      throw StateError('initialize() must be called before startMicOnly()');
    }
    await _ensurePermissions();
    await _addMicrophone();
  }

  Future<void> _addMicrophone() async {
    if (_micStream != null) return;
    final mic = await navigator.mediaDevices.getUserMedia({
      'audio': true,
      'video': false,
    });
    _micStream = mic;
    for (final track in mic.getAudioTracks()) {
      await _pc!.addTrack(track, mic);
    }
  }

  Future<void> stopScreenCapture() async {
    if (_screenStream != null) {
      for (final track in _screenStream!.getTracks()) {
        await track.stop();
      }
      await _screenStream!.dispose();
      _screenStream = null;
    }
    _isScreenSharing = false;
  }

  Future<void> toggleAudioMute(bool mute) async {
    _isAudioMuted = mute;
    final tracks = _micStream?.getAudioTracks() ?? const <MediaStreamTrack>[];
    for (final track in tracks) {
      track.enabled = !mute;
    }
  }

  // ---------------------------------------------------------------------------
  // Signaling primitives (plain maps so RealtimeService can relay them)
  // ---------------------------------------------------------------------------

  Future<Map<String, dynamic>> createOffer() async {
    final offer = await _pc!.createOffer({
      'offerToReceiveVideo': !_isScreenSharing,
      'offerToReceiveAudio': true,
    });
    await _pc!.setLocalDescription(offer);
    final desc = await _pc!.getLocalDescription();
    return {'type': desc!.type, 'sdp': desc.sdp};
  }

  Future<Map<String, dynamic>> createAnswer() async {
    final answer = await _pc!.createAnswer({
      'offerToReceiveVideo': true,
      'offerToReceiveAudio': true,
    });
    await _pc!.setLocalDescription(answer);
    final desc = await _pc!.getLocalDescription();
    return {'type': desc!.type, 'sdp': desc.sdp};
  }

  Future<void> setRemoteDescription(Map<String, dynamic> sdp) async {
    await _pc!.setRemoteDescription(
      RTCSessionDescription(sdp['sdp'] as String?, sdp['type'] as String?),
    );
  }

  Future<void> addIceCandidate(Map<String, dynamic> candidate) async {
    await _pc?.addCandidate(
      RTCIceCandidate(
        candidate['candidate'] as String?,
        candidate['sdpMid'] as String?,
        candidate['sdpMLineIndex'] as int?,
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  void _setState(WebRTCEngineState next) {
    _state = next;
    onStateChanged?.call(next);
  }

  Future<void> _ensurePermissions() async {
    final mic = await Permission.microphone.request();
    if (mic.isDenied || mic.isPermanentlyDenied) {
      throw StateError('Microphone permission needed - please allow it in settings');
    }
  }

  Future<void> dispose() async {
    try {
      await stopScreenCapture();
      if (_micStream != null) {
        for (final track in _micStream!.getTracks()) {
          await track.stop();
        }
        await _micStream!.dispose();
        _micStream = null;
      }
      await _pc?.close();
      _pc = null;
    } finally {
      _isScreenSharing = false;
      _isAudioMuted = false;
      _setState(WebRTCEngineState.disconnected);
    }
  }
}
