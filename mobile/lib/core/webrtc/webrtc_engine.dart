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
import 'dart:async';

import 'package:flutter/foundation.dart';
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

  /// Diagnostic build flag (`--dart-define=FORCE_TURN_RELAY=true`): every call
  /// uses relay-only ICE, so it connects only if TURN really works. Off by
  /// default; normal builds keep choosing direct paths when possible.
  static const bool forceTurnRelay = bool.fromEnvironment('FORCE_TURN_RELAY');
  bool _relayOnly = forceTurnRelay;

  RTCPeerConnection? _pc;
  RTCDataChannel? _dataChannel;
  RTCDataChannel? _previewDataChannel;
  Timer? _diagnosticsTimer;
  MediaStream? _micStream;
  MediaStream? _screenStream;

  /// Remote media (helper's mic / helpee sees nothing video-side) arrives here.
  void Function(MediaStream stream)? onRemoteStream;

  /// Trickle ICE candidates generated locally; relay to the remote peer.
  void Function(Map<String, dynamic> candidate)? onLocalCandidate;

  /// Peer connection state transitions for UI status display.
  void Function(WebRTCEngineState state)? onStateChanged;

  /// Direct P2P data channel messages (annotations and gestures).
  void Function(Map<String, dynamic> data)? onDataChannelMessage;

  /// P2P DataChannel state changes.
  void Function(bool isOpen)? onDataChannelState;

  /// Periodic transport metrics for diagnosing network and relay behavior.
  /// The payload omits IP addresses, candidate IDs and other identifying data.
  void Function(Map<String, Object?> metrics)? onDiagnosticsUpdated;
  void Function(String state)? onIceStateChanged;

  WebRTCEngineState get state => _state;
  bool get isScreenSharing => _isScreenSharing;
  bool get isAudioMuted => _isAudioMuted;
  bool get hasTurnServer => _iceServers.any((server) {
    final urls = server['urls'];
    bool isTurn(Object? url) =>
        url is String && (url.startsWith('turn:') || url.startsWith('turns:'));
    return urls is String ? isTurn(urls) : urls is List && urls.any(isTurn);
  });
  bool get isDataChannelOpen =>
      _dataChannel != null &&
      _dataChannel!.state == RTCDataChannelState.RTCDataChannelOpen;
  bool get isPreviewDataChannelOpen => _previewDataChannel != null &&
      _previewDataChannel!.state == RTCDataChannelState.RTCDataChannelOpen;
  int get dataChannelBufferedAmount =>
      (_dataChannel?.bufferedAmount ?? 0).toInt();
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
        'iceTransportPolicy': _relayOnly ? 'relay' : 'all',
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
      final value = candidate.candidate;
      if (value != null && value.isNotEmpty) {
        onLocalCandidate?.call(candidate.toMap());
      }
    };
    _pc!.onTrack = (event) async {
      debugPrint(
        '[AssistMe][MEDIA] remote track kind=${event.track.kind} '
        'enabled=${event.track.enabled} muted=${event.track.muted} '
        'streams=${event.streams.length}',
      );
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
      debugPrint('[AssistMe][MEDIA] peer connection state=$state');
      switch (state) {
        case RTCPeerConnectionState.RTCPeerConnectionStateConnected:
          _setState(WebRTCEngineState.connected);
          _startDiagnostics();
          break;
        case RTCPeerConnectionState.RTCPeerConnectionStateFailed:
          _setState(WebRTCEngineState.failed);
          _stopDiagnostics();
          break;
        case RTCPeerConnectionState.RTCPeerConnectionStateClosed:
        case RTCPeerConnectionState.RTCPeerConnectionStateDisconnected:
          _setState(WebRTCEngineState.disconnected);
          _stopDiagnostics();
          break;
        default:
          break;
      }
    };
    _pc!.onIceConnectionState = (state) {
      debugPrint('[AssistMe][MEDIA] ICE connection state=$state');
      onIceStateChanged?.call(state.toString());
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
  Future<void> rebuildPeerConnection({bool forceRelayOnly = false}) async {
    if (_iceServers.isEmpty) {
      throw StateError('initialize() must be called before rebuilding');
    }
    _relayOnly = forceRelayOnly || _relayOnly;
    _setState(WebRTCEngineState.initializing);
    final old = _pc;
    _pc = null;
    try {
      try {
        await _dataChannel?.close();
      } catch (_) {}
      try {
        await _previewDataChannel?.close();
      } catch (_) {}
      _dataChannel = null;
      _previewDataChannel = null;
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

    if (_screenStream != null) {
      for (final track in _screenStream!.getTracks()) {
        await track.stop();
      }
      await _screenStream!.dispose();
      _screenStream = null;
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

    debugPrint(
      '[AssistMe][MEDIA] screen capture returned '
      'videoTracks=${screen.getVideoTracks().length} '
      'audioTracks=${screen.getAudioTracks().length}',
    );
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
    if (_pc == null) return;
    if (_micStream == null) {
      final mic = await navigator.mediaDevices.getUserMedia({
        'audio': true,
        'video': false,
      });
      _micStream = mic;
    }

    try {
      final senders = await _pc!.getSenders();
      final audioTrackIds = senders.map((s) => s.track?.id).toSet();

      for (final track in _micStream!.getAudioTracks()) {
        if (!audioTrackIds.contains(track.id)) {
          await _pc!.addTrack(track, _micStream!);
        }
        track.enabled = !_isAudioMuted;
      }
    } catch (_) {
      for (final track in _micStream!.getAudioTracks()) {
        track.enabled = !_isAudioMuted;
      }
    }
  }

  /// Bounds the sender bitrate and lets WebRTC balance resolution and frame
  /// rate under congestion instead of insisting on a fixed frame cadence.
  Future<void> _tuneVideoSender(MediaStreamTrack track) async {
    try {
      final senders = await _pc?.getSenders() ?? const <RTCRtpSender>[];
      final sender = senders.firstWhere((candidate) => candidate.track?.id == track.id);
      final parameters = sender.parameters;
      final encodings = parameters.encodings ?? [RTCRtpEncoding()];
      for (final encoding in encodings) {
        encoding.maxBitrate = 2500000;
        encoding.maxFramerate = 30;
        encoding.scaleResolutionDownBy = 1.0;
        encoding.active = true;
      }
      parameters.encodings = encodings;
      parameters.degradationPreference = RTCDegradationPreference.BALANCED;
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
      if (_dataChannel == null) {
        final reliable = await _pc!.createDataChannel(
          label,
          RTCDataChannelInit()..ordered = true,
        );
        _setupDataChannel(reliable);
      }
      if (_previewDataChannel == null) {
        // Drawing previews are replaceable state; do not let retransmits block
        // committed strokes or control messages on the reliable channel.
        final preview = await _pc!.createDataChannel(
          '${label}_preview',
          RTCDataChannelInit()
            ..ordered = false
            // The native plugin omits maxRetransmits=0 from its serialized
            // config; a short packet lifetime gives previews bounded retries.
            ..maxRetransmitTime = 50,
        );
        _setupDataChannel(preview);
      }
    } catch (_) {}
  }

  void _setupDataChannel(RTCDataChannel channel) {
    if (channel.label?.endsWith('_preview') == true) {
      _previewDataChannel = channel;
    } else {
      _dataChannel = channel;
    }
    channel.onDataChannelState = (state) {
      if (identical(channel, _dataChannel)) {
        onDataChannelState?.call(state == RTCDataChannelState.RTCDataChannelOpen);
      }
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

  /// Sends a JSON payload directly over the open P2P data channel.
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

  /// Sends replaceable drawing previews without allowing a congested queue to
  /// grow behind the user's current pen position.
  bool sendPreviewData(Map<String, dynamic> data) {
    final channel = _previewDataChannel;
    if (channel == null || channel.state != RTCDataChannelState.RTCDataChannelOpen) {
      return false;
    }
    try {
      final bufferedAmount = channel.bufferedAmount;
      if (bufferedAmount != null && bufferedAmount > 64 * 1024) return false;
      channel.send(RTCDataChannelMessage(jsonEncode(data)));
      return true;
    } catch (_) {
      return false;
    }
  }

  void _startDiagnostics() {
    _diagnosticsTimer ??= Timer.periodic(
      const Duration(seconds: 5),
      (_) => _collectDiagnostics(),
    );
    _collectDiagnostics();
  }

  void _stopDiagnostics() {
    _diagnosticsTimer?.cancel();
    _diagnosticsTimer = null;
  }

  Future<void> _collectDiagnostics() async {
    final peerConnection = _pc;
    if (peerConnection == null) return;
    try {
      final reports = await peerConnection.getStats();
      final reportsById = {for (final report in reports) report.id: report};
      StatsReport? pair;
      for (final report in reports) {
        if (report.type == 'candidate-pair' &&
            (report.values['selected'] == true ||
                (report.values['nominated'] == true &&
                    report.values['state'] == 'succeeded'))) {
          pair = report;
          break;
        }
      }
      if (pair == null) {
        onDiagnosticsUpdated?.call({'candidatePairSelected': false});
        return;
      }

      final local = reportsById[pair.values['localCandidateId']];
      final remote = reportsById[pair.values['remoteCandidateId']];
      final inbound = reports.where((report) => report.type == 'inbound-rtp');
      final inboundVideo = inbound.where((report) =>
          report.values['kind'] == 'video' ||
          report.values['mediaType'] == 'video');
      final outbound = reports.where((report) => report.type == 'outbound-rtp');
      final roundTripSeconds = pair.values['currentRoundTripTime'] as num?;
      final jitterSeconds = inbound
          .map((report) => report.values['jitter'] as num?)
          .whereType<num>()
          .fold<num>(0, (largest, value) => value > largest ? value : largest);
      final lost = inbound
          .map((report) => report.values['packetsLost'] as num?)
          .whereType<num>()
          .fold<num>(0, (sum, value) => sum + value);
      final videoFps = inboundVideo
          .map((report) => report.values['framesPerSecond'] as num?)
          .whereType<num>()
          .fold<num>(0, (largest, value) => value > largest ? value : largest);
      final videoFramesDecoded = inboundVideo
          .map((report) => report.values['framesDecoded'] as num?)
          .whereType<num>()
          .fold<num>(0, (sum, value) => sum + value);
      final videoBytesReceived = inboundVideo
          .map((report) => report.values['bytesReceived'] as num?)
          .whereType<num>()
          .fold<num>(0, (sum, value) => sum + value);

      onDiagnosticsUpdated?.call({
        'candidatePairSelected': true,
        'localCandidateType': local?.values['candidateType'],
        'remoteCandidateType': remote?.values['candidateType'],
        'protocol': local?.values['protocol'],
        'roundTripTimeMs': roundTripSeconds == null
            ? null
            : (roundTripSeconds * 1000).round(),
        'jitterMs': (jitterSeconds * 1000).round(),
        'packetsLost': lost.round(),
        'incomingVideoFps': videoFps.round(),
        'videoFramesDecoded': videoFramesDecoded.round(),
        'videoBytesReceived': videoBytesReceived.round(),
        'outboundBytes': outbound
            .map((report) => report.values['bytesSent'] as num?)
            .whereType<num>()
            .fold<num>(0, (sum, value) => sum + value)
            .round(),
      });
    } catch (_) {
      // Stats are optional; do not interrupt the media path on plugin gaps.
    }
  }

  // ---------------------------------------------------------------------------
  // Signaling primitives (plain maps so RealtimeService can relay them)
  // ---------------------------------------------------------------------------

  Future<Map<String, dynamic>> createOffer() async {
    // Automatically prepare data channel on offerer side
    if (_dataChannel == null || _previewDataChannel == null) {
      await createDataChannel();
    }
    final offer = await _pc!.createOffer({});
    debugPrint(
      '[AssistMe][MEDIA] local offer created '
      'audio=${_sdpHasMedia(offer.sdp, 'audio')} '
      'video=${_sdpHasMedia(offer.sdp, 'video')}',
    );
    await _pc!.setLocalDescription(offer);
    final desc = await _pc!.getLocalDescription();
    return {'type': desc!.type, 'sdp': desc.sdp};
  }

  Future<Map<String, dynamic>> createAnswer() async {
    final answer = await _pc!.createAnswer({});
    debugPrint(
      '[AssistMe][MEDIA] local answer created '
      'audio=${_sdpHasMedia(answer.sdp, 'audio')} '
      'video=${_sdpHasMedia(answer.sdp, 'video')}',
    );
    await _pc!.setLocalDescription(answer);
    final desc = await _pc!.getLocalDescription();
    return {'type': desc!.type, 'sdp': desc.sdp};
  }

  Future<void> setRemoteDescription(Map<String, dynamic> sdp) async {
    final peer = _pc;
    final type = sdp['type'] as String?;
    final description = sdp['sdp'] as String?;
    if (peer == null || type == null || description == null) return;
    final signalingState = await peer.getSignalingState();
    if (type == 'answer' &&
        signalingState == RTCSignalingState.RTCSignalingStateStable) {
      debugPrint('[AssistMe][MEDIA] ignored stale answer in stable state');
      return;
    }
    debugPrint(
      '[AssistMe][MEDIA] applying remote $type '
      'audio=${_sdpHasMedia(description, 'audio')} '
      'video=${_sdpHasMedia(description, 'video')}',
    );
    await peer.setRemoteDescription(RTCSessionDescription(description, type));
  }

  bool _sdpHasMedia(String? sdp, String kind) =>
      sdp?.split('\n').any((line) => line.trim().startsWith('m=$kind ')) ??
      false;

  Future<void> addIceCandidate(Map<String, dynamic> candidate) async {
    final peer = _pc;
    final value = candidate['candidate'] as String?;
    if (peer == null || value == null || value.trim().isEmpty) return;
    final line = candidate['sdpMLineIndex'];
    await peer.addCandidate(
      RTCIceCandidate(
        value,
        candidate['sdpMid'] as String?,
        line is num ? line.toInt() : null,
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

  /// Captures a single image frame from the active screen video track.
  /// Used by the silent visual-guide keyframe manager; never on the hot
  /// media path, so it cannot add startup or streaming latency.
  Future<Uint8List?> captureScreenFrame({MediaStream? remoteStream}) async {
    try {
      final stream = remoteStream ?? _screenStream;
      if (stream == null) return null;
      final tracks = stream.getVideoTracks();
      if (tracks.isEmpty) return null;
      final track = tracks.first;
      final buffer = await track.captureFrame();
      return buffer.asUint8List();
    } catch (e) {
      return null;
    }
  }

  Future<void> dispose() async {
    _stopDiagnostics();
    try {
      await stopScreenCapture();
      try {
        await _dataChannel?.close();
      } catch (_) {}
      try {
        await _previewDataChannel?.close();
      } catch (_) {}
      _dataChannel = null;
      _previewDataChannel = null;
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
