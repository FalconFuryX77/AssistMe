/// Risk disclaimer modal shown to the helpee before any control is granted.
///
/// This is the security gate: the helper can draw on an overlay by default,
/// but interactive control (tap/drag) requires the helpee to read and accept
/// the stated risks explicitly.
library;

import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';

class RiskDisclaimerModal extends StatelessWidget {
  final String disclaimerText;
  final VoidCallback onAccept;
  final VoidCallback onDecline;

  const RiskDisclaimerModal({
    Key? key,
    required this.disclaimerText,
    required this.onAccept,
    required this.onDecline,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AppTheme.bgSecondary,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.warning_amber_rounded, color: AppTheme.accentRose, size: 28),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Control Requested',
                    style: TextStyle(
                      color: AppTheme.accentRose,
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            const Text(
              'The helper wants more than just drawing. Read the risks carefully.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: AppTheme.bgPrimary,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: AppTheme.borderGlass),
              ),
              child: Text(
                disclaimerText,
                style: const TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 13,
                  height: 1.4,
                ),
              ),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: onDecline,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppTheme.textSecondary,
                    ),
                    child: const Text('Decline'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton(
                    onPressed: onAccept,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.accentEmerald,
                    ),
                    child: const Text('I Accept the Risks'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}