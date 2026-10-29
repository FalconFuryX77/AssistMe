import 'package:flutter/material.dart';

/// Asks the helper for a captured step's name and instruction.
///
/// The dialog owns its text controllers and disposes them when its route is
/// actually removed. Disposing them right after `showDialog` returns crashes
/// in debug builds ("'_dependents.isEmpty' is not true"), because the fields
/// are still on screen while the dialog animates closed.
class GuideStepDetailsDialog extends StatefulWidget {
  final int stepNumber;

  const GuideStepDetailsDialog({super.key, required this.stepNumber});

  /// Returns `{'title': …, 'instruction': …}`, or null when cancelled.
  static Future<Map<String, String>?> show(
    BuildContext context, {
    required int stepNumber,
  }) => showDialog<Map<String, String>>(
    context: context,
    builder: (_) => GuideStepDetailsDialog(stepNumber: stepNumber),
  );

  @override
  State<GuideStepDetailsDialog> createState() => _GuideStepDetailsDialogState();
}

class _GuideStepDetailsDialogState extends State<GuideStepDetailsDialog> {
  late final TextEditingController _title = TextEditingController(
    text: 'Step ${widget.stepNumber}',
  );
  final TextEditingController _instruction = TextEditingController();

  @override
  void dispose() {
    _title.dispose();
    _instruction.dispose();
    super.dispose();
  }

  void _submit() {
    final title = _title.text.trim();
    final instruction = _instruction.text.trim();
    if (title.isEmpty || instruction.isEmpty) return;
    Navigator.pop(context, {'title': title, 'instruction': instruction});
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Write this guide step'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _title,
              autofocus: true,
              maxLength: 100,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'Step name',
                hintText: 'For example, Open account settings',
              ),
            ),
            TextField(
              controller: _instruction,
              maxLength: 4000,
              minLines: 2,
              maxLines: 4,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'What should the user do?',
                hintText: 'For example, Tap "Wi-Fi", then tap "Saved networks"',
                // Clicky points at quoted labels when the guide is replayed.
                helperText:
                    'Put button names in quotes so Clicky can point at them.',
                helperMaxLines: 2,
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Add step')),
      ],
    );
  }
}
