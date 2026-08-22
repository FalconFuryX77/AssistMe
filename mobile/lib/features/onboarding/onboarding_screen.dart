/// First-launch onboarding — the only time identity is ever visible.
///
/// One screen, one field: "What should we call you?" Behind the scenes the app
/// registers this install as an identity (no email/password) and shows the
/// recovery code exactly once. Every future launch lands straight on Home.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/config/app_config.dart';
import '../../core/network/api_client.dart';
import '../../core/security/device_identity.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';

class OnboardingScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;

  const OnboardingScreen({
    Key? key,
    required this.apiClient,
    required this.secureStorage,
  }) : super(key: key);

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
      setState(() => _error = 'Please enter a name first');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      final fingerprint = await DeviceIdentity.getFingerprint(widget.secureStorage);
      final resp = await widget.apiClient.deviceBootstrap(
        deviceFingerprint: fingerprint,
        displayName: name,
      );
      if (resp.statusCode != 201) {
        setState(() {
          _busy = false;
          _error = 'Could not set up (${resp.statusCode}). Check the server '
              'address in Settings.';
        });
        return;
      }

      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      await widget.secureStorage.saveTokens(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
      );
      await widget.secureStorage.saveDisplayName(name);

      if (!mounted) return;

      final recoveryCode = data['recovery_code'] as String?;
      if (recoveryCode == null || recoveryCode.isEmpty) {
        // Re-install over same fingerprint or re-onboard: go straight home.
        Navigator.of(context).pushReplacementNamed('/home');
        return;
      }

      // Show the recovery code exactly once.
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          backgroundColor: AppTheme.bgSecondary,
          title: const Text('Write this down'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'This is your recovery code. If you ever lose your phone or '
                'reinstall the app, entering this code brings back all your '
                'trusted people.',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
              ),
              const SizedBox(height: 20),
              Container(
                padding: const EdgeInsets.symmetric(vertical: 18),
                decoration: BoxDecoration(
                  color: AppTheme.bgPrimary,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppTheme.accentPrimary, width: 2),
                ),
                child: Text(
                  recoveryCode,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 26,
                    letterSpacing: 4,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.accentSecondary,
                  ),
                ),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: recoveryCode));
                  ScaffoldMessenger.of(ctx).showSnackBar(
                    const SnackBar(content: Text('Copied to clipboard')),
                  );
                },
                icon: const Icon(Icons.copy, size: 16),
                label: const Text('Copy'),
              ),
            ],
          ),
          actions: [
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('I wrote it down'),
            ),
          ],
        ),
      );

      if (mounted) Navigator.of(context).pushReplacementNamed('/home');
    } catch (e) {
      setState(() {
        _busy = false;
        _error = 'Network error: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.bgPrimary,
      appBar: AppBar(
        title: const Text('Welcome'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            tooltip: 'Server address',
            onPressed: _openServerSettings,
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 32),
              Icon(Icons.volunteer_activism,
                  size: 72, color: AppTheme.accentEmerald),
              const SizedBox(height: 24),
              const Text(
                'Welcome to AssistMe',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 10),
              const Text(
                'Get help from people you trust — or be there for them. '
                'One tap, no passwords.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 15),
              ),
              const SizedBox(height: 40),
              TextField(
                controller: _nameController,
                textCapitalization: TextCapitalization.words,
                maxLength: 60,
                style: const TextStyle(color: AppTheme.textPrimary, fontSize: 20),
                decoration: const InputDecoration(
                  labelText: 'What should we call you?',
                  hintText: 'e.g. Grandma, Dad, Alex',
                  counterText: '',
                ),
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 14),
                  child: Text(_error!,
                      style:
                          const TextStyle(color: AppTheme.accentRose, fontSize: 13)),
                ),
              const SizedBox(height: 24),
              SizedBox(
                height: 58,
                child: ElevatedButton.icon(
                  onPressed: _busy ? null : _start,
                  icon: _busy
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white))
                      : const Icon(Icons.arrow_forward),
                  label: Text(_busy ? 'Setting up…' : 'Get started',
                      style: const TextStyle(fontSize: 18)),
                ),
              ),
              const SizedBox(height: 16),
              Text(
                'Connected to ${AppConfig.baseUrl}',
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppTheme.textMuted, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// Same server-address dialog pattern as before: quick, saved locally.
  Future<void> _openServerSettings() async {
    final controller = TextEditingController(text: AppConfig.baseUrl);
    final url = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Server address'),
        content: TextField(
          controller: controller,
          style: const TextStyle(color: AppTheme.textPrimary),
          decoration: const InputDecoration(
            labelText: 'https:// or http:// address',
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          ElevatedButton(
            onPressed: () {
              var v = controller.text.trim();
              if (v.isNotEmpty && !v.startsWith('http')) v = 'http://$v';
              Navigator.pop(ctx, v);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (url == null || url.isEmpty) return;
    AppConfig.baseUrl = url;
    await widget.secureStorage.saveServerUrl(url);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Server set to $url')),
      );
    }
  }
}
