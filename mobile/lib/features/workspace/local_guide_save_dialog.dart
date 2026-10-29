import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_edge_ai/flutter_edge_ai.dart' show CancelToken;

import '../../core/guides/session_keyframe_manager.dart';
import '../../core/guides/local_guide_ai_service.dart';
import '../../core/guides/local_guide_audio_capture.dart';
import '../../core/guides/local_guide_transcription_service.dart';
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
  final List<LocalGuideAudioRecording> audioRecordings;
  final bool helperCuratedFrames;
  final bool guideOwner;

  const LocalGuideSaveDialog({
    super.key,
    required this.frames,
    required this.suggestedTitle,
    this.audioRecordings = const [],
    this.helperCuratedFrames = false,
    this.guideOwner = false,
  });

  @override
  State<LocalGuideSaveDialog> createState() => _LocalGuideSaveDialogState();
}

class _LocalGuideSaveDialogState extends State<LocalGuideSaveDialog> {
  @override
  void initState() {
    super.initState();
    if (widget.helperCuratedFrames) {
      for (final frame in widget.frames) {
        _includedFrameIds.add(frame.id);
        _reviewedFrameIds.add(frame.id);
        _reviewedImages[frame.id] = frame.imageBytes;
      }
    }
  }

  late final TextEditingController _title = TextEditingController(
    text: widget.suggestedTitle,
  );
  late final TextEditingController _transcript = TextEditingController();
  final Set<String> _includedFrameIds = <String>{};
  final Set<String> _reviewedFrameIds = <String>{};
  final Map<String, Uint8List> _reviewedImages = <String, Uint8List>{};
  final Map<String, TextEditingController> _stepControllers = {};
  final Map<String, String> _stepTitles = {};
  bool _generating = false;
  bool _transcribing = false;
  bool _speechInferenceStarted = false;
  bool _transcriptionCompleted = false;
  double? _downloadProgress;
  double? _speechDownloadProgress;
  String? _generationError;
  String? _transcriptionError;
  CancelToken? _downloadCancelToken;

  bool get _selectedFramesReviewed =>
      _includedFrameIds.every(_reviewedFrameIds.contains);

  String? get _saveValidationMessage {
    if (_title.text.trim().isEmpty) return 'Enter a title for this guide.';
    if (!_selectedFramesReviewed) {
      return 'Open and review every selected screenshot before saving.';
    }
    if (_includedFrameIds.isEmpty && _transcript.text.trim().isEmpty) {
      return 'Add notes or select a screenshot before saving.';
    }
    return null;
  }

  Uint8List _imageFor(CapturedKeyframe frame) =>
      _reviewedImages[frame.id] ?? frame.imageBytes;

