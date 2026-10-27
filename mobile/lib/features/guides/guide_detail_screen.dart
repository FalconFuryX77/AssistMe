/// Full-screen, high-contrast step-by-step guide viewer for elderly & non-technical users.
library;

import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';

import '../../core/guides/guide_models.dart';
import '../../core/guides/local_guide_store.dart';
import '../../theme/app_theme.dart';

class GuideDetailScreen extends StatefulWidget {
  final SessionGuideItem guide;
  final LocalGuideStore guideStore;

  const GuideDetailScreen({
    super.key,
    required this.guide,
    required this.guideStore,
  });

  @override
  State<GuideDetailScreen> createState() => _GuideDetailScreenState();
}

class _GuideDetailScreenState extends State<GuideDetailScreen> {
  int _currentStepIndex = 0;
  bool _speaking = false;

  List<GuideStepItem> get _steps => widget.guide.steps;
  GuideStepItem get _currentStep => _steps.isNotEmpty
      ? _steps[_currentStepIndex]
      : GuideStepItem(
          id: '',
          stepNumber: 1,
          title: 'Overview',
          instruction: widget.guide.summary,
          createdAt: DateTime.now(),
        );

  void _nextStep() {
    if (_currentStepIndex < _steps.length - 1) {
      setState(() {
        _currentStepIndex++;
        _speaking = false;
      });
    }
  }

  void _prevStep() {
    if (_currentStepIndex > 0) {
      setState(() {
        _currentStepIndex--;
        _speaking = false;
      });
    }
  }

  void _toggleSpeak() {
    setState(() => _speaking = !_speaking);
  }

  Widget _buildStepImage(String? imageUrl, String? localImagePath) {
    if (localImagePath != null) {
      return FutureBuilder<Uint8List?>(
        future: widget.guideStore.readImage(localImagePath),
        builder: (context, snapshot) {
          final bytes = snapshot.data;
          if (snapshot.hasError ||
              (snapshot.connectionState == ConnectionState.done &&
                  bytes == null)) {
            return _imagePlaceholder(
              Icons.broken_image,
              'Saved screenshot unavailable',
            );
          }
          if (bytes == null) {
            return const SizedBox(
              height: 220,
              child: Center(
                child: CircularProgressIndicator(color: AppTheme.accentEmerald),
              ),
            );
          }
          return _imageFrame(
            Image.memory(bytes, fit: BoxFit.contain, width: double.infinity),
          );
        },
      );
    }
    if (imageUrl == null || imageUrl.isEmpty) {
      return _imagePlaceholder(
        Icons.touch_app,
        'Follow the step on your device',
      );
    }

    Uint8List? imageBytes;
    if (imageUrl.startsWith('data:image')) {
      try {
        final commaIdx = imageUrl.indexOf(',');
        if (commaIdx != -1) {
          imageBytes = base64Decode(imageUrl.substring(commaIdx + 1));
        }
      } catch (_) {}
    }

    return _imageFrame(
      imageBytes != null
          ? Image.memory(
              imageBytes,
              fit: BoxFit.contain,
              width: double.infinity,
            )
          : Image.network(
              imageUrl,
              fit: BoxFit.contain,
              errorBuilder: (context, error, stackTrace) =>  Icon(
                Icons.broken_image,
                size: 48,
                color: AppTheme.textMuted,
              ),
            ),
    );
  }

