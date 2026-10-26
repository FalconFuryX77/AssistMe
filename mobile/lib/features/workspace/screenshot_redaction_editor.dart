import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../../core/guides/screenshot_redaction.dart';

/// Opens an explicit review step and returns a PNG with redactions burned in.
/// A null result means the user cancelled review.
Future<Uint8List?> editScreenshotRedactions(
  BuildContext context,
  Uint8List sourceBytes,
) => Navigator.of(context).push<Uint8List>(
  MaterialPageRoute<Uint8List>(
    builder: (_) => _ScreenshotRedactionEditor(sourceBytes: sourceBytes),
  ),
);

class _ScreenshotRedactionEditor extends StatefulWidget {
  final Uint8List sourceBytes;

  const _ScreenshotRedactionEditor({required this.sourceBytes});

  @override
  State<_ScreenshotRedactionEditor> createState() =>
      _ScreenshotRedactionEditorState();
}

class _ScreenshotRedactionEditorState
    extends State<_ScreenshotRedactionEditor> {
  ui.Image? _image;
  final List<NormalizedRedaction> _regions = [];
  Offset? _dragStart;
  Offset? _dragEnd;
  Rect? _imageRect;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _decode();
  }

  Future<void> _decode() async {
    try {
      final codec = await ui.instantiateImageCodec(widget.sourceBytes);
      final frame = await codec.getNextFrame();
      codec.dispose();
      if (!mounted) {
        frame.image.dispose();
        return;
      }
      setState(() => _image = frame.image);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'This screenshot could not be opened.');
      }
    }
  }

  @override
  void dispose() {
    _image?.dispose();
    super.dispose();
  }

  Offset? _normalizedPoint(Offset point) {
    final imageRect = _imageRect;
    if (imageRect == null || !imageRect.contains(point)) return null;
    return Offset(
      ((point.dx - imageRect.left) / imageRect.width).clamp(0.0, 1.0),
      ((point.dy - imageRect.top) / imageRect.height).clamp(0.0, 1.0),
    );
  }

  void _startRedaction(DragStartDetails details) {
    final point = _normalizedPoint(details.localPosition);
    if (point == null) return;
    setState(() {
      _dragStart = point;
      _dragEnd = point;
    });
  }

  void _updateRedaction(DragUpdateDetails details) {
    if (_dragStart == null) return;
    final imageRect = _imageRect;
    if (imageRect == null) return;
    final point = Offset(
      ((details.localPosition.dx - imageRect.left) / imageRect.width).clamp(
        0.0,
        1.0,
      ),
      ((details.localPosition.dy - imageRect.top) / imageRect.height).clamp(
        0.0,
        1.0,
      ),
    );
    setState(() => _dragEnd = point);
  }

  void _finishRedaction(DragEndDetails _) {
    final start = _dragStart;
    final end = _dragEnd;
    if (start == null || end == null) return;
    final left = math.min(start.dx, end.dx);
    final top = math.min(start.dy, end.dy);
    final right = math.max(start.dx, end.dx);
    final bottom = math.max(start.dy, end.dy);
    if (right - left >= 0.008 && bottom - top >= 0.008) {
      _regions.add(
        NormalizedRedaction(left: left, top: top, right: right, bottom: bottom),
      );
    }
    setState(() {
      _dragStart = null;
      _dragEnd = null;
    });
  }

  Future<void> _saveReviewedImage() async {
    if (_saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final redacted = await burnInScreenshotRedactions(
        widget.sourceBytes,
        _regions,
      );
      if (mounted) Navigator.pop(context, redacted);
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = 'Could not prepare the reviewed screenshot. Try again.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: Colors.black,
    appBar: AppBar(
      title: const Text('Review screenshot'),
      backgroundColor: Colors.black,
      foregroundColor: Colors.white,
      actions: [
        IconButton(
          tooltip: 'Undo last redaction',
          onPressed: _regions.isEmpty || _saving
              ? null
              : () => setState(() => _regions.removeLast()),
          icon: const Icon(Icons.undo),
        ),
        IconButton(
          tooltip: 'Clear redactions',
          onPressed: _regions.isEmpty || _saving
              ? null
              : () => setState(_regions.clear),
          icon: const Icon(Icons.delete_outline),
        ),
      ],
    ),
    body: SafeArea(
      child: Column(
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: Text(
              'Drag over passwords, names, notifications, or other private details. Covered pixels are permanently removed from the copy used by the model and saved in your guide.',
              style: TextStyle(color: Colors.white70),
              textAlign: TextAlign.center,
            ),
          ),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final image = _image;
                if (_error != null) {
                  return Center(
                    child: Text(
                      _error!,
                      style: const TextStyle(color: Colors.white),
                    ),
                  );
                }
                if (image == null) {
                  return const Center(child: CircularProgressIndicator());
                }
                final size = Size(
                  image.width.toDouble(),
                  image.height.toDouble(),
                );
                final fitted = applyBoxFit(
                  BoxFit.contain,
                  size,
                  constraints.biggest,
                );
                final destination = Alignment.center.inscribe(
                  fitted.destination,
                  Offset.zero & constraints.biggest,
                );
                _imageRect = destination;
                return GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onPanStart: _saving ? null : _startRedaction,
                  onPanUpdate: _saving ? null : _updateRedaction,
                  onPanEnd: _saving ? null : _finishRedaction,
                  child: CustomPaint(
                    size: constraints.biggest,
                    painter: _ScreenshotRedactionPainter(
                      image: image,
                      destination: destination,
                      regions: List.of(_regions),
                      dragStart: _dragStart,
                      dragEnd: _dragEnd,
                    ),
                  ),
                );
              },
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(
                _error!,
                style: const TextStyle(color: Colors.redAccent),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            child: SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: _image == null || _saving
                    ? null
                    : _saveReviewedImage,
                icon: _saving
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.verified_user_outlined),
                label: Text(
                  _saving ? 'Preparing screenshot…' : 'Use reviewed screenshot',
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}

class _ScreenshotRedactionPainter extends CustomPainter {
  final ui.Image image;
  final Rect destination;
  final List<NormalizedRedaction> regions;
  final Offset? dragStart;
  final Offset? dragEnd;

  const _ScreenshotRedactionPainter({
    required this.image,
    required this.destination,
    required this.regions,
    required this.dragStart,
    required this.dragEnd,
  });

  Rect _toCanvas(NormalizedRedaction region) => Rect.fromLTRB(
    destination.left + region.left * destination.width,
    destination.top + region.top * destination.height,
    destination.left + region.right * destination.width,
    destination.top + region.bottom * destination.height,
  );

  @override
  void paint(Canvas canvas, Size size) {
    final source = Rect.fromLTWH(
      0,
      0,
      image.width.toDouble(),
      image.height.toDouble(),
    );
    canvas.drawImageRect(image, source, destination, Paint());
    final black = Paint()..color = Colors.black;
    for (final region in regions) {
      canvas.drawRect(_toCanvas(region), black);
    }
    if (dragStart != null && dragEnd != null) {
      final preview = NormalizedRedaction(
        left: math.min(dragStart!.dx, dragEnd!.dx),
        top: math.min(dragStart!.dy, dragEnd!.dy),
        right: math.max(dragStart!.dx, dragEnd!.dx),
        bottom: math.max(dragStart!.dy, dragEnd!.dy),
      );
      canvas.drawRect(_toCanvas(preview), black);
      canvas.drawRect(
        _toCanvas(preview),
        Paint()
          ..color = Colors.white
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _ScreenshotRedactionPainter oldDelegate) =>
      oldDelegate.image != image ||
      oldDelegate.destination != destination ||
      oldDelegate.regions != regions ||
      oldDelegate.dragStart != dragStart ||
      oldDelegate.dragEnd != dragEnd;
}
