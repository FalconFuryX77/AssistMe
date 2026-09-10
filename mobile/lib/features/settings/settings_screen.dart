import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../../core/config/app_config.dart';
import '../../core/network/api_client.dart';
import '../../core/security/secure_storage_service.dart';
import '../../main.dart';
import '../../theme/app_theme.dart';

class SettingsScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;
  final VoidCallback? onServerUrlChanged;

  const SettingsScreen({
    super.key,
    required this.apiClient,
    required this.secureStorage,
    this.onServerUrlChanged,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  // Appearance & Preferences
  late bool _darkMode;
  bool _notificationsEnabled = true;
  bool _soundVibrationEnabled = true;

  // Advanced Developer Section
  bool _advancedUnlocked = false;
  late final TextEditingController _serverUrlController;
  bool _testingConnection = false;
  String? _testResult;
  bool _testSuccess = false;

  @override
  void initState() {
    super.initState();
    _darkMode = appThemeModeNotifier.value == ThemeMode.dark;
    _serverUrlController = TextEditingController(text: AppConfig.baseUrl);
  }

  @override
  void dispose() {
    _serverUrlController.dispose();
    super.dispose();
  }

  Future<void> _testConnection() async {
    final raw = _serverUrlController.text.trim();
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
      _testingConnection = true;
      _testResult = null;
    });

    try {
      final healthUri = Uri.parse('$url/health');
      final resp = await http.get(
        healthUri,
        headers: {'ngrok-skip-browser-warning': 'true'},
      ).timeout(const Duration(seconds: 4));
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
      if (mounted) setState(() => _testingConnection = false);
    }
  }

  Future<void> _saveAndApplyServerUrl() async {
    final raw = _serverUrlController.text.trim();
    if (raw.isEmpty) return;

    try {
      final normalized = AppConfig.normalize(raw);
      await widget.secureStorage.saveServerUrl(normalized);
      AppConfig.setBaseUrl(normalized);
      widget.apiClient.updateBaseUrl(normalized);
      widget.onServerUrlChanged?.call();

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Server URL updated to: $normalized'),
            backgroundColor: AppTheme.accentEmerald,
            duration: const Duration(seconds: 3),
          ),
        );
        setState(() {
          _testResult = 'Saved and active: $normalized';
          _testSuccess = true;
        });
      }
    } catch (e) {
      setState(() {
        _testResult = 'Invalid URL: $e';
        _testSuccess = false;
      });
    }
  }

  Future<void> _resetServerUrlToDefault() async {
    final defaultUrl = AppConfig.resetToDefault();
    await widget.secureStorage.clearServerUrl();
    widget.apiClient.updateBaseUrl(defaultUrl);
    widget.onServerUrlChanged?.call();

    setState(() {
      _serverUrlController.text = defaultUrl;
      _testResult = 'Reset to default: $defaultUrl';
      _testSuccess = true;
    });

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Reset to default server: $defaultUrl'),
          backgroundColor: AppTheme.accentEmerald,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.bgPrimary,
      appBar: AppBar(
        title: Text(
          'Settings',
          style: TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w800,
            color: context.textPrimary,
          ),
        ),
        backgroundColor: context.bgSecondary,
        iconTheme: IconThemeData(color: context.textPrimary),
        elevation: 0,
      ),
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 20),
        children: [
          // Section: Appearance
          _sectionHeader('Appearance', Icons.palette_outlined),
          _card(
            child: Column(
              children: [
                SwitchListTile(
                  secondary: const Icon(Icons.dark_mode_outlined, color: AppTheme.accentPrimary),
                  title: Text(
                    'Dark Theme',
                    style: TextStyle(fontWeight: FontWeight.w700, color: context.textPrimary),
                  ),
                  subtitle: Text(
                    'Optimized for OLED displays & high contrast',
                    style: TextStyle(color: context.textSecondary, fontSize: 13),
                  ),
                  value: _darkMode,
                  activeTrackColor: AppTheme.accentPrimary.withValues(alpha: 0.5),
                  activeThumbColor: AppTheme.accentPrimary,
                  onChanged: (val) {
                    setState(() => _darkMode = val);
                    appThemeModeNotifier.value = val ? ThemeMode.dark : ThemeMode.light;
                    widget.secureStorage.saveDarkMode(val);
                  },
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),

          // Section: Notifications
          _sectionHeader('Notifications', Icons.notifications_outlined),
          _card(
            child: Column(
              children: [
                SwitchListTile(
                  secondary: const Icon(Icons.ring_volume_outlined, color: AppTheme.accentEmerald),
                  title: Text(
                    'Assistance Requests',
                    style: TextStyle(fontWeight: FontWeight.w700, color: context.textPrimary),
                  ),
                  subtitle: Text(
                    'Alert when contacts request help or call',
                    style: TextStyle(color: context.textSecondary, fontSize: 13),
                  ),
                  value: _notificationsEnabled,
                  activeTrackColor: AppTheme.accentEmerald.withValues(alpha: 0.5),
                  activeThumbColor: AppTheme.accentEmerald,
                  onChanged: (val) {
                    setState(() => _notificationsEnabled = val);
                  },
                ),
                Divider(height: 1, color: context.borderGlass),
                SwitchListTile(
                  secondary: const Icon(Icons.vibration_outlined, color: AppTheme.accentAmber),
                  title: Text(
                    'Sound & Vibration',
                    style: TextStyle(fontWeight: FontWeight.w700, color: context.textPrimary),
                  ),
                  subtitle: Text(
                    'Play chime and vibrate for incoming calls',
                    style: TextStyle(color: context.textSecondary, fontSize: 13),
                  ),
                  value: _soundVibrationEnabled,
                  activeTrackColor: AppTheme.accentAmber.withValues(alpha: 0.5),
                  activeThumbColor: AppTheme.accentAmber,
                  onChanged: (val) {
                    setState(() => _soundVibrationEnabled = val);
                  },
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),

          // Section: How-To Guide
          _sectionHeader('How-To Guide', Icons.menu_book_outlined),
          _card(
            child: Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                leading: const Icon(Icons.help_outline, color: AppTheme.accentPrimary),
                title: Text(
                  'First-Time Setup & Help Guide',
                  style: TextStyle(fontWeight: FontWeight.w700, color: context.textPrimary),
                ),
                subtitle: Text(
                  'How to pair devices and use AssistMe',
                  style: TextStyle(color: context.textSecondary, fontSize: 13),
                ),
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                    child: Column(
                      children: [
                        _guideStep(
                          step: '1',
                          title: 'Add a Contact',
                          description:
                              'Share your 6-digit code or enter your companion’s code in the Add Contact section.',
                        ),
                        const SizedBox(height: 12),
                        _guideStep(
                          step: '2',
                          title: 'Request Help (Helpee)',
                          description:
                              'Tap "Request Help" to notify your helper. When they accept, screen sharing begins immediately.',
                        ),
                        const SizedBox(height: 12),
                        _guideStep(
                          step: '3',
                          title: 'Interactive Guidance (Helper)',
                          description:
                              'Helper sees your screen live and can draw lines, circles, and pointers to show you what to tap.',
                        ),
                        const SizedBox(height: 12),
                        _guideStep(
                          step: '4',
                          title: 'Safety & Emergency Stop',
                          description:
                              'Helpee has 100% control at all times. Tapping the red Panic STOP button instantly terminates screen sharing.',
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),

          // Section: About AssistMe
          _sectionHeader('About', Icons.info_outline),
          _card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 44,
                        height: 44,
                        decoration: BoxDecoration(
                          color: AppTheme.accentPrimary.withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: const Icon(Icons.handshake_outlined, color: AppTheme.accentPrimary, size: 26),
                      ),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'AssistMe',
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                                color: context.textPrimary,
                              ),
                            ),
                            Text(
                              'Version 1.1.0 (Build 2026.09)',
                              style: TextStyle(
                                fontSize: 13,
                                color: context.textSecondary,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'One-tap remote help for family and trusted companions. Built with privacy-first WebRTC streaming and zero-lag interactive annotations.',
                    style: TextStyle(color: context.textSecondary, fontSize: 13, height: 1.4),
                  ),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                      color: AppTheme.accentEmerald.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: AppTheme.accentEmerald.withValues(alpha: 0.3)),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: const BoxDecoration(
                            color: AppTheme.accentEmerald,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Server: ${AppConfig.baseUrl}',
                            style: const TextStyle(
                              color: AppTheme.accentEmerald,
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),

          // Section: Contact Us
          _sectionHeader('Contact & Creators', Icons.people_outline),
          _card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 22,
                    backgroundColor: AppTheme.accentPrimary.withValues(alpha: 0.2),
                    child: const Text(
                      'P',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.accentPrimary,
                      ),
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Praneel (Falcon)',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: context.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          'Creator & Lead Architect',
                          style: TextStyle(
                            fontSize: 13,
                            color: context.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 2),
                        const Text(
                          'AssistMe Open-Source Project',
                          style: TextStyle(
                            fontSize: 12,
                            color: AppTheme.textMuted,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),

          // Section: Advanced Settings (Developer / Self-Hosted Backend)
          _sectionHeader('Advanced Settings', Icons.terminal_outlined),
          _card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Icon(
                        _advancedUnlocked ? Icons.lock_open_outlined : Icons.lock_outline,
                        color: _advancedUnlocked ? AppTheme.accentAmber : AppTheme.textMuted,
                        size: 22,
                      ),
                      const SizedBox(width: 10),
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Custom Backend Server',
                              style: TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w700,
                                color: AppTheme.textPrimary,
                              ),
                            ),
                            Text(
                              'For developers & self-hosted instances',
                              style: TextStyle(
                                fontSize: 12,
                                color: AppTheme.textSecondary,
                              ),
                            ),
                          ],
                        ),
                      ),
                      TextButton(
                        style: TextButton.styleFrom(
                          foregroundColor: _advancedUnlocked ? AppTheme.accentRose : AppTheme.accentPrimary,
                        ),
                        onPressed: () {
                          setState(() {
                            _advancedUnlocked = !_advancedUnlocked;
                          });
                        },
                        child: Text(_advancedUnlocked ? 'Lock' : 'Unlock'),
                      ),
                    ],
                  ),

                  if (_advancedUnlocked) ...[
                    const SizedBox(height: 14),
                    // Warning disclaimer box
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: AppTheme.accentAmber.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: AppTheme.accentAmber.withValues(alpha: 0.4),
                        ),
                      ),
                      child: const Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Icon(Icons.warning_amber_rounded, color: AppTheme.accentAmber, size: 20),
                          SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              'Caution: Modifying these settings connects AssistMe to a custom server. Incorrect settings will cause connection errors. Fresh installs always point to the default server.',
                              style: TextStyle(
                                color: AppTheme.accentAmber,
                                fontSize: 12,
                                fontWeight: FontWeight.w500,
                                height: 1.3,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _serverUrlController,
                      style: const TextStyle(color: AppTheme.textPrimary, fontSize: 14),
                      decoration: InputDecoration(
                        labelText: 'Server Base URL',
                        hintText: 'http://192.168.1.39:8000',
                        prefixIcon: const Icon(Icons.link, color: AppTheme.textMuted, size: 20),
                        suffixIcon: IconButton(
                          icon: const Icon(Icons.clear, size: 18),
                          onPressed: () => _serverUrlController.clear(),
                        ),
                        filled: true,
                        fillColor: AppTheme.bgPrimary,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: const BorderSide(color: AppTheme.borderGlass),
                        ),
                      ),
                      keyboardType: TextInputType.url,
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      'Quick Presets:',
                      style: TextStyle(color: AppTheme.textMuted, fontSize: 12, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      children: [
                        ActionChip(
                          avatar: const Icon(Icons.bolt, size: 16, color: AppTheme.accentEmerald),
                          label: const Text('Public Tunnel (ngrok)', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
                          onPressed: () {
                            setState(() {
                              _serverUrlController.text = 'https://arcane-unserviceably-tosha.ngrok-free.dev';
                              _testResult = null;
                            });
                          },
                        ),
                        ActionChip(
                          label: const Text('Wi-Fi (192.168.1.39)', style: TextStyle(fontSize: 12)),
                          onPressed: () {
                            setState(() {
                              _serverUrlController.text = 'http://192.168.1.39:8000';
                              _testResult = null;
                            });
                          },
                        ),
                        ActionChip(
                          label: const Text('USB (localhost)', style: TextStyle(fontSize: 12)),
                          onPressed: () {
                            setState(() {
                              _serverUrlController.text = 'http://127.0.0.1:8000';
                              _testResult = null;
                            });
                          },
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    OutlinedButton.icon(
                      icon: _testingConnection
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2, color: AppTheme.accentPrimary),
                            )
                          : const Icon(Icons.network_check, size: 18),
                      label: Text(_testingConnection ? 'Testing connection...' : 'Test Connection'),
                      onPressed: _testingConnection ? null : _testConnection,
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
                    const SizedBox(height: 14),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            style: OutlinedButton.styleFrom(
                              foregroundColor: AppTheme.textSecondary,
                              side: const BorderSide(color: AppTheme.borderGlass),
                            ),
                            onPressed: _resetServerUrlToDefault,
                            child: const Text('Reset Default'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ElevatedButton(
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppTheme.accentPrimary,
                              foregroundColor: Colors.white,
                            ),
                            onPressed: _saveAndApplyServerUrl,
                            child: const Text('Save & Apply'),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 40),
        ],
      ),
    );
  }

  Widget _sectionHeader(String title, IconData icon) {
    return Builder(
      builder: (context) => Padding(
        padding: const EdgeInsets.only(left: 4, bottom: 8),
        child: Row(
          children: [
            Icon(icon, size: 18, color: AppTheme.accentPrimary),
            const SizedBox(width: 8),
            Text(
              title,
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: context.textSecondary,
                letterSpacing: 0.4,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _card({required Widget child}) {
    return Builder(
      builder: (context) => Container(
        decoration: BoxDecoration(
          color: context.bgSecondary,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: context.borderGlass),
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(18),
          child: child,
        ),
      ),
    );
  }

  Widget _guideStep({
    required String step,
    required String title,
    required String description,
  }) {
    return Builder(
      builder: (context) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 12,
            backgroundColor: AppTheme.accentPrimary.withValues(alpha: 0.2),
            child: Text(
              step,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: AppTheme.accentPrimary,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: context.textPrimary,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  description,
                  style: TextStyle(
                    fontSize: 12,
                    color: context.textSecondary,
                    height: 1.3,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
