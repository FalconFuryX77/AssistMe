import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../../theme/app_theme.dart';
import '../network/api_client.dart';
import '../security/secure_storage_service.dart';
import 'app_config.dart';

/// Interactive modal dialog allowing users to inspect, test, and update
/// the backend server URL at runtime.
class ServerConfigDialog extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;
  final VoidCallback? onUrlChanged;

  const ServerConfigDialog({
    super.key,
    required this.apiClient,
    required this.secureStorage,
    this.onUrlChanged,
  });

  static Future<bool?> show(
    BuildContext context, {
    required ApiClient apiClient,
    required SecureStorageService secureStorage,
    VoidCallback? onUrlChanged,
  }) {
    return showDialog<bool>(
      context: context,
      builder: (ctx) => ServerConfigDialog(
        apiClient: apiClient,
        secureStorage: secureStorage,
        onUrlChanged: onUrlChanged,
      ),
    );
  }

  @override
  State<ServerConfigDialog> createState() => _ServerConfigDialogState();
}

class _ServerConfigDialogState extends State<ServerConfigDialog> {
  late final TextEditingController _controller;
  bool _testing = false;
  String? _testResult;
  bool _testSuccess = false;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: AppConfig.baseUrl);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _testConnection() async {
    final raw = _controller.text.trim();
    if (raw.isEmpty) {
      setState(() {
        _testResult = 'Please enter a server URL';
        _testSuccess = false;
      });
      return;
    }

    String url;
    try {
      url = AppConfig.normalize(raw);
    } catch (e) {
      setState(() {
        _testResult = 'Invalid URL format ($e)';
        _testSuccess = false;
      });
      return;
    }

    setState(() {
      _testing = true;
      _testResult = null;
    });

    try {
      final healthUri = Uri.parse('$url/health');
      final resp = await http.get(healthUri).timeout(const Duration(seconds: 4));
      if (resp.statusCode == 200) {
        setState(() {
          _testSuccess = true;
          _testResult = 'Connected! Server is healthy (200 OK)';
        });
      } else {
        setState(() {
          _testSuccess = false;
          _testResult = 'Server returned HTTP ${resp.statusCode}';
        });
      }
    } catch (e) {
      setState(() {
        _testSuccess = false;
        _testResult = 'Could not reach server: $e';
      });
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  Future<void> _saveAndApply() async {
    final raw = _controller.text.trim();
    if (raw.isEmpty) return;

    try {
      final normalized = AppConfig.normalize(raw);
      await widget.secureStorage.saveServerUrl(normalized);
      AppConfig.setBaseUrl(normalized);
      widget.apiClient.updateBaseUrl(normalized);

      widget.onUrlChanged?.call();
      if (mounted) {
        Navigator.of(context).pop(true);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Backend updated to: $normalized'),
            backgroundColor: AppTheme.accentEmerald,
          ),
        );
      }
    } catch (e) {
      setState(() {
        _testResult = 'Invalid URL: $e';
        _testSuccess = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    Theme.of(context); // Rebuild legacy color-token widgets when the app theme changes.
    return AlertDialog(
      backgroundColor: AppTheme.bgSecondary,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      title: Row(
        children: [
          Icon(Icons.dns_outlined, color: AppTheme.accentPrimary, size: 26),
          SizedBox(width: 10),
          Text(
            'Server Connection',
            style: TextStyle(
              color: AppTheme.textPrimary,
              fontSize: 20,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
              Text(
              'Set the backend address used by this device.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              style: TextStyle(color: AppTheme.textPrimary, fontSize: 15),
              decoration: InputDecoration(
                labelText: 'Server URL',
                hintText: 'http://192.168.1.39:8000',
                prefixIcon: Icon(Icons.link, color: AppTheme.textMuted),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.clear, size: 18),
                  onPressed: () => _controller.clear(),
                ),
              ),
              keyboardType: TextInputType.url,
            ),
            const SizedBox(height: 12),
              Text(
              'Quick Presets:',
              style: TextStyle(color: AppTheme.textMuted, fontSize: 12, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                ActionChip(
                  label: const Text('Wi-Fi (192.168.1.39)', style: TextStyle(fontSize: 12)),
                  onPressed: () {
                    setState(() {
                      _controller.text = 'http://192.168.1.39:8000';
                      _testResult = null;
                    });
                  },
                ),
                ActionChip(
                  label: const Text('USB (localhost)', style: TextStyle(fontSize: 12)),
                  onPressed: () {
                    setState(() {
                      _controller.text = 'http://127.0.0.1:8000';
                      _testResult = null;
                    });
                  },
                ),
              ],
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              icon: _testing
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: AppTheme.accentPrimary),
                    )
                  : const Icon(Icons.network_check, size: 18),
              label: Text(_testing ? 'Testing connection...' : 'Test Connection'),
              onPressed: _testing ? null : _testConnection,
            ),
            if (_testResult != null) ...[
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: (_testSuccess ? AppTheme.accentEmerald : AppTheme.accentRose).withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: (_testSuccess ? AppTheme.accentEmerald : AppTheme.accentRose).withValues(alpha: 0.4),
                  ),
                ),
                child: Text(
                  _testResult!,
                  style: TextStyle(
                    color: _testSuccess ? AppTheme.accentEmerald : AppTheme.accentRose,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _saveAndApply,
          child: const Text('Save & Connect'),
        ),
      ],
    );
  }
}
