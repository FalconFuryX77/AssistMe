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

import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

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
  bool _mediaReady = false;
  bool _screenShareStarted = false;
  bool _remoteControlGranted = false;
  bool _helpeeOverlayRunning = false;
  Map<String, dynamic>? _pendingOffer;
  final List<Map<String, dynamic>> _pendingIceCandidates = [];
  bool _remoteDescriptionSet = false;
  bool _mediaRecovering = false;
  DrawStroke? _draftStroke;
  Timer? _previewTimer;
  List<Offset>? _pendingPreviewPoints;
  Timer? _overlayTimer;
  Offset _helperDockOffset = const Offset(16, 16);

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
    // Send over sub-15ms P2P WebRTC DataChannel first; fallback to WebSocket
    final sentP2P = _engine.sendData(payload);
    if (!sentP2P) {
      _realtime?.send(payload);
    }
  }

  void _sendDrawPreview(List<Offset> points) {
    if (points.isEmpty) return;
    final draft = DrawStroke(
      points: points,
      color: _annotationColor,
      width: _annotationWidth,
    );
    setState(() => _draftStroke = draft);
    _pendingPreviewPoints = points;
    if (_previewTimer?.isActive == true) return;
    _previewTimer = Timer(const Duration(milliseconds: 16), () {
      _previewTimer = null;
      final latest = _pendingPreviewPoints;
      _pendingPreviewPoints = null;
      if (latest == null || latest.isEmpty) return;
      _sendRealtimeOrP2P({
        'type': 'draw_preview',
        'points': latest
            .map((p) => {
                  'x': double.parse(p.dx.toStringAsFixed(4)),
                  'y': double.parse(p.dy.toStringAsFixed(4)),
                })
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
      'points': points
          .map((p) => {
                'x': double.parse(p.dx.toStringAsFixed(4)),
                'y': double.parse(p.dy.toStringAsFixed(4)),
              })
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
    _overlayTimer?.cancel();
    _overlayTimer = null;
    _draftStroke = null;
    setState(() {
      _strokes.clear();
      _redoStrokes.clear();
    });
    _sendRealtimeOrP2P({'type': 'draw_clear'});
    if (notifyOverlay) {
      try {
        await AnnotationOverlayService.clear();
      } catch (_) {}
    }
  }

  bool get isMediaReady => _mediaReady;
  bool get isScreenShareStarted => _screenShareStarted;
  bool get remoteControlGranted => _remoteControlGranted;

  @override
  void initState() {
    super.initState();
    widget.annotationModeSink?.addListener(_onAnnotationModeChanged);
    if (widget.isHelpee) {
      AnnotationOverlayService.initialize(
        onPanic: _panicStop,
        onClear: () async => _clearDrawings(notifyOverlay: false),
        onDrawStroke: (points, color, width) => _handleNativeHelpeeStroke(points, color, width),
        onErase: (point) => _eraseAt(point),
        onUndo: _undoDrawing,
        onRedo: _redoDrawing,
      );
    }
    _bootstrap();
  }

  void _handleNativeHelpeeStroke(List<Offset> points, int colorValue, double width) {
    // Helpee drew on the system overlay – use the native-selected color
    // (not the helper's currently selected color) so both sides see the same.
    final color = Color(colorValue);
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
      'points': points
          .map((p) => {
                'x': double.parse(p.dx.toStringAsFixed(4)),
                'y': double.parse(p.dy.toStringAsFixed(4)),
              })
          .toList(),
      'color': colorValue,
      'width': width,
    });
    // Local overlay already shows the stroke via native canvas; _pushOverlay
    // keeps it in sync for any future helper replay but does not duplicate.
    _pushOverlay();
  }

  Future<void> toggleAudioMute(bool mute) async {
    await _engine.toggleAudioMute(mute);
    _sendRealtimeOrP2P({'type': 'audio_mute_toggle', 'is_muted': mute});
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
  /// stale docs after helpee closed the app or tapped STOP. This is what the
  /// user asked for: "shutting down the meeting just shut down everything for
  /// the other guy".
  Future<void> _panicStop() async {
    try {
      await widget.apiClient.post('/sessions/${widget.sessionId}/leave');
    } catch (_) {}
    _remoteControlGranted = false;
    widget.remoteControlSink?.value = false;
    await _clearDrawings(notifyOverlay: true);
    await stopScreenShare();
    try { await AnnotationOverlayService.stop(); } catch (_) {}
    _helpeeOverlayRunning = false;
    if (mounted) setState(() {});
    // Ensure helper sees session_ended immediately (leave already broadcasts,
    // but also send explicit clear for overlay docs).
    _realtime?.send({'type': 'draw_clear'});
    await widget.onSessionEnded?.call();
    await widget.onSessionClosed?.call();
  }

  Future<void> _bootstrap() async {
    final fingerprint = await DeviceIdentity.getFingerprint(
      widget.secureStorage,
    );
    final token = await widget.secureStorage.getAccessToken();
    setState(() => _helperDeviceFingerprint = fingerprint);

    if (token != null) {
      try {
        _realtime = RealtimeService(
          sessionId: widget.sessionId,
          accessToken: token,
          accessTokenProvider: widget.apiClient.getRealtimeAccessToken,
        );
        _realtime!.onConnected = _handleRealtimeConnected;
        await _realtime!.connect();
        _realtime!.events.listen(_onEvent);
      } catch (e) {
        debugPrint('Realtime connect failed: $e');
      }
    }

    await _initMediaEngine();

    // Screen share is started by an explicit tap on "Start Sharing"
    // (no auto-start) so the mic + MediaProjection consent dialogs appear
    // while the UI is fully settled, not mid-mount.
  }

  /// Re-negotiate after the signaling socket returns. The local MediaProjection
  /// and microphone tracks are kept alive; only the stale peer connection is
  /// replaced. This avoids a second Android capture consent flow and restores
  /// the remote video after either phone briefly drops off the network.
  Future<void> _handleRealtimeConnected() async {
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

  Future<void> _recoverMedia({required bool sendOffer}) async {
    if (!_mediaReady || _mediaRecovering) return;
    _mediaRecovering = true;
    _remoteDescriptionSet = false;
    _pendingIceCandidates.clear();
    remoteStreamNotifier.value = null;
    try {
      await _engine.rebuildPeerConnection();
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
        if (sendOffer && _screenShareStarted) {
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
      }
    } catch (_) {
      // fall back to default STUN-only config
    }

    try {
      _engine.onLocalCandidate = (candidate) {
        _realtime?.send({
          'type': 'signal_ice_candidate',
          'candidate': candidate,
        });
      };
      _engine.onDataChannelMessage = (data) {
        final type = data['type'] as String?;
        if (type != null) {
          _onEvent(RealtimeEvent(type, data));
        }
      };
      _engine.onRemoteStream = (stream) {
        // The helpee publishes screen video and mic audio as separate
        // streams; keep whichever carries video for the viewport (remote
        // audio plays through the peer connection regardless).
        final current = remoteStreamNotifier.value;
        if (current == null || stream.getVideoTracks().isNotEmpty) {
          remoteStreamNotifier.value = stream;
        }
      };
      await _engine.initialize(iceServers: iceServers);
      if (mounted) setState(() => _mediaReady = true);

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

  /// Helpee: capture screen + mic, then offer to the room.
  Future<void> startScreenShare() async {
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
    try {
      // Will pop system dialogs: microphone + screen capture
      await _engine.startScreenCapture();
      final offer = await _engine.createOffer();
      _realtime?.send({'type': 'signal_offer', 'sdp': offer});
      _realtime?.send({'type': 'screen_share_start', 'platform': 'android'});
      if (mounted) setState(() => _screenShareStarted = true);
      await _startHelpeeOverlay();
    } catch (e) {
      debugPrint('Screen share failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Could not start sharing: $e'),
            backgroundColor: AppTheme.accentRose,
          ),
        );
      }
    }
  }

  Future<void> stopScreenShare() async {
    if (!_screenShareStarted) return;
    try {
      await _engine.stopScreenCapture();
      _realtime?.send({'type': 'screen_share_stop'});
      if (mounted) setState(() => _screenShareStarted = false);
    } catch (e) {
      debugPrint('Stop screen share failed: $e');
    }
  }

  /// Helper: answer an incoming screen-share offer with our mic attached.
  Future<void> _handleIncomingOffer(Map<String, dynamic> sdp) async {
    if (!_mediaReady || _mediaRecovering) {
      _pendingOffer = sdp;
      return;
    }
    if (remoteStreamNotifier.value != null) return;
    try {
      await _engine.setRemoteDescription(sdp);
      _remoteDescriptionSet = true;
      for (final candidate in _pendingIceCandidates) {
        await _engine.addIceCandidate(candidate);
      }
      _pendingIceCandidates.clear();
      await _engine.startMicOnly();
      final answer = await _engine.createAnswer();
      _realtime?.send({'type': 'signal_answer', 'sdp': answer});
    } catch (e) {
      debugPrint('Answering offer failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTheme.accentRose,
            content: Text('Could not join the call: $e'),
          ),
        );
      }
    }
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
          final rawColor = event.data['color'];
          final rawWidth = event.data['width'];
          setState(() {
            _draftStroke = null;
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
          _pushOverlay();
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
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                '${widget.peerName} disconnected. Waiting briefly for them to reconnect…',
              ),
              duration: const Duration(seconds: 4),
            ),
          );
        }
        break;

      case 'user_reconnected':
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
        if (widget.isHelpee && _screenShareStarted) {
          // Helper reconnected and has no video – re-offer immediately.
          // If media is still recovering, queue via _handleRealtimeConnected.
          if (!_mediaRecovering) {
            await _recoverMedia(sendOffer: true);
          }
        }
        break;

      // --- WebRTC signaling relay ---
      case 'signal_offer':
        if (!widget.isHelpee) {
          final sdp = event.data['sdp'];
          if (sdp is Map) _handleIncomingOffer(Map<String, dynamic>.from(sdp));
        }
        break;

      case 'signal_answer':
        if (widget.isHelpee) {
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
      case 'session_ended':
        // VISION: either side shutting down must clear everything for the other – annotations, overlay, control.
        _clearDrawings(notifyOverlay: true);
        stopScreenShare();
        AnnotationOverlayService.stop();
        _remoteControlGranted = false;
        widget.remoteControlSink?.value = false;
        remoteStreamNotifier.value = null;
        _helpeeOverlayRunning = false;
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Help session ended.',
              ),
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
              const Text(
                'This phone is the HELPEE (person being helped). Pick the '
                'helper and their trusted device.',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
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
                    style: TextStyle(color: AppTheme.accentRose, fontSize: 12),
                  ),
                )
              else
                Text(
                  'Trusted helper devices: ${trusted.map((d) => (d['friendly_name'] ?? 'device')).join(', ')}',
                  style: const TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: 12,
                  ),
                ),
              const SizedBox(height: 12),
              TextField(
                controller: userIdController,
                style: const TextStyle(color: AppTheme.textPrimary),
                decoration: const InputDecoration(
                  labelText: "Helper's user ID",
                  hintText: 'Paste the helper user id',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: fingerprintController,
                style: const TextStyle(color: AppTheme.textPrimary),
                decoration: const InputDecoration(
                  labelText: "Helper's Device ID",
                  hintText: 'assistme-... or browser-...',
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'The Device ID must match one you already paired in Trusted '
                'Devices, or the request will be rejected.',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
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
              const Text(
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
    return Stack(
      children: [
        // Helpee permanent Start Sharing – always visible until sharing succeeds, never hidden behind banner.
        // Banner is at top 12, so button is centered to avoid overlap. Disabled when media not ready.
        if (widget.isHelpee && !_screenShareStarted)
          Positioned.fill(
            child: Center(
              child: ElevatedButton.icon(
                icon: const Icon(Icons.screen_share),
                label: const Text(
                  'Start Sharing',
                  style: TextStyle(fontSize: 16),
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.accentEmerald,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 14,
                  ),
                ),
                onPressed: startScreenShare,
              ),
            ),
          ),

        // Drawing overlay – for helper, only show the in-progress draft for low-latency
        // feedback. Completed strokes are already visible via the helpee's captured
        // overlay video (now not FLAG_SECURE so screenshots work), so showing them
        // again here would duplicate. For helpee, no Flutter overlay needed – native
        // canvas shows everything.
        if (!widget.isHelpee && _draftStroke != null)
          ValueListenableBuilder<double>(
            valueListenable: widget.contentAspectRatioNotifier ?? ValueNotifier<double>(9 / 16),
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
                valueListenable: widget.contentAspectRatioNotifier ?? ValueNotifier<double>(9 / 16),
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
                    child: const Padding(
                      padding: EdgeInsets.all(8),
                      child: Icon(
                        Icons.drag_indicator,
                        color: AppTheme.textSecondary,
                        size: 20,
                      ),
                    ),
                  ),
                  _annotationToolbar(),
                  if (!_remoteControlGranted)
                    IconButton(
                      tooltip: 'Request touch control',
                      color: AppTheme.accentSecondary,
                      icon: const Icon(Icons.open_in_full),
                      onPressed: _requestEscalation,
                    ),
                ],
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
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            IconButton(
              tooltip: 'Pen',
              color: _annotationTool == AnnotationTool.pen
                  ? AppTheme.accentEmerald
                  : AppTheme.textSecondary,
              icon: const Icon(Icons.edit),
              onPressed: () => _selectAnnotationTool(AnnotationTool.pen),
            ),
            IconButton(
              tooltip: 'Eraser',
              color: _annotationTool == AnnotationTool.eraser
                  ? AppTheme.accentRose
                  : AppTheme.textSecondary,
              icon: const Icon(Icons.auto_fix_normal),
              onPressed: () => _selectAnnotationTool(AnnotationTool.eraser),
            ),
            IconButton(
              tooltip: 'Colour and thickness',
              icon: Icon(Icons.tune, color: _annotationColor),
              onPressed: _showAnnotationOptions,
            ),
            IconButton(
              tooltip: 'Undo',
              icon: const Icon(Icons.undo),
              onPressed: _strokes.isEmpty ? null : _undoDrawing,
            ),
            IconButton(
              tooltip: 'Redo',
              icon: const Icon(Icons.redo),
              onPressed: _redoStrokes.isEmpty ? null : _redoDrawing,
            ),
            IconButton(
              tooltip: 'Clear annotations',
              icon: const Icon(Icons.delete_sweep),
              onPressed: _strokes.isEmpty ? null : _clearDrawings,
            ),
          ],
        ),
      ),
    );
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
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
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
    _previewTimer?.cancel();
    _overlayTimer?.cancel();
    _realtime?.disconnect();
    _engine.dispose();
    if (widget.isHelpee) AnnotationOverlayService.stop();
    super.dispose();
  }
}
