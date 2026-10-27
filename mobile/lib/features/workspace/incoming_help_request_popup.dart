/// Incoming assistance request popup shown on the helper's device.
///
/// The helpee tapped "request help" — the helper can accept (grants overlay
/// drawing only) or deny.
library;

import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';

class IncomingHelpRequestPopup extends StatelessWidget {
  final String helperDeviceFingerprint;
  final VoidCallback onAccept;
  final VoidCallback onDeny;

  const IncomingHelpRequestPopup({
    super.key,
    required this.helperDeviceFingerprint,
    required this.onAccept,
    required this.onDeny,
  });

  @override
  Widget build(BuildContext context) {
    Theme.of(context); // Rebuild legacy color-token widgets when the app theme changes.
    return Dialog(
      backgroundColor: AppTheme.bgSecondary,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Icon(
              Icons.support_agent,
              color: AppTheme.accentPrimary,
              size: 40,
            ),
            const SizedBox(height: 10),
              Text(
              'Assistance Request',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: AppTheme.textPrimary,
                fontSize: 18,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 6),
              Text(
              'A trusted user needs your help. Accepting lets you draw on an '
              'overlay above their screen. More control requires their consent.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: onDeny,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppTheme.textSecondary,
                    ),
                    child: const Text('Deny'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton(
                    onPressed: onAccept,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.accentEmerald,
                    ),
                    child: const Text('Accept'),
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
