/// After a call, walks the helper through every screenshot they captured, one
/// at a time and full screen, so private details can be covered before the
/// guide is saved or leaves this phone.
///
/// Capturing during the call is a single tap; this is where the privacy review
/// happens. "Skip all" keeps the rest as they are when nothing needs covering.
library;

import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../core/guides/session_keyframe_manager.dart';
import '../../theme/app_theme.dart';
import 'screenshot_redaction_editor.dart';

/// Shows each frame in order and returns the frames to keep, with any
/// redactions burned in and marked reviewed. Removed frames are left out.
Future<List<CapturedKeyframe>> reviewScreenshotsInOrder(
  BuildContext context,
  List<CapturedKeyframe> frames,
) async {
  if (frames.isEmpty) return const [];
  final kept = await Navigator.of(context).push<List<CapturedKeyframe>>(
    MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) => _ScreenshotReviewSequence(frames: frames),
    ),
  );
  // Leaving the screen any other way keeps everything as captured; nothing
  // is lost, and the guide is still only on this phone.
  return kept ??
      [for (final frame in frames) _reviewed(frame, frame.imageBytes)];
}

CapturedKeyframe _reviewed(CapturedKeyframe frame, Uint8List bytes) =>
    CapturedKeyframe(
      id: frame.id,
      timestamp: frame.timestamp,
      imageBytes: bytes,
      title: frame.title,
      instruction: frame.instruction,
      perceptualHash: frame.perceptualHash,
      colorSignature: frame.colorSignature,
      privacyReviewed: true,
    );

class _ScreenshotReviewSequence extends StatefulWidget {
  final List<CapturedKeyframe> frames;

  const _ScreenshotReviewSequence({required this.frames});

  @override
  State<_ScreenshotReviewSequence> createState() =>
      _ScreenshotReviewSequenceState();
}

class _ScreenshotReviewSequenceState extends State<_ScreenshotReviewSequence> {
  final List<CapturedKeyframe> _kept = [];
  late final List<Uint8List> _images = [
    for (final frame in widget.frames) frame.imageBytes,
  ];
  int _index = 0;
  bool _editing = false;

  CapturedKeyframe get _frame => widget.frames[_index];

  void _next({required bool keep}) {
    if (keep) _kept.add(_reviewed(_frame, _images[_index]));
    if (_index == widget.frames.length - 1) {
      Navigator.pop(context, _kept);
      return;
    }
    setState(() => _index++);
  }

  void _skipAll() {
    for (var i = _index; i < widget.frames.length; i++) {
      _kept.add(_reviewed(widget.frames[i], _images[i]));
    }
    Navigator.pop(context, _kept);
  }

  Future<void> _cover() async {
    if (_editing) return;
    setState(() => _editing = true);
    final redacted = await editScreenshotRedactions(context, _images[_index]);
    if (!mounted) return;
    setState(() {
      _editing = false;
      if (redacted != null) _images[_index] = redacted;
    });
  }

  @override
  Widget build(BuildContext context) {
    final total = widget.frames.length;
    final last = _index == total - 1;
    return PopScope(
      // Back keeps everything reviewed so far plus the rest, like "Skip all".
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _skipAll();
      },
      child: Scaffold(
        backgroundColor: AppTheme.bgPrimary,
        appBar: AppBar(
          automaticallyImplyLeading: false,
          title: Text('Screenshot ${_index + 1} of $total'),
          actions: [
            if (!last)
              TextButton(
                onPressed: _skipAll,
                child: const Text(
                  'Skip all',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
          ],
        ),
        body: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 4, 20, 12),
                child: Text(
                  'Cover anything private, like names, messages or passwords. '
                  'Nothing has been shared yet.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: AppTypography.body,
                  ),
                ),
              ),
              Expanded(
                child: GestureDetector(
                  onTap: _cover,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(16),
                      child: Image.memory(_images[_index], fit: BoxFit.contain),
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
                child: Column(
                  children: [
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: _editing ? null : _cover,
                        icon: const Icon(Icons.format_color_fill),
                        label: const Text('Cover private parts'),
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: TextButton.icon(
                            onPressed: _editing
                                ? null
                                : () => _next(keep: false),
                            icon: const Icon(
                              Icons.delete_outline,
                              color: AppTheme.accentRose,
                            ),
                            label: const Text(
                              'Remove',
                              style: TextStyle(color: AppTheme.accentRose),
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          flex: 2,
                          child: ElevatedButton.icon(
                            onPressed: _editing
                                ? null
                                : () => _next(keep: true),
                            icon: Icon(
                              last ? Icons.check : Icons.arrow_forward,
                            ),
                            label: Text(last ? 'Done' : 'Looks good'),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppTheme.accentEmerald,
                              foregroundColor: Colors.white,
                              padding: const EdgeInsets.symmetric(vertical: 14),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
