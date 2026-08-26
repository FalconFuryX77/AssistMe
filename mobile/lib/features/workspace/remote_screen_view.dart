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

  const RemoteScreenView({
    Key? key,
    required this.sessionId,
    required this.apiClient,
    this.isFlagSecureActive = false,
    this.isScreenSharing = true,
    this.remoteStreamNotifier,
    this.allowRemoteControl = false,
    this.onRemoteInput,
  }) : super(key: key);

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

  @override
  void initState() {
    super.initState();
    widget.remoteStreamNotifier?.addListener(_onStreamChanged);
    _renderer.addListener(_onRendererChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) => _onStreamChanged());
  }

  void _onRendererChanged() {
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
        'x': x * 1080,
        'y': y * 1920,
        'normalized_x': x,
        'normalized_y': y,
        if (endX != null) 'end_x': endX * 1080,
        if (endY != null) 'end_y': endY * 1920,
        if (endX != null) 'normalized_end_x': endX,
        if (endY != null) 'normalized_end_y': endY,
        if (durationMs != null) 'duration_ms': durationMs,
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

  /// Return the normalized coordinate inside the actual `contain` video
  /// rectangle. The previous implementation used the whole widget bounds,
  /// which included letterboxing and the helper's app chrome and caused taps
  /// to land consistently above the visible target on the helpee phone.
  Offset? _normalizedVideoPoint(Offset point, Size size) {
    final sourceWidth = _renderer.videoWidth > 0
        ? _renderer.videoWidth.toDouble()
        : 9.0;
    final sourceHeight = _renderer.videoHeight > 0
        ? _renderer.videoHeight.toDouble()
        : 16.0;
    final scale = math.min(
      size.width / sourceWidth,
      size.height / sourceHeight,
    );
    final videoWidth = sourceWidth * scale;
    final videoHeight = sourceHeight * scale;
    final left = (size.width - videoWidth) / 2;
    final top = (size.height - videoHeight) / 2;
    final x = (point.dx - left) / videoWidth;
    final y = (point.dy - top) / videoHeight;
    if (x < 0 || x > 1 || y < 0 || y > 1) return null;
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
                    child: AspectRatio(
                      aspectRatio: 9 / 16,
                      child: Container(
                        decoration: BoxDecoration(
                          color: const Color(0xFF161F30),
                          border: Border.all(color: AppTheme.borderGlass),
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Center(
                          child: Text(
                            _attachedStream != null
                                ? 'Connecting to the remote screen…'
                                : 'Waiting for the other device to share…',
                            style: const TextStyle(
                              color: AppTheme.textSecondary,
                              fontSize: 12,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),

                // FLAG_SECURE Overlay
                if (widget.isFlagSecureActive)
                  Container(
                    color: Colors.black.withOpacity(0.92),
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
                        color: AppTheme.accentRose.withOpacity(0.75),
                        border: Border.all(color: Colors.white, width: 2),
                        boxShadow: [
                          BoxShadow(
                            color: AppTheme.accentRose.withOpacity(0.5),
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
