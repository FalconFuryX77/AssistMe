import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_edge_ai/flutter_edge_ai.dart' show CancelToken;

import '../../core/guides/session_keyframe_manager.dart';
import '../../core/guides/local_guide_ai_service.dart';
import '../../theme/app_theme.dart';
import 'screenshot_redaction_editor.dart';

class LocalGuideSaveInput {
  final String title;
  final String transcript;
  final Set<String> includedFrameIds;
  final Map<String, Uint8List> redactedImages;
  final Map<String, String> generatedInstructions;
  final Map<String, String> generatedTitles;

  const LocalGuideSaveInput({
    required this.title,
    required this.transcript,
    required this.includedFrameIds,
    required this.redactedImages,
    required this.generatedInstructions,
    required this.generatedTitles,
  });
}

class LocalGuideSaveDialog extends StatefulWidget {
  final List<CapturedKeyframe> frames;
  final String suggestedTitle;

  const LocalGuideSaveDialog({
    super.key,
    required this.frames,
    required this.suggestedTitle,
  });

  @override
  State<LocalGuideSaveDialog> createState() => _LocalGuideSaveDialogState();
}

class _LocalGuideSaveDialogState extends State<LocalGuideSaveDialog> {
  late final TextEditingController _title = TextEditingController(
    text: widget.suggestedTitle,
  );
  final TextEditingController _transcript = TextEditingController();
  final Set<String> _includedFrameIds = <String>{};
  final Set<String> _reviewedFrameIds = <String>{};
  final Map<String, Uint8List> _reviewedImages = <String, Uint8List>{};
  final Map<String, TextEditingController> _stepControllers = {};
  final Map<String, String> _stepTitles = {};
  bool _generating = false;
  double? _downloadProgress;
  String? _generationError;
  CancelToken? _downloadCancelToken;

  bool get _selectedFramesReviewed =>
      _includedFrameIds.every(_reviewedFrameIds.contains);

  Uint8List _imageFor(CapturedKeyframe frame) =>
      _reviewedImages[frame.id] ?? frame.imageBytes;

