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

import 'dart:convert';

import 'package:flutter/services.dart';
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
  static const _mediaProjectionChannel = MethodChannel('com.assistme/media_projection');
  WebRTCEngineState _state = WebRTCEngineState.uninitialized;
  bool _isScreenSharing = false;
  bool _isAudioMuted = false;
  List<Map<String, dynamic>> _iceServers = const [];

  RTCPeerConnection? _pc;
  RTCDataChannel? _dataChannel;
  MediaStream? _micStream;
  MediaStream? _screenStream;

  /// Remote media (helper's mic / helpee sees nothing video-side) arrives here.
  void Function(MediaStream stream)? onRemoteStream;

  /// Trickle ICE candidates generated locally; relay to the remote peer.
  void Function(Map<String, dynamic> candidate)? onLocalCandidate;

  /// Peer connection state transitions for UI status display.
  void Function(WebRTCEngineState state)? onStateChanged;

  /// Direct P2P data channel messages (annotations, gestures) for sub-15ms latency.
  void Function(Map<String, dynamic> data)? onDataChannelMessage;

  /// P2P DataChannel state changes.
  void Function(bool isOpen)? onDataChannelState;

  WebRTCEngineState get state => _state;
  bool get isScreenSharing => _isScreenSharing;
  bool get isAudioMuted => _isAudioMuted;
  bool get isDataChannelOpen =>
      _dataChannel != null &&
      _dataChannel!.state == RTCDataChannelState.RTCDataChannelOpen;
  RTCPeerConnection? get peerConnection => _pc;
  MediaStream? get micStream => _micStream;

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
      {
        'iceServers': _iceServers,
        'sdpSemantics': 'unified-plan',
        'bundlePolicy': 'max-bundle',
        'rtcpMuxPolicy': 'require',
      },
      {
        'mandatory': {},
        'optional': [
          {'DtlsSrtpKeyAgreement': true},
          {'googCpuOveruseDetection': true},
          {'googHighpassFilter': true},
          {'googEchoCancellation': true},
        ],
      },
    );

    _pc!.onIceCandidate = (candidate) {
      onLocalCandidate?.call(candidate.toMap());
    };
    _pc!.onTrack = (event) async {
      if (event.streams.isNotEmpty) {
        onRemoteStream?.call(event.streams.first);
      } else {
        // Some Android WebRTC builds emit a track without a bundled stream.
        // Synthesize a MediaStream so the helper's viewport never stays black.
        try {
          final stream = await createLocalMediaStream('assistme-remote-${event.track.kind}');
          await stream.addTrack(event.track, addToNative: true);
          onRemoteStream?.call(stream);
        } catch (_) {
          // Fallback: the coordinator also registers onAddStream.
        }
      }
    };
    _pc!.onAddStream = (stream) {
      onRemoteStream?.call(stream);
    };
    _pc!.onDataChannel = (channel) {
      _setupDataChannel(channel);
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

    // Android requires a foreground service of type mediaProjection while capturing.
    // On Android 14+ getDisplayMedia will throw
    // "Media projections require a foreground service of type MEDIA_PROJECTION"
    // if no such service is active.
    Future<void> ensureForeground() async {
      try {
        await _mediaProjectionChannel.invokeMethod('startForeground');
      } catch (_) {}
    }

    bool captureGranted = false;
    if (WebRTC.platformIsAndroid) {
      // Request system MediaProjection permission first (stores consent)
      captureGranted = await Helper.requestCapturePermission(fullScreenOnly: true);
      if (!captureGranted) {
        throw StateError('Screen capture permission was not granted');
      }
      // Now start foreground service(s) BEFORE getDisplayMedia (Android 14 requirement)
      await ensureForeground();
      // Small delay to let service enter foreground
      await Future<void>.delayed(const Duration(milliseconds: 400));
    } else {
      await _ensurePermissions();
    }

    MediaStream? screen;
    try {
      screen = await navigator.mediaDevices.getDisplayMedia({
        'video': {
          'width': {'ideal': 720, 'max': 720},
          'height': {'ideal': 1280, 'max': 1280},
          'frameRate': {'ideal': 30, 'max': 30},
        },
        'audio': false,
      });
    } catch (e) {
      // Android 14 foreground service race – retry once after ensuring service
      final msg = e.toString();
      if (msg.contains('FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION') || msg.contains('getDisplayMedia')) {
        await ensureForeground();
        await Future<void>.delayed(const Duration(milliseconds: 600));
        screen = await navigator.mediaDevices.getDisplayMedia({
          'video': {
            'width': {'ideal': 720, 'max': 720},
            'height': {'ideal': 1280, 'max': 1280},
            'frameRate': {'ideal': 30, 'max': 30},
          },
          'audio': false,
        });
      } else {
        rethrow;
      }
    }
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

  /// Low-latency real-time video sender tuning: maintain smooth 30fps cadence
  /// with bounded bitrate to avoid jitter buffer bloat and queue lag during remote control.
  Future<void> _tuneVideoSender(MediaStreamTrack track) async {
    try {
      final senders = await _pc?.getSenders() ?? const <RTCRtpSender>[];
      final sender = senders.firstWhere((candidate) => candidate.track?.id == track.id);
      final parameters = sender.parameters;
      final encodings = parameters.encodings ?? [RTCRtpEncoding()];
      for (final encoding in encodings) {
        encoding.maxBitrate = 2500000;
        encoding.minBitrate = 500000;
        encoding.maxFramerate = 30;
        encoding.scaleResolutionDownBy = 1.0;
        encoding.active = true;
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
    try { await _mediaProjectionChannel.invokeMethod('stopForeground'); } catch (_) {}
  }

  Future<void> toggleAudioMute(bool mute) async {
    _isAudioMuted = mute;
    final tracks = _micStream?.getAudioTracks() ?? const <MediaStreamTrack>[];
    for (final track in tracks) {
      track.enabled = !mute;
    }
  }

  // ---------------------------------------------------------------------------
  // P2P Data Channel (Instantaneous Annotations & Gestures)
  // ---------------------------------------------------------------------------

  Future<void> createDataChannel([String label = 'assistme_channel']) async {
    if (_pc == null) return;
    try {
      final init = RTCDataChannelInit()..ordered = true;
      final channel = await _pc!.createDataChannel(label, init);
      _setupDataChannel(channel);
    } catch (_) {}
  }

  void _setupDataChannel(RTCDataChannel channel) {
    _dataChannel = channel;
    channel.onDataChannelState = (state) {
      onDataChannelState?.call(state == RTCDataChannelState.RTCDataChannelOpen);
    };
    channel.onMessage = (RTCDataChannelMessage msg) {
      if (msg.isBinary) return;
      try {
        final decoded = jsonDecode(msg.text);
        if (decoded is Map<String, dynamic>) {
          onDataChannelMessage?.call(decoded);
        }
      } catch (_) {}
    };
  }

  /// Sends a JSON payload directly over P2P DataChannel (UDP, sub-15ms latency).
  /// Returns true if successfully queued on the open data channel.
  bool sendData(Map<String, dynamic> data) {
    if (_dataChannel != null &&
        _dataChannel!.state == RTCDataChannelState.RTCDataChannelOpen) {
      try {
        _dataChannel!.send(RTCDataChannelMessage(jsonEncode(data)));
        return true;
      } catch (_) {
        return false;
      }
    }
    return false;
  }

  // ---------------------------------------------------------------------------
  // Signaling primitives (plain maps so RealtimeService can relay them)
  // ---------------------------------------------------------------------------

  Future<Map<String, dynamic>> createOffer() async {
    // Automatically prepare data channel on offerer side
    if (_dataChannel == null) {
      await createDataChannel();
    }
    final offer = await _pc!.createOffer({});
    await _pc!.setLocalDescription(offer);
    final desc = await _pc!.getLocalDescription();
    return {'type': desc!.type, 'sdp': desc.sdp};
  }

  Future<Map<String, dynamic>> createAnswer() async {
    final answer = await _pc!.createAnswer({});
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
      try {
        await _dataChannel?.close();
      } catch (_) {}
      _dataChannel = null;
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
