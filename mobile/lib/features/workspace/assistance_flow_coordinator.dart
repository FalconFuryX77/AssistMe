/// Assistance flow coordinator — wires the realtime channel to the security UI.
///
/// Handles the full one-click help experience:
///   - helpee taps "request help" → popup on helper
///   - helper accepts (overlay-only) / denies
///   - helper requests escalation → helpee sees risk disclaimer
///   - helpee accepts risks → control granted
///   - helper draw strokes are rendered on the overlay
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../core/guides/session_keyframe_manager.dart';
import '../../core/guides/local_guide_store.dart';
import '../../core/guides/guide_delivery_service.dart';
import '../../core/guides/local_guide_audio_capture.dart';
import '../../core/guides/screenshot_redaction.dart' show shrinkGuideScreenshot;
import '../../core/network/api_client.dart';
import '../../core/platform/accessibility_bridge.dart';
import '../../core/platform/annotation_overlay_service.dart';
import '../../core/realtime/realtime_service.dart';
import '../../core/security/device_identity.dart';
import '../../core/security/secure_storage_service.dart';
import '../../core/webrtc/webrtc_engine.dart';
import '../../theme/app_theme.dart';
import 'drawing_overlay.dart';
import 'incoming_help_request_popup.dart';
import 'risk_disclaimer_modal.dart';
import 'local_guide_save_dialog.dart';
import 'guide_step_details_dialog.dart';
import 'screenshot_redaction_editor.dart';

class _IncomingGuideFrameTransfer {
  final String id;
  final String title;
  final String instruction;
  final int expectedBytes;
  final int expectedChunks;
  final List<Uint8List> chunks = <Uint8List>[];
  int receivedBytes = 0;

  _IncomingGuideFrameTransfer({
    required this.id,
    required this.title,
    required this.instruction,
    required this.expectedBytes,
    required this.expectedChunks,
  });
}

class AssistanceFlowCoordinator extends StatefulWidget {
  final String sessionId;
  final ApiClient apiClient;
  final SecureStorageService secureStorage;
  final bool isHelpee;

  /// When launched straight from an accepted ring, the helpee starts sharing
  /// as soon as the media engine is ready — zero extra taps.
  final bool autoStartScreenShare;
  final String peerName;
  final Future<void> Function()? onSessionClosed;
  final Future<void> Function()? onSessionEnded;

  /// Sink the coordinator publishes the remote WebRTC stream into so sibling
  /// widgets (e.g. the remote viewport) can render it without rebuilding.
  final ValueNotifier<dynamic>? remoteStreamSink;
  final ValueNotifier<bool>? remoteControlSink;
  final ValueNotifier<bool>? annotationModeSink;
  final ValueNotifier<double>? contentAspectRatioNotifier;
  final ValueNotifier<bool>? screenSharingSink;
  final ValueNotifier<GuideAudioCaptureStatus>? guideAudioStatusSink;

  /// True while a guide step is being captured, so the button can show it.
  final ValueNotifier<bool>? guideStepBusySink;

  const AssistanceFlowCoordinator({
    super.key,
    required this.sessionId,
    required this.apiClient,
    required this.secureStorage,
    required this.isHelpee,
    this.autoStartScreenShare = false,
    this.peerName = 'your contact',
    this.onSessionClosed,
    this.onSessionEnded,
    this.remoteStreamSink,
    this.remoteControlSink,
    this.annotationModeSink,
    this.contentAspectRatioNotifier,
    this.screenSharingSink,
    this.guideAudioStatusSink,
    this.guideStepBusySink,
  });

  @override
  State<AssistanceFlowCoordinator> createState() =>
      AssistanceFlowCoordinatorState();
}

class AssistanceFlowCoordinatorState extends State<AssistanceFlowCoordinator> {
  RealtimeService? _realtime;
  final List<DrawStroke> _strokes = [];
  final List<DrawStroke> _redoStrokes = [];
  AnnotationTool _annotationTool = AnnotationTool.pen;
  Color _annotationColor = const Color(0xFFFF3B30);
  double _annotationWidth = 4;
  String? _helperDeviceFingerprint;
  bool _isRequestingHelp = false;

  // Pending incoming request / escalation
  String? _pendingRequestId;
  Map<String, dynamic>? _pendingEscalation;

  // WebRTC media pipeline (screen share + two-way voice)
  final WebRTCEngine _engine = WebRTCEngine();
  late final ValueNotifier<dynamic> remoteStreamNotifier =
      widget.remoteStreamSink ?? ValueNotifier<dynamic>(null);

  // Silent visual session guide keyframe manager
  late final SessionKeyframeManager _keyframeManager = SessionKeyframeManager(
    captureFrameCallback: () async {
      if (widget.isHelpee) {
        return await _engine.captureScreenFrame();
      } else {
        final stream = remoteStreamNotifier.value;
        return await _engine.captureScreenFrame(
          remoteStream: stream is MediaStream ? stream : null,
        );
      }
    },
  );
  bool _mediaReady = false;
  bool _bootstrapping = false;
  bool _screenShareStarting = false;
  bool _shareWaitingForSignaling = false;
  bool _screenShareStarted = false;
  bool _remoteControlGranted = false;
  bool _helpeeOverlayRunning = false;
  Map<String, dynamic>? _pendingOffer;
  final List<Map<String, dynamic>> _pendingIceCandidates = [];
  bool _remoteDescriptionSet = false;
  bool _mediaRecovering = false;
  DateTime? _lastSignalingWarningAt;
  bool _relayFallbackAttempted = false;
  bool _directIceRecoveryAttempted = false;
  DrawStroke? _draftStroke;
  int _nextLocalDrawStrokeId = 0;
  int? _activeLocalDrawStrokeId;
  int _localDrawPreviewSequence = 0;
  int _lastRemotePreviewStrokeId = -1;
  int _lastRemotePreviewSequence = -1;
  int _lastRemoteCommittedStrokeId = -1;
  int? _remoteDraftStrokeId;
  Timer? _previewTimer;
  Timer? _realtimePreviewTimer;
  Map<String, dynamic>? _pendingRealtimePreview;
  List<Offset>? _pendingPreviewPoints;
  Timer? _overlayTimer;
  Offset _helperDockOffset = const Offset(16, 16);
  Timer? _disconnectCountdownTimer;
  int? _disconnectCountdownSeconds;
  int _totalAloneSeconds = 0;
  bool _sessionTerminationHandled = false;
  bool _guideReviewShown = false;
  Completer<bool>? _pendingGuideFinalizationAck;
  Completer<void>? _sessionEndCompleter;
  bool _waitingForHelperFinalization = false;
  static const int _maxGuideFrameBytes = 2 * 1024 * 1024;
  static const int _guideFrameChunkBytes = 12 * 1024;
  _IncomingGuideFrameTransfer? _incomingGuideFrameTransfer;
  final Map<String, Completer<KeyframeCaptureResult>> _pendingGuideFrameAcks =
      {};
  int _guideFrameOrdinal = 0;
  // Guide steps the helpee has confirmed it stored (helper side only).
  final Set<String> _guideFramesOnHelpee = <String>{};
  // Transfers to the helpee run one at a time; the helpee accepts one at once.
  Future<void> _helpeeSendChain = Future<void>.value();
  // Helper only: per-call key for the encrypted post-call guide delivery.
  // It reaches the helpee only over the call's peer data channel.
  final List<int> _guideSyncKey = GuideDeliveryService.newKey();
  bool _guideFrameTransferInProgress = false;
  final LocalGuideAudioCapture _guideAudioCapture = LocalGuideAudioCapture();
  bool _localGuideAudioConsent = false;
  bool _peerGuideAudioConsent = false;
  final List<LocalGuideAudioRecording> _pendingGuideAudioRecordings = [];
  Timer? _guideAudioLimitTimer;
  DateTime? _guideAudioStartedAt;
  Duration _guideAudioRecordedDuration = Duration.zero;
  static const Duration _maxGuideAudioDuration = Duration(minutes: 20);
  static const int _maxAloneSeconds = 300; // 5 minutes max alone time

  bool get _annotationMode => widget.annotationModeSink?.value ?? false;

  void _onAnnotationModeChanged() {
    if (mounted) setState(() {});
  }

  void _moveHelperDock(Offset delta) {
    final viewport = MediaQuery.sizeOf(context);
    final maxX = (viewport.width - 360).clamp(0.0, double.infinity).toDouble();
    final maxY = (viewport.height - 180).clamp(0.0, double.infinity).toDouble();
    setState(() {
      _helperDockOffset = Offset(
        (_helperDockOffset.dx + delta.dx).clamp(0.0, maxX).toDouble(),
        (_helperDockOffset.dy + delta.dy).clamp(0.0, maxY).toDouble(),
      );
    });
  }

  void _selectAnnotationTool(AnnotationTool tool) {
    // Selecting a drawing tool while in phase 3 is an explicit, low-friction
    // way to return to Guide mode. This keeps the persistent toolbar useful
    // without silently enabling touch input on the helpee's phone.
    if (_remoteControlGranted && !_annotationMode) {
      widget.annotationModeSink?.value = true;
    }
    setState(() => _annotationTool = tool);
  }

  void _sendRealtimeOrP2P(Map<String, dynamic> payload) {
    // Reliable events (committed strokes, control and session state) use P2P
    // first, then the WebSocket signaling path as a fallback.
    final sentP2P = _engine.sendData(payload);
    if (!sentP2P) {
      _realtime?.send(payload);
    }
  }

  void _sendPreviewRealtimeOrP2P(Map<String, dynamic> payload) {
    if (_engine.sendPreviewData(payload)) return;
    // If the unreliable channel is open but congested, drop this transient
    // preview instead of queuing stale points behind the current pen position.
    if (_engine.isPreviewDataChannelOpen) return;
    // A WebSocket/TCP fallback can queue behind a slow network. Keep only the
    // newest full-stroke snapshot and cap fallback previews at 10 per second.
    _pendingRealtimePreview = payload;
    if (_realtimePreviewTimer?.isActive == true) return;
    _realtimePreviewTimer = Timer(const Duration(milliseconds: 100), () {
      _realtimePreviewTimer = null;
      final latest = _pendingRealtimePreview;
      _pendingRealtimePreview = null;
      if (latest != null) _realtime?.send(latest);
    });
  }

  void _sendDrawPreview(List<Offset> points) {
    if (points.isEmpty) return;
    final draft = DrawStroke(
      points: points,
      color: _annotationColor,
      width: _annotationWidth,
    );
    final strokeId = _activeLocalDrawStrokeId ??= ++_nextLocalDrawStrokeId;
    final previewSequence = ++_localDrawPreviewSequence;
    setState(() => _draftStroke = draft);
    _pendingPreviewPoints = points;
    if (_previewTimer?.isActive == true) return;
    _previewTimer = Timer(const Duration(milliseconds: 32), () {
      _previewTimer = null;
      final latest = _pendingPreviewPoints;
      _pendingPreviewPoints = null;
      if (latest == null || latest.isEmpty) return;
      _sendPreviewRealtimeOrP2P({
        'type': 'draw_preview',
        'stroke_id': strokeId,
        'preview_sequence': previewSequence,
        'points': latest
            .map(
              (p) => {
                'x': double.parse(p.dx.toStringAsFixed(4)),
                'y': double.parse(p.dy.toStringAsFixed(4)),
              },
            )
            .toList(),
        'color': _annotationColor.toARGB32(),
        'width': _annotationWidth,
      });
    });
  }

  void _sendDrawStroke(List<Offset> points) {
    // One pen tool owns both colour and thickness. The style sheet below is
    // the single source of truth; there is no separate thin/thick mode.
    final color = _annotationColor;
    final width = _annotationWidth;
    final strokeId = _activeLocalDrawStrokeId ?? ++_nextLocalDrawStrokeId;
    _activeLocalDrawStrokeId = null;
    _localDrawPreviewSequence = 0;
    _previewTimer?.cancel();
    _previewTimer = null;
    _realtimePreviewTimer?.cancel();
    _realtimePreviewTimer = null;
    _pendingRealtimePreview = null;
    _pendingPreviewPoints = null;
    setState(() {
      _draftStroke = null;
      _redoStrokes.clear();
      _strokes.add(DrawStroke(points: points, color: color, width: width));
    });
    _sendRealtimeOrP2P({
      'type': 'draw_stroke',
      'stroke_id': strokeId,
      'points': points
          .map(
            (p) => {
              'x': double.parse(p.dx.toStringAsFixed(4)),
              'y': double.parse(p.dy.toStringAsFixed(4)),
            },
          )
          .toList(),
      'color': color.toARGB32(),
      'width': width,
    });
    _pushOverlay();
  }

