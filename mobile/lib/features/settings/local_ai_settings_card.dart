/// Settings card that prepares the on-device guide AI before a call: shows
/// whether this phone can run it (and why not), downloads Gemma 4 and
/// Whisper over Wi-Fi ahead of time, and runs a short self-test.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_edge_ai/flutter_edge_ai.dart' show CancelToken;

import '../../core/guides/local_ai_device_support.dart';
import '../../core/guides/local_guide_ai_service.dart';
import '../../core/guides/local_guide_transcription_service.dart';
import '../../theme/app_theme.dart';

class LocalAiSettingsCard extends StatefulWidget {
  const LocalAiSettingsCard({super.key});

  @override
  State<LocalAiSettingsCard> createState() => _LocalAiSettingsCardState();
}

class _LocalAiSettingsCardState extends State<LocalAiSettingsCard> {
  LocalAiDeviceReport? _report;
  bool _gemmaReady = false;
  bool _whisperReady = false;
  bool _busy = false;
  String? _activity;
  double? _progress;
  String? _message;
  bool _messageIsError = false;
  CancelToken? _cancelToken;

  @override
  void initState() {
    super.initState();
    unawaited(_refresh());
  }

  @override
  void dispose() {
    _cancelToken?.cancel('Settings closed.');
    super.dispose();
  }

  Future<void> _refresh() async {
    var report = await LocalAiDeviceSupport.check(modelAlreadyInstalled: true);
    if (report.canRunModel) {
      try {
        await LocalGuideAiService.initialize();
      } catch (_) {}
      report = await LocalAiDeviceSupport.check(
        modelAlreadyInstalled: LocalGuideAiService.isModelInstalled,
      );
    }
    if (!mounted) return;
    setState(() {
      _report = report;
      _gemmaReady = LocalGuideAiService.isModelInstalled;
      _whisperReady = LocalGuideTranscriptionService.isModelInstalled;
    });
  }

  Future<void> _run(String activity, Future<String> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _activity = activity;
      _progress = null;
      _message = null;
      _cancelToken = CancelToken();
    });
    try {
      final done = await action();
      if (mounted) {
        setState(() {
          _message = done;
          _messageIsError = false;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _message = error is LocalAiException
              ? error.message
              : 'That did not finish (${error.runtimeType}). Try again.';
          _messageIsError = true;
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _activity = null;
          _progress = null;
        });
      }
      await _refresh();
    }
  }

  Future<void> _downloadModels() => _run('Downloading Gemma 4', () async {
    await LocalGuideAiService.installModel(
      cancelToken: _cancelToken!,
      onProgress: (progress) {
        if (mounted) setState(() => _progress = progress / 100);
      },
    );
    if (mounted) {
      setState(() {
        _activity = 'Downloading the speech model';
        _progress = null;
      });
    }
    await LocalGuideTranscriptionService.installModel(
      cancelToken: _cancelToken!,
      onProgress: (progress) {
        if (mounted) setState(() => _progress = progress / 100);
      },
    );
    return 'Both models are on this phone. Guides can now be written offline.';
  });

  Future<void> _selfTest() => _run('Testing Gemma on this phone', () async {
    final result = await LocalGuideAiService.runSelfTest();
    return 'Gemma works on this phone (${result.backend.toUpperCase()}). '
        'Loaded in ${result.loadTime.inSeconds} s, answered in '
        '${result.generationTime.inSeconds} s.\n\n${result.sample}';
  });

  @override
  Widget build(BuildContext context) {
    final report = _report;
    final supported = report?.canRunModel ?? false;
    final modelsReady = _gemmaReady && _whisperReady;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Writes step-by-step guides from the call transcript and the '
            'moments you capture, entirely on this phone. Download the models '
            'once over Wi-Fi before a call.',
            style: TextStyle(
              color: context.textSecondary,
              fontSize: AppTypography.bodySmall,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 12),
          if (report == null)
            const LinearProgressIndicator()
          else ...[
            _statusRow(
              icon: supported ? Icons.check_circle : Icons.block,
              color: supported
                  ? report.canUseScreenshots
                        ? AppTheme.accentEmerald
                        : AppTheme.accentAmber
                  : AppTheme.accentRose,
              title: !supported
                  ? 'Not available on this phone'
                  : report.canUseScreenshots
                  ? 'Reads screenshots and transcripts'
                  : 'Text only (transcripts and notes)',
              detail: [
                if (report.reason != null) report.reason!,
                if (report.model.isNotEmpty) report.summary,
              ].join('\n'),
            ),
            if (supported) ...[
              const SizedBox(height: 8),
              _statusRow(
                icon: _gemmaReady ? Icons.download_done : Icons.download,
                color: _gemmaReady
                    ? AppTheme.accentEmerald
                    : context.textSecondary,
                title: _gemmaReady
                    ? 'Gemma 4 downloaded'
                    : 'Gemma 4 not downloaded (about 2.6 GB)',
              ),
              const SizedBox(height: 8),
              _statusRow(
                icon: _whisperReady ? Icons.download_done : Icons.download,
                color: _whisperReady
                    ? AppTheme.accentEmerald
                    : context.textSecondary,
                title: _whisperReady
                    ? 'Speech model downloaded'
                    : 'Speech model not downloaded (about 150 MB)',
              ),
            ],
          ],
          if (_activity != null) ...[
            const SizedBox(height: 12),
            Text(
              _progress == null
                  ? '$_activity…'
                  : '$_activity · ${(_progress! * 100).round()}%',
              style: TextStyle(color: context.textPrimary),
            ),
            const SizedBox(height: 6),
            LinearProgressIndicator(value: _progress),
          ],
          if (_message != null) ...[
            const SizedBox(height: 12),
            Text(
              _message!,
              style: TextStyle(
                color: _messageIsError
                    ? AppTheme.accentRose
                    : context.textPrimary,
                fontSize: AppTypography.bodySmall,
                height: 1.35,
              ),
            ),
          ],
          if (supported) ...[
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (!modelsReady)
                  ElevatedButton.icon(
                    onPressed: _busy ? null : _downloadModels,
                    icon: const Icon(Icons.download),
                    label: const Text('Download models'),
                  ),
                OutlinedButton.icon(
                  onPressed: _busy || !_gemmaReady ? null : _selfTest,
                  icon: const Icon(Icons.play_circle_outline),
                  label: const Text('Test on this phone'),
                ),
                if (_busy)
                  TextButton(
                    onPressed: () => _cancelToken?.cancel('Cancelled.'),
                    child: const Text('Cancel'),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _statusRow({
    required IconData icon,
    required Color color,
    required String title,
    String detail = '',
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, color: color, size: 22),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  color: context.textPrimary,
                ),
              ),
              if (detail.isNotEmpty)
                Text(
                  detail,
                  style: TextStyle(
                    color: context.textSecondary,
                    fontSize: AppTypography.caption,
                    height: 1.3,
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}
