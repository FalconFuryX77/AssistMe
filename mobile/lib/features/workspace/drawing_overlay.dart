/// Drawing overlay that renders helper strokes on top of the screen.
///
/// The helper sends normalized draw events over the realtime channel; this
/// widget converts them to screen coordinates and paints them live. This is the
/// default (least-privilege) capability granted when a helper accepts.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

class DrawStroke {
  final List<Offset> points;
  final Color color;
  final double width;

  DrawStroke({
    required this.points,
    this.color = const Color(0xFFFF3B30),
    this.width = 4,
  });
}

enum AnnotationTool { pen, highlighter, eraser }

/// Captures a helper's pen stroke without turning the screen viewport into a
/// remote-control surface. Points are normalized so phones with different
/// screen sizes render the same mark in the same place.
class DrawingInputOverlay extends StatefulWidget {
  final ValueChanged<List<Offset>> onStroke;
  final ValueChanged<List<Offset>>? onStrokeUpdate;
  final ValueChanged<Offset>? onErase;
  final AnnotationTool tool;
  final double contentAspectRatio;

  const DrawingInputOverlay({
    Key? key,
    required this.onStroke,
    this.onStrokeUpdate,
    this.onErase,
    this.tool = AnnotationTool.pen,
    this.contentAspectRatio = 9 / 16,
  }) : super(key: key);

  @override
  State<DrawingInputOverlay> createState() => _DrawingInputOverlayState();
}

class _DrawingInputOverlayState extends State<DrawingInputOverlay> {
  final List<Offset> _points = [];

  Offset? _normalizedPoint(Offset point, Size size) {
    final scale = math.min(
      size.width / widget.contentAspectRatio,
      size.height,
    );
    final contentSize = Size(
      scale * widget.contentAspectRatio,
      scale,
    );
    final contentRect = Rect.fromCenter(
      center: Offset(size.width / 2, size.height / 2),
      width: contentSize.width,
      height: contentSize.height,
    );
    if (!contentRect.contains(point)) return null;
    return Offset(
      (point.dx - contentRect.left) / contentRect.width,
      (point.dy - contentRect.top) / contentRect.height,
    );
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = Size(constraints.maxWidth, constraints.maxHeight);
        return GestureDetector(
        behavior: HitTestBehavior.translucent,
        onPanStart: (details) {
          final point = _normalizedPoint(details.localPosition, size);
          _points.clear();
          if (point != null) _points.add(point);
          if (widget.tool != AnnotationTool.eraser) {
            widget.onStrokeUpdate?.call(List<Offset>.from(_points));
          }
        },
        onPanUpdate: (details) {
          final point = _normalizedPoint(details.localPosition, size);
          if (point == null) return;
          _points.add(point);
          if (widget.tool != AnnotationTool.eraser) {
            widget.onStrokeUpdate?.call(List<Offset>.from(_points));
          }
        },
        onPanEnd: (_) {
          if (widget.tool == AnnotationTool.eraser) {
            if (_points.isNotEmpty) widget.onErase?.call(_points.last);
          } else if (_points.isNotEmpty) {
            // Ensure single-tap dot is visible – duplicate point if needed
            final out = _points.length == 1
                ? [ _points.first, Offset((_points.first.dx+0.001).clamp(0.0,1.0), _points.first.dy) ]
                : List<Offset>.from(_points);
            widget.onStroke(out);
          }
          _points.clear();
        },
        child: const SizedBox.expand(),
        );
      },
    );
  }
}

class DrawingOverlay extends StatefulWidget {
  final List<DrawStroke> strokes;
  final double contentAspectRatio;

  const DrawingOverlay({
    Key? key,
    required this.strokes,
    this.contentAspectRatio = 9 / 16,
  }) : super(key: key);

  @override
  State<DrawingOverlay> createState() => _DrawingOverlayState();
}

bool strokeNearPoint(DrawStroke stroke, Offset point, {double radius = 0.035}) {
  return stroke.points.any((p) {
    final dx = p.dx - point.dx;
    final dy = p.dy - point.dy;
    return (dx * dx) + (dy * dy) <= radius * radius;
  });
}

class _DrawingOverlayState extends State<DrawingOverlay> {
  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: CustomPaint(
        size: Size.infinite,
        painter: _StrokePainter(widget.strokes, widget.contentAspectRatio),
      ),
    );
  }
}

class _StrokePainter extends CustomPainter {
  final List<DrawStroke> strokes;
  final double contentAspectRatio;

  _StrokePainter(this.strokes, this.contentAspectRatio);

  @override
  void paint(Canvas canvas, Size size) {
    final contentHeight = math.min(size.height, size.width / contentAspectRatio);
    final contentWidth = contentHeight * contentAspectRatio;
    final contentRect = Rect.fromCenter(
      center: Offset(size.width / 2, size.height / 2),
      width: contentWidth,
      height: contentHeight,
    );
    for (final stroke in strokes) {
      if (stroke.points.isEmpty) continue;
      final paint = Paint()
        ..color = stroke.color
        ..strokeWidth = stroke.width
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..style = PaintingStyle.stroke;
      if (stroke.points.length == 1) {
        // Single dot
        final p = stroke.points.first;
        canvas.drawCircle(
          Offset(contentRect.left + p.dx * contentRect.width,
                 contentRect.top + p.dy * contentRect.height),
          stroke.width / 2,
          paint..style = PaintingStyle.fill,
        );
        continue;
      }
      final path = Path()
        ..moveTo(
          contentRect.left + stroke.points.first.dx * contentRect.width,
          contentRect.top + stroke.points.first.dy * contentRect.height,
        );
      for (final p in stroke.points.skip(1)) {
        path.lineTo(
          contentRect.left + p.dx * contentRect.width,
          contentRect.top + p.dy * contentRect.height,
        );
      }
      canvas.drawPath(path, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _StrokePainter oldDelegate) => true;
}
