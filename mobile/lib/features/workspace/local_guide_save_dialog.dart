import 'package:flutter/material.dart';

import '../../core/guides/session_keyframe_manager.dart';
import '../../theme/app_theme.dart';

class LocalGuideSaveInput {
  final String title;
  final String transcript;
  final Set<String> includedFrameIds;

  const LocalGuideSaveInput({
    required this.title,
    required this.transcript,
    required this.includedFrameIds,
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

  @override
  void dispose() {
    _title.dispose();
    _transcript.dispose();
    super.dispose();
  }

  Future<void> _showFullImage(CapturedKeyframe frame) => showDialog<void>(
    context: context,
    builder: (context) => Dialog(
      child: InteractiveViewer(
        child: Image.memory(frame.imageBytes, fit: BoxFit.contain),
      ),
    ),
  );

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
              'The guide and notes will be encrypted and saved on this device. Nothing is uploaded. Screenshots are currently unredacted: inspect each one and deselect any that show sensitive information.',
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
                    'Type or paste key points; call audio is not transcribed yet.',
              ),
              onChanged: (_) => setState(() {}),
            ),
            if (widget.frames.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'Review screenshots · ${_includedFrameIds.length} of ${widget.frames.length} selected',
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
                        frame.instruction,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      secondary: GestureDetector(
                        onTap: () => _showFullImage(frame),
                        child: Image.memory(
                          frame.imageBytes,
                          width: 72,
                          height: 56,
                          fit: BoxFit.cover,
                        ),
                      ),
                    );
                  },
                ),
              ),
            ],
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Discard'),
      ),
      ElevatedButton(
        onPressed:
            _title.text.trim().isEmpty ||
                (_includedFrameIds.isEmpty && _transcript.text.trim().isEmpty)
            ? null
            : () => Navigator.pop(
                context,
                LocalGuideSaveInput(
                  title: _title.text.trim(),
                  transcript: _transcript.text.trim(),
                  includedFrameIds: Set.unmodifiable(_includedFrameIds),
                ),
              ),
        child: const Text('Save on this device'),
      ),
    ],
  );
}