  void _eraseAt(Offset point) {
    setState(
      () => _strokes.removeWhere((stroke) => strokeNearPoint(stroke, point)),
    );
    _redoStrokes.clear();
    _sendRealtimeOrP2P({
      'type': 'draw_erase',
      'point': {
        'x': double.parse(point.dx.toStringAsFixed(4)),
        'y': double.parse(point.dy.toStringAsFixed(4)),
      },
    });
    _pushOverlay();
  }

  void _undoDrawing() {
    if (_strokes.isEmpty) return;
    setState(() {
      _redoStrokes.add(_strokes.removeLast());
    });
    _sendRealtimeOrP2P({'type': 'draw_undo'});
    _pushOverlay();
  }

  void _redoDrawing() {
    if (_redoStrokes.isEmpty) return;
    setState(() {
      _strokes.add(_redoStrokes.removeLast());
    });
    _sendRealtimeOrP2P({'type': 'draw_redo'});
    _pushOverlay();
  }

  Future<void> _clearDrawings({bool notifyOverlay = true}) async {
    _previewTimer?.cancel();
    _previewTimer = null;
    _pendingPreviewPoints = null;
    _realtimePreviewTimer?.cancel();
    _realtimePreviewTimer = null;
    _pendingRealtimePreview = null;
    _activeLocalDrawStrokeId = null;
    _localDrawPreviewSequence = 0;
    _overlayTimer?.cancel();
    _overlayTimer = null;
    _draftStroke = null;
    setState(() {
      _strokes.clear();
      _redoStrokes.clear();
    });
    _sendRealtimeOrP2P({
      'type': 'draw_clear',
      'stroke_id': ++_nextLocalDrawStrokeId,
    });
    if (notifyOverlay) {
      try {
        await AnnotationOverlayService.clear();
      } catch (_) {}
    }
  }

  bool get isMediaReady => _mediaReady;
  bool get isScreenShareStarted => _screenShareStarted;
  bool get remoteControlGranted => _remoteControlGranted;
  bool get canOptIntoGuideAudio =>
      Platform.isAndroid && _mediaReady && _engine.isDataChannelOpen;

  @override
  void initState() {
    super.initState();
    unawaited(LocalGuideAudioCapture.clearStaleRecordings());
    widget.guideAudioStatusSink?.value = GuideAudioCaptureStatus.off;
    widget.annotationModeSink?.addListener(_onAnnotationModeChanged);
    if (widget.isHelpee) {
      AnnotationOverlayService.initialize(
        onPanic: _panicStop,
        onClear: () async => _clearDrawings(notifyOverlay: false),
        onDrawStroke: (points, color, width) =>
            _handleNativeHelpeeStroke(points, color, width),
        onErase: (point) => _eraseAt(point),
        onUndo: _undoDrawing,
        onRedo: _redoDrawing,
      );
    }
    _bootstrap();
  }

  void _handleNativeHelpeeStroke(
    List<Offset> points,
    int colorValue,
    double width,
  ) {
    // Helpee drew on the system overlay – use the native-selected color
    // (not the helper's currently selected color) so both sides see the same.
    final color = Color(colorValue);
    final strokeId = ++_nextLocalDrawStrokeId;
    _previewTimer?.cancel();
    _previewTimer = null;
    _pendingPreviewPoints = null;
    setState(() {
      _draftStroke = null;
      _redoStrokes.clear();
      _strokes.add(DrawStroke(points: points, color: color, width: width));
    });
    _sendRealtimeOrP2P({
      'type': 'draw_stroke',
      'stroke_id': strokeId,
      'points': points
          .map(
            (p) => {
              'x': double.parse(p.dx.toStringAsFixed(4)),
              'y': double.parse(p.dy.toStringAsFixed(4)),
            },
          )
          .toList(),
      'color': colorValue,
      'width': width,
    });
    // Local overlay already shows the stroke via native canvas; _pushOverlay
    // keeps it in sync for any future helper replay but does not duplicate.
    _pushOverlay();
  }

  Future<void> toggleAudioMute(bool mute) async {
    if (mute &&
        widget.isHelpee &&
        (_localGuideAudioConsent || _guideAudioCapture.isRecording)) {
      _localGuideAudioConsent = false;
      _sendGuideAudioConsent(false);
      await _stopGuideAudioCapture(discard: true);
      _setGuideAudioStatus(GuideAudioCaptureStatus.off);
    }
    await _engine.toggleAudioMute(mute);
    _sendRealtimeOrP2P({'type': 'audio_mute_toggle', 'is_muted': mute});
  }

  /// Helper requests permission, then starts and stops recording. Audio is
  /// recorded on the helper's phone, which hears both sides of the call (its
  /// mic and the call playback) and is where the guide is curated, transcribed
  /// and drafted. The helpee can revoke at any time, which discards it.
  Future<void> toggleGuideAudioControl() async {
    if (!Platform.isAndroid || !_mediaReady || !_engine.isDataChannelOpen) {
      _showGuideMessage('Guide audio needs a ready Android call connection.');
      return;
    }
    if (widget.isHelpee) {
      if (!_localGuideAudioConsent) return;
      _localGuideAudioConsent = false;
      _sendGuideAudioConsent(false);
      await _stopGuideAudioCapture(discard: true);
      _setGuideAudioStatus(GuideAudioCaptureStatus.off);
      return;
    }
    final status =
        widget.guideAudioStatusSink?.value ?? GuideAudioCaptureStatus.off;
    if (!_peerGuideAudioConsent) {
      if (!_engine.sendData({'type': 'guide_audio_consent_request'})) {
        _showGuideMessage('Could not ask for guide-audio permission.');
        return;
      }
      _setGuideAudioStatus(GuideAudioCaptureStatus.awaitingConsent);
      return;
    }
    if (status == GuideAudioCaptureStatus.awaitingConsent) return;
    if (status == GuideAudioCaptureStatus.recording) {
      await _stopGuideAudioCapture(discard: false);
      _setGuideAudioStatus(GuideAudioCaptureStatus.consented);
      _sendGuideAudioStatus('consented');
    } else {
      await _startHelperGuideAudio();
    }
  }

  /// Starts recording on the helper's phone after the helpee consented.
  Future<void> _startHelperGuideAudio() async {
    if (widget.isHelpee || !_peerGuideAudioConsent) return;
    if (_guideAudioCapture.isRecording) return;
    final remaining = _maxGuideAudioDuration - _guideAudioRecordedDuration;
    if (remaining <= Duration.zero) {
      _showGuideMessage('The 20 minute guide-audio limit was reached.');
      return;
    }
    try {
      await _guideAudioCapture.start();
    } catch (_) {
      _showGuideMessage('Audio capture could not start on this phone.');
      _setGuideAudioStatus(GuideAudioCaptureStatus.consented);
      return;
    }
    _guideAudioStartedAt = DateTime.now();
    _setGuideAudioStatus(GuideAudioCaptureStatus.recording);
    _sendGuideAudioStatus('recording');
    _guideAudioLimitTimer?.cancel();
    _guideAudioLimitTimer = Timer(remaining, () async {
      await _stopGuideAudioCapture(discard: false);
      _setGuideAudioStatus(GuideAudioCaptureStatus.consented);
      _sendGuideAudioStatus('consented', error: 'limit');
      _showGuideMessage('The 20 minute guide-audio limit was reached.');
    });
  }

  /// Lets the helpee's phone show whether the helper is recording.
  bool _sendGuideAudioStatus(String state, {String? error}) =>
      _engine.sendData({
        'type': 'guide_audio_capture_status',
        'state': state,
        'error': ?error,
      });

  /// Kept as a small UI compatibility wrapper: only the helpee may revoke.
  Future<void> setGuideAudioConsent(bool consented) async {
    if (!widget.isHelpee || consented || !_localGuideAudioConsent) return;
    _localGuideAudioConsent = false;
    _sendGuideAudioConsent(false);
    await _stopGuideAudioCapture(discard: true);
    _setGuideAudioStatus(GuideAudioCaptureStatus.off);
  }

  void _setGuideAudioStatus(GuideAudioCaptureStatus status) {
    widget.guideAudioStatusSink?.value = status;
  }

  bool _sendGuideAudioConsent(bool consented) =>
      _engine.sendData({'type': 'guide_audio_consent', 'consented': consented});

