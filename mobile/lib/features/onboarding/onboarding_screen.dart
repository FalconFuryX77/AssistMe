/// First-launch onboarding — the only time identity is ever visible.
///
/// One screen, one field: "What should we call you?" Behind the scenes the app
/// registers this install as an identity (no email/password) and shows the
/// recovery code exactly once. Every future launch lands straight on Home.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../core/config/server_config_dialog.dart';
import '../../core/network/api_client.dart';
import '../../core/security/device_identity.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';

class OnboardingScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;

  const OnboardingScreen({
    super.key,
    required this.apiClient,
    required this.secureStorage,
  });

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _nameController = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _start() async {
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Please enter your name');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      final fingerprint = await DeviceIdentity.getFingerprint(widget.secureStorage);
      final existingSecret = await widget.secureStorage.getDeviceSecret();
      final resp = await widget.apiClient.deviceBootstrap(
        deviceFingerprint: fingerprint,
        displayName: name,
        deviceSecret: existingSecret,
      );
      if (resp.statusCode != 201) {
        String errorMsg = 'Could not set up (${resp.statusCode}). Please try again.';
        try {
          final decoded = jsonDecode(resp.body);
          if (decoded is Map && decoded['detail'] != null) {
            errorMsg = decoded['detail'].toString();
          }
        } catch (_) {}
        setState(() {
          _busy = false;
          _error = errorMsg;
        });
        return;
      }

      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      await widget.secureStorage.saveTokens(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
      );
      final returnedSecret = data['device_secret'] as String?;
      if (returnedSecret != null && returnedSecret.isNotEmpty) {
        await widget.secureStorage.saveDeviceSecret(returnedSecret);
      }
      await widget.secureStorage.saveDisplayName(name);

      if (!mounted) return;

      final recoveryCode = data['recovery_code'] as String?;
      if (recoveryCode == null || recoveryCode.isEmpty) {
        // Existing account re-login: go straight to home
        Navigator.of(context).pushReplacementNamed('/home');
        await Permission.microphone.request();
        return;
      }

      // Show the recovery code once
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          backgroundColor: AppTheme.bgSecondary,
          title: const Row(
            children: [
              Icon(Icons.key, color: AppTheme.accentAmber, size: 28),
              SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Your Recovery Code',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                ),
              ),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Save this code in a safe place. If you get a new phone, this code restores your name and all your trusted helpers.',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 15, height: 1.4),
              ),
              const SizedBox(height: 20),
              Container(
                padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
                decoration: BoxDecoration(
                  color: AppTheme.bgPrimary,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: AppTheme.accentEmerald, width: 2),
                ),
                child: Text(
                  recoveryCode,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 28,
                    letterSpacing: 4,
                    fontWeight: FontWeight.w900,
                    color: AppTheme.accentEmerald,
                  ),
                ),
              ),
              const SizedBox(height: 14),
              OutlinedButton.icon(
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: recoveryCode));
                  ScaffoldMessenger.of(ctx).showSnackBar(
                    const SnackBar(
                      content: Text('Recovery code copied to clipboard'),
                      backgroundColor: AppTheme.accentEmerald,
                    ),
                  );
                },
                icon: const Icon(Icons.copy, size: 18),
                label: const Text('Copy to clipboard', style: TextStyle(fontSize: 16)),
              ),
            ],
          ),
          actionsPadding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          actions: [
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('I saved my code'),
              ),
            ),
          ],
        ),
      );

      if (mounted) Navigator.of(context).pushReplacementNamed('/home');
      await Permission.microphone.request();
    } catch (e) {
      setState(() {
        _busy = false;
        _error = 'Connection error: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.bgPrimary,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          IconButton(
            tooltip: 'Server Connection',
            icon: const Icon(Icons.dns_outlined, color: AppTheme.accentPrimary),
            onPressed: () {
              ServerConfigDialog.show(
                context,
                apiClient: widget.apiClient,
                secureStorage: widget.secureStorage,
              );
            },
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  width: 96,
                  height: 96,
                  decoration: BoxDecoration(
                    color: AppTheme.accentEmerald.withValues(alpha: 0.15),
                    shape: BoxShape.circle,
                    border: Border.all(color: AppTheme.accentEmerald.withValues(alpha: 0.4), width: 2),
                  ),
                  child: const Center(
                    child: Icon(
                      Icons.volunteer_activism,
                      size: 52,
                      color: AppTheme.accentEmerald,
                    ),
                  ),
                ),
                const SizedBox(height: 28),
                const Text(
                  'Welcome to AssistMe',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 30,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -0.5,
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'One-tap remote help from family and trusted people. No passwords to remember.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: 17,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 36),
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: AppTheme.bgSecondary,
                    borderRadius: BorderRadius.circular(24),
                    border: Border.all(color: AppTheme.borderGlass),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        'What should we call you?',
                        style: TextStyle(
                          color: AppTheme.textPrimary,
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _nameController,
                        textCapitalization: TextCapitalization.words,
                        maxLength: 50,
                        style: const TextStyle(
                          color: AppTheme.textPrimary,
                          fontSize: 22,
                          fontWeight: FontWeight.w600,
                        ),
                        decoration: const InputDecoration(
                          hintText: 'e.g. Grandma, Dad, Alex',
                          counterText: '',
                          prefixIcon: Icon(Icons.person, color: AppTheme.accentEmerald),
                        ),
                        onSubmitted: (_) => _start(),
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 14),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: AppTheme.accentRose.withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(color: AppTheme.accentRose.withValues(alpha: 0.5)),
                          ),
                          child: Row(
                            children: [
                              const Icon(Icons.error_outline, color: AppTheme.accentRose, size: 20),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  _error!,
                                  style: const TextStyle(color: AppTheme.accentRose, fontSize: 14),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                      const SizedBox(height: 24),
                      SizedBox(
                        height: 60,
                        child: ElevatedButton.icon(
                          onPressed: _busy ? null : _start,
                          icon: _busy
                              ? const SizedBox(
                                  width: 22,
                                  height: 22,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2.5,
                                    color: Colors.white,
                                  ),
                                )
                              : const Icon(Icons.arrow_forward, size: 22),
                          label: Text(
                            _busy ? 'Setting up…' : 'Get Started',
                            style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                Center(
                  child: TextButton.icon(
                    onPressed: _busy ? null : _reclaimWithCode,
                    icon: const Icon(Icons.restore, size: 18),
                    label: const Text(
                      'Reinstalling? Restore with recovery code',
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Reinstall path: enter the recovery code from the old install to
  /// reclaim that identity — trusted people come straight back.
  Future<void> _reclaimWithCode() async {
    final controller = TextEditingController();
    final code = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Row(
          children: [
            Icon(Icons.restore, color: AppTheme.accentSecondary, size: 26),
            SizedBox(width: 10),
            Text('Enter Recovery Code', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Type the 12-character code you saved. This will restore your name and all your trusted contacts.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 15),
            ),
            const SizedBox(height: 18),
            TextField(
              controller: controller,
              autofocus: true,
              textCapitalization: TextCapitalization.characters,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AppTheme.textPrimary,
                fontSize: 22,
                letterSpacing: 3,
                fontWeight: FontWeight.w800,
              ),
              decoration: const InputDecoration(
                hintText: 'ABCD-EFGH-1234',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('Restore'),
          ),
        ],
      ),
    );
    if (code == null || code.isEmpty || !mounted) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final fingerprint = await DeviceIdentity.getFingerprint(widget.secureStorage);
      final resp = await widget.apiClient.reclaimIdentity(
        deviceFingerprint: fingerprint,
        recoveryCode: code,
      );
      if (resp.statusCode != 200) {
        String detail = 'Could not restore account';
        try {
          final decoded = jsonDecode(resp.body);
          if (decoded is Map && decoded['detail'] != null) {
            detail = decoded['detail'].toString();
          }
        } catch (_) {}
        setState(() {
          _busy = false;
          _error = detail;
        });
        return;
      }
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      await widget.secureStorage.saveTokens(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
      );
      final returnedSecret = data['device_secret'] as String?;
      if (returnedSecret != null && returnedSecret.isNotEmpty) {
        await widget.secureStorage.saveDeviceSecret(returnedSecret);
      }
      final name = (data['display_name'] as String?) ?? '';
      if (name.isNotEmpty) await widget.secureStorage.saveDisplayName(name);
      if (mounted) Navigator.of(context).pushReplacementNamed('/home');
    } catch (e) {
      setState(() {
        _busy = false;
        _error = 'Connection error: $e';
      });
    }
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }
}
