/// Trusted devices screen — the security center of the app.
///
/// Two dead-simple flows, matching the product vision:
///   1. "I'm getting help" (the elderly person): show a setup code, read it
///      aloud to their helper, then approve the helper's request with one tap.
///   2. "I'm giving help" (the helper): enter the setup code they heard; the
///      helper's own device fingerprint is bound automatically.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../../core/network/api_client.dart';
import '../../core/security/device_identity.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';

class TrustedDevicesScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;

  const TrustedDevicesScreen({
    Key? key,
    required this.apiClient,
    required this.secureStorage,
  }) : super(key: key);

  @override
  State<TrustedDevicesScreen> createState() => _TrustedDevicesScreenState();
}

class _TrustedDevicesScreenState extends State<TrustedDevicesScreen> {
  List<Map<String, dynamic>> _devices = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadDevices();
  }

  Future<void> _loadDevices() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final resp = await widget.apiClient.listTrustedDevices();
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _devices = List<Map<String, dynamic>>.from(data['devices']);
        });
      } else {
        setState(() => _error = 'Failed to load devices (${resp.statusCode})');
      }
    } catch (e) {
      setState(() => _error = 'Network error: $e');
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  // -------------------------------------------------------------------------
  // Flow 1: "I'm getting help" — show a code, then one-tap approve.
  // -------------------------------------------------------------------------

  Future<void> _showMyCode() async {
    String? pairingId;
    String? setupCode;
    String? error;

    try {
      final resp = await widget.apiClient.generateSetupCode();
      if (resp.statusCode == 201) {
        final data = jsonDecode(resp.body);
        pairingId = data['pairing_id'];
        setupCode = data['setup_code'];
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Failed';
        error = 'Could not create code: $detail';
      }
    } catch (e) {
      error = 'Network error: $e';
    }

    if (!mounted) return;
    if (error != null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error)));
      return;
    }

    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => _MyCodeScreen(
          apiClient: widget.apiClient,
          pairingId: pairingId!,
          setupCode: setupCode!,
        ),
      ),
    );
    _loadDevices();
  }

  // -------------------------------------------------------------------------
  // Flow 2: "I'm giving help" — enter the code I heard.
  // -------------------------------------------------------------------------

  Future<void> _enterCode() async {
    final code = await _promptForSetupCode();
    if (code == null || code.isEmpty) return;

    String? error;
    try {
      final fingerprint = await DeviceIdentity.getFingerprint(widget.secureStorage);
      final resp = await widget.apiClient.claimSetupCode(
        setupCode: code,
        deviceFingerprint: fingerprint,
        friendlyName: 'My Device',
        devicePlatform: 'android',
      );
      if (resp.statusCode == 200) {
        if (!mounted) return;
        await showDialog<void>(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: AppTheme.bgSecondary,
            title: const Text('Request sent'),
            content: const Text(
              'The person you want to help has been notified. They just need to '
              'tap "Allow" on their phone — no passwords, nothing else for you '
              'to do. Once approved, this device can help them.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
            ),
            actions: [
              ElevatedButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Got it'),
              ),
            ],
          ),
        );
        return;
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Failed';
        error = 'Could not send request: $detail';
      }
    } catch (e) {
      error = 'Network error: $e';
    }

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
  }

  Future<String?> _promptForSetupCode() async {
    final controller = TextEditingController();
    final code = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Enter the setup code'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Ask the person you are helping to open this app and press '
              '"Show my code". They will read you a 6-digit code over the call. '
              'Type it here.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: controller,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AppTheme.textPrimary,
                letterSpacing: 6,
                fontSize: 22,
                fontWeight: FontWeight.w700,
              ),
              decoration: const InputDecoration(labelText: 'Setup code'),
              maxLength: 6,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('Send request'),
          ),
        ],
      ),
    );
    return code;
  }

  Future<void> _revokeDevice(Map<String, dynamic> device) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Remove this device?'),
        content: Text(
          '"${device['friendly_name'] ?? 'Device'}" will no longer be able to '
          'help you.',
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 14),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Keep'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    try {
      final resp = await widget.apiClient.revokeDevice(device['id']);
      if (resp.statusCode == 204) {
        _loadDevices();
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Failed to remove';
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Remove failed: $detail')),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Network error: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Help & Trusted People'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadDevices,
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // --- Getting help (elderly side) ---
              _FlowCard(
                icon: Icons.help_outline,
                iconColor: AppTheme.accentEmerald,
                title: 'I need help',
                subtitle:
                    'If someone will be helping you, show them your code so they '
                    'can be added.',
                onPressed: _showMyCode,
                buttonLabel: 'Show my code',
              ),
              const SizedBox(height: 14),
              // --- Giving help (helper side) ---
              _FlowCard(
                icon: Icons.volunteer_activism,
                iconColor: AppTheme.accentPrimary,
                title: 'I\'m the helper',
                subtitle:
                    'If you will help someone, enter the code they read to you.',
                onPressed: _enterCode,
                buttonLabel: 'I have a code',
              ),
              const SizedBox(height: 24),
              if (_error != null)
                Container(
                  padding: const EdgeInsets.all(12),
                  margin: const EdgeInsets.only(bottom: 12),
                  decoration: BoxDecoration(
                    color: AppTheme.accentRose.withOpacity(0.15),
                    border: Border.all(color: AppTheme.accentRose),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _error!,
                    style: const TextStyle(color: AppTheme.accentRose, fontSize: 13),
                  ),
                ),
              const Text(
                'People who can help you',
                style: TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
              if (_isLoading)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_devices.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Text(
                    'No helpers yet. Use one of the buttons above.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppTheme.textSecondary),
                  ),
                )
              else
                ..._devices.map(_buildDeviceTile),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDeviceTile(Map<String, dynamic> device) {
    return Card(
      color: AppTheme.bgSecondary,
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: const BorderSide(color: AppTheme.borderGlass),
      ),
      child: ListTile(
        leading: const CircleAvatar(
          backgroundColor: AppTheme.accentEmerald,
          child: Icon(Icons.person, color: Colors.white),
        ),
        title: Text(
          device['friendly_name'] ?? 'Device',
          style: const TextStyle(color: AppTheme.textPrimary),
        ),
        subtitle: Text(
          '${device['device_platform'] ?? 'unknown'} • ${device['status']}',
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
        ),
        trailing: IconButton(
          icon: const Icon(Icons.delete_outline, color: AppTheme.accentRose),
          onPressed: () => _revokeDevice(device),
        ),
      ),
    );
  }
}

