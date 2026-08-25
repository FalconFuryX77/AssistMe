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

  DrawStroke({required this.points, this.color = const Color(0xFF00E5FF), this.width = 4});
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
      final path = Path()..moveTo(stroke.points.first.dx, stroke.points.first.dy);
      for (final p in stroke.points.skip(1)) {
        path.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(path, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _StrokePainter oldDelegate) => true;
}