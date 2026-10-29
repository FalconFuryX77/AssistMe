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
    super.key,
    required this.disclaimerText,
    required this.onAccept,
    required this.onDecline,
  });

  @override
  Widget build(BuildContext context) {
    Theme.of(context); // Rebuild legacy color-token widgets when the app theme changes.
    final maxHeight = MediaQuery.sizeOf(context).height * 0.86;
    return Dialog(
      insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 20),
      backgroundColor: AppTheme.bgSecondary,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: 480, maxHeight: maxHeight),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: LayoutBuilder(
            builder: (context, constraints) => Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.warning_amber_rounded,
                      color: AppTheme.accentRose,
                      size: 28,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Control Requested',
                        style: TextStyle(
                          color: AppTheme.accentRose,
                          fontSize: AppTypography.bodyLarge,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  'The helper wants more than just drawing. Read the risks carefully.',
                  style: TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: AppTypography.caption,
                  ),
                ),
                const SizedBox(height: 12),
                Flexible(
                  fit: FlexFit.loose,
                  child: SingleChildScrollView(
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: AppTheme.bgPrimary,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: AppTheme.borderGlass),
                      ),
                      child: Text(
                        disclaimerText,
                        style: TextStyle(
                          color: AppTheme.textPrimary,
                          fontSize: AppTypography.caption,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                if (constraints.maxWidth < 360) ...[
                  OutlinedButton(
                    onPressed: onDecline,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppTheme.textSecondary,
                    ),
                    child: const Text('Decline'),
                  ),
                  const SizedBox(height: 8),
                  ElevatedButton(
                    onPressed: onAccept,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.accentEmerald,
                    ),
                    child: const Text('I Accept the Risks'),
                  ),
                ] else
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
        ),
      ),
    );
  }
}