/// A tappable card for one of the two flows (get help / give help).
class _FlowCard extends StatelessWidget {
  final IconData icon;
  final Color iconColor;
  final String title;
  final String subtitle;
  final String buttonLabel;
  final VoidCallback onPressed;

  const _FlowCard({
    required this.icon,
    required this.iconColor,
    required this.title,
    required this.subtitle,
    required this.buttonLabel,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppTheme.bgSecondary,
        border: Border.all(color: AppTheme.borderGlass),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CircleAvatar(
                radius: 18,
                backgroundColor: iconColor.withOpacity(0.15),
                child: Icon(icon, color: iconColor, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 17,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            subtitle,
            style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
          ),
          const SizedBox(height: 12),
          ElevatedButton.icon(
            onPressed: onPressed,
            icon: const Icon(Icons.arrow_forward, size: 18),
            label: Text(buttonLabel),
            style: ElevatedButton.styleFrom(
              backgroundColor: iconColor,
              foregroundColor: Colors.white,
            ),
          ),
        ],
      ),
    );
  }
}

/// Full-screen view showing the setup code to read aloud, polling for the
/// helper's claim, and offering a one-tap "Allow".
class _MyCodeScreen extends StatefulWidget {
  final ApiClient apiClient;
  final String pairingId;
  final String setupCode;

  const _MyCodeScreen({
    required this.apiClient,
    required this.pairingId,
    required this.setupCode,
  });

  @override
  State<_MyCodeScreen> createState() => _MyCodeScreenState();
}

class _MyCodeScreenState extends State<_MyCodeScreen> {
  Timer? _timer;
  bool _approving = false;
  bool _completed = false;

  @override
  void initState() {
    super.initState();
    _startPolling();
  }

  void _startPolling() {
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _checkPending());
  }

  Future<void> _checkPending() async {
    if (_approving || _completed || !mounted) return;
    try {
      final resp = await widget.apiClient.listPendingPairings();
      if (resp.statusCode != 200) return;
      final data = jsonDecode(resp.body);
      final pairings = List<Map<String, dynamic>>.from(data['pairings']);
      if (pairings.isEmpty) return;

      final pairing = pairings.firstWhere(
        (p) => p['pairing_id'] == widget.pairingId,
        orElse: () => const {},
      );
      if (pairing.isEmpty || pairing['pairing_id'] != widget.pairingId) return;

      final friendlyName = pairing['friendly_name']?.toString() ?? 'this person';
      if (!mounted) return;
      _timer?.cancel();

      final allow = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: AppTheme.bgSecondary,
          title: const Text('Someone wants to help you'),
          content: Text(
            '$friendlyName wants to be able to help you when you ask. '
            'Do you allow this?',
            style: const TextStyle(color: AppTheme.textSecondary, fontSize: 15),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('No'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Allow'),
            ),
          ],
        ),
      );

      if (!mounted) return;
      if (allow == true) {
        await _approve();
      } else {
        _restartPolling();
      }
    } catch (_) {
      // transient network error — keep polling
    }
  }

  Future<void> _approve() async {
    setState(() => _approving = true);
    try {
      final resp = await widget.apiClient.approvePairing(widget.pairingId);
      if (resp.statusCode == 200) {
        if (mounted) {
          setState(() => _completed = true);
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Done! This person can now help you.'),
              backgroundColor: AppTheme.accentEmerald,
            ),
          );
          Navigator.of(context).pop();
        }
      } else {
        if (mounted) {
          final detail = jsonDecode(resp.body)['detail'] ?? 'Failed';
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text('Could not approve: $detail')));
          _restartPolling();
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Network error: $e')));
        _restartPolling();
      }
    } finally {
      if (mounted) setState(() => _approving = false);
    }
  }

  void _restartPolling() {
    _timer?.cancel();
    _startPolling();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.bgPrimary,
      appBar: AppBar(title: const Text('Your setup code')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Read this code to the person who will help you. '
                'They enter it on their phone.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 15),
              ),
              const SizedBox(height: 24),
              Container(
                padding: const EdgeInsets.symmetric(vertical: 24),
                decoration: BoxDecoration(
                  color: AppTheme.bgSecondary,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: AppTheme.accentPrimary, width: 2),
                ),
                child: Text(
                  widget.setupCode,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 48,
                    letterSpacing: 12,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.accentPrimary,
                  ),
                ),
              ),
              const SizedBox(height: 24),
              const Text(
                'Waiting for them to enter the code…\n'
                'A button will appear here when they do.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
              ),
              const SizedBox(height: 24),
              if (_approving)
                const Center(
                  child: CircularProgressIndicator(color: AppTheme.accentPrimary),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
