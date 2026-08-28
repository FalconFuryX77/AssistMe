import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

import '../../core/network/api_client.dart';
import '../../theme/app_theme.dart';

class RemoteScreenView extends StatefulWidget {
  final String sessionId;
  final ApiClient apiClient;
  final bool isFlagSecureActive;
  final bool isScreenSharing;
  final ValueNotifier<dynamic>? remoteStreamNotifier;

  /// Control is opt-in and must only become true after the helpee approves
  /// the plain-language risk screen. Annotation remains available without it.
  final bool allowRemoteControl;
  final ValueChanged<Map<String, dynamic>>? onRemoteInput;
  final ValueChanged<double>? onAspectRatioChanged;

  const RemoteScreenView({
    super.key,
    required this.sessionId,
    required this.apiClient,
    this.isFlagSecureActive = false,
    this.isScreenSharing = true,
    this.remoteStreamNotifier,
    this.allowRemoteControl = false,
    this.onRemoteInput,
    this.onAspectRatioChanged,
  });

  @override
  State<RemoteScreenView> createState() => _RemoteScreenViewState();
}

class _RemoteScreenViewState extends State<RemoteScreenView> {
  Offset? _laserPointer;
  Offset? _dragStartOffset;
  Offset? _dragCurrentOffset;
  final RTCVideoRenderer _renderer = RTCVideoRenderer();
  bool _rendererInitialized = false;
  dynamic _attachedStream;
  double _videoAspectRatio = 9 / 16;

