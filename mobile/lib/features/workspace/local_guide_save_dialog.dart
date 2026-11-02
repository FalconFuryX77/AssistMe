import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_edge_ai/flutter_edge_ai.dart' show CancelToken;

import '../../core/guides/session_keyframe_manager.dart';
import '../../core/guides/local_ai_device_support.dart';
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

  /// Steps with no screenshot, in order, after the screenshot steps.
  final List<GeneratedGuideStep> textSteps;

  const LocalGuideSaveInput({
    required this.title,
    required this.transcript,
    required this.includedFrameIds,
    required this.redactedImages,
    required this.generatedInstructions,
    required this.generatedTitles,
    this.textSteps = const [],
  });
}

class _WrittenStep {
  final TextEditingController title;
  final TextEditingController instruction;

  _WrittenStep({String title = '', String instruction = ''})
    : title = TextEditingController(text: title),
      instruction = TextEditingController(text: instruction);

  bool get isComplete =>
      title.text.trim().isNotEmpty && instruction.text.trim().isNotEmpty;

  void dispose() {
    title.dispose();
    instruction.dispose();
  }
}

class LocalGuideSaveDialog extends StatefulWidget {
  final List<CapturedKeyframe> frames;
  final String suggestedTitle;
  final List<LocalGuideAudioRecording> audioRecordings;
  final bool helperCuratedFrames;
  final bool guideOwner;

  /// Transcribe the call and write the steps as soon as the dialog opens, when
  /// the on-device models are already installed. Nothing is downloaded
  /// without the helper asking.
  final bool autoGenerate;

  const LocalGuideSaveDialog({
    super.key,
    required this.frames,
    required this.suggestedTitle,
    this.audioRecordings = const [],
    this.helperCuratedFrames = false,
    this.guideOwner = false,
    this.autoGenerate = false,
  });

  @override
  State<LocalGuideSaveDialog> createState() => _LocalGuideSaveDialogState();
}

class _LocalGuideSaveDialogState extends State<LocalGuideSaveDialog> {
  @override
  void initState() {
    super.initState();
    if (widget.helperCuratedFrames) {
      for (final (index, frame) in widget.frames.indexed) {
        _includedFrameIds.add(frame.id);
        _reviewedFrameIds.add(frame.id);
        _reviewedImages[frame.id] = frame.imageBytes;
        // Screenshots are taken with one tap during the call, so a step has
        // no words yet; Gemma fills them in, and the helper can edit them.
        _stepTitles[frame.id] = frame.title.trim().isEmpty
            ? 'Step ${index + 1}'
            : frame.title;
        _stepControllers[frame.id] = TextEditingController(
          text: frame.instruction,
        );
      }
    }
    unawaited(widget.autoGenerate ? _autoGenerate() : _loadAiSupport());
  }

  /// Transcript first (Gemma reads it), then the steps: per screenshot, or
  /// from the transcript alone when there are no screenshots.
  Future<void> _autoGenerate() async {
    await _loadAiSupport();
    if (!mounted) return;
    if (widget.audioRecordings.isNotEmpty &&
        LocalGuideTranscriptionService.isModelInstalled) {
      await _transcribeCallAudio();
      if (!mounted) return;
    }
    if (!_aiAvailable || !LocalGuideAiService.isModelInstalled) return;
    if (_includedFrameIds.isNotEmpty) {
      await _generateGuide();
    } else if (_transcript.text.trim().isNotEmpty && _writtenSteps.isEmpty) {
      await _generateWrittenSteps();
    }
  }

  Future<void> _loadAiSupport() async {
    final report = await LocalAiDeviceSupport.check(
      modelAlreadyInstalled: LocalGuideAiService.isModelInstalled,
    );
    if (mounted) setState(() => _aiReport = report);
  }

  bool get _aiAvailable => _aiReport?.canRunModel ?? false;

  static String _errorText(Object error, String fallback) =>
      error is LocalAiException ? error.message : fallback;

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
  LocalAiDeviceReport? _aiReport;
  final List<_WrittenStep> _writtenSteps = [];

  bool get _selectedFramesReviewed =>
      _includedFrameIds.every(_reviewedFrameIds.contains);

  String? get _saveValidationMessage {
    if (_title.text.trim().isEmpty) return 'Enter a title for this guide.';
    if (!_selectedFramesReviewed) {
      return 'Open and review every selected screenshot before saving.';
    }
    if (_writtenSteps.any(
      (step) =>
          !step.isComplete &&
          (step.title.text.trim().isNotEmpty ||
              step.instruction.text.trim().isNotEmpty),
    )) {
      return 'Give every written step a name and an instruction, or remove it.';
    }
    if (_includedFrameIds.isEmpty &&
        _transcript.text.trim().isEmpty &&
        !_writtenSteps.any((step) => step.isComplete)) {
      return 'Add notes, a written step or a screenshot before saving.';
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
    for (final step in _writtenSteps) {
      step.dispose();
    }
    unawaited(LocalGuideAiService.releaseModel());
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
      await _installGemma();
      if (!mounted) return;
      for (var index = 0; index < selectedFrames.length; index++) {
        final frame = selectedFrames[index];
        final step = await LocalGuideAiService.generateStep(
          imageBytes: _imageFor(frame),
          transcript: sessionNotes,
          stepNumber: index + 1,
          helperTitle: frame.title,
          helperInstruction: frame.instruction,
        );
        if (!mounted) return;
        _stepTitles[frame.id] = step.title;
        _stepControllers
                .putIfAbsent(frame.id, () => TextEditingController())
                .text =
            step.instruction;
        setState(() {});
      }
    } catch (error) {
      if (mounted) {
        setState(
          () => _generationError =
              '${_errorText(error, 'Local generation failed.')} '
              'The steps you wrote are kept, and you can still save them.',
        );
      }
    } finally {
      await LocalGuideAiService.releaseModel();
      if (mounted) {
        setState(() {
          _generating = false;
          _downloadProgress = null;
        });
      }
    }
  }

