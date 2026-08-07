import 'package:flutter/material.dart';
import '../../core/network/api_client.dart';
import '../../theme/app_theme.dart';

class RemoteScreenView extends StatefulWidget {
  final String sessionId;
  final ApiClient apiClient;
  final bool isFlagSecureActive;
  final bool isScreenSharing;

  const RemoteScreenView({
    Key? key,
    required this.sessionId,
    required this.apiClient,
    this.isFlagSecureActive = false,
    this.isScreenSharing = true,
  }) : super(key: key);

  @override
  State<RemoteScreenView> createState() => _RemoteScreenViewState();
}

class _RemoteScreenViewState extends State<RemoteScreenView> {
  Offset? _laserPointer;
  Offset? _dragStartOffset;

  Future<void> _dispatchInput({
    required String eventType,
    required double x,
    required double y,
    double? endX,
    double? endY,
    int? durationMs,
  }) async {
    try {
      await widget.apiClient.post(
        '/sessions/${widget.sessionId}/remote-control/input',
        body: {
          'event_type': eventType,
          'x': x * 1080,
          'y': y * 1920,
          'normalized_x': x,
          'normalized_y': y,
          if (endX != null) 'end_x': endX * 1080,
          if (endY != null) 'end_y': endY * 1920,
          if (durationMs != null) 'duration_ms': durationMs,
        },
      );
    } catch (e) {
      debugPrint('Remote input dispatch notice: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final height = constraints.maxHeight;

        return GestureDetector(
          onTapDown: (details) {
            final x = details.localPosition.dx / width;
            final y = details.localPosition.dy / height;
            setState(() {
              _laserPointer = details.localPosition;
            });
            _dispatchInput(eventType: 'tap', x: x, y: y);
          },
          onPanStart: (details) {
            _dragStartOffset = details.localPosition;
          },
          onPanEnd: (details) {
            if (_dragStartOffset != null) {
              final startX = _dragStartOffset!.dx / width;
              final startY = _dragStartOffset!.dy / height;
              final currentPointer = _laserPointer ?? _dragStartOffset!;
              final endX = currentPointer.dx / width;
              final endY = currentPointer.dy / height;

              _dispatchInput(
                eventType: 'drag',
                x: startX,
                y: startY,
                endX: endX,
                endY: endY,
                durationMs: 300,
              );
            }
          },
          onLongPressStart: (details) {
            final x = details.localPosition.dx / width;
            final y = details.localPosition.dy / height;
            _dispatchInput(
              eventType: 'long_press',
              x: x,
              y: y,
              durationMs: 600,
            );
          },
          child: Container(
            color: Colors.black,
            child: Stack(
              fit: StackFit.expand,
              children: [
                // Screen Stream Simulation Render Surface
                Center(
                  child: AspectRatio(
                    aspectRatio: 9 / 16,
                    child: Container(
                      decoration: BoxDecoration(
                        color: const Color(0xFF161F30),
                        border: Border.all(color: AppTheme.borderGlass),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: widget.isScreenSharing
                          ? const Center(
                              child: Text(
                                'Mobile WebRTC Remote Viewport Active',
                                style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                              ),
                            )
                          : const Center(
                              child: Text(
                                'Waiting for screen stream...',
                                style: TextStyle(color: AppTheme.textMuted),
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
                          Icon(Icons.lock, color: AppTheme.accentAmber, size: 48),
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
                            style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
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