  @override
  void initState() {
    super.initState();
    widget.remoteStreamNotifier?.addListener(_onStreamChanged);
    _renderer.addListener(_onRendererChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) => _onStreamChanged());
  }

  void _onRendererChanged() {
    if (_renderer.videoWidth > 0 && _renderer.videoHeight > 0) {
      final newAspect = _renderer.videoWidth / _renderer.videoHeight;
      if ((newAspect - _videoAspectRatio).abs() > 0.001) {
        _videoAspectRatio = newAspect;
        widget.onAspectRatioChanged?.call(newAspect);
      }
    }
    if (mounted) setState(() {});
  }

  Future<void> _onStreamChanged() async {
    final stream = widget.remoteStreamNotifier?.value;
    if (stream == null) {
      if (_rendererInitialized && _attachedStream != null) {
        _renderer.srcObject = null;
        if (mounted) setState(() => _attachedStream = null);
      }
      return;
    }
    if (identical(stream, _attachedStream)) return;

    if (!_rendererInitialized) {
      await _renderer.initialize();
      _rendererInitialized = true;
    }
    setState(() {
      _attachedStream = stream;
      _renderer.srcObject = stream as MediaStream;
    });
  }

  @override
  void dispose() {
    widget.remoteStreamNotifier?.removeListener(_onStreamChanged);
    _renderer.removeListener(_onRendererChanged);
    if (_rendererInitialized) {
      _renderer.dispose();
    }
    super.dispose();
  }

  Future<void> _dispatchInput({
    required String eventType,
    required double x,
    required double y,
    double? endX,
    double? endY,
    int? durationMs,
  }) async {
    if (!widget.allowRemoteControl) return;
    try {
      final payload = <String, dynamic>{
        'event_type': eventType,
        'x': x,
        'y': y,
        'normalized_x': x,
        'normalized_y': y,
        if (endX != null) ...{
          'end_x': endX,
          'normalized_end_x': endX,
        },
        if (endY != null) ...{
          'end_y': endY,
          'normalized_end_y': endY,
        },
        ...?durationMs == null ? null : {'duration_ms': durationMs},
      };
      final response = await widget.apiClient.post(
        '/sessions/${widget.sessionId}/remote-control/input',
        body: payload,
      );
      if (response.statusCode == 200) widget.onRemoteInput?.call(payload);
    } catch (e) {
      debugPrint('Remote input dispatch notice: $e');
    }
  }

  /// Normalized point inside the bounded video rect that matches RTCVideoView's
  /// actual rendered letterbox/pillarbox area.
  Offset? _normalizedVideoPoint(Offset point, Size size) {
    final aspect = _videoAspectRatio;
    final contentHeight = math.min(size.height, size.width / aspect);
    final contentWidth = contentHeight * aspect;
    final left = (size.width - contentWidth) / 2;
    final top = (size.height - contentHeight) / 2;

    if (point.dx < left || point.dx > left + contentWidth ||
        point.dy < top || point.dy > top + contentHeight) {
      return null;
    }

    final x = ((point.dx - left) / contentWidth).clamp(0.0, 1.0);
    final y = ((point.dy - top) / contentHeight).clamp(0.0, 1.0);
    return Offset(x, y);
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final height = constraints.maxHeight;

        return GestureDetector(
          onTapUp: (details) {
            if (!widget.allowRemoteControl) return;
            final point = _normalizedVideoPoint(
              details.localPosition,
              Size(width, height),
            );
            if (point == null) return;
            setState(() {
              _laserPointer = details.localPosition;
            });
            _dispatchInput(eventType: 'tap', x: point.dx, y: point.dy);
          },
          onPanStart: (details) {
            if (!widget.allowRemoteControl) return;
            _dragStartOffset = details.localPosition;
            _dragCurrentOffset = details.localPosition;
          },
          onPanUpdate: (details) {
            if (!widget.allowRemoteControl) return;
            _dragCurrentOffset = details.localPosition;
          },
          onPanEnd: (details) {
            if (!widget.allowRemoteControl) return;
            if (_dragStartOffset != null) {
              final currentPointer = _dragCurrentOffset ?? _dragStartOffset!;
              final start = _normalizedVideoPoint(
                _dragStartOffset!,
                Size(width, height),
              );
              final end = _normalizedVideoPoint(
                currentPointer,
                Size(width, height),
              );
              _dragStartOffset = null;
              _dragCurrentOffset = null;
              if (start == null || end == null) return;

              _dispatchInput(
                eventType: 'drag',
                x: start.dx,
                y: start.dy,
                endX: end.dx,
                endY: end.dy,
                durationMs: 300,
              );
            }
          },
          onLongPressStart: (details) {
            if (!widget.allowRemoteControl) return;
            final point = _normalizedVideoPoint(
              details.localPosition,
              Size(width, height),
            );
            if (point == null) return;
            _dispatchInput(
              eventType: 'long_press',
              x: point.dx,
              y: point.dy,
              durationMs: 600,
            );
          },
          child: Container(
            color: Colors.black,
            child: Stack(
              fit: StackFit.expand,
              children: [
                // Live remote screen stream (WebRTC), fallback placeholder.
                if (_attachedStream != null &&
                    _rendererInitialized &&
                    _renderer.renderVideo)
                  RTCVideoView(
                    _renderer,
                    objectFit:
                        RTCVideoViewObjectFit.RTCVideoViewObjectFitContain,
                  )
                else
                  Center(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
                        decoration: BoxDecoration(
                          color: const Color(0xFF1E293B),
                          border: Border.all(color: AppTheme.accentEmerald.withValues(alpha: 0.5), width: 1.5),
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(
                              _attachedStream != null ? Icons.sync : Icons.videocam_off,
                              color: AppTheme.accentEmerald,
                              size: 36,
                            ),
                            const SizedBox(height: 14),
                            Text(
                              _attachedStream != null
                                  ? 'Connecting to remote screen…'
                                  : 'Waiting for the other device to share…',
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 16,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(height: 8),
                            const Text(
                              'Make sure the helpee tapped Start Sharing\nand granted screen permission',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                color: AppTheme.textSecondary,
                                fontSize: 12,
                              ),
                            ),
                            if (!widget.isFlagSecureActive) ...[
                              const SizedBox(height: 12),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                                decoration: BoxDecoration(
                                  color: AppTheme.bgSecondary,
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: Text(
                                  'Session: ${widget.sessionId.substring(0, 6)}',
                                  style: const TextStyle(color: AppTheme.textMuted, fontSize: 11),
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),

                if (widget.isFlagSecureActive)
                  Container(
                    color: Colors.black.withValues(alpha: 0.92),
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: const [
                          Icon(
                            Icons.lock,
                            color: AppTheme.accentAmber,
                            size: 48,
                          ),
                          SizedBox(height: 12),
                          Text(
                            'Sensitive Content Protected',
                            style: TextStyle(
                              color: AppTheme.accentAmber,
                              fontWeight: FontWeight.w700,
                              fontSize: 16,
                            ),
                          ),
                          SizedBox(height: 6),
                          Text(
                            'The remote screen opened a FLAG_SECURE window',
                            style: TextStyle(
                              color: AppTheme.textSecondary,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),

                // Touch / Laser Pointer Visual Indicator
                if (_laserPointer != null)
                  Positioned(
                    left: _laserPointer!.dx - 12,
                    top: _laserPointer!.dy - 12,
                    child: Container(
                      width: 24,
                      height: 24,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: AppTheme.accentRose.withValues(alpha: 0.75),
                        border: Border.all(color: Colors.white, width: 2),
                        boxShadow: [
                          BoxShadow(
                            color: AppTheme.accentRose.withValues(alpha: 0.5),
                            blurRadius: 10,
                            spreadRadius: 2,
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}