  Future<void> _requestHelpeeGuideAudioConsent() async {
    if (!widget.isHelpee || !Platform.isAndroid || !mounted) return;
    if (_localGuideAudioConsent) {
      _sendGuideAudioConsent(true);
      _setGuideAudioStatus(GuideAudioCaptureStatus.consented);
      return;
    }
    final accepted = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Allow guide audio capture?'),
        content: Text(
          'Your helper is asking to record selected parts of this call to write your step-by-step guide. The audio is kept temporarily in private storage on your helper\'s phone and turned into text there. It is deleted after that, and it is never uploaded to AssistMe or an AI service. You will see when recording starts and can stop it at any time.',
          style: TextStyle(color: AppTheme.textSecondary, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Decline'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Allow for this call'),
          ),
        ],
      ),
    );
    if (!mounted) return;
    _localGuideAudioConsent = accepted == true;
    _setGuideAudioStatus(
      _localGuideAudioConsent
          ? GuideAudioCaptureStatus.consented
          : GuideAudioCaptureStatus.off,
    );
    if (!_sendGuideAudioConsent(_localGuideAudioConsent)) {
      _localGuideAudioConsent = false;
      _setGuideAudioStatus(GuideAudioCaptureStatus.off);
    }
  }

  Future<void> _handleGuideAudioCaptureCommand(String action) async {
    if (!widget.isHelpee) return;
    if (action == 'stop') {
      await _stopGuideAudioCapture(discard: false);
      _setGuideAudioStatus(
        _localGuideAudioConsent
            ? GuideAudioCaptureStatus.consented
            : GuideAudioCaptureStatus.off,
      );
      _engine.sendData({
        'type': 'guide_audio_capture_status',
        'state': _localGuideAudioConsent ? 'consented' : 'off',
      });
      return;
    }
    if (action != 'start' || !_localGuideAudioConsent) {
      _engine.sendData({
        'type': 'guide_audio_capture_status',
        'state': 'off',
        'error': 'permission',
      });
      return;
    }
    if (_guideAudioCapture.isRecording) return;
    final remaining = _maxGuideAudioDuration - _guideAudioRecordedDuration;
    if (remaining <= Duration.zero) {
      _localGuideAudioConsent = false;
      _sendGuideAudioConsent(false);
      _engine.sendData({
        'type': 'guide_audio_capture_status',
        'state': 'off',
        'error': 'limit',
      });
      _setGuideAudioStatus(GuideAudioCaptureStatus.off);
      return;
    }
    try {
      await _guideAudioCapture.start();
      _guideAudioStartedAt = DateTime.now();
      _setGuideAudioStatus(GuideAudioCaptureStatus.recording);
      _engine.sendData({
        'type': 'guide_audio_capture_status',
        'state': 'recording',
      });
      _guideAudioLimitTimer?.cancel();
      _guideAudioLimitTimer = Timer(remaining, () async {
        _localGuideAudioConsent = false;
        _sendGuideAudioConsent(false);
        await _stopGuideAudioCapture(discard: false);
        _setGuideAudioStatus(GuideAudioCaptureStatus.off);
        _engine.sendData({
          'type': 'guide_audio_capture_status',
          'state': 'off',
          'error': 'limit',
        });
      });
    } catch (_) {
      _engine.sendData({
        'type': 'guide_audio_capture_status',
        'state': 'consented',
        'error': 'capture',
      });
      _setGuideAudioStatus(GuideAudioCaptureStatus.consented);
    }
  }

  Future<void> _stopGuideAudioCapture({required bool discard}) async {
    _guideAudioLimitTimer?.cancel();
    _guideAudioLimitTimer = null;
    final startedAt = _guideAudioStartedAt;
    _guideAudioStartedAt = null;
    if (startedAt != null) {
      _guideAudioRecordedDuration += DateTime.now().difference(startedAt);
    }
    try {
      final recording = await _guideAudioCapture.stop();
      if (recording != null) {
        if (discard) {
          await recording.delete();
        } else {
          _pendingGuideAudioRecordings.add(recording);
        }
      }
      if (discard) {
        for (final pending in _pendingGuideAudioRecordings) {
          await pending.delete();
        }
        _pendingGuideAudioRecordings.clear();
        _guideAudioRecordedDuration = Duration.zero;
      }
    } catch (_) {
      if (discard) {
        for (final pending in _pendingGuideAudioRecordings) {
          try {
            await pending.delete();
          } catch (_) {}
        }
        _pendingGuideAudioRecordings.clear();
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Temporary audio cleanup could not be confirmed. It remains in app-private cache and will be retried.',
            ),
          ),
        );
      }
    }
  }

  Future<void> sendRemoteInput(Map<String, dynamic> event) async {
    if (!_remoteControlGranted || widget.isHelpee) return;
    _sendRealtimeOrP2P({'type': 'remote_control_input', 'event': event});
  }

  List<Map<String, dynamic>> _overlayPayload() => _strokes
      .followedBy(_draftStroke == null ? const <DrawStroke>[] : [_draftStroke!])
      .map(
        (stroke) => {
          'points': stroke.points
              .map((point) => {'x': point.dx, 'y': point.dy})
              .toList(),
          'color': stroke.color.toARGB32(),
          'width': stroke.width,
        },
      )
      .toList();

  Future<void> _pushOverlay() async {
    if (!widget.isHelpee || !_helpeeOverlayRunning) return;
    try {
      await AnnotationOverlayService.updateStrokes(_overlayPayload());
    } catch (e) {
      debugPrint('Annotation overlay update failed: $e');
    }
  }

  void _pushOverlayThrottled() {
    if (!widget.isHelpee || !_helpeeOverlayRunning) return;
    if (_overlayTimer?.isActive == true) return;
    _overlayTimer = Timer(const Duration(milliseconds: 33), () {
      _overlayTimer = null;
      _pushOverlay();
    });
  }

  Future<void> _startHelpeeOverlay() async {
    if (!widget.isHelpee || _helpeeOverlayRunning) return;
    try {
      var allowed = await AnnotationOverlayService.canDrawOverlays();
      if (!allowed && mounted) {
        final openSettings = await showDialog<bool>(
          context: context,
          barrierDismissible: false,
          builder: (ctx) => AlertDialog(
            backgroundColor: AppTheme.bgSecondary,
            title: const Text('Keep guidance visible'),
            content: const Text(
              'Allow AssistMe to display the helper\'s annotations above other '
              'apps. The drawing itself cannot receive touches. Your STOP and '
              'Clear controls remain yours at all times.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Not now'),
              ),
              ElevatedButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Open settings'),
              ),
            ],
          ),
        );
        if (openSettings == true) {
          await AnnotationOverlayService.requestPermission();
          for (var i = 0; i < 120 && mounted; i++) {
            await Future<void>.delayed(const Duration(milliseconds: 500));
            allowed = await AnnotationOverlayService.canDrawOverlays();
            if (allowed) break;
          }
        }
      }
      if (!allowed) return;
      await AnnotationOverlayService.start();
      _helpeeOverlayRunning = true;
      await _pushOverlay();
    } catch (e) {
      debugPrint('Helpee overlay failed to start: $e');
    }
  }

  /// Helpee STOP – VISION §12.5 panic: immediately shuts down everything for
  /// both sides (screen, annotations, control, overlay) so helper never sees
  /// stale docs after helpee closed the app or tapped STOP.
  Future<void> _panicStop({
    bool isLocalLeave = false,
    bool skipGuideFinalization = false,
  }) async {
    if (_sessionTerminationHandled) return;
    _sessionTerminationHandled = true;

    // The helper owns the guide. Finalize and sync it while the secure data
    // channel is still alive, before either participant leaves the session.
    if (!widget.isHelpee && !skipGuideFinalization) {
      await _offerLocalGuideSave();
    }

    _sendRealtimeOrP2P({'type': 'session_ended'});
    _sendRealtimeOrP2P({'type': 'draw_clear'});
    try {
      await widget.apiClient.post('/sessions/${widget.sessionId}/leave');
    } catch (_) {}
    _remoteControlGranted = false;
    widget.remoteControlSink?.value = false;
    await _clearDrawings(notifyOverlay: true);
    await stopScreenShare();
    try {
      await AnnotationOverlayService.stop();
    } catch (_) {}
    _helpeeOverlayRunning = false;
    if (mounted) setState(() {});

    if (widget.isHelpee) await _offerLocalGuideSave();

    if (!isLocalLeave) {
      await widget.onSessionEnded?.call();
    }
    await widget.onSessionClosed?.call();
  }

  Future<void> _offerLocalGuideSave() async {
    if (_guideReviewShown || !mounted) return;
    _guideReviewShown = true;
    _localGuideAudioConsent = false;
    _peerGuideAudioConsent = false;
    await _stopGuideAudioCapture(discard: widget.isHelpee);
    if (!mounted) return;
    _setGuideAudioStatus(GuideAudioCaptureStatus.off);

    // The helpee no longer has a save/redaction/review prompt. The helper's
    // finalized guide arrives over the encrypted peer data channel and is
    // stored automatically by _receiveFinalizedGuide().
    if (widget.isHelpee) {
      await _deletePendingGuideAudio();
      return;
    }

    final now = DateTime.now();
    // The dialog now owns these files and deletes them after transcription,
    // save or discard.
    final audioRecordings = List<LocalGuideAudioRecording>.of(
      _pendingGuideAudioRecordings,
    );
    _pendingGuideAudioRecordings.clear();
    final input = await showDialog<LocalGuideSaveInput>(
      context: context,
      barrierDismissible: false,
      builder: (_) => LocalGuideSaveDialog(
        frames: _keyframeManager.keyframes,
        audioRecordings: audioRecordings,
        helperCuratedFrames: true,
        guideOwner: true,
        suggestedTitle:
            'Help guide ${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}',
      ),
    );
    if (!mounted) return;
    if (input == null) {
      await _sendGuideFinalization(saved: false);
      return;
    }
    try {
      final transcript = input.transcript;
      final includedFrames = _keyframeManager.keyframes
          .where((frame) => input.includedFrameIds.contains(frame.id))
          .map((frame) {
            final generatedInstruction = input.generatedInstructions[frame.id]
                ?.trim();
            return CapturedKeyframe(
              id: frame.id,
              timestamp: frame.timestamp,
              imageBytes: input.redactedImages[frame.id] ?? frame.imageBytes,
              // The dialog's titles are the helper's own or reviewed AI drafts.
              title: input.generatedTitles[frame.id] ?? frame.title,
              instruction:
                  generatedInstruction == null || generatedInstruction.isEmpty
                  ? frame.instruction
                  : generatedInstruction,
              perceptualHash: frame.perceptualHash,
              colorSignature: frame.colorSignature,
            );
          })
          .followedBy(
            input.textSteps.indexed.map(
              (entry) => CapturedKeyframe(
                id: 'text-${now.microsecondsSinceEpoch}-${entry.$1}',
                timestamp: now,
                imageBytes: Uint8List(0),
                title: entry.$2.title,
                instruction: entry.$2.instruction,
                perceptualHash: null,
                colorSignature: null,
                privacyReviewed: true,
              ),
            ),
          )
          .toList(growable: false);
      final guide = await LocalGuideStore(secureStorage: widget.secureStorage)
          .saveSession(
            title: input.title,
            summary: transcript.isEmpty
                ? includedFrames.isEmpty
                      ? 'Notes from an assistance session.'
                      : 'Draft guide from an assistance session. Review each step before relying on it.'
                : transcript.length > 320
                ? '${transcript.substring(0, 317)}…'
                : transcript,
            transcript: transcript,
            frames: includedFrames,
            sessionId: widget.sessionId,
          );
      final synced = await _sendGuideFinalization(
        saved: true,
        title: input.title,
        summary: guide.summary,
        transcript: transcript,
        frames: includedFrames,
      );
      // The call is not needed for delivery: if the live sync failed, the
      // guide goes through the backend, encrypted, whenever the other phone
      // is next online.
      var queued = false;
      if (!synced) {
        try {
          queued = await GuideDeliveryService.sendAfterCall(
            apiClient: widget.apiClient,
            sessionId: widget.sessionId,
            key: _guideSyncKey,
            title: input.title,
            summary: guide.summary,
            transcript: transcript,
            frames: includedFrames,
          );
        } catch (error) {
          debugPrint('[AssistMe][GUIDE] post-call delivery failed: $error');
        }
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              synced
                  ? 'Saved “${guide.title}” on both devices.'
                  : queued
                  ? 'Saved “${guide.title}” here. It will reach the other phone the next time it is online.'
                  : 'Saved “${guide.title}” here. It will be sent to the other phone when this phone is back online.',
            ),
          ),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Could not encrypt and save this guide.'),
          ),
        );
      }
    }
  }

  Future<void> _deletePendingGuideAudio() async {
    for (final recording in _pendingGuideAudioRecordings) {
      try {
        await recording.delete();
      } catch (_) {}
    }
    _pendingGuideAudioRecordings.clear();
  }

  Future<bool> _sendGuideFinalization({
    required bool saved,
    String? title,
    String? summary,
    String? transcript,
    List<CapturedKeyframe> frames = const [],
  }) async {
    final steps = frames
        .map(
          (frame) => {
            'id': frame.id,
            'title': frame.title,
            'instruction': frame.instruction,
            // Written steps have no screenshot for the helpee to look up.
            'has_image': frame.imageBytes.isNotEmpty,
          },
        )
        .toList(growable: false);
    final payload = <String, dynamic>{
      'type': 'guide_finalize',
      'saved': saved,
      if (saved) ...{
        'title': title,
        'summary': summary,
        'transcript': transcript,
        'steps': steps,
      },
    };
    if (!saved) {
      // Nothing to deliver: tell the helpee once and leave right away instead
      // of waiting up to 25 s for a reply (that made "End call" feel stuck).
      _engine.sendData(payload);
      return false;
    }
    // The peer is gone: skip the live path, the post-call delivery takes over.
    if (!_engine.isDataChannelOpen) return false;
    if (saved) {
      _sendGuideSyncKey();
      // Let screenshots still being sent in the background finish first.
      await _helpeeSendChain.timeout(
        const Duration(seconds: 30),
        onTimeout: () {},
      );
      // Steps captured while the channel was busy only exist here so far.
      // Send them now so the helpee can attach every screenshot.
      for (final frame in frames) {
        if (frame.imageBytes.isEmpty || !mounted) continue;
        final delivered = await _sendGuideFrameToHelpee(
          id: frame.id,
          bytes: frame.imageBytes,
          title: frame.title,
          instruction: frame.instruction,
        );
        if (!delivered) {
          debugPrint('[AssistMe][GUIDE] screenshot ${frame.id} still missing on helpee');
        }
      }
    }
    final ack = Completer<bool>();
    _pendingGuideFinalizationAck = ack;
    try {
      var sent = false;
      for (var attempt = 0; attempt < 6 && mounted; attempt++) {
        if (_engine.sendData(payload)) {
          sent = true;
          break;
        }
        await Future<void>.delayed(const Duration(milliseconds: 500));
      }
      if (!sent) return false;
      return await ack.future.timeout(const Duration(seconds: 10));
    } catch (_) {
      return false;
    } finally {
      if (identical(_pendingGuideFinalizationAck, ack)) {
        _pendingGuideFinalizationAck = null;
      }
    }
  }

  Future<void> _receiveFinalizedGuide(Map<String, dynamic> data) async {
    final saved = data['saved'] == true;
    if (!saved) {
      _engine.sendData({'type': 'guide_finalize_ack', 'saved': false});
      return;
    }
    if (!widget.isHelpee) {
      _engine.sendData({'type': 'guide_finalize_ack', 'saved': false});
      return;
    }

    try {
      final title = data['title'];
      final summary = data['summary'];
      final transcript = data['transcript'];
      final rawSteps = data['steps'];
      if (title is! String ||
          title.trim().isEmpty ||
          title.length > 100 ||
          summary is! String ||
          transcript is! String ||
          transcript.length > 20000 ||
          rawSteps is! List) {
        throw const FormatException('Invalid finalized guide metadata.');
      }
      final cachedFrames = {
        for (final frame in _keyframeManager.keyframes) frame.id: frame,
      };
      final frames = <CapturedKeyframe>[];
      for (final rawStep in rawSteps) {
        if (rawStep is! Map) {
          throw const FormatException('Invalid guide step.');
        }
        final step = Map<String, dynamic>.from(rawStep);
        final id = step['id'];
        final stepTitle = step['title'];
        final instruction = step['instruction'];
        if (step['has_image'] == false) {
          if (id is! String ||
              id.isEmpty ||
              id.length > 100 ||
              stepTitle is! String ||
              stepTitle.length > 100 ||
              instruction is! String ||
              instruction.length > 4000) {
            throw const FormatException('A written guide step is invalid.');
          }
          frames.add(
            CapturedKeyframe(
              id: id,
              timestamp: DateTime.now(),
              imageBytes: Uint8List(0),
              title: stepTitle,
              instruction: instruction,
              perceptualHash: null,
              colorSignature: null,
              privacyReviewed: true,
            ),
          );
          continue;
        }
        if (id is! String ||
            stepTitle is! String ||
            stepTitle.length > 100 ||
            instruction is! String ||
            instruction.length > 4000) {
          throw const FormatException('A guide step is invalid.');
        }
        final cached = cachedFrames[id];
        if (cached == null) {
          // The screenshot never arrived. Keep the written step rather than
          // losing the whole guide.
          debugPrint('[AssistMe][GUIDE] screenshot $id missing; saving step as text');
          frames.add(
            CapturedKeyframe(
              id: id,
              timestamp: DateTime.now(),
              imageBytes: Uint8List(0),
              title: stepTitle,
              instruction: instruction,
              perceptualHash: null,
              colorSignature: null,
              privacyReviewed: true,
            ),
          );
          continue;
        }
        frames.add(
          CapturedKeyframe(
            id: cached.id,
            timestamp: cached.timestamp,
            imageBytes: cached.imageBytes,
            title: stepTitle,
            instruction: instruction,
            perceptualHash: cached.perceptualHash,
            colorSignature: cached.colorSignature,
            privacyReviewed: true,
          ),
        );
      }
      final guide = await LocalGuideStore(secureStorage: widget.secureStorage)
          .saveSession(
            title: title.trim(),
            summary: summary,
            transcript: transcript,
            frames: frames,
            sessionId: widget.sessionId,
          );
      _engine.sendData({'type': 'guide_finalize_ack', 'saved': true});
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('“${guide.title}” was saved from your helper.')),
        );
      }
    } catch (_) {
      _engine.sendData({'type': 'guide_finalize_ack', 'saved': false});
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('The helper guide could not be synced.')),
        );
      }
    }
  }

  Future<void> leave() async {
    if (!widget.isHelpee) {
      await _panicStop(isLocalLeave: true);
      return;
    }

    if (_sessionTerminationHandled || _waitingForHelperFinalization) return;
    _waitingForHelperFinalization = true;
    final ended = Completer<void>();
    _sessionEndCompleter = ended;
    _sendRealtimeOrP2P({'type': 'session_end_requested'});
    _showGuideMessage('Waiting for your helper to finish and sync the guide…');
    try {
      // Transcribing and running Gemma on the helper's phone can take a few
      // minutes; leaving earlier would lose the synced guide.
      await ended.future.timeout(const Duration(minutes: 5));
    } on TimeoutException {
      // If the helper is gone, let the helpee leave cleanly after the bounded
      // wait. The helper remains the only participant who can finalize a guide.
      await _panicStop(isLocalLeave: true, skipGuideFinalization: true);
    } finally {
      _waitingForHelperFinalization = false;
      if (identical(_sessionEndCompleter, ended)) _sessionEndCompleter = null;
    }
  }

  Future<void> requestGuideScreenshot() async {
    if (!widget.isHelpee) return;
    _sendRealtimeOrP2P({'type': 'guide_screenshot_request'});
    _showGuideMessage('Screenshot request sent to your helper.');
  }

  Future<void> _bootstrap() async {
    final fingerprint = await DeviceIdentity.getFingerprint(
      widget.secureStorage,
    );
    final token = await widget.secureStorage.getAccessToken();
    setState(() => _helperDeviceFingerprint = fingerprint);

    _bootstrapping = true;
    Future<void> connectRealtime() async {
      if (token == null) return;
      try {
        _realtime = RealtimeService(
          sessionId: widget.sessionId,
          accessToken: token,
          accessTokenProvider: widget.apiClient.getRealtimeAccessToken,
        );
        _realtime!.onConnected = _handleRealtimeConnected;
        _realtime!.onConnectionIssue = _handleSignalingIssue;
        _realtime!.events.listen(_onEvent);
        await _realtime!.connect();
      } catch (e) {
        debugPrint('Realtime connect failed: $e');
      }
    }

    // Signaling, ICE credentials, and local media setup do not depend on one
    // another. Run them together so session startup takes roughly the slower
    // of the two paths instead of adding their network and permission delays.
    try {
      await Future.wait<void>([connectRealtime(), _initMediaEngine()]);
    } finally {
      _bootstrapping = false;
    }

    // Screen share is started by an explicit tap on "Start Sharing"
    // (no auto-start) so the mic + MediaProjection consent dialogs appear
    // while the UI is fully settled, not mid-mount.
  }

  /// Re-negotiate after the signaling socket returns. The local MediaProjection
  /// and microphone tracks are kept alive; only the stale peer connection is
  /// replaced. This avoids a second Android capture consent flow and restores
  /// the remote video after either phone briefly drops off the network.
  Future<void> _handleRealtimeConnected() async {
    debugPrint(
      '[AssistMe][CALL] signaling connected '
      'role=${widget.isHelpee ? 'helpee' : 'helper'} '
      'shareActive=$_screenShareStarted bootstrapping=$_bootstrapping',
    );
    if (widget.isHelpee && _shareWaitingForSignaling && !_screenShareStarted) {
      _shareWaitingForSignaling = false;
      debugPrint(
        '[AssistMe][CALL] signaling ready; starting the screen share that was waiting for it',
      );
      unawaited(startScreenShare());
      return;
    }
    // The first connection is part of bootstrap. Media setup sends the initial
    // offer once it is ready, so recovery here would rebuild an empty peer.
    if (_bootstrapping) return;
    await Future<void>.delayed(const Duration(milliseconds: 400));
    if (!mounted || _mediaRecovering) return;
    if (widget.isHelpee && _screenShareStarted) {
      await _recoverMedia(sendOffer: true);
    } else if (!widget.isHelpee) {
      // Helper reconnected but still has no video – ask helpee to re-offer.
      // The video check uses notifier so we don't trigger when video already live.
      if (remoteStreamNotifier.value == null) {
        await _recoverMedia(sendOffer: false);
        // Nudge helpee to re-create offer if it hasn't already (e.g., helpee
        // didn't detect the reconnect). This also restores mic.
        _realtime?.send({'type': 'request_offer'});
      }
    }
  }

  Future<void> _recoverMedia({
    required bool sendOffer,
    bool forceRelayOnly = false,
  }) async {
    if (!_mediaReady || _mediaRecovering) return;
    _mediaRecovering = true;
    _remoteDescriptionSet = false;
    _pendingIceCandidates.clear();
    remoteStreamNotifier.value = null;
    try {
      await _engine.rebuildPeerConnection(forceRelayOnly: forceRelayOnly);
      // Ensure mic is re-attached and respects previous mute state – VISION requires
      // reconnection restores full session (voice + video), not just video.
      if (!widget.isHelpee) {
        await _engine.startMicOnly();
        // Re-apply mute state so mic doesn't stay muted after rebuild.
        await _engine.toggleAudioMute(_engine.isAudioMuted);
      } else {
        // Helpee: mic was via screen capture's addMicrophone; ensure it's there.
        // If screen stream was lost (e.g., app backgrounded), restart capture silently.
        if (_engine.isScreenSharing) {
          // Ensure mic track exists even after rebuild
          await _engine.startMicOnly();
        }
        if (sendOffer) {
          final offer = await _engine.createOffer();
          _realtime?.send({'type': 'signal_offer', 'sdp': offer});
        }
      }
    } catch (e) {
      debugPrint('WebRTC recovery failed: $e');
    } finally {
      _mediaRecovering = false;
      final pendingOffer = _pendingOffer;
      _pendingOffer = null;
      if (!widget.isHelpee && pendingOffer != null && mounted) {
        await _handleIncomingOffer(pendingOffer);
      }
    }
  }

  // ------------------------------------------------------------------
  // WebRTC media pipeline (screen share + two-way voice)
  // ------------------------------------------------------------------

  Future<void> _initMediaEngine() async {
    // Ask for mic up front so the later call never fails silently.
    await Permission.microphone.request();

    List<Map<String, dynamic>> iceServers = const [
      {'urls': 'stun:stun.l.google.com:19302'},
    ];
    try {
      final resp = await widget.apiClient.getIceServers(widget.sessionId);
      if (resp.statusCode == 200) {
        final servers = jsonDecode(resp.body)['ice_servers'] as List;
        iceServers = servers.map<Map<String, dynamic>>((s) {
          final m = Map<String, dynamic>.from(s as Map);
          // Android's IceServer builder throws on explicit null
          // username/credential keys sent for plain STUN entries.
          m.removeWhere((k, v) => v == null);
          return m;
        }).toList();
        final hasRelay = iceServers.any((server) {
          final urls = server['urls'];
          return urls is String
              ? urls.startsWith('turn:') || urls.startsWith('turns:')
              : urls is List &&
                    urls.any(
                      (url) =>
                          url is String &&
                          (url.startsWith('turn:') || url.startsWith('turns:')),
                    );
        });
        if (!hasRelay) {
          debugPrint(
            'ICE configuration has no TURN relay; calls may fail behind UDP-blocking firewalls.',
          );
        }
      } else {
        debugPrint(
          'ICE configuration request returned ${resp.statusCode}; trying STUN-only.',
        );
      }
    } catch (error) {
      // STUN-only is useful on permissive networks, but cannot relay media
      // through firewalls that block peer-to-peer UDP.
      debugPrint('ICE configuration request failed; trying STUN-only: $error');
    }

    try {
      _engine.onStateChanged = (state) {
        debugPrint(
          '[AssistMe][MEDIA] role=${widget.isHelpee ? 'helpee' : 'helper'} '
          'peer=${state.name}',
        );
      };
      _engine.onIceStateChanged = (state) {
        debugPrint(
          '[AssistMe][MEDIA] role=${widget.isHelpee ? 'helpee' : 'helper'} '
          'ICE=$state',
        );
        if (state.toLowerCase().contains('connected')) {
          _relayFallbackAttempted = false;
          _directIceRecoveryAttempted = false;
        }
        if (state.toLowerCase().contains('failed') &&
            _engine.hasTurnServer &&
            !_relayFallbackAttempted &&
            mounted) {
          _relayFallbackAttempted = true;
          unawaited(_retryUsingRelay());
        } else if (state.toLowerCase().contains('failed') &&
            !_engine.hasTurnServer &&
            !widget.isHelpee &&
            !_directIceRecoveryAttempted &&
            mounted) {
          // Without TURN, a fresh host-candidate negotiation is the only
          // automatic recovery available after a transient network change.
          // Keep the helper as the requester; the helpee remains the sole
          // offerer so both peers do not race to replace the connection.
          _directIceRecoveryAttempted = true;
          unawaited(_retryDirectConnection());
        }
      };
      _engine.onDiagnosticsUpdated = (metrics) {
        debugPrint('[AssistMe][MEDIA] transport=$metrics');
      };
      _engine.onLocalCandidate = (candidate) {
        _realtime?.send({
          'type': 'signal_ice_candidate',
          'candidate': candidate,
        });
      };
      _engine.onDataChannelMessage = (data) {
        final type = data['type'] as String?;
        if (type == null) return;
        if (type.startsWith('guide_frame_') ||
            type.startsWith('guide_finalize')) {
          unawaited(_onGuideFrameMessage(data));
        } else {
          _onEvent(RealtimeEvent(type, data));
        }
      };
      _engine.onDataChannelState = (isOpen) {
        if (isOpen && !widget.isHelpee) _sendGuideSyncKey();
        if (!isOpen &&
            widget.isHelpee &&
            (_localGuideAudioConsent || _guideAudioCapture.isRecording)) {
          _localGuideAudioConsent = false;
          _sendGuideAudioConsent(false);
          unawaited(_stopGuideAudioCapture(discard: true));
          _setGuideAudioStatus(GuideAudioCaptureStatus.off);
        } else if (!isOpen && !widget.isHelpee) {
          // The helpee can no longer see or revoke recording, so stop. What
          // was recorded while consent was given is kept for the guide.
          _peerGuideAudioConsent = false;
          unawaited(_stopGuideAudioCapture(discard: false));
          _setGuideAudioStatus(GuideAudioCaptureStatus.off);
        }
      };
      _engine.onRemoteStream = (stream) {
        // The helpee publishes screen video and mic audio as separate
        // streams; keep whichever carries video for the viewport (remote
        // audio plays through the peer connection regardless).
        final current = remoteStreamNotifier.value;
        debugPrint(
          '[AssistMe][MEDIA] remote stream received '
          'audioTracks=${stream.getAudioTracks().length} '
          'videoTracks=${stream.getVideoTracks().length}',
        );
        if (current == null || stream.getVideoTracks().isNotEmpty) {
          remoteStreamNotifier.value = stream;
        }
      };
      await _engine.initialize(iceServers: iceServers);
      // Start microphone immediately for both sides so voice is connected from second 1
      await _engine.startMicOnly();
      if (mounted) setState(() => _mediaReady = true);

      // Helpee: if not auto-starting screen share immediately, send initial audio offer
      // so two-way voice works while deciding when to share screen.
      if (widget.isHelpee &&
          !_screenShareStarted &&
          !widget.autoStartScreenShare) {
        try {
          final offer = await _engine.createOffer();
          _realtime?.send({'type': 'signal_offer', 'sdp': offer});
        } catch (_) {}
      }

      // The helper can receive the offer before its media engine finishes
      // initializing. Keep it instead of dropping the first negotiation.
      final pendingOffer = _pendingOffer;
      _pendingOffer = null;
      if (pendingOffer != null && !widget.isHelpee) {
        await _handleIncomingOffer(pendingOffer);
      }

      if (mounted && widget.isHelpee && widget.autoStartScreenShare) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted && !_screenShareStarted) startScreenShare();
        });
      }
    } catch (e) {
      debugPrint('WebRTC init failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTheme.accentRose,
            content: Text('Media engine failed to start: $e'),
          ),
        );
      }
    }
  }

  Future<void> _retryUsingRelay() async {
    // A bounded fallback avoids repeatedly rebuilding a call when the TURN
    // service itself is unavailable. The helpee remains the offerer.
    await _recoverMedia(sendOffer: widget.isHelpee, forceRelayOnly: true);
    if (!widget.isHelpee && mounted) {
      _realtime?.send({'type': 'request_relay_offer'});
    }
  }

  Future<void> _retryDirectConnection() async {
    await _recoverMedia(sendOffer: false);
    if (mounted && !widget.isHelpee) {
      _realtime?.send({'type': 'request_offer'});
    }
  }

  void _updateScreenShareState(bool started) {
    if (_screenShareStarted != started) {
      _screenShareStarted = started;
      if (mounted) setState(() {});
      widget.screenSharingSink?.value = started;
    }
  }

  void _handleSignalingIssue(String message) {
    final sessionPrefix = widget.sessionId.length > 6
        ? widget.sessionId.substring(0, 6)
        : widget.sessionId;
    debugPrint(
      '[AssistMe][CALL] role=${widget.isHelpee ? 'helpee' : 'helper'} '
      'session=$sessionPrefix signalingIssue=$message',
    );
    final now = DateTime.now();
    final previous = _lastSignalingWarningAt;
    if (!mounted ||
        (previous != null && now.difference(previous).inSeconds < 15)) {
      return;
    }
    _lastSignalingWarningAt = now;
    final displayMessage = message.length > 180
        ? '${message.substring(0, 180)}…'
        : message;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          duration: const Duration(seconds: 10),
          content: Text(
            'Call signaling is unavailable. Screen, voice, and annotations '
            'cannot negotiate until it reconnects. $displayMessage',
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      );
  }

  /// Helpee: capture screen + mic, then offer to the room.
  Future<void> startScreenShare() async {
    if (_screenShareStarting) return;
    if (_screenShareStarted || !_mediaReady) {
      if (!_mediaReady && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Still connecting... try again in a second'),
          ),
        );
      }
      return;
    }
    if (_realtime?.isConnected != true) {
      debugPrint(
        '[AssistMe][CALL] refusing to start screen share because signaling '
        'websocket is disconnected',
      );
      // Media setup and the signaling socket start in parallel, so the
      // auto-start can arrive a few milliseconds before the socket opens.
      // Start sharing as soon as it does instead of leaving the helper on
      // "Waiting for the other device to share" for the whole call.
      if (widget.isHelpee) _shareWaitingForSignaling = true;
      if (!_bootstrapping) {
        _handleSignalingIssue(
          'The session WebSocket is not connected. Rejoin the session before sharing.',
        );
      }
      return;
    }
    _shareWaitingForSignaling = false;
    _screenShareStarting = true;
    try {
      // Will pop system dialogs: microphone + screen capture
      await _engine.startScreenCapture();
      final offer = await _engine.createOffer();
      final offerSent = _realtime?.send({'type': 'signal_offer', 'sdp': offer}) ?? false;
      if (!offerSent) {
        await _engine.stopScreenCapture();
        throw StateError('The session signaling socket closed before the screen offer was sent.');
      }
      _realtime?.send({'type': 'screen_share_start', 'platform': 'android'});
      _updateScreenShareState(true);
      await _startHelpeeOverlay();
    } catch (e) {
      try {
        await _engine.stopScreenCapture();
      } catch (_) {}
      debugPrint('Screen share failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Could not start sharing: $e'),
            backgroundColor: AppTheme.accentRose,
          ),
        );
      }
    } finally {
      _screenShareStarting = false;
    }
  }

  Future<void> stopScreenShare() async {
    if (!_screenShareStarted) return;
    try {
      await _engine.stopScreenCapture();
      _realtime?.send({'type': 'screen_share_stop'});
      _updateScreenShareState(false);
    } catch (e) {
      debugPrint('Stop screen share failed: $e');
    }
  }

  /// Helper: answer an incoming screen-share offer with our mic attached.
  Future<void> _handleIncomingOffer(
    Map<String, dynamic> sdp, {
    bool onFreshPeer = false,
  }) async {
    if (!_mediaReady || _mediaRecovering) {
      _pendingOffer = sdp;
      return;
    }
    // Queue the offer's ICE candidates until it is applied; candidates sent
    // to a connection that is about to be replaced would be lost.
    _remoteDescriptionSet = false;
    try {
      debugPrint('[AssistMe][CALL] received WebRTC offer; applying remote SDP');
      // Match the offer's transceiver order before adding the helper mic.
      // The caller adds screen video first and audio second; creating an audio
      // transceiver here first can make the answer's SDP m-lines disagree.
      try {
        await _engine.setRemoteDescription(sdp);
      } catch (error) {
        // After the helpee locks the phone, leaves the app or loses signaling,
        // it rebuilds its connection and offers again. That fresh offer cannot
        // be applied to the helper's old connection ("The order of m-lines in
        // subsequent offer doesn't match"), which left the helper on "Waiting
        // for the other device to share" for the rest of the call. Rebuild
        // the helper side to match and apply the offer to the fresh one.
        if (widget.isHelpee || onFreshPeer) rethrow;
        debugPrint(
          '[AssistMe][CALL] offer does not fit the current connection; rebuilding helper peer ($error)',
        );
        remoteStreamNotifier.value = null;
        await _engine.rebuildPeerConnection();
        await _handleIncomingOffer(sdp, onFreshPeer: true);
        return;
      }
      _remoteDescriptionSet = true;
      if (!widget.isHelpee) {
        await _engine.startMicOnly();
        if (onFreshPeer) {
          // Keep the helper's mute choice on the rebuilt connection.
          await _engine.toggleAudioMute(_engine.isAudioMuted);
        }
      }
      for (final candidate in _pendingIceCandidates) {
        await _engine.addIceCandidate(candidate);
      }
      _pendingIceCandidates.clear();
      final answer = await _engine.createAnswer();
      final answerSent = _realtime?.send({'type': 'signal_answer', 'sdp': answer}) ?? false;
      debugPrint('[AssistMe][CALL] answer written to signaling socket=$answerSent');
    } catch (e) {
      debugPrint('Answering offer failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            backgroundColor: AppTheme.accentRose,
            content: Text(
              'The shared screen could not reconnect. Ask them to tap Stop Sharing, then share again.',
            ),
          ),
        );
      }
    }
  }

  bool _acceptRemoteDrawPreview(Map<String, dynamic> data) {
    final rawStrokeId = data['stroke_id'];
    final rawSequence = data['preview_sequence'];
    // Accept legacy peers that do not send ordering metadata.
    if (rawStrokeId is! num || rawSequence is! num) return true;

    final strokeId = rawStrokeId.toInt();
    final sequence = rawSequence.toInt();
    if (strokeId <= _lastRemoteCommittedStrokeId ||
        strokeId < _lastRemotePreviewStrokeId ||
        (strokeId == _lastRemotePreviewStrokeId &&
            sequence <= _lastRemotePreviewSequence)) {
      return false;
    }
    if (strokeId > _lastRemotePreviewStrokeId) {
      _lastRemotePreviewStrokeId = strokeId;
      _lastRemotePreviewSequence = -1;
    }
    _lastRemotePreviewSequence = sequence;
    _remoteDraftStrokeId = strokeId;
    return true;
  }

  Future<void> _onEvent(RealtimeEvent event) async {
    switch (event.type) {
      case 'assistance_requested':
        // A helpee is asking us (helper) for help.
        final requestId = event.data['request_id'];
        if (widget.isHelpee) break;
        setState(() {
          _pendingRequestId = requestId;
        });
        break;

      case 'escalation_requested':
        // Helper wants more control; we are the helpee.
        final escalationId = event.data['escalation_id'];
        final disclaimer = event.data['disclaimer_text'];
        if (!widget.isHelpee) break;
        setState(() {
          _pendingEscalation = {
            'id': escalationId,
            'disclaimer_text': disclaimer ?? '',
          };
        });
        break;

      case 'draw_stroke':
        // Helper sends draw points for the overlay.
        final raw = event.data['points'];
        if (raw is List) {
          final points = <Offset>[];
          for (final item in raw) {
            if (item is Map) {
              final dx = item['x'] as num;
              final dy = item['y'] as num;
              points.add(Offset(dx.toDouble(), dy.toDouble()));
            }
          }
          final rawStrokeId = event.data['stroke_id'];
          final strokeId = rawStrokeId is num ? rawStrokeId.toInt() : null;
          final keepNewerDraft =
              strokeId != null &&
              _remoteDraftStrokeId != null &&
              _remoteDraftStrokeId! > strokeId;
          if (strokeId != null && strokeId > _lastRemoteCommittedStrokeId) {
            _lastRemoteCommittedStrokeId = strokeId;
          }
          if (strokeId != null && _remoteDraftStrokeId == strokeId) {
            _remoteDraftStrokeId = null;
          }
          final rawColor = event.data['color'];
          final rawWidth = event.data['width'];
          _overlayTimer?.cancel();
          _overlayTimer = null;
          setState(() {
            if (!keepNewerDraft) _draftStroke = null;
            _redoStrokes.clear();
            _strokes.add(
              DrawStroke(
                points: points,
                color: rawColor is num
                    ? Color(rawColor.toInt())
                    : const Color(0xFFFF3B30),
                width: rawWidth is num ? rawWidth.toDouble() : 4,
              ),
            );
          });
          _pushOverlay();
        }
        break;

      case 'draw_preview':
        if (!_acceptRemoteDrawPreview(event.data)) break;
        final raw = event.data['points'];
        if (raw is List) {
          final points = <Offset>[];
          for (final item in raw) {
            if (item is Map && item['x'] is num && item['y'] is num) {
              points.add(
                Offset(
                  (item['x'] as num).toDouble(),
                  (item['y'] as num).toDouble(),
                ),
              );
            }
          }
          final color = event.data['color'];
          final width = event.data['width'];
          setState(
            () => _draftStroke = DrawStroke(
              points: points,
              color: color is num
                  ? Color(color.toInt())
                  : const Color(0xFFFF3B30),
              width: width is num ? width.toDouble() : 4,
            ),
          );
          _pushOverlayThrottled();
        }
        break;

      case 'draw_erase':
        final point = event.data['point'];
        if (point is Map && point['x'] is num && point['y'] is num) {
          final target = Offset(
            (point['x'] as num).toDouble(),
            (point['y'] as num).toDouble(),
          );
          setState(
            () => _strokes.removeWhere(
              (stroke) => strokeNearPoint(stroke, target),
            ),
          );
          _pushOverlay();
        }
        break;

      case 'draw_undo':
        if (_strokes.isNotEmpty) {
          setState(() => _redoStrokes.add(_strokes.removeLast()));
          _pushOverlay();
        }
        break;

      case 'draw_redo':
        if (_redoStrokes.isNotEmpty) {
          setState(() => _strokes.add(_redoStrokes.removeLast()));
          _pushOverlay();
        }
        break;

      case 'draw_clear':
        final rawStrokeId = event.data['stroke_id'];
        if (rawStrokeId is num &&
            rawStrokeId.toInt() > _lastRemoteCommittedStrokeId) {
          _lastRemoteCommittedStrokeId = rawStrokeId.toInt();
        }
        _remoteDraftStrokeId = null;
        setState(() {
          _draftStroke = null;
          _strokes.clear();
          _redoStrokes.clear();
        });
        _pushOverlay();
        break;

      case 'escalation_responded':
        if (!widget.isHelpee && event.data['status'] == 'approved') {
          _remoteControlGranted = true;
          widget.remoteControlSink?.value = true;
          if (mounted) setState(() {});
        }
        break;

      case 'remote_control_revoked':
        _remoteControlGranted = false;
        widget.remoteControlSink?.value = false;
        if (mounted) setState(() {});
        break;

      case 'remote_control_input':
        if (widget.isHelpee && _remoteControlGranted) {
          final rawEvent = event.data['event'];
          if (rawEvent is Map) {
            AccessibilityBridge.dispatchInput(
              Map<String, dynamic>.from(rawEvent),
            );
          }
        }
        break;

      case 'user_disconnected':
        _disconnectCountdownTimer?.cancel();
        _disconnectCountdownTimer = null;
        if (!widget.isHelpee) {
          final isReconnecting = event.data['reconnecting'] == true;
          if (!isReconnecting) {
            // Helpee permanently disconnected: Disconnection is INSTANT for the helper!
            _panicStop(isLocalLeave: false);
            return;
          }
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('${widget.peerName} is reconnecting…'),
                duration: const Duration(seconds: 2),
              ),
            );
          }
          return;
        }
        // Helper disconnected: Helpee gets the 10-second countdown with Wait (+30s) button
        _totalAloneSeconds = 0;
        setState(() {
          _disconnectCountdownSeconds = 10;
        });
        _disconnectCountdownTimer = Timer.periodic(const Duration(seconds: 1), (
          timer,
        ) {
          if (!mounted) {
            timer.cancel();
            return;
          }
          _totalAloneSeconds++;
          if (_totalAloneSeconds >= _maxAloneSeconds) {
            timer.cancel();
            _disconnectCountdownTimer = null;
            setState(() {
              _disconnectCountdownSeconds = null;
            });
            _panicStop(isLocalLeave: false);
            return;
          }
          if ((_disconnectCountdownSeconds ?? 0) <= 1) {
            timer.cancel();
            _disconnectCountdownTimer = null;
            setState(() {
              _disconnectCountdownSeconds = null;
            });
            _panicStop(isLocalLeave: false);
          } else {
            setState(() {
              _disconnectCountdownSeconds =
                  (_disconnectCountdownSeconds ?? 1) - 1;
            });
          }
        });
        break;

      case 'user_reconnected':
        _disconnectCountdownTimer?.cancel();
        _disconnectCountdownTimer = null;
        _totalAloneSeconds = 0;
        if (_disconnectCountdownSeconds != null) {
          setState(() {
            _disconnectCountdownSeconds = null;
          });
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('${widget.peerName} reconnected.'),
                backgroundColor: AppTheme.accentEmerald,
                duration: const Duration(seconds: 3),
              ),
            );
          }
        }
        // A new WebSocket is not enough to restore an old ICE/DTLS session.
        // Rebuild the media transport on both sides; the helpee is the only
        // side that creates the fresh screen-share offer.
        if (widget.isHelpee && _screenShareStarted) {
          _recoverMedia(sendOffer: true);
        } else if (!widget.isHelpee) {
          _recoverMedia(sendOffer: false);
        }
        break;

      case 'request_offer':
        if (widget.isHelpee) {
          if (!_screenShareStarted && widget.autoStartScreenShare) {
            startScreenShare();
          } else if (_screenShareStarted && !_mediaRecovering) {
            _recoverMedia(sendOffer: true);
          }
        }
        break;

      case 'request_relay_offer':
        if (widget.isHelpee && !_relayFallbackAttempted) {
          _relayFallbackAttempted = true;
          await _recoverMedia(sendOffer: true, forceRelayOnly: true);
        }
        break;

      case 'screen_share_start':
        // The matching offer is sent immediately before this event. Requesting
        // another offer here can collide with the first negotiation.
        break;

      case 'hide_controls_for_capture':
        if (widget.isHelpee) {
          final ms = (event.data['ms'] as num?)?.toInt() ?? 1500;
          try {
            await AnnotationOverlayService.hideControlsFor(
              Duration(milliseconds: ms.clamp(200, 5000)),
            );
          } catch (_) {
            // Overlay not running: nothing to hide.
          }
        }
        break;

      case 'guide_audio_consent_request':
        await _requestHelpeeGuideAudioConsent();
        break;

      case 'guide_audio_consent':
        if (!widget.isHelpee) {
          _peerGuideAudioConsent = event.data['consented'] == true;
          _setGuideAudioStatus(
            _peerGuideAudioConsent
                ? GuideAudioCaptureStatus.consented
                : GuideAudioCaptureStatus.off,
          );
          if (!_peerGuideAudioConsent) {
            // Revoked: nothing recorded on this phone may be kept.
            await _stopGuideAudioCapture(discard: true);
            _showGuideMessage(
              'Guide-audio permission was declined or revoked.',
            );
          }
        }
        break;

      case 'guide_audio_capture_control':
        await _handleGuideAudioCaptureCommand(
          event.data['action'] as String? ?? '',
        );
        break;

      case 'guide_audio_capture_status':
        if (widget.isHelpee) {
          // The helper records; mirror its state so the helpee always sees it.
          if (_localGuideAudioConsent) {
            _setGuideAudioStatus(
              event.data['state'] == 'recording'
                  ? GuideAudioCaptureStatus.recording
                  : GuideAudioCaptureStatus.consented,
            );
          }
        } else {
          final state = event.data['state'] as String?;
          _setGuideAudioStatus(switch (state) {
            'recording' => GuideAudioCaptureStatus.recording,
            'consented' => GuideAudioCaptureStatus.consented,
            _ => GuideAudioCaptureStatus.off,
          });
          final error = event.data['error'] as String?;
          if (error == 'limit') {
            _showGuideMessage('The 20 minute guide-audio limit was reached.');
          } else if (error == 'capture') {
            _showGuideMessage(
              'Audio capture could not start on the other phone.',
            );
          }
        }
        break;

      // --- WebRTC signaling relay ---
      case 'signal_offer':
        if (!widget.isHelpee) {
          debugPrint('[AssistMe][CALL] signaling delivered signal_offer to helper');
          final sdp = event.data['sdp'];
          if (sdp is Map) _handleIncomingOffer(Map<String, dynamic>.from(sdp));
        }
        break;

      case 'signal_answer':
        if (widget.isHelpee) {
          debugPrint('[AssistMe][CALL] signaling delivered signal_answer to helpee');
          final sdp = event.data['sdp'];
          if (sdp is Map) {
            _engine
                .setRemoteDescription(Map<String, dynamic>.from(sdp))
                .then((_) async {
                  _remoteDescriptionSet = true;
                  for (final candidate in _pendingIceCandidates) {
                    await _engine.addIceCandidate(candidate);
                  }
                  _pendingIceCandidates.clear();
                })
                .catchError((e) {
                  debugPrint('Applying answer failed: $e');
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        backgroundColor: AppTheme.accentRose,
                        content: Text('Connection problem: $e'),
                      ),
                    );
                  }
                });
          }
        }
        break;

      case 'signal_ice_candidate':
        final candidate = event.data['candidate'];
        if (candidate is Map) {
          debugPrint(
            '[AssistMe][CALL] remote ICE candidate received '
            'remoteDescriptionSet=$_remoteDescriptionSet',
          );
          final normalized = Map<String, dynamic>.from(candidate);
          if (!_remoteDescriptionSet) {
            _pendingIceCandidates.add(normalized);
          } else {
            _engine.addIceCandidate(normalized);
          }
        }
        break;

      case 'assistance_request_responded':
        // Helper accepted: helpee starts sharing automatically.
        if (widget.isHelpee &&
            event.data['status'] == 'accepted' &&
            !_screenShareStarted) {
          startScreenShare();
        }
        break;

      case 'screen_share_stop':
        if (!widget.isHelpee) remoteStreamNotifier.value = null;
        break;
      case 'guide_screenshot_request':
        if (!widget.isHelpee) unawaited(captureGuideStep());
        break;
      case 'session_end_requested':
        if (!widget.isHelpee) {
          unawaited(_panicStop(isLocalLeave: false));
        }
        break;
      case 'user_left':
      case 'session_ended':
      case 'session_closed':
        if (_sessionTerminationHandled) break;
        _sessionTerminationHandled = true;
        _disconnectCountdownTimer?.cancel();
        _disconnectCountdownTimer = null;
        _disconnectCountdownSeconds = null;
        _totalAloneSeconds = 0;
        // VISION: either side shutting down must clear everything for the other – annotations, overlay, control.
        _clearDrawings(notifyOverlay: true);
        stopScreenShare();
        try {
          await AnnotationOverlayService.stop();
        } catch (_) {}
        _remoteControlGranted = false;
        widget.remoteControlSink?.value = false;
        if (event.type == 'session_ended' &&
            _sessionEndCompleter != null &&
            !_sessionEndCompleter!.isCompleted) {
          _sessionEndCompleter!.complete();
        }
        await _offerLocalGuideSave();
        remoteStreamNotifier.value = null;
        _helpeeOverlayRunning = false;
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Help session ended.'),
              duration: Duration(seconds: 2),
            ),
          );
          widget.onSessionEnded?.call();
        }
        break;
    }
  }

  // ------------------------------------------------------------------
  // Helpee actions
  // ------------------------------------------------------------------

  bool get isRequestingHelp => _isRequestingHelp;

  Future<void> requestHelp() async {
    if (_isRequestingHelp) return;

    // Load the trusted devices so the user can pick the helper's device.
    List<Map<String, dynamic>> trusted = [];
    try {
      final resp = await widget.apiClient.listTrustedDevices();
      if (resp.statusCode == 200) {
        trusted = List<Map<String, dynamic>>.from(
          jsonDecode(resp.body)['devices'],
        );
      }
    } catch (_) {
      // fall through, dialog will explain
    }

    final selection = await _promptHelperSelection(trusted);
    if (selection == null) return;
    final helperUserId = selection['userId'] as String;
    final helperFingerprint = selection['fingerprint'] as String;

    setState(() => _isRequestingHelp = true);
    try {
      final resp = await widget.apiClient.requestHelp(
        sessionId: widget.sessionId,
        helperUserId: helperUserId,
        helperDeviceFingerprint: helperFingerprint,
      );
      if (resp.statusCode == 201) {
        // Broadcast the request to the room (helper will see the popup).
        _realtime?.send({
          'type': 'assistance_requested',
          'request_id': jsonDecode(resp.body)['id'],
          'helper_user_id': helperUserId,
          'helpee_user_id': helperUserId,
        });
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Request failed';
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(detail.toString())));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Network error: $e')));
      }
    } finally {
      if (mounted) setState(() => _isRequestingHelp = false);
    }
  }

  /// Ask who to request help from. Requires the helper's user ID AND the
  /// helper's device fingerprint (must match a trusted device).
  Future<Map<String, String>?> _promptHelperSelection(
    List<Map<String, dynamic>> trusted,
  ) async {
    final userIdController = TextEditingController();
    final fingerprintController = TextEditingController();

    // Pre-fill the fingerprint with the first trusted device if present.
    if (trusted.isNotEmpty) {
      fingerprintController.text =
          trusted.first['device_fingerprint'] as String? ?? '';
    }

    return showDialog<Map<String, String>>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Request Help'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'This phone is the HELPEE (person being helped). Pick the '
                'helper and their trusted device.',
                style: TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: AppTypography.caption,
                ),
              ),
              const SizedBox(height: 12),
              if (trusted.isEmpty)
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppTheme.accentRose.withValues(alpha: 0.12),
                    border: Border.all(color: AppTheme.accentRose),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Text(
                    'No trusted devices yet. Go to Trusted Devices and pair '
                    'the helper\'s device first (paste their Device ID).',
                    style: TextStyle(
                      color: AppTheme.accentRose,
                      fontSize: AppTypography.caption,
                    ),
                  ),
                )
              else
                Text(
                  'Trusted helper devices: ${trusted.map((d) => (d['friendly_name'] ?? 'device')).join(', ')}',
                  style: TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: AppTypography.caption,
                  ),
                ),
              const SizedBox(height: 12),
              TextField(
                controller: userIdController,
                style: TextStyle(color: AppTheme.textPrimary),
                decoration: const InputDecoration(
                  labelText: "Helper's user ID",
                  hintText: 'Paste the helper user id',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: fingerprintController,
                style: TextStyle(color: AppTheme.textPrimary),
                decoration: const InputDecoration(
                  labelText: "Helper's Device ID",
                  hintText: 'assistme-... or browser-...',
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'The Device ID must match one you already paired in Trusted '
                'Devices, or the request will be rejected.',
                style: TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: AppTypography.caption,
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              final userId = userIdController.text.trim();
              final fp = fingerprintController.text.trim();
              if (userId.isEmpty || fp.isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Enter both the user ID and Device ID'),
                  ),
                );
                return;
              }
              Navigator.pop(ctx, {'userId': userId, 'fingerprint': fp});
            },
            child: const Text('Send'),
          ),
        ],
      ),
    );
  }

  Future<void> _respondToEscalation({required bool accept}) async {
    final escalation = _pendingEscalation;
    if (escalation == null) return;

    if (accept && !await _ensureAccessibilityService()) {
      return;
    }

    try {
      final resp = await widget.apiClient.respondToEscalation(
        sessionId: widget.sessionId,
        escalationId: escalation['id'],
        accept: accept,
        acceptDisclaimer: accept,
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        if (data['status'] == 'approved') {
          _remoteControlGranted = true;
          widget.remoteControlSink?.value = true;
          _realtime?.send({
            'type': 'escalation_responded',
            'escalation_id': escalation['id'],
            'status': 'approved',
          });
        }
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Escalation failed';
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(detail.toString())));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Network error: $e')));
      }
    }
    if (mounted) setState(() => _pendingEscalation = null);
  }

  Future<bool> _ensureAccessibilityService() async {
    if (await AccessibilityBridge.isEnabled()) return true;
    if (!mounted) return false;
    final open = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Turn on full control'),
        content: const Text(
          'Android needs AssistMe\'s accessibility service to perform the '
          'tap and swipe actions you are about to approve. Turn it on in '
          'Settings, then return here. You can turn it off again at any time.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Open Settings'),
          ),
        ],
      ),
    );
    if (open != true) return false;
    await AccessibilityBridge.openSettings();
    for (var i = 0; i < 120 && mounted; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 500));
      if (await AccessibilityBridge.isEnabled()) return true;
    }
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Full control was not enabled.')),
      );
    }
    return false;
  }

  // ------------------------------------------------------------------
  // Helper actions
  // ------------------------------------------------------------------

  Future<void> _respondToRequest({required bool accept}) async {
    final requestId = _pendingRequestId;
    if (requestId == null) return;

    try {
      final resp = await widget.apiClient.respondToHelpRequest(
        sessionId: widget.sessionId,
        requestId: requestId,
        accept: accept,
        helperDeviceFingerprint: _helperDeviceFingerprint,
      );
      if (resp.statusCode == 200) {
        _realtime?.send({
          'type': 'assistance_request_responded',
          'request_id': requestId,
          'status': accept ? 'accepted' : 'denied',
        });
      }
    } catch (e) {
      debugPrint('Respond request failed: $e');
    }
    if (mounted) setState(() => _pendingRequestId = null);
  }

  Future<void> requestControl() => _requestEscalation();

  Future<void> _requestEscalation() async {
    final capabilities = await _promptCapabilities();
    if (capabilities == null) return;

    try {
      final resp = await widget.apiClient.requestEscalation(
        sessionId: widget.sessionId,
        targetCapabilities: capabilities,
      );
      if (resp.statusCode == 201) {
        final data = jsonDecode(resp.body);
        _realtime?.send({
          'type': 'escalation_requested',
          'escalation_id': data['id'],
          'target_capabilities': capabilities,
          'disclaimer_text': data['disclaimer_text'],
        });
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Control request sent — awaiting helpee approval'),
            ),
          );
        }
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Escalation failed';
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(detail.toString())));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Network error: $e')));
      }
    }
  }

  Future<List<String>?> _promptCapabilities() async {
    return showDialog<List<String>>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: AppTheme.bgSecondary,
          title: const Text('Request Phase 3 control'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'Phase 2 is annotation only. This single request asks for '
                'Phase 3 full touch control: tap, swipe, and scroll. The '
                'helpee must approve the risk screen first.',
                style: TextStyle(color: AppTheme.textSecondary),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () {
                Navigator.pop(ctx, ['tap', 'drag']);
              },
              child: const Text('Request'),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    Theme.of(
      context,
    ); // Rebuild legacy color-token widgets when the app theme changes.
    return Stack(
      children: [
        // Drawing overlay – for helper, only show the in-progress draft for low-latency
        // feedback. Completed strokes are already visible via the helpee's captured
        // overlay video (now not FLAG_SECURE so screenshots work), so showing them
        // again here would duplicate. For helpee, no Flutter overlay needed – native
        // canvas shows everything.
        if (!widget.isHelpee && _draftStroke != null)
          ValueListenableBuilder<double>(
            valueListenable:
                widget.contentAspectRatioNotifier ??
                ValueNotifier<double>(9 / 16),
            builder: (context, aspect, _) => Positioned.fill(
              child: DrawingOverlay(
                strokes: [_draftStroke!],
                contentAspectRatio: aspect,
              ),
            ),
          ),

        // The helper can annotate without gaining any touch control, but only when video is live – per user's fix: don't allow drawing blind.
        if (!widget.isHelpee && (!_remoteControlGranted || _annotationMode))
          ValueListenableBuilder<dynamic>(
            valueListenable: remoteStreamNotifier,
            builder: (context, stream, _) {
              if (stream == null) return const SizedBox.shrink();
              return ValueListenableBuilder<double>(
                valueListenable:
                    widget.contentAspectRatioNotifier ??
                    ValueNotifier<double>(9 / 16),
                builder: (context, aspect, _) => Positioned.fill(
                  child: DrawingInputOverlay(
                    onStroke: _sendDrawStroke,
                    onStrokeUpdate: _sendDrawPreview,
                    onErase: _eraseAt,
                    tool: _annotationTool,
                    contentAspectRatio: aspect,
                  ),
                ),
              );
            },
          ),

        // Helper controls stay visible in both phase 2 and phase 3. Only the
        // drag handle moves the dock, so buttons remain reliable to tap.
        if (!widget.isHelpee)
          Positioned(
            left: _helperDockOffset.dx,
            top: _helperDockOffset.dy,
            child: Material(
              color: AppTheme.bgSecondary.withValues(alpha: 0.96),
              borderRadius: BorderRadius.circular(14),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onPanUpdate: (details) => _moveHelperDock(details.delta),
                    child: Padding(
                      padding: EdgeInsets.all(8),
                      child: Icon(
                        Icons.drag_indicator,
                        color: AppTheme.textSecondary,
                        size: 20,
                      ),
                    ),
                  ),
                  _annotationToolbar(),
                ],
              ),
            ),
          ),

        // Disconnect countdown banner with immediate Leave Now action
        if (_disconnectCountdownSeconds != null)
          Positioned(
            top: widget.isHelpee ? 16 : 76,
            left: 16,
            right: 16,
            child: Material(
              elevation: 8,
              borderRadius: BorderRadius.circular(16),
              color: AppTheme.bgSecondary,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 12,
                ),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(
                    color: AppTheme.accentAmber.withValues(alpha: 0.6),
                    width: 1.5,
                  ),
                ),
                child: Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: AppTheme.accentAmber.withValues(alpha: 0.15),
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.wifi_off_rounded,
                        color: AppTheme.accentAmber,
                        size: 22,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            '${widget.peerName} disconnected',
                            style: TextStyle(
                              color: AppTheme.textPrimary,
                              fontSize: AppTypography.bodySmall,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            'Auto-leaving in ${_disconnectCountdownSeconds}s…',
                            style: const TextStyle(
                              color: AppTheme.accentAmber,
                              fontSize: AppTypography.caption,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 6),
                    if (_totalAloneSeconds + 30 <= _maxAloneSeconds) ...[
                      OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppTheme.accentEmerald,
                          side: BorderSide(
                            color: AppTheme.accentEmerald.withValues(
                              alpha: 0.6,
                            ),
                          ),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 8,
                          ),
                          visualDensity: VisualDensity.compact,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10),
                          ),
                        ),
                        onPressed: () {
                          final remainingAllowed =
                              _maxAloneSeconds - _totalAloneSeconds;
                          final addSeconds = remainingAllowed < 30
                              ? remainingAllowed
                              : 30;
                          setState(() {
                            _disconnectCountdownSeconds =
                                (_disconnectCountdownSeconds ?? 0) + addSeconds;
                          });
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text(
                                'Added $addSeconds seconds. Max wait: 5 min.',
                              ),
                              duration: const Duration(seconds: 2),
                            ),
                          );
                        },
                        child: const Text(
                          'Wait (+30s)',
                          style: TextStyle(
                            fontWeight: FontWeight.w600,
                            fontSize: AppTypography.caption,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                    ],
                    ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.accentRose,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 8,
                        ),
                        visualDensity: VisualDensity.compact,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                      onPressed: () {
                        _disconnectCountdownTimer?.cancel();
                        _disconnectCountdownTimer = null;
                        setState(() {
                          _disconnectCountdownSeconds = null;
                        });
                        _panicStop(isLocalLeave: false);
                      },
                      child: const Text(
                        'Leave Now',
                        style: TextStyle(
                          fontWeight: FontWeight.w600,
                          fontSize: AppTypography.caption,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),

        // Helper: incoming assistance request popup
        if (_pendingRequestId != null)
          Positioned.fill(
            child: Container(
              color: Colors.black54,
              child: Center(
                child: IncomingHelpRequestPopup(
                  helperDeviceFingerprint: _helperDeviceFingerprint ?? '',
                  onAccept: () => _respondToRequest(accept: true),
                  onDeny: () => _respondToRequest(accept: false),
                ),
              ),
            ),
          ),

        // Helpee: escalation risk disclaimer popup
        if (_pendingEscalation != null)
          Positioned.fill(
            child: Container(
              color: Colors.black54,
              child: Center(
                child: RiskDisclaimerModal(
                  disclaimerText: _pendingEscalation!['disclaimer_text'] ?? '',
                  onAccept: () => _respondToEscalation(accept: true),
                  onDecline: () => _respondToEscalation(accept: false),
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _annotationToolbar() {
    return Material(
      color: AppTheme.bgSecondary.withValues(alpha: 0.94),
      borderRadius: BorderRadius.circular(14),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              IconButton(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.all(6),
                constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
                iconSize: 20,
                tooltip: 'Pen',
                color: _annotationTool == AnnotationTool.pen
                    ? AppTheme.accentEmerald
                    : AppTheme.textSecondary,
                icon: const Icon(Icons.edit),
                onPressed: () => _selectAnnotationTool(AnnotationTool.pen),
              ),
              IconButton(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.all(6),
                constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
                iconSize: 20,
                tooltip: 'Eraser',
                color: _annotationTool == AnnotationTool.eraser
                    ? AppTheme.accentRose
                    : AppTheme.textSecondary,
                icon: const Icon(Icons.auto_fix_normal),
                onPressed: () => _selectAnnotationTool(AnnotationTool.eraser),
              ),
              IconButton(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.all(6),
                constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
                iconSize: 20,
                tooltip: 'Colour and thickness',
                icon: Icon(Icons.tune, color: _annotationColor),
                onPressed: _showAnnotationOptions,
              ),
              IconButton(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.all(6),
                constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
                iconSize: 20,
                tooltip: 'Undo',
                icon: const Icon(Icons.undo),
                onPressed: _strokes.isEmpty ? null : _undoDrawing,
              ),
              IconButton(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.all(6),
                constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
                iconSize: 20,
                tooltip: 'Redo',
                icon: const Icon(Icons.redo),
                onPressed: _redoStrokes.isEmpty ? null : _redoDrawing,
              ),
              IconButton(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.all(6),
                constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
                iconSize: 20,
                tooltip: 'Clear annotations',
                icon: const Icon(Icons.delete_sweep),
                onPressed: _strokes.isEmpty ? null : _clearDrawings,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> captureGuideStep() async {
    if (widget.isHelpee || _guideFrameTransferInProgress) return;
    final stream = remoteStreamNotifier.value;
    if (stream is! MediaStream || stream.getVideoTracks().isEmpty) {
      _showGuideMessage(
        'Wait until the shared screen is visible, then add a step.',
      );
      return;
    }
    _setGuideStepBusy(true);
    try {
      // Ask the helpee's phone to hide its AssistMe toolbar for a moment, then
      // wait for a fresh frame without it before capturing.
      if (_engine.sendData({
        'type': 'hide_controls_for_capture',
        'ms': 1500,
      })) {
        await Future<void>.delayed(const Duration(milliseconds: 700));
      }
      final captured = await _engine.captureScreenFrame(remoteStream: stream);
      if (captured == null || captured.isEmpty) {
        debugPrint('[AssistMe][GUIDE] capture returned no frame');
        _showGuideMessage('Could not capture the shared screen.');
        return;
      }
      if (!mounted) return;
      // Shrink before the redaction editor so drawing, the redaction burn-in
      // and the transfer all work on a small image instead of a full frame.
      final small = await shrinkGuideScreenshot(captured);
      if (!mounted) return;
      final redacted = await editScreenshotRedactions(context, small);
      if (!mounted || redacted == null) return;
      var image = redacted;
      if (image.length > _maxGuideFrameBytes) {
        image = await shrinkGuideScreenshot(image, maxSide: 960);
      }
      debugPrint(
        '[AssistMe][GUIDE] step image ${captured.length} -> ${image.length} bytes',
      );
      if (image.length > _maxGuideFrameBytes) {
        _showGuideMessage('This screenshot is too large to send. Try again.');
        return;
      }
      final stepNumber = _guideFrameOrdinal + 1;
      final stepId = '${DateTime.now().microsecondsSinceEpoch}_$stepNumber';
      final details = await _requestGuideStepDetails(stepNumber);
      if (details == null || !mounted) return;
      final title = details['title']!;
      final instruction = details['instruction']!;

      // The helper owns the guide, so keep the step here first. Sending it to
      // the helpee is best effort; anything missed is sent again on save.
      final localResult = await _keyframeManager.addPreReviewedFrame(
        image,
        title: title,
        instruction: instruction,
        id: stepId,
      );
      debugPrint('[AssistMe][GUIDE] step $stepNumber kept on helper: ${localResult.name}');
      if (localResult != KeyframeCaptureResult.saved) {
        _showGuideMessage(
          localResult == KeyframeCaptureResult.capacityReached
              ? 'The private guide reached its on-device image limit. Save the current guide before adding more steps.'
              : 'This step could not be kept on your phone. Try again.',
        );
        return;
      }
      _guideFrameOrdinal++;
      // The step is safe on this phone: free the button now. Waiting for the
      // helpee's confirmation here used to lock it for up to 20 seconds,
      // silently swallowing taps.
      _setGuideStepBusy(false);
      _showGuideMessage('Step $stepNumber saved. Sending it to the other phone…');
      _helpeeSendChain = _helpeeSendChain.then((_) async {
        final delivered = await _sendGuideFrameToHelpee(
          id: stepId,
          bytes: image,
          title: title,
          instruction: instruction,
        );
        _showGuideMessage(
          delivered
              ? 'Step $stepNumber is on both devices.'
              : 'Step $stepNumber is saved on your phone. It will be sent to the other phone when you save the guide.',
        );
      });
    } finally {
      _setGuideStepBusy(false);
    }
  }

  void _setGuideStepBusy(bool busy) {
    _guideFrameTransferInProgress = busy;
    widget.guideStepBusySink?.value = busy;
    if (mounted) setState(() {});
  }

  bool _sendGuideSyncKey() => _engine.sendData({
    'type': 'guide_frame_sync_key',
    'key': base64Encode(_guideSyncKey),
  });

  /// Sends one guide screenshot to the helpee in data-channel chunks and waits
  /// for its acknowledgement. Returns true once the helpee has stored it.
  Future<bool> _sendGuideFrameToHelpee({
    required String id,
    required Uint8List bytes,
    required String title,
    required String instruction,
  }) async {
    if (_guideFramesOnHelpee.contains(id)) return true;
    final chunkCount =
        (bytes.length + _guideFrameChunkBytes - 1) ~/ _guideFrameChunkBytes;
    final ack = Completer<KeyframeCaptureResult>();
    _pendingGuideFrameAcks[id] = ack;
    try {
      if (!_engine.sendData({
        'type': 'guide_frame_start',
        'transfer_id': id,
        'title': title,
        'instruction': instruction,
        'byte_count': bytes.length,
        'chunk_count': chunkCount,
      })) {
        debugPrint('[AssistMe][GUIDE] send $id: data channel not open');
        return false;
      }
      for (var index = 0; index < chunkCount; index++) {
        final deadline = DateTime.now().add(const Duration(seconds: 8));
        while (_engine.dataChannelBufferedAmount > 96 * 1024 &&
            DateTime.now().isBefore(deadline)) {
          await Future<void>.delayed(const Duration(milliseconds: 20));
        }
        final start = index * _guideFrameChunkBytes;
        final end = (start + _guideFrameChunkBytes).clamp(0, bytes.length);
        final sent =
            _engine.dataChannelBufferedAmount <= 96 * 1024 &&
            _engine.sendData({
              'type': 'guide_frame_chunk',
              'transfer_id': id,
              'index': index,
              'data': base64Encode(Uint8List.sublistView(bytes, start, end)),
            });
        if (!sent) {
          _engine.sendData({'type': 'guide_frame_abort', 'transfer_id': id});
          debugPrint('[AssistMe][GUIDE] send $id: stopped at chunk $index/$chunkCount');
          return false;
        }
      }
      if (!_engine.sendData({'type': 'guide_frame_finish', 'transfer_id': id})) {
        debugPrint('[AssistMe][GUIDE] send $id: finish not sent');
        return false;
      }
      final result = await ack.future.timeout(
        const Duration(seconds: 20),
        onTimeout: () => KeyframeCaptureResult.unavailable,
      );
      debugPrint('[AssistMe][GUIDE] send $id: helpee answered ${result.name}');
      final stored = result == KeyframeCaptureResult.saved;
      if (stored) _guideFramesOnHelpee.add(id);
      return stored;
    } finally {
      _pendingGuideFrameAcks.remove(id);
    }
  }

  Future<Map<String, String>?> _requestGuideStepDetails(int stepNumber) =>
      GuideStepDetailsDialog.show(context, stepNumber: stepNumber);

  void _showGuideMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _onGuideFrameMessage(Map<String, dynamic> data) async {
    final type = data['type'] as String?;
    final transferId = data['transfer_id'] as String?;
    if (type == 'guide_finalize') {
      await _receiveFinalizedGuide(data);
      return;
    }
    if (type == 'guide_finalize_ack') {
      final ack = _pendingGuideFinalizationAck;
      if (ack != null && !ack.isCompleted) {
        ack.complete(data['saved'] == true);
      }
      return;
    }
    if (type == 'guide_frame_sync_key') {
      final key = data['key'];
      if (widget.isHelpee && key is String) {
        try {
          final bytes = base64Decode(key);
          if (bytes.length == 32) {
            await GuideDeliveryService.rememberKey(
              widget.secureStorage,
              widget.sessionId,
              bytes,
            );
          }
        } catch (_) {}
      }
      return;
    }
    if (type == null || transferId == null) return;
    if (type == 'guide_frame_ack') {
      if (widget.isHelpee) return;
      final completer = _pendingGuideFrameAcks[transferId];
      if (completer == null || completer.isCompleted) return;
      final resultName = data['result'] as String?;
      final result = KeyframeCaptureResult.values.firstWhere(
        (value) => value.name == resultName,
        orElse: () => KeyframeCaptureResult.unavailable,
      );
      completer.complete(result);
      return;
    }
    if (type == 'guide_frame_abort') {
      if (_incomingGuideFrameTransfer?.id == transferId) {
        _incomingGuideFrameTransfer = null;
      }
      return;
    }
    if (!widget.isHelpee) return;
    if (type == 'guide_frame_start') {
      final byteCount = data['byte_count'];
      final chunkCount = data['chunk_count'];
      final title = (data['title'] as String? ?? '').trim();
      final instruction = (data['instruction'] as String? ?? '').trim();
      // A transfer the helper abandoned (busy channel, timeout) must not
      // block every later screenshot: a new start replaces it.
      if (_incomingGuideFrameTransfer != null) {
        debugPrint('[AssistMe][GUIDE] dropping unfinished transfer ${_incomingGuideFrameTransfer!.id}');
        _incomingGuideFrameTransfer = null;
      }
      if (byteCount is! int ||
          byteCount < 1 ||
          byteCount > _maxGuideFrameBytes ||
          chunkCount is! int ||
          chunkCount < 1 ||
          chunkCount >
              (_maxGuideFrameBytes + _guideFrameChunkBytes - 1) ~/
                  _guideFrameChunkBytes ||
          title.isEmpty ||
          title.length > 100 ||
          instruction.isEmpty ||
          instruction.length > 4000) {
        _engine.sendData({
          'type': 'guide_frame_ack',
          'transfer_id': transferId,
          'result': 'unavailable',
        });
        return;
      }
      _incomingGuideFrameTransfer = _IncomingGuideFrameTransfer(
        id: transferId,
        title: title,
        instruction: instruction,
        expectedBytes: byteCount,
        expectedChunks: chunkCount,
      );
      return;
    }
    if (type == 'guide_frame_chunk') {
      final transfer = _incomingGuideFrameTransfer;
      final index = data['index'];
      final payload = data['data'];
      if (transfer == null ||
          transfer.id != transferId ||
          index is! int ||
          index != transfer.chunks.length ||
          payload is! String) {
        _incomingGuideFrameTransfer = null;
        _engine.sendData({
          'type': 'guide_frame_ack',
          'transfer_id': transferId,
          'result': 'unavailable',
        });
        return;
      }
      try {
        final chunk = base64Decode(payload);
        if (chunk.isEmpty ||
            chunk.length > _guideFrameChunkBytes ||
            transfer.receivedBytes + chunk.length > transfer.expectedBytes) {
          throw const FormatException('Invalid guide frame chunk size.');
        }
        transfer.chunks.add(Uint8List.fromList(chunk));
        transfer.receivedBytes += chunk.length;
      } catch (_) {
        _incomingGuideFrameTransfer = null;
        _engine.sendData({
          'type': 'guide_frame_ack',
          'transfer_id': transferId,
          'result': 'unavailable',
        });
      }
      return;
    }
    if (type == 'guide_frame_finish') {
      final transfer = _incomingGuideFrameTransfer;
      _incomingGuideFrameTransfer = null;
      if (transfer == null ||
          transfer.id != transferId ||
          transfer.chunks.length != transfer.expectedChunks ||
          transfer.receivedBytes != transfer.expectedBytes) {
        _engine.sendData({
          'type': 'guide_frame_ack',
          'transfer_id': transferId,
          'result': 'unavailable',
        });
        return;
      }
      final builder = BytesBuilder(copy: false);
      for (final chunk in transfer.chunks) {
        builder.add(chunk);
      }
      final result = await _keyframeManager.addPreReviewedFrame(
        builder.takeBytes(),
        title: transfer.title,
        instruction: transfer.instruction,
        id: transfer.id,
      );
      _engine.sendData({
        'type': 'guide_frame_ack',
        'transfer_id': transferId,
        'result': result.name,
      });
      if (mounted && result == KeyframeCaptureResult.saved) setState(() {});
    }
  }

  Future<void> _showAnnotationOptions() async {
    final colors = <Color>[
      const Color(0xFFFF3B30),
      const Color(0xFFFFD54F),
      const Color(0xFF34C759),
      const Color(0xFF0A84FF),
      const Color(0xFFFFFFFF),
      const Color(0xFF000000),
    ];
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppTheme.bgSecondary,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) => Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Annotation style',
                style: TextStyle(
                  fontSize: AppTypography.bodyLarge,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 14),
              const Text('Colour'),
              const SizedBox(height: 8),
              Wrap(
                spacing: 12,
                children: colors
                    .map(
                      (color) => GestureDetector(
                        onTap: () {
                          setState(() => _annotationColor = color);
                          setSheetState(() {});
                        },
                        child: CircleAvatar(
                          radius: 17,
                          backgroundColor: color,
                          child: _annotationColor == color
                              ? const Icon(Icons.check, color: Colors.black)
                              : null,
                        ),
                      ),
                    )
                    .toList(),
              ),
              const SizedBox(height: 14),
              Text('Thickness ${_annotationWidth.toStringAsFixed(0)}'),
              Slider(
                value: _annotationWidth,
                min: 2,
                max: 18,
                divisions: 16,
                label: _annotationWidth.toStringAsFixed(0),
                onChanged: (value) {
                  setState(() => _annotationWidth = value);
                  setSheetState(() {});
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    widget.annotationModeSink?.removeListener(_onAnnotationModeChanged);
    _disconnectCountdownTimer?.cancel();
    _previewTimer?.cancel();
    _realtimePreviewTimer?.cancel();
    _overlayTimer?.cancel();
    _guideAudioLimitTimer?.cancel();
    unawaited(_guideAudioCapture.dispose());
    for (final recording in _pendingGuideAudioRecordings) {
      unawaited(recording.delete());
    }
    _realtime?.disconnect();
    _engine.dispose();
    _keyframeManager.dispose();
    if (widget.isHelpee) AnnotationOverlayService.stop();
    super.dispose();
  }
}