  Future<void> _installGemma() async {
    await LocalGuideAiService.installModel(
      cancelToken: _downloadCancelToken!,
      onProgress: (progress) {
        if (mounted) setState(() => _downloadProgress = progress / 100);
      },
    );
    if (mounted) setState(() => _downloadProgress = null);
  }

  /// No screenshots (or extra steps): Gemma reads the transcript and writes
  /// numbered text steps the helper can edit.
  Future<void> _generateWrittenSteps() async {
    final notes = _transcript.text.trim();
    if (notes.isEmpty || _generating || _transcribing) return;
    setState(() {
      _generating = true;
      _generationError = null;
      _downloadCancelToken = CancelToken();
    });
    try {
      await _installGemma();
      final steps = await LocalGuideAiService.generateStepsFromTranscript(
        notes,
      );
      if (!mounted) return;
      setState(() {
        for (final step in steps) {
          _writtenSteps.add(
            _WrittenStep(title: step.title, instruction: step.instruction),
          );
        }
      });
    } catch (error) {
      if (mounted) {
        setState(
          () => _generationError =
              '${_errorText(error, 'Local generation failed.')} '
              'You can still add written steps yourself.',
        );
      }
    } finally {
      await LocalGuideAiService.releaseModel();
      if (mounted) {
        setState(() {
          _generating = false;
          _downloadProgress = null;
        });
      }
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
    } catch (error) {
      if (mounted) {
        setState(
          () => _transcriptionError =
              '${_errorText(error, 'Local transcription failed.')} '
              'The audio was not uploaded. You can retry or save your notes without it.',
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
        textSteps: List.unmodifiable(
          _writtenSteps
              .where((step) => step.isComplete)
              .map(
                (step) => GeneratedGuideStep(
                  title: step.title.text.trim(),
                  instruction: step.instruction.text.trim(),
                ),
              ),
        ),
      ),
    );
  }

  /// Steps that have no screenshot: typed by the helper or written by Gemma
  /// from the transcript.
  List<Widget> _buildWrittenSteps() {
    final firstNumber = _includedFrameIds.length + 1;
    final busy = _generating || _transcribing;
    return [
      const SizedBox(height: 14),
      const Text(
        'Steps without a screenshot',
        style: TextStyle(
          fontSize: AppTypography.bodyLarge,
          fontWeight: FontWeight.w700,
        ),
      ),
      for (var index = 0; index < _writtenSteps.length; index++) ...[
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                children: [
                  TextField(
                    controller: _writtenSteps[index].title,
                    maxLength: 100,
                    decoration: InputDecoration(
                      labelText: 'Step ${firstNumber + index} name',
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                  TextField(
                    controller: _writtenSteps[index].instruction,
                    minLines: 2,
                    maxLines: 4,
                    maxLength: 1000,
                    decoration: const InputDecoration(
                      labelText: 'What should the user do?',
                      helperText:
                          'Put button names in quotes so Clicky can point at them.',
                      helperMaxLines: 2,
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                ],
              ),
            ),
            IconButton(
              tooltip: 'Remove this step',
              icon: const Icon(Icons.delete_outline),
              onPressed: busy
                  ? null
                  : () =>
                        setState(() => _writtenSteps.removeAt(index).dispose()),
            ),
          ],
        ),
      ],
      const SizedBox(height: 6),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          OutlinedButton.icon(
            onPressed: busy
                ? null
                : () => setState(() => _writtenSteps.add(_WrittenStep())),
            icon: const Icon(Icons.add),
            label: const Text('Add a written step'),
          ),
          OutlinedButton.icon(
            onPressed: !_aiAvailable || busy || _transcript.text.trim().isEmpty
                ? null
                : _generateWrittenSteps,
            icon: const Icon(Icons.auto_awesome),
            label: const Text('Write steps from the transcript'),
          ),
        ],
      ),
    ];
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
                              _stepTitles[frame.id] ?? frame.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            subtitle: Text(
                              widget.guideOwner
                                  ? 'Reviewed by you.'
                                  : 'Chosen and privacy-reviewed by your helper.',
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
                        !_aiAvailable ||
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
                          : !_selectedFramesReviewed
                          ? 'Review selected screenshots first'
                          : _aiReport?.canUseScreenshots == false &&
                                _aiAvailable
                          ? 'Improve steps with Gemma 4 (text only)'
                          : 'Improve steps with Gemma 4',
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
                          helperText:
                              'Review and edit these instructions. Put button names in quotes so Clicky can point at them.',
                          helperMaxLines: 2,
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
                if (widget.guideOwner || !widget.helperCuratedFrames)
                  ..._buildWrittenSteps(),
                if (_aiReport != null && _aiReport!.reason != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    _aiAvailable
                        ? _aiReport!.reason!
                        : 'On-device AI is not available on this phone. '
                              '${_aiReport!.reason} You can still save the steps you wrote.',
                    style: TextStyle(
                      color: _aiAvailable
                          ? AppTheme.textSecondary
                          : AppTheme.accentAmber,
                      fontSize: AppTypography.bodySmall,
                      height: 1.35,
                    ),
                  ),
                ],
                if (_generationError != null && widget.frames.isEmpty) ...[
                  const SizedBox(height: 8),
                  Text(
                    _generationError!,
                    style: const TextStyle(color: Colors.redAccent),
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