  @override
  void dispose() {
    _title.dispose();
    _transcript.dispose();
    _downloadCancelToken?.cancel('The local guide dialog was closed.');
    unawaited(_deleteAudioRecordings());
    for (final controller in _stepControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<bool> _deleteAudioRecordings() async {
    var allDeleted = true;
    for (final recording in widget.audioRecordings) {
      try {
        await recording.delete();
      } catch (_) {
        allDeleted = false;
      }
    }
    return allDeleted;
  }

  Future<void> _reviewScreenshot(CapturedKeyframe frame) async {
    if (_generating || widget.helperCuratedFrames) return;
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
    if (selectedFrames.isEmpty ||
        !_selectedFramesReviewed ||
        _generating ||
        _transcribing) {
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

  Future<void> _transcribeCallAudio() async {
    if (widget.audioRecordings.isEmpty ||
        _transcribing ||
        _transcriptionCompleted) {
      return;
    }
    setState(() {
      _transcribing = true;
      _transcriptionError = null;
      _downloadCancelToken = CancelToken();
    });
    try {
      await LocalGuideTranscriptionService.installModel(
        cancelToken: _downloadCancelToken!,
        onProgress: (progress) {
          if (mounted) {
            setState(() => _speechDownloadProgress = progress / 100);
          }
        },
      );
      if (!mounted) return;
      setState(() => _speechDownloadProgress = null);
      setState(() => _speechInferenceStarted = true);
      final generated =
          await LocalGuideTranscriptionService.transcribeRecordings(
            widget.audioRecordings,
            language: 'en',
          );
      if (!mounted) return;
      final existingNotes = _transcript.text.trim();
      _transcript.text = [
        if (generated.isNotEmpty) generated,
        if (existingNotes.isNotEmpty) 'Additional notes:\n$existingNotes',
      ].join('\n\n');
      _transcriptionCompleted = true;
      setState(() {});
    } catch (_) {
      if (mounted) {
        setState(
          () => _transcriptionError =
              'Local transcription failed. The audio was not uploaded. You can retry or save your notes without it.',
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _transcribing = false;
          _speechInferenceStarted = false;
          _speechDownloadProgress = null;
        });
      }
    }
  }

  Future<bool> _deleteTemporaryAudio() async {
    final deleted = await _deleteAudioRecordings();
    if (deleted) return true;
    if (mounted) {
      setState(
        () => _transcriptionError =
            'Could not remove the temporary audio file. Retry discard or save after cleanup succeeds.',
      );
    }
    return false;
  }

  Future<void> _discardGuide() async {
    if (_transcribing) {
      _downloadCancelToken?.cancel('Cancel local transcription.');
      return;
    }
    if (_generating) {
      _downloadCancelToken?.cancel('Cancel local guide generation.');
    }
    if (!await _deleteTemporaryAudio() || !mounted) return;
    Navigator.pop(context);
  }

  Future<void> _saveGuide() async {
    if (_generating || _transcribing) return;
    final validationMessage = _saveValidationMessage;
    if (validationMessage != null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(validationMessage)));
      return;
    }
    if (!await _deleteTemporaryAudio() || !mounted) return;
    Navigator.pop(
      context,
      LocalGuideSaveInput(
        title: _title.text.trim(),
        transcript: _transcript.text.trim(),
        includedFrameIds: Set.unmodifiable(_includedFrameIds),
        redactedImages: Map.unmodifiable({
          for (final id in _includedFrameIds)
            if (_reviewedImages.containsKey(id)) id: _reviewedImages[id]!,
        }),
        generatedInstructions: Map.unmodifiable({
          for (final entry in _stepControllers.entries)
            entry.key: entry.value.text.trim(),
        }),
        generatedTitles: Map.unmodifiable(_stepTitles),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    Theme.of(context);
    return PopScope(
      // Keep the temporary recording alive until native decode and on-device
      // inference finish; the explicit dialog action is disabled during inference.
      canPop: !_speechInferenceStarted,
      child: AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Save a private guide?'),
        content: SizedBox(
          width: 440,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  widget.helperCuratedFrames
                      ? widget.guideOwner
                            ? 'You chose and redacted these steps during the call. Review the guide, add notes, and save it. The finished guide will be encrypted on your phone and synced to the other participant.'
                            : 'Your helper chose and redacted these steps. The finished guide is saved automatically on this phone.'
                      : 'Your guide stays encrypted on this phone. To include a screenshot, select it and open it to cover private details. You can then generate and edit numbered steps on this phone.',
                  style: TextStyle(fontSize: AppTypography.body, height: 1.4),
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
                  decoration: InputDecoration(
                    labelText: 'Transcript or notes (optional)',
                    hintText: widget.audioRecordings.isEmpty
                        ? 'Type or paste session notes.'
                        : 'Type notes here, or transcribe the opted-in call locally below.',
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                if (widget.audioRecordings.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppTheme.bgCard,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: AppTheme.borderGlass),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          'Call audio is temporary and stays on this device. Downloading Whisper sends only model requests; audio is deleted after transcription or when this guide is discarded.',
                          style: TextStyle(
                            color: AppTheme.textSecondary,
                            fontSize: AppTypography.bodySmall,
                            height: 1.35,
                          ),
                        ),
                        const SizedBox(height: 8),
                        OutlinedButton.icon(
                          onPressed: _transcribing || _transcriptionCompleted
                              ? null
                              : _transcribeCallAudio,
                          icon: _transcribing
                              ? const SizedBox(
                                  width: 16,
                                  height: 16,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : Icon(
                                  _transcriptionCompleted
                                      ? Icons.verified
                                      : Icons.graphic_eq,
                                ),
                          label: Text(
                            _transcriptionCompleted
                                ? 'Transcribed locally'
                                : _transcribing
                                ? (_speechDownloadProgress == null
                                      ? 'Transcribing on this device…'
                                      : 'Downloading speech model · ${(_speechDownloadProgress! * 100).round()}%')
                                : 'Transcribe call locally',
                          ),
                        ),
                        if (_speechDownloadProgress != null) ...[
                          const SizedBox(height: 5),
                          LinearProgressIndicator(
                            value: _speechDownloadProgress,
                          ),
                        ],
                        if (_transcriptionError != null)
                          Text(
                            _transcriptionError!,
                            style: const TextStyle(color: Colors.redAccent),
                          ),
                      ],
                    ),
                  ),
                ],
                if (widget.frames.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  const Text(
                    'Choose screenshots',
                    style: TextStyle(
                      fontSize: AppTypography.bodyLarge,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  Text(
                    widget.helperCuratedFrames
                        ? 'Screenshots selected and redacted by your helper.'
                        : 'Select a screenshot, then open it to cover private details.',
                    style: TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: AppTypography.bodySmall,
                    ),
                  ),
                  const SizedBox(height: 6),
                  SizedBox(
                    height: 220,
                    child: ListView.builder(
                      itemCount: widget.frames.length,
                      itemBuilder: (context, index) {
                        final frame = widget.frames[index];
                        if (widget.helperCuratedFrames) {
                          return ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(
                              Icons.verified_user,
                              color: AppTheme.accentEmerald,
                            ),
                            title: Text(
                              frame.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            subtitle: const Text(
                              'Chosen and privacy-reviewed by your helper.',
                            ),
                            trailing: SizedBox(
                              width: 72,
                              height: 56,
                              child: Image.memory(
                                _imageFor(frame),
                                fit: BoxFit.cover,
                              ),
                            ),
                          );
                        }
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
                                ? 'Reviewed. Tap the image to change redactions.'
                                : 'Select, then tap the image to hide private details.',
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
                                  Image.memory(
                                    _imageFor(frame),
                                    fit: BoxFit.cover,
                                  ),
                                  Align(
                                    alignment: Alignment.topRight,
                                    child: Icon(
                                      _reviewedFrameIds.contains(frame.id)
                                          ? Icons.verified_user
                                          : Icons.visibility_outlined,
                                      size: 18,
                                      color: Colors.white,
                                      shadows: const [
                                        Shadow(
                                          blurRadius: 4,
                                          color: Colors.black,
                                        ),
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
                            _generating ||
                            _transcribing
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
                      _generating || _transcribing
                          ? (_transcribing
                                ? (_speechDownloadProgress == null
                                      ? 'Transcribing on this device…'
                                      : 'Downloading speech model · ${(_speechDownloadProgress! * 100).round()}%')
                                : (_downloadProgress == null
                                      ? 'Generating on this device…'
                                      : 'Downloading Gemma 4 · ${(_downloadProgress! * 100).round()}%'))
                          : _selectedFramesReviewed
                          ? 'Generate guide locally with Gemma 4'
                          : 'Review selected screenshots first',
                    ),
                  ),
                  if (_downloadProgress != null) ...[
                    const SizedBox(height: 6),
                    LinearProgressIndicator(value: _downloadProgress),
                    Text(
                      'First setup downloads about 2.6 GB of model files. This download contains no session data.',
                      style: TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: AppTypography.bodySmall,
                      ),
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
                          labelText:
                              'Step ${widget.frames.indexOf(frame) + 1}: ${_stepTitles[frame.id] ?? frame.title}',
                          helperText: 'Review and edit these instructions.',
                        ),
                      ),
                    ],
                  if (_includedFrameIds.any(
                    (id) => !_reviewedFrameIds.contains(id),
                  ))
                    Text(
                      'Review every selected screenshot before saving.',
                      style: TextStyle(
                        color: AppTheme.accentRose,
                        fontSize: AppTypography.bodySmall,
                      ),
                    )
                  else if (_includedFrameIds.isEmpty &&
                      _transcript.text.trim().isEmpty)
                    Text(
                      'Add notes or select a screenshot to enable saving.',
                      style: TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: AppTypography.bodySmall,
                      ),
                    ),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: _transcribing && _speechInferenceStarted
                ? null
                : _discardGuide,
            child: Text(
              _transcribing && _speechInferenceStarted
                  ? 'Transcribing…'
                  : _generating || _transcribing
                  ? 'Cancel'
                  : 'Discard',
            ),
          ),
          ElevatedButton(
            onPressed: _generating || _transcribing ? null : _saveGuide,
            child: const Text('Save private guide'),
          ),
        ],
      ),
    );
  }
}
