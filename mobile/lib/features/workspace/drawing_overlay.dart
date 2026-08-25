/// Drawing overlay that renders helper strokes on top of the screen.
///
/// The helper sends normalized draw events over the realtime channel; this
/// widget converts them to screen coordinates and paints them live. This is the
/// default (least-privilege) capability granted when a helper accepts.
library;

import 'package:flutter/material.dart';

class DrawStroke {
  final List<Offset> points;
  final Color color;
  final double width;

  DrawStroke({required this.points, this.color = const Color(0xFFFF3B30), this.width = 4});
}

/// Captures a helper's pen stroke without turning the screen viewport into a
/// remote-control surface. Points are normalized so phones with different
/// screen sizes render the same mark in the same place.
class DrawingInputOverlay extends StatefulWidget {
  final ValueChanged<List<Offset>> onStroke;

  const DrawingInputOverlay({Key? key, required this.onStroke}) : super(key: key);

  @override
  State<DrawingInputOverlay> createState() => _DrawingInputOverlayState();
}

class _DrawingInputOverlayState extends State<DrawingInputOverlay> {
  final List<Offset> _points = [];

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => GestureDetector(
        behavior: HitTestBehavior.translucent,
        onPanStart: (details) => _points
          ..clear()
          ..add(Offset(
            details.localPosition.dx / constraints.maxWidth,
            details.localPosition.dy / constraints.maxHeight,
          )),
        onPanUpdate: (details) => _points.add(Offset(
          details.localPosition.dx / constraints.maxWidth,
          details.localPosition.dy / constraints.maxHeight,
        )),
        onPanEnd: (_) {
          if (_points.length > 1) widget.onStroke(List<Offset>.from(_points));
          _points.clear();
        },
        child: const SizedBox.expand(),
      ),
    );
  }
}

class DrawingOverlay extends StatefulWidget {
  final List<DrawStroke> strokes;

  const DrawingOverlay({Key? key, required this.strokes}) : super(key: key);

  @override
  State<DrawingOverlay> createState() => _DrawingOverlayState();
}

class _DrawingOverlayState extends State<DrawingOverlay> {
  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: CustomPaint(
        size: Size.infinite,
        painter: _StrokePainter(widget.strokes),
      ),
    );
  }
}

class _StrokePainter extends CustomPainter {
  final List<DrawStroke> strokes;

  _StrokePainter(this.strokes);

  @override
  void paint(Canvas canvas, Size size) {
    for (final stroke in strokes) {
      if (stroke.points.length < 2) continue;
      final paint = Paint()
        ..color = stroke.color
        ..strokeWidth = stroke.width
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..style = PaintingStyle.stroke;
      final path = Path()
        ..moveTo(stroke.points.first.dx * size.width, stroke.points.first.dy * size.height);
      for (final p in stroke.points.skip(1)) {
        path.lineTo(p.dx * size.width, p.dy * size.height);
      }
      canvas.drawPath(path, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _StrokePainter oldDelegate) => true;
}
