import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/config/app_config.dart';
import '../../core/network/api_client.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';

class ServerConfigScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;

  const ServerConfigScreen({
    Key? key,
    required this.apiClient,
    required this.secureStorage,
  }) : super(key: key);

  @override
  State<ServerConfigScreen> createState() => _ServerConfigScreenState();
}

class _ServerConfigScreenState extends State<ServerConfigScreen> {
  final _controller = TextEditingController();
  String? _error;
  bool _saving = false;
  bool _testing = false;

  @override
  void initState() {
    super.initState();
    _controller.text = AppConfig.baseUrl;
  }

  Future<void> _save() async {
    final raw = _controller.text.trim();
    if (raw.isEmpty) {
      setState(() => _error = 'Enter your server URL (e.g. http://192.168.1.39:8000)');
      return;
    }
    String normalized;
    try {
      normalized = AppConfig.normalizeUrl(raw);
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst('FormatException: ', ''));
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
      _testing = true;
    });
    // Optionally test reachability — never block saving if server is temporarily offline.
    try {
      widget.apiClient.updateBaseUrl(normalized);
      // Lightweight probe — ignore body, just check TCP.
      // Use a short timeout so LAN mis-config doesn't hang UI.
      await widget.apiClient
          .get('/health', requireAuth: false)
          .timeout(const Duration(seconds: 4));
    } catch (_) {
      // Keep normalized URL even if probe fails; server might be waking up.
    } finally {
      if (mounted) setState(() => _testing = false);
    }
    try {
      AppConfig.baseUrl = normalized;
      widget.apiClient.updateBaseUrl(normalized);
      await widget.secureStorage.saveServerUrl(normalized);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Saved $normalized')),
      );
      Navigator.of(context).pop(normalized);
    } catch (e) {
      setState(() => _error = 'Could not save: $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.bgPrimary,
      appBar: AppBar(title: const Text('Server settings')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Icon(Icons.dns, size: 56, color: AppTheme.accentPrimary),
              const SizedBox(height: 16),
              const Text(
                'Where is your AssistMe server?',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: AppTheme.textPrimary),
              ),
              const SizedBox(height: 10),
              const Text(
                'For local testing use your LAN address (e.g. http://192.168.1.39:8000). '
                'For production use https://your.domain. You can change this anytime in Settings. '
                'If you installed the release APK without a built-in server URL, you must set it here before anything will load.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 13, height: 1.5),
              ),
              const SizedBox(height: 24),
              TextField(
                controller: _controller,
                keyboardType: TextInputType.url,
                autocorrect: false,
                style: const TextStyle(color: AppTheme.textPrimary),
                decoration: const InputDecoration(
                  labelText: 'Server URL',
                  hintText: 'http://192.168.1.39:8000',
                  prefixIcon: Icon(Icons.link),
                ),
                onSubmitted: (_) => _save(),
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppTheme.accentRose.withOpacity(0.12),
                      border: Border.all(color: AppTheme.accentRose),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(_error!, style: const TextStyle(color: AppTheme.accentRose, fontSize: 13)),
                  ),
                ),
              const SizedBox(height: 18),
              if (!AppConfig.isConfigured)
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppTheme.accentAmber.withOpacity(0.12),
                    border: Border.all(color: AppTheme.accentAmber),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Row(
                    children: [
                      Icon(Icons.warning_amber, color: AppTheme.accentAmber, size: 20),
                      SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'No server configured — Trusted People, Help calls, and onboarding will fail until you save a URL.',
                          style: TextStyle(color: AppTheme.accentAmber, fontSize: 12),
                        ),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 18),
              SizedBox(
                height: 54,
                child: ElevatedButton.icon(
                  onPressed: _saving ? null : _save,
                  icon: _saving
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Icon(Icons.save),
                  label: Text(_saving ? (_testing ? 'Testing…' : 'Saving…') : 'Save'),
                ),
              ),
              const SizedBox(height: 12),
              Text(
                'Current: ${AppConfig.isConfigured ? AppConfig.baseUrl : '(not set)'}',
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppTheme.textMuted, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }
}