  Widget _imagePlaceholder(IconData icon, String message) => Container(
    height: 220,
    decoration: BoxDecoration(
      color: AppTheme.bgSecondary,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: AppTheme.borderGlass),
    ),
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 48, color: AppTheme.accentEmerald),
          const SizedBox(height: 8),
          Text(
            message,
            style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
          ),
        ],
      ),
    ),
  );

  Widget _imageFrame(Widget child) => ClipRRect(
    borderRadius: BorderRadius.circular(16),
    child: Container(
      constraints: const BoxConstraints(maxHeight: 380),
      decoration: BoxDecoration(
        color: Colors.black,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: AppTheme.accentEmerald.withValues(alpha: 0.3),
          width: 1.5,
        ),
      ),
      child: child,
    ),
  );

  @override
  Widget build(BuildContext context) {
    Theme.of(context); // Rebuild legacy color-token widgets when the app theme changes.
    final totalSteps = _steps.length;
    final progress = totalSteps > 0
        ? (_currentStepIndex + 1) / totalSteps
        : 1.0;

    return Scaffold(
      backgroundColor: AppTheme.bgPrimary,
      appBar: AppBar(
        backgroundColor: AppTheme.bgSecondary,
        elevation: 0,
        title: Text(
          widget.guide.title,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: SafeArea(
        child: Column(
          children: [
            // Progress Header
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              color: AppTheme.bgSecondary,
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Step ${_currentStepIndex + 1} of $totalSteps',
                        style: const TextStyle(
                          color: AppTheme.accentEmerald,
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      IconButton(
                        tooltip: _speaking
                            ? 'Stop listening'
                            : 'Listen to step instructions',
                        icon: Icon(
                          _speaking
                              ? Icons.volume_up
                              : Icons.volume_up_outlined,
                          color: _speaking
                              ? AppTheme.accentEmerald
                              : AppTheme.textSecondary,
                          size: 28,
                        ),
                        onPressed: _toggleSpeak,
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: LinearProgressIndicator(
                      value: progress,
                      backgroundColor: AppTheme.borderGlass,
                      valueColor: const AlwaysStoppedAnimation<Color>(
                        AppTheme.accentEmerald,
                      ),
                      minHeight: 6,
                    ),
                  ),
                ],
              ),
            ),

            // Read-aloud accessible audio prompt banner
            if (_speaking)
              Container(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 12,
                ),
                decoration: BoxDecoration(
                  color: AppTheme.accentEmerald.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppTheme.accentEmerald),
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.record_voice_over,
                      color: AppTheme.accentEmerald,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        _currentStep.instruction,
                        style: TextStyle(
                          color: AppTheme.textPrimary,
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

            // Scrollable Step Content
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (_currentStep.title.isNotEmpty) ...[
                      Text(
                        _currentStep.title,
                        style: TextStyle(
                          color: AppTheme.textPrimary,
                          fontSize: 22,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],

                    // Large Instruction Callout
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: AppTheme.bgSecondary,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: AppTheme.borderGlass),
                      ),
                      child: Text(
                        _currentStep.instruction,
                        style: TextStyle(
                          color: AppTheme.textPrimary,
                          fontSize: 17,
                          height: 1.45,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),

                    const SizedBox(height: 18),

                    // Visual Screenshot Frame
                    _buildStepImage(
                      _currentStep.imageUrl,
                      _currentStep.localImagePath,
                    ),
                    if (widget.guide.transcript.isNotEmpty) ...[
                      const SizedBox(height: 20),
                      ExpansionTile(
                        tilePadding: EdgeInsets.zero,
                        collapsedIconColor: AppTheme.accentEmerald,
                        iconColor: AppTheme.accentEmerald,
                        title: Text(
                          'Session transcript',
                          style: TextStyle(
                            color: AppTheme.textPrimary,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        children: [
                          Align(
                            alignment: Alignment.centerLeft,
                            child: SelectableText(
                              widget.guide.transcript,
                              style: TextStyle(
                                color: AppTheme.textSecondary,
                                height: 1.45,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),

            // Bottom Navigation Footer
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: AppTheme.bgSecondary,
                boxShadow: [
                  BoxShadow(
                    color: Colors.black26,
                    blurRadius: 8,
                    offset: Offset(0, -2),
                  ),
                ],
              ),
              child: Row(
                children: [
                  if (_currentStepIndex > 0)
                    Expanded(
                      child: OutlinedButton.icon(
                        icon: const Icon(Icons.chevron_left),
                        label: const Text(
                          'Previous',
                          style: TextStyle(fontSize: 16),
                        ),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppTheme.textPrimary,
                          side: BorderSide(color: AppTheme.borderGlassStrong),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                        onPressed: _prevStep,
                      ),
                    ),
                  if (_currentStepIndex > 0) const SizedBox(width: 12),
                  Expanded(
                    flex: 2,
                    child: ElevatedButton.icon(
                      icon: Icon(
                        _currentStepIndex == totalSteps - 1
                            ? Icons.check_circle
                            : Icons.chevron_right,
                      ),
                      label: Text(
                        _currentStepIndex == totalSteps - 1
                            ? 'Finish Guide'
                            : 'Next Step',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.accentEmeraldAccessible,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                      onPressed: () {
                        if (_currentStepIndex == totalSteps - 1) {
                          Navigator.pop(context);
                        } else {
                          _nextStep();
                        }
                      },
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
