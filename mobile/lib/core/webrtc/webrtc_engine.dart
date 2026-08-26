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
import 'package:flutter_background/flutter_background.dart';
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
  bool _backgroundServiceActive = false;
  List<Map<String, dynamic>> _iceServers = const [];

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

  Future<void> initialize({
    required List<Map<String, dynamic>> iceServers,
  }) async {
    if (_pc != null) return;
    _setState(WebRTCEngineState.initializing);
    try {
      _iceServers = List<Map<String, dynamic>>.from(iceServers);
      await _createPeerConnection();
      _setState(WebRTCEngineState.connected);
    } catch (e) {
      _setState(WebRTCEngineState.failed);
      rethrow;
    }
  }

  Future<void> _createPeerConnection() async {
    _pc = await createPeerConnection(
      {'iceServers': _iceServers, 'sdpSemantics': 'unified-plan'},
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

    // Reattach existing local tracks when a transient transport reconnect
    // replaces the peer connection. The MediaProjection stream stays alive.
    for (final track
        in _screenStream?.getVideoTracks() ?? const <MediaStreamTrack>[]) {
      await _pc!.addTrack(track, _screenStream!);
      await _tuneVideoSender(track);
    }
    for (final track
        in _micStream?.getAudioTracks() ?? const <MediaStreamTrack>[]) {
      await _pc!.addTrack(track, _micStream!);
    }
  }

  /// Rebuild signaling state without stopping MediaProjection or the mic.
  ///
  /// A WebSocket reconnect does not make the old ICE/SDP negotiation usable
  /// again. Reusing that peer connection is why the first screen share worked
  /// but a rejoined session often showed a blank viewport. Keep local tracks,
  /// replace only the peer connection, and let the coordinator negotiate a
  /// fresh offer/answer.
  Future<void> rebuildPeerConnection() async {
    if (_iceServers.isEmpty) {
      throw StateError('initialize() must be called before rebuilding');
    }
    _setState(WebRTCEngineState.initializing);
    final old = _pc;
    _pc = null;
    try {
      await old?.close();
      await _createPeerConnection();
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
      throw StateError(
        'initialize() must be called before startScreenCapture()',
      );
    }
    await _ensurePermissions();

    // Android requires a foreground execution grant while MediaProjection is
    // active. Without this, newer Samsung/Android builds can terminate the
    // app immediately after the user approves the system capture dialog.
    if (WebRTC.platformIsAndroid &&
        !FlutterBackground.isBackgroundExecutionEnabled) {
      const config = FlutterBackgroundAndroidConfig(
        notificationTitle: 'AssistMe screen sharing',
        notificationText: 'Your screen is being shared with your helper.',
        notificationImportance: AndroidNotificationImportance.normal,
        notificationIcon: AndroidResource(
          name: 'ic_launcher',
          defType: 'mipmap',
        ),
      );
      final initialized = await FlutterBackground.initialize(
        androidConfig: config,
      );
      if (!initialized) {
        throw StateError('Android could not prepare screen sharing');
      }

      // Android 14+ requires the user to grant MediaProjection before a
      // mediaProjection foreground service is started. Calling
      // enableBackgroundExecution() first is exactly what made the old flow
      // crash after the system consent sheet was accepted. flutter_webrtc
      // stores this consent result, so the service can be started safely
      // between the permission step and getDisplayMedia().
      final granted = await Helper.requestCapturePermission(
        fullScreenOnly: true,
      );
      if (!granted) {
        throw StateError('Screen capture permission was not granted');
      }

      final enabled = await FlutterBackground.enableBackgroundExecution();
      if (!enabled) {
        throw StateError(
          'Android could not start the screen-sharing foreground service',
        );
      }
      _backgroundServiceActive = true;
    }

    final screen = await navigator.mediaDevices.getDisplayMedia({
      // A bounded capture profile keeps guidance responsive on mobile data.
      // The renderer still scales this to the full helper viewport.
      'video': {
        'width': {'ideal': 720, 'max': 1080},
        'height': {'ideal': 1280, 'max': 1920},
        'frameRate': {'ideal': 15, 'max': 24},
      },
      // System/internal audio capture is only reliable on Android 10+ and is
      // not needed while the mic carries the elderly person's voice.
      'audio': false,
    });
    _screenStream = screen;

    for (final track in screen.getVideoTracks()) {
      await _pc!.addTrack(track, screen);
      await _tuneVideoSender(track);
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

  /// Prefer a stable frame cadence for guidance over an unnecessarily large
  /// bitrate. Dropping frames creates a laggy control experience; keeping the
  /// capture at a bounded 15 fps makes the remote viewport react sooner on
  /// both LAN and mobile networks.
  Future<void> _tuneVideoSender(MediaStreamTrack track) async {
    try {
      final sender = (await _pc?.getSenders() ?? const <RTCRtpSender>[])
          .firstWhere((candidate) => candidate.track?.id == track.id);
      final parameters = sender.parameters;
      final encodings = parameters.encodings ?? [RTCRtpEncoding()];
      for (final encoding in encodings) {
        encoding.maxBitrate = 1200000;
        encoding.maxFramerate = 15;
        encoding.scaleResolutionDownBy = 1.0;
      }
      parameters.encodings = encodings;
      parameters.degradationPreference =
          RTCDegradationPreference.MAINTAIN_FRAMERATE;
      await sender.setParameters(parameters);
    } catch (_) {
      // Some Android WebRTC builds do not expose sender parameters. The
      // capture constraints remain the safe fallback on those devices.
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
    if (WebRTC.platformIsAndroid && _backgroundServiceActive) {
      await FlutterBackground.disableBackgroundExecution();
      _backgroundServiceActive = false;
    }
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
      'offerToReceiveVideo': true,
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
    final statuses = await [
      Permission.microphone,
      Permission.notification,
    ].request();
    final mic = statuses[Permission.microphone];
    if (mic != null && (mic.isDenied || mic.isPermanentlyDenied)) {
      throw StateError(
        'Microphone permission needed - please allow it in settings',
      );
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
      _backgroundServiceActive = false;
      _setState(WebRTCEngineState.disconnected);
    }
  }
}