  @override
  void dispose() {
    _title.dispose();
    _transcript.dispose();
    for (final controller in _stepControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _reviewScreenshot(CapturedKeyframe frame) async {
    if (_generating) return;
    final reviewed = await editScreenshotRedactions(
      context,
      _reviewedImages[frame.id] ?? frame.imageBytes,
    );
    if (!mounted || reviewed == null) return;
    setState(() {
      _reviewedFrameIds.add(frame.id);
      _reviewedImages[frame.id] = reviewed;
    });
  }

  Future<void> _generateGuide() async {
    final selectedFrames = widget.frames
        .where((frame) => _includedFrameIds.contains(frame.id))
        .toList(growable: false);
    if (selectedFrames.isEmpty || !_selectedFramesReviewed || _generating) {
      return;
    }
    final sessionNotes = _transcript.text;
    setState(() {
      _generating = true;
      _generationError = null;
      _downloadCancelToken = CancelToken();
    });
    try {
      await LocalGuideAiService.installModel(
        cancelToken: _downloadCancelToken!,
        onProgress: (progress) {
          if (mounted) setState(() => _downloadProgress = progress / 100);
        },
      );
      if (!mounted) return;
      if (mounted) setState(() => _downloadProgress = null);
      for (var index = 0; index < selectedFrames.length; index++) {
        final frame = selectedFrames[index];
        final generated = await LocalGuideAiService.generateStep(
          imageBytes: _imageFor(frame),
          transcript: sessionNotes,
          stepNumber: index + 1,
        );
        if (!mounted) return;
        final title = RegExp(
          r'^TITLE:\s*(.+)$',
          multiLine: true,
        ).firstMatch(generated)?.group(1)?.trim();
        final action = RegExp(
          r'^ACTION:\s*([\s\S]+)$',
          multiLine: true,
        ).firstMatch(generated)?.group(1)?.trim();
        _stepTitles[frame.id] = title == null || title.isEmpty
            ? 'Step ${index + 1}'
            : title.substring(0, title.length.clamp(0, 100));
        final controller = _stepControllers.putIfAbsent(
          frame.id,
          () => TextEditingController(),
        );
        controller.text = action == null || action.isEmpty ? generated : action;
        if (mounted) setState(() {});
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _generationError =
              'Local generation failed. Your screenshots and notes remain on this device. You can save the notes and try again later.',
        );
      }
    } finally {
      if (mounted) setState(() => _generating = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    backgroundColor: AppTheme.bgSecondary,
    title: const Text('Save a private guide?'),
    content: SizedBox(
      width: 440,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'The guide and notes are encrypted and saved on this device. Nothing is uploaded. The model runs on this device. Review every selected screenshot; drag over sensitive details to permanently black them out before generation or saving.',
              style: TextStyle(color: AppTheme.textSecondary, height: 1.4),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _title,
              maxLength: 100,
              decoration: const InputDecoration(labelText: 'Guide title'),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _transcript,
              minLines: 3,
              maxLines: 7,
              maxLength: 20000,
              decoration: const InputDecoration(
                labelText: 'Transcript or notes (optional)',
                hintText:
                    'Type or paste session notes. Audio transcription is not enabled yet.',
              ),
              onChanged: (_) => setState(() {}),
            ),
            if (widget.frames.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'Review screenshots · ${_reviewedFrameIds.length} reviewed · ${_includedFrameIds.length} selected',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 6),
              SizedBox(
                height: 220,
                child: ListView.builder(
                  itemCount: widget.frames.length,
                  itemBuilder: (context, index) {
                    final frame = widget.frames[index];
                    return CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      value: _includedFrameIds.contains(frame.id),
                      activeColor: AppTheme.accentEmerald,
                      controlAffinity: ListTileControlAffinity.leading,
                      onChanged: (value) => setState(() {
                        if (value == true) {
                          _includedFrameIds.add(frame.id);
                        } else {
                          _includedFrameIds.remove(frame.id);
                        }
                      }),
                      title: Text(
                        frame.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Text(
                        _reviewedFrameIds.contains(frame.id)
                            ? 'Reviewed · ${frame.instruction}'
                            : 'Tap the image to review and redact before use.',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      secondary: GestureDetector(
                        onTap: () => _reviewScreenshot(frame),
                        child: SizedBox(
                          width: 72,
                          height: 56,
                          child: Stack(
                            fit: StackFit.expand,
                            children: [
                              Image.memory(_imageFor(frame), fit: BoxFit.cover),
                              Align(
                                alignment: Alignment.topRight,
                                child: Icon(
                                  _reviewedFrameIds.contains(frame.id)
                                      ? Icons.verified_user
                                      : Icons.visibility_outlined,
                                  size: 18,
                                  color: Colors.white,
                                  shadows: const [
                                    Shadow(blurRadius: 4, color: Colors.black),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed:
                    _includedFrameIds.isEmpty ||
                        !_selectedFramesReviewed ||
                        _generating
                    ? null
                    : _generateGuide,
                icon: _generating
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.auto_awesome),
                label: Text(
                  _generating
                      ? (_downloadProgress == null
                            ? 'Generating on this device…'
                            : 'Downloading Gemma 4 · ${(_downloadProgress! * 100).round()}%')
                      : _selectedFramesReviewed
                      ? 'Generate guide locally with Gemma 4'
                      : 'Review selected screenshots first',
                ),
              ),
              if (_downloadProgress != null) ...[
                const SizedBox(height: 6),
                LinearProgressIndicator(value: _downloadProgress),
                const Text(
                  'First setup downloads about 2.6 GB of model files. This download contains no session data.',
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                ),
              ],
              if (_generationError != null) ...[
                const SizedBox(height: 8),
                Text(
                  _generationError!,
                  style: const TextStyle(color: Colors.redAccent),
                ),
              ],
              for (final frame in widget.frames)
                if (_includedFrameIds.contains(frame.id) &&
                    _stepControllers.containsKey(frame.id)) ...[
                  const SizedBox(height: 8),
                  TextField(
                    controller: _stepControllers[frame.id],
                    minLines: 2,
                    maxLines: 4,
                    maxLength: 1000,
                    decoration: InputDecoration(
                      labelText: _stepTitles[frame.id] ?? frame.title,
                      helperText: 'Review and edit this generated draft.',
                    ),
                  ),
                ],
            ],
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () {
          _downloadCancelToken?.cancel('User closed the guide review.');
          Navigator.pop(context);
        },
        child: Text(_generating ? 'Cancel' : 'Discard'),
      ),
      ElevatedButton(
        onPressed:
            _generating ||
                !_selectedFramesReviewed ||
                _title.text.trim().isEmpty ||
                (_includedFrameIds.isEmpty && _transcript.text.trim().isEmpty)
            ? null
            : () => Navigator.pop(
                context,
                LocalGuideSaveInput(
                  title: _title.text.trim(),
                  transcript: _transcript.text.trim(),
                  includedFrameIds: Set.unmodifiable(_includedFrameIds),
                  redactedImages: Map.unmodifiable({
                    for (final id in _includedFrameIds)
                      if (_reviewedImages.containsKey(id))
                        id: _reviewedImages[id]!,
                  }),
                  generatedInstructions: Map.unmodifiable({
                    for (final entry in _stepControllers.entries)
                      entry.key: entry.value.text.trim(),
                  }),
                  generatedTitles: Map.unmodifiable(_stepTitles),
                ),
              ),
        child: const Text('Save on this device'),
      ),
    ],
  );
}
