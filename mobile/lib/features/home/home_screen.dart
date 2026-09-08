/// The app's heart: two giant role buttons and one-tap help calls.
///
/// Helpee side: tap a trusted person -> their phone rings -> live session.
/// Helper side: full-screen ring popup anywhere in the app -> accept drops
/// both phones straight into the live session. No codes, no IDs, ever.
library;

import 'dart:async';
import 'dart:convert';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../core/network/api_client.dart';
import '../../core/notifications/push_notification_service.dart';
import '../../core/realtime/device_channel_service.dart';
import '../../core/security/device_identity.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';
import '../workspace/mobile_workspace_screen.dart';

class HomeScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;

  const HomeScreen({
    super.key,
    required this.apiClient,
    required this.secureStorage,
  });

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  static const _tabNeedHelp = 0;
  static const _tabHelping = 1;

  int _tab = _tabNeedHelp;
  String _myName = '';

  List<Map<String, dynamic>> _myHelpers = []; // who can help me
  List<Map<String, dynamic>> _iHelp = []; // who I help

  DeviceChannelService? _channel;
  StreamSubscription<DeviceChannelEvent>? _channelSub;

  // Active outgoing call state
  String? _ringingRequestId;
  String? _ringingSessionId;
  String? _ringingName;
  Timer? _ringStatusTimer;
  DateTime? _ringStartedAt;
  Map<String, dynamic>? _incomingCall;
  bool _incomingDialogOpen = false;
  Map<String, dynamic>? _activeSession;
  bool _isReconnecting = false;
  bool _isOpeningSession = false;

  // Inline setup code handling for "Add a helper"
  String? _myCode;
  String? _myPairingId;
  bool _generatingCode = false;
  Timer? _codePollTimer;
  Timer? _heartbeatTimer;
  final TextEditingController _codeInputController = TextEditingController();
  bool _submittingCode = false;

  bool get _isBusy =>
      _ringingRequestId != null ||
      _incomingCall != null ||
      _incomingDialogOpen ||
      _activeSession != null;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    _myName = await widget.secureStorage.getDisplayName() ?? '';
    final token = await widget.secureStorage.getAccessToken();
    if (token == null || token.isEmpty) {
      final secret = await widget.secureStorage.getDeviceSecret();
      if (secret != null && secret.isNotEmpty) {
        final fingerprint = await DeviceIdentity.getFingerprint(widget.secureStorage);
        try {
          await widget.apiClient.deviceBootstrap(
            deviceFingerprint: fingerprint,
            displayName: _myName.isNotEmpty ? _myName : null,
            deviceSecret: secret,
          );
        } catch (_) {}
      }
    }
    await _refreshActiveSession();
    await [Permission.microphone, Permission.notification].request();
    await _loadLists();
    await _connectChannel();
    await _registerPushToken();
    await _checkMissedCalls();
    _heartbeatTimer?.cancel();
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (mounted) {
        _checkMissedCalls();
        _refreshActiveSession();
      }
    });
  }

  /// Give the backend this device's FCM token so rings reach us even when
  /// the app is closed.
  Future<void> _registerPushToken() async {
    try {
      final messaging = FirebaseMessaging.instance;
      final token = await messaging.getToken();
      if (token != null && token.isNotEmpty) {
        await widget.apiClient.registerPushToken(token);
      }
      messaging.onTokenRefresh.listen((t) {
        widget.apiClient.registerPushToken(t);
      });
    } catch (_) {
      /* push not available on this build */
    }
  }

  /// A closed app must never lose a request: fetch pending rings on open.
  Future<void> _checkMissedCalls() async {
    if (_incomingCall != null || _ringingRequestId != null) return;
    try {
      final resp = await widget.apiClient.listPendingCalls();
      if (resp.statusCode != 200) return;
      final data = jsonDecode(resp.body);
      final items = List<Map<String, dynamic>>.from(data['items'] ?? []);
      if (items.isEmpty) return;
      final first = items.first;
      if (mounted) {
        setState(() {
          _incomingCall = {
            'request_id': first['request_id'],
            'session_id': first['session_id'],
            'from_name': first['from_name'],
            'message': first['message'],
          };
        });
      }
    } catch (_) {
      /* offline — try again next bootstrap */
    }
  }

  Future<void> _loadLists() async {
    try {
      final helpersResp = await widget.apiClient.listTrustedDevices();
      if (helpersResp.statusCode == 200) {
        final devices = List<Map<String, dynamic>>.from(
          jsonDecode(helpersResp.body)['devices'],
        );
        if (mounted) setState(() => _myHelpers = devices);
      }
      final helpingResp = await widget.apiClient.listHelping();
      if (helpingResp.statusCode == 200) {
        final entries = List<Map<String, dynamic>>.from(
          jsonDecode(helpingResp.body)['entries'],
        );
        if (mounted) setState(() => _iHelp = entries);
      }
    } catch (_) {
      /* offline: lists stay as-is */
    }
  }

  Future<void> _generateMyCode() async {
    if (_generatingCode) return;
    setState(() => _generatingCode = true);
    try {
      final resp = await widget.apiClient.generateSetupCode();
      if (resp.statusCode == 201) {
        final data = jsonDecode(resp.body);
        setState(() {
          _myCode = data['setup_code'] as String?;
          _myPairingId = data['pairing_id'] as String?;
        });
        _startCodePolling();
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(_responseDetail(resp.body, fallback: 'Could not create setup code')),
              backgroundColor: AppTheme.accentRose,
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Connection error: $e'), backgroundColor: AppTheme.accentRose),
        );
      }
    } finally {
      if (mounted) setState(() => _generatingCode = false);
    }
  }

  void _startCodePolling() {
    _codePollTimer?.cancel();
    _codePollTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      if (_myPairingId == null || !mounted) return;
      try {
        final resp = await widget.apiClient.listPendingPairings();
        if (resp.statusCode != 200) return;
        final data = jsonDecode(resp.body);
        final pairings = List<Map<String, dynamic>>.from(data['pairings']);
        final pairing = pairings.firstWhere((p) => p['pairing_id'] == _myPairingId, orElse: () => {});
        if (pairing.isEmpty) return;
        final friendlyName = pairing['friendly_name']?.toString() ?? 'This helper';
        if (!mounted) return;
        _codePollTimer?.cancel();
        
        final allow = await showDialog<bool>(
          context: context,
          barrierDismissible: false,
          builder: (ctx) => AlertDialog(
            backgroundColor: AppTheme.bgSecondary,
            title: Row(
              children: [
                const Icon(Icons.shield, color: AppTheme.accentEmerald, size: 28),
                const SizedBox(width: 12),
                Expanded(
                  child: Text('Allow $friendlyName?', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
                ),
              ],
            ),
            content: Text(
              '$friendlyName entered your code and wants to be added as your trusted helper.\n\nDo you allow this?',
              style: const TextStyle(color: AppTheme.textSecondary, fontSize: 16, height: 1.4),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('No, cancel', style: TextStyle(color: AppTheme.accentRose, fontSize: 16)),
              ),
              ElevatedButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Allow & Add'),
              ),
            ],
          ),
        );

        if (allow == true && mounted) {
          final approveResp = await widget.apiClient.approvePairing(_myPairingId!);
          if (approveResp.statusCode == 200) {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text('Success! $friendlyName can now help you.'),
                  backgroundColor: AppTheme.accentEmerald,
                ),
              );
              setState(() {
                _myCode = null;
                _myPairingId = null;
              });
              await _loadLists();
            }
          } else {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text('Could not approve: ${_responseDetail(approveResp.body, fallback: 'Failed')}'),
                  backgroundColor: AppTheme.accentRose,
                ),
              );
            }
            _startCodePolling();
          }
        } else {
          _startCodePolling();
        }
      } catch (_) {}
    });
  }

  Future<void> _submitCode() async {
    final code = _codeInputController.text.trim();
    if (code.length != 6) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please enter the full 6-digit code'),
          backgroundColor: AppTheme.accentAmber,
        ),
      );
      return;
    }
    setState(() => _submittingCode = true);
    try {
      final fingerprint = await DeviceIdentity.getFingerprint(widget.secureStorage);
      final storedName = (await widget.secureStorage.getDisplayName())?.trim();
      final resp = await widget.apiClient.claimSetupCode(
        setupCode: code,
        deviceFingerprint: fingerprint,
        friendlyName: storedName == null || storedName.isEmpty ? 'Helper' : storedName,
        devicePlatform: 'android',
      );
      if (resp.statusCode == 200) {
        if (!mounted) return;
        _codeInputController.clear();
        await showDialog<void>(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: AppTheme.bgSecondary,
            title: const Row(
              children: [
                Icon(Icons.check_circle, color: AppTheme.accentEmerald, size: 28),
                SizedBox(width: 12),
                Text('Request Sent!', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              ],
            ),
            content: const Text(
              'The person you want to help just needs to tap "Allow" on their phone screen. Once they tap Allow, they will appear in your list here.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 16, height: 1.4),
            ),
            actions: [
              ElevatedButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Got it'),
              ),
            ],
          ),
        );
        await _loadLists();
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Could not connect: ${_responseDetail(resp.body, fallback: 'Invalid code')}'),
              backgroundColor: AppTheme.accentRose,
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Connection error: $e'), backgroundColor: AppTheme.accentRose),
        );
      }
    } finally {
      if (mounted) setState(() => _submittingCode = false);
    }
  }

  Future<void> _removeHelper(Map<String, dynamic> device) async {
    final name = (device['helper_display_name'] as String?) ??
        (device['friendly_name'] as String?) ??
        'this helper';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Remove Helper?'),
        content: Text(
          'Remove $name from your trusted helpers? They will no longer receive help calls from you.',
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 16),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.accentRose),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      final id = device['id']?.toString();
      if (id != null) {
        await widget.apiClient.revokeDevice(id);
      }
      await _loadLists();
    } catch (_) {}
  }

  Future<void> _removeHelping(Map<String, dynamic> entry) async {
    final name = entry['owner_display_name']?.toString() ?? 'this person';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Remove from List?'),
        content: Text(
          'Remove $name from the list of people you help?',
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 16),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.accentRose),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final id = entry['id']?.toString() ?? entry['device_id']?.toString();
    if (id != null) {
      try {
        await widget.apiClient.revokeDevice(id);
      } catch (_) {}
    }
    setState(() => _iHelp.removeWhere((e) => e['id'] == entry['id']));
  }

  Future<void> _connectChannel() async {
    final token = await widget.secureStorage.getAccessToken();
    if (token == null) return;
    _channel?.dispose();
    final channel = DeviceChannelService(
      accessToken: token,
      accessTokenProvider: widget.apiClient.getRealtimeAccessToken,
    );
    _channel = channel;
    _channelSub?.cancel();
    _channelSub = channel.events.listen(_onChannelEvent);
    await channel.connect();
  }

  // -------------------------------------------------------------------------
  // Ring channel events
  // -------------------------------------------------------------------------

  Future<void> _onChannelEvent(DeviceChannelEvent event) async {
    switch (event.type) {
      case 'incoming_call':
        if (!mounted || _isBusy) return;
        setState(() => _incomingCall = event.data);
        try {
          await PushNotificationService.instance.showIncomingCall(
            title: '${event.data['from_name'] ?? 'Someone'} needs your help',
            body: (event.data['message'] as String?) ?? 'Tap to respond',
          );
        } catch (_) {}
        if (!mounted) return;
        if (ModalRoute.of(context)?.isCurrent == true) {
          _showIncomingDialog();
        }
        break;

      case 'call_accepted':
        if (_ringingSessionId == event.data['session_id']) {
          final sessionId = _ringingSessionId!;
          final peerName =
              (event.data['helper_name'] as String?) ??
              _ringingName ??
              'your helper';
          _clearOutgoing();
          _openLiveSession(sessionId, isHelpee: true, peerName: peerName);
        }
        break;

      case 'call_denied':
        if (_ringingRequestId == event.data['request_id']) {
          final name = _ringingName ?? 'They';
          _clearOutgoing();
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('$name can\'t help right now'),
                backgroundColor: AppTheme.accentAmber,
              ),
            );
          }
        }
        break;

      case 'call_cancelled':
        if (_incomingCall?['request_id'] == event.data['request_id']) {
          if (!_incomingDialogOpen) {
            setState(() => _incomingCall = null);
          }
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('The help request was cancelled.')),
            );
          }
        }
        break;
    }
  }

  void _clearOutgoing() {
    _ringStatusTimer?.cancel();
    _ringStatusTimer = null;
    _ringStartedAt = null;
    if (mounted) {
      setState(() {
        _ringingRequestId = null;
        _ringingSessionId = null;
        _ringingName = null;
      });
    } else {
      _ringingRequestId = null;
      _ringingSessionId = null;
      _ringingName = null;
    }
  }

  Future<void> _clearActiveSession() async {
    await widget.secureStorage.clearActiveSession();
    if (mounted) setState(() => _activeSession = null);
  }

  // -------------------------------------------------------------------------
  // Helpee: tap a trusted person to ring them
  // -------------------------------------------------------------------------

  Future<void> _ringHelper(Map<String, dynamic> device) async {
    if (_activeSession != null) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('You are already in a session. Please leave or reconnect.')),
        );
      }
      return;
    }
    if (_isBusy) return;

    final message = await _askForMessage(device);
    if (message == null) return; // user cancelled

    setState(() {
      _ringingName =
          (device['helper_display_name'] as String?) ??
          (device['friendly_name'] as String?) ??
          'your helper';
    });

    try {
      final targetId = (device['device_fingerprint'] as String?) ??
          (device['helper_user_id'] as String?) ??
          (device['owner_user_id'] as String?) ??
          (device['device_id'] as String?);
      final resp = await widget.apiClient.placeHelpCall(
        helperDeviceFingerprint: targetId ?? '',
        message: message.isEmpty ? null : message,
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _ringingRequestId = data['request_id'] as String?;
          _ringingSessionId = data['session_id'] as String?;
          _ringingName = (data['helper_name'] as String?) ?? _ringingName;
          _ringStartedAt = DateTime.now();
        });
        _startRingStatusPolling();
      } else {
        _clearOutgoing();
        if (mounted) {
          final detail = _responseDetail(resp.body, fallback: 'Call could not be placed');
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(detail), backgroundColor: AppTheme.accentRose),
          );
        }
      }
    } catch (e) {
      _clearOutgoing();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Connection error: $e'), backgroundColor: AppTheme.accentRose),
        );
      }
    }
  }

  String _responseDetail(String body, {required String fallback}) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map && decoded['detail'] != null) {
        return decoded['detail'].toString();
      }
    } catch (_) {}
    return body.trim().isEmpty ? fallback : body.trim();
  }

  void _startRingStatusPolling() {
    _ringStatusTimer?.cancel();
    _ringStatusTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      final requestId = _ringingRequestId;
      if (!mounted || requestId == null) return;
      final started = _ringStartedAt ?? DateTime.now();
      if (DateTime.now().difference(started) > const Duration(seconds: 90)) {
        _clearOutgoing();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('No response yet. You can try again in a moment.'),
              backgroundColor: AppTheme.accentAmber,
            ),
          );
        }
        return;
      }
      try {
        final resp = await widget.apiClient.getHelpCallStatus(requestId);
        if (resp.statusCode != 200) return;
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final state = data['status']?.toString();
        if (state == 'accepted') {
          final sessionId = _ringingSessionId ?? data['session_id']?.toString();
          if (sessionId != null) {
            final peerName =
                _ringingName ??
                data['helper_name']?.toString() ??
                'your helper';
            _clearOutgoing();
            _openLiveSession(sessionId, isHelpee: true, peerName: peerName);
          }
        } else if (state == 'denied') {
          final name = _ringingName ?? 'They';
          _clearOutgoing();
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('$name can\'t help right now'), backgroundColor: AppTheme.accentAmber),
            );
          }
        }
      } catch (_) {}
    });
  }

  Future<void> _openLiveSession(
    String sessionId, {
    required bool isHelpee,
    String? peerName,
  }) async {
    if (!mounted || _isOpeningSession) return;
    _isOpeningSession = true;
    final resolvedPeerName = peerName ?? _ringingName ?? 'your contact';
    await widget.secureStorage.saveActiveSession(
      sessionId: sessionId,
      peerName: resolvedPeerName,
      isHelpee: isHelpee,
    );
    if (!mounted) {
      _isOpeningSession = false;
      return;
    }
    try {
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => MobileWorkspaceScreen(
            sessionId: sessionId,
            sessionCode: 'LIVE',
            apiClient: widget.apiClient,
            secureStorage: widget.secureStorage,
            isHelpee: isHelpee,
            autoStartScreenShare: isHelpee,
            peerName: resolvedPeerName,
            onSessionClosed: _clearActiveSession,
          ),
        ),
      );
    } finally {
      _isOpeningSession = false;
      if (mounted) {
        await _loadLists();
      }
    }
  }

  Future<String?> _askForMessage(Map<String, dynamic> device) async {
    final controller = TextEditingController();
    final name =
        (device['helper_display_name'] as String?) ??
        (device['friendly_name'] as String?) ??
        'your helper';
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: Row(
          children: [
            const Icon(Icons.phone_in_talk, color: AppTheme.accentEmerald, size: 28),
            const SizedBox(width: 12),
            Expanded(
              child: Text('Call $name?', style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'What do you need help with? (Optional)',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 15),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: controller,
              maxLines: 2,
              maxLength: 200,
              autofocus: true,
              style: const TextStyle(color: AppTheme.textPrimary, fontSize: 18),
              decoration: const InputDecoration(
                hintText: 'e.g. My screen is stuck',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(fontSize: 16)),
          ),
          ElevatedButton.icon(
            icon: const Icon(Icons.call, size: 20),
            label: const Text('Call Now', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
          ),
        ],
      ),
    );
  }

  Future<void> _cancelRing() async {
    final requestId = _ringingRequestId;
    if (requestId != null) {
      try {
        await widget.apiClient.cancelHelpCall(requestId);
      } catch (_) {}
    }
    _clearOutgoing();
  }

  // -------------------------------------------------------------------------
  // Helper: answer the ring
  // -------------------------------------------------------------------------

  Future<void> _respondIncoming({required bool accept}) async {
    final call = _incomingCall;
    if (call == null) return;
    setState(() => _incomingCall = null);

    try {
      final fingerprint = accept
          ? await DeviceIdentity.getFingerprint(widget.secureStorage)
          : null;
      final resp = await widget.apiClient.respondToRequestSimple(
        sessionId: call['session_id'] as String,
        requestId: call['request_id'] as String,
        accept: accept,
        helperDeviceFingerprint: fingerprint,
      );
      if (resp.statusCode != 200 && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not answer call (${resp.statusCode})')),
        );
        return;
      }
      if (accept && mounted) {
        await _openLiveSession(
          call['session_id'] as String,
          isHelpee: false,
          peerName: (call['from_name'] as String?) ?? 'your contact',
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Connection error: $e')),
        );
      }
    }
    await _checkMissedCalls();
  }

  Future<void> _showIncomingDialog() async {
    if (!mounted || _incomingCall == null || _incomingDialogOpen) return;
    _incomingDialogOpen = true;
    try {
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (dialogContext) => _incomingCallCard(
          onAccept: () async {
            Navigator.of(dialogContext).pop();
            await _respondIncoming(accept: true);
          },
          onDeny: () async {
            Navigator.of(dialogContext).pop();
            await _respondIncoming(accept: false);
          },
        ),
      );
    } finally {
      _incomingDialogOpen = false;
    }
  }

  Widget _incomingCallCard({
    required VoidCallback onAccept,
    required VoidCallback onDeny,
  }) {
    final call = _incomingCall!;
    final fromName = (call['from_name'] as String?) ?? 'Someone';
    final message = call['message'] as String?;
    return AlertDialog(
      backgroundColor: AppTheme.bgSecondary,
      title: const Center(
        child: Column(
          children: [
            Icon(Icons.ring_volume, color: AppTheme.accentEmerald, size: 48),
            SizedBox(height: 12),
            Text('Incoming Help Request', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
          ],
        ),
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppTheme.bgPrimary,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: AppTheme.accentEmerald.withValues(alpha: 0.4)),
            ),
            child: Column(
              children: [
                Text(
                  fromName,
                  style: const TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w900,
                    color: AppTheme.accentEmerald,
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  'needs your help on their phone',
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 15),
                ),
                if (message != null && message.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppTheme.bgCard,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      '"$message"',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: AppTheme.textPrimary,
                        fontSize: 16,
                        fontStyle: FontStyle.italic,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
      actionsPadding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
      actions: [
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppTheme.accentRose,
                  side: const BorderSide(color: AppTheme.accentRose),
                ),
                onPressed: onDeny,
                child: const Text("Can't now"),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              flex: 2,
              child: ElevatedButton.icon(
                icon: const Icon(Icons.call),
                label: const Text('Accept & Help'),
                onPressed: onAccept,
              ),
            ),
          ],
        ),
      ],
    );
  }

  // -------------------------------------------------------------------------
  // UI
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.bgPrimary,
      appBar: AppBar(
        title: Text(_myName.isEmpty ? 'AssistMe' : 'Hi, $_myName'),
      ),
      body: Stack(
        children: [
          SafeArea(
            child: Column(
              children: [
                _roleSwitch(),
                Expanded(
                  child: _tab == _tabNeedHelp ? _needHelpTab() : _helpingTab(),
                ),
              ],
            ),
          ),
          if (_ringingRequestId != null) _ringingOverlay(),
          if (_incomingCall != null && !_incomingDialogOpen) _incomingPopup(),
          if (_activeSession != null) _activeSessionBanner(),
        ],
      ),
    );
  }

  Widget _roleSwitch() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 8),
      child: Container(
        decoration: BoxDecoration(
          color: AppTheme.bgSecondary,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppTheme.borderGlass),
        ),
        child: Row(
          children: [
            Expanded(
              child: _roleTab(
                _tabNeedHelp,
                'I need help',
                Icons.help_outline,
                AppTheme.accentEmerald,
              ),
            ),
            Expanded(
              child: _roleTab(
                _tabHelping,
                "I'm helping",
                Icons.volunteer_activism,
                AppTheme.accentPrimary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _roleTab(int index, String label, IconData icon, Color activeColor) {
    final selected = _tab == index;
    return InkWell(
      borderRadius: BorderRadius.circular(18),
      onTap: () => setState(() => _tab = index),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 16),
        decoration: BoxDecoration(
          color: selected ? activeColor.withValues(alpha: 0.18) : null,
          borderRadius: BorderRadius.circular(18),
          border: selected ? Border.all(color: activeColor.withValues(alpha: 0.6), width: 1.5) : null,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              size: 24,
              color: selected ? activeColor : AppTheme.textMuted,
            ),
            const SizedBox(width: 10),
            Text(
              label,
              style: TextStyle(
                fontSize: 18,
                fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                color: selected ? activeColor : AppTheme.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _needHelpTab() {
    return RefreshIndicator(
      onRefresh: _loadLists,
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          // Simplified inline helper code display card
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: AppTheme.bgSecondary,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: AppTheme.borderGlass),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Row(
                  children: [
                    Icon(Icons.person_add, color: AppTheme.accentEmerald, size: 24),
                    SizedBox(width: 10),
                    Text(
                      'Add a new helper',
                      style: TextStyle(
                        color: AppTheme.textPrimary,
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text(
                  'Want someone new to help you? Show them your 6-digit code.',
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
                ),
                const SizedBox(height: 16),
                if (_myCode != null) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(vertical: 18),
                    decoration: BoxDecoration(
                      color: AppTheme.bgPrimary,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: AppTheme.accentEmerald, width: 2),
                    ),
                    child: Text(
                      _myCode!,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 40,
                        letterSpacing: 10,
                        fontWeight: FontWeight.w900,
                        color: AppTheme.accentEmerald,
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'Read this code to your helper. Waiting for them to enter it...',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppTheme.accentAmber, fontSize: 14, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    onPressed: () {
                      _codePollTimer?.cancel();
                      setState(() {
                        _myCode = null;
                        _myPairingId = null;
                      });
                    },
                    child: const Text('Hide Code'),
                  ),
                ] else ...[
                  SizedBox(
                    height: 52,
                    child: ElevatedButton.icon(
                      onPressed: _generatingCode ? null : _generateMyCode,
                      icon: _generatingCode
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                          : const Icon(Icons.qr_code, size: 20),
                      label: Text(_generatingCode ? 'Creating code...' : 'Show My 6-Digit Code'),
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 24),
          const Text(
            'Your Trusted Helpers',
            style: TextStyle(
              color: AppTheme.textPrimary,
              fontSize: 18,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 12),
          if (_myHelpers.isEmpty)
            _emptyState(
              icon: Icons.people_outline,
              text: 'No helpers added yet. Tap "Show My 6-Digit Code" above and have your helper enter it on their phone.',
            )
          else ...[
            ..._myHelpers.map((d) {
              final name = (d['helper_display_name'] as String?) ??
                  (d['friendly_name'] as String?) ??
                  'Helper';
              final initial = name.isNotEmpty ? name[0].toUpperCase() : '?';
              return Container(
                margin: const EdgeInsets.only(bottom: 16),
                decoration: BoxDecoration(
                  color: AppTheme.bgSecondary,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppTheme.borderGlassStrong),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      CircleAvatar(
                        radius: 28,
                        backgroundColor: AppTheme.accentEmerald,
                        child: Text(
                          initial,
                          style: const TextStyle(
                            fontSize: 24,
                            fontWeight: FontWeight.w900,
                            color: Colors.white,
                          ),
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              name,
                              style: const TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.w800,
                                color: AppTheme.textPrimary,
                              ),
                            ),
                            const SizedBox(height: 4),
                            const Text(
                              'Tap Call to ask for help',
                              style: TextStyle(fontSize: 14, color: AppTheme.textSecondary),
                            ),
                          ],
                        ),
                      ),
                      ElevatedButton.icon(
                        icon: const Icon(Icons.call, size: 20),
                        label: const Text('Call'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.accentEmerald,
                          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                          minimumSize: const Size(80, 48),
                        ),
                        onPressed: _isBusy ? null : () => _ringHelper(d),
                      ),
                      const SizedBox(width: 4),
                      IconButton(
                        icon: const Icon(Icons.delete_outline, color: AppTheme.textMuted, size: 22),
                        tooltip: 'Remove helper',
                        onPressed: () => _removeHelper(d),
                      ),
                    ],
                  ),
                ),
              );
            }),
          ],
        ],
      ),
    );
  }

  Widget _helpingTab() {
    return RefreshIndicator(
      onRefresh: _loadLists,
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: AppTheme.bgSecondary,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: AppTheme.borderGlass),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Row(
                  children: [
                    Icon(Icons.add_link, color: AppTheme.accentPrimary, size: 24),
                    SizedBox(width: 10),
                    Text(
                      'Connect to someone you help',
                      style: TextStyle(
                        color: AppTheme.textPrimary,
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text(
                  'Ask them for their 6-digit code shown on their "I need help" screen.',
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _codeInputController,
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          letterSpacing: 6,
                          fontSize: 22,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                        decoration: const InputDecoration(
                          hintText: '000000',
                          counterText: '',
                        ),
                        maxLength: 6,
                      ),
                    ),
                    const SizedBox(width: 12),
                    SizedBox(
                      height: 58,
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.accentPrimary,
                        ),
                        onPressed: _submittingCode ? null : _submitCode,
                        child: _submittingCode
                            ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
                            : const Text('Connect'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          const Text(
            'People You Help',
            style: TextStyle(
              color: AppTheme.textPrimary,
              fontSize: 18,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 12),
          if (_iHelp.isEmpty)
            _emptyState(
              icon: Icons.volunteer_activism,
              text: 'No one added yet. Enter their 6-digit code above to connect and start helping them.',
            )
          else ...[
            ..._iHelp.map((e) {
              final name = (e['owner_display_name'] as String?) ?? 'Someone';
              final initial = name.isNotEmpty ? name[0].toUpperCase() : '?';
              return Container(
                margin: const EdgeInsets.only(bottom: 14),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppTheme.bgSecondary,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppTheme.borderGlass),
                ),
                child: Row(
                  children: [
                    CircleAvatar(
                      radius: 26,
                      backgroundColor: AppTheme.accentPrimary,
                      child: Text(
                        initial,
                        style: const TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w900,
                          color: Colors.white,
                        ),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            name,
                            style: const TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.w800,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 4),
                          const Text(
                            'They can ring your phone for help anytime',
                            style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.delete_outline, color: AppTheme.accentRose),
                      tooltip: 'Remove',
                      onPressed: () => _removeHelping(e),
                    ),
                  ],
                ),
              );
            }),
          ],
        ],
      ),
    );
  }

  Widget _emptyState({required IconData icon, required String text}) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 36),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 64, color: AppTheme.textMuted.withValues(alpha: 0.6)),
            const SizedBox(height: 18),
            Text(
              text,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AppTheme.textSecondary,
                fontSize: 16,
                height: 1.5,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _activeSessionBanner() {
    final active = _activeSession!;
    final name = active['peer_name'] as String? ?? 'your contact';
    return Positioned(
      left: 16,
      right: 16,
      bottom: 16,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppTheme.bgCardElevated,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppTheme.accentEmerald, width: 2),
          boxShadow: const [
            BoxShadow(color: Colors.black54, blurRadius: 16, offset: Offset(0, 4)),
          ],
        ),
        child: Row(
          children: [
            const Icon(Icons.phone_in_talk, color: AppTheme.accentEmerald, size: 32),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'Reconnect to $name',
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Colors.white),
                  ),
                  const SizedBox(height: 2),
                  const Text(
                    'Session is active. Tap to rejoin.',
                    style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                  ),
                ],
              ),
            ),
            ElevatedButton(
              onPressed: (_isReconnecting || _isOpeningSession) ? null : _reconnectActiveSession,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.accentEmerald,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                minimumSize: const Size(70, 44),
              ),
              child: _isReconnecting
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.5,
                        color: Colors.white,
                      ),
                    )
                  : const Text('Rejoin'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _refreshActiveSession() async {
    final active = await widget.secureStorage.getActiveSession();
    if (active == null) {
      if (mounted && _activeSession != null) {
        setState(() => _activeSession = null);
      }
      return;
    }
    final sessionId = active['session_id'] as String?;
    if (sessionId == null) {
      await widget.secureStorage.clearActiveSession();
      if (mounted) setState(() => _activeSession = null);
      return;
    }
    try {
      final resp = await widget.apiClient.get('/sessions/$sessionId');
      if (resp.statusCode != 200) {
        await widget.secureStorage.clearActiveSession();
        if (mounted) setState(() => _activeSession = null);
        return;
      }
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      final status = data['status'] as String?;
      final participants = (data['participants'] as List?) ?? [];

      if (status == 'ended') {
        await widget.secureStorage.clearActiveSession();
        if (mounted) setState(() => _activeSession = null);
        return;
      }

      // Check if the other person is still in the call (connected or waiting)
      bool otherConnected = false;
      for (final p in participants) {
        if (p is Map) {
          final pStatus = p['status'] as String?;
          if (pStatus == 'connected' || pStatus == 'waiting') {
            otherConnected = true;
            break;
          }
        }
      }
      if (!otherConnected) {
        // Nobody is in the session -> end and clear
        await widget.secureStorage.clearActiveSession();
        if (mounted) setState(() => _activeSession = null);
        return;
      }

      if (mounted && _activeSession == null) {
        setState(() => _activeSession = active);
      }
    } catch (_) {
      await widget.secureStorage.clearActiveSession();
      if (mounted) setState(() => _activeSession = null);
    }
  }

  Future<void> _reconnectActiveSession() async {
    if (_isReconnecting || _isOpeningSession) return;
    final active = _activeSession;
    if (active == null || !mounted) return;
    final sessionId = active['session_id'] as String;
    setState(() => _isReconnecting = true);
    try {
      final response = await widget.apiClient.post(
        '/sessions/recover',
        body: {'session_id': sessionId},
      );
      if (response.statusCode != 200) {
        final session = await widget.apiClient.get('/sessions/$sessionId');
        if (session.statusCode != 200) {
          await widget.secureStorage.clearActiveSession();
          if (mounted) setState(() => _activeSession = null);
          return;
        }
      }
      await _openLiveSession(
        sessionId,
        isHelpee: active['is_helpee'] == true,
        peerName: active['peer_name'] as String? ?? 'your contact',
      );
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('That session is no longer available.')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isReconnecting = false);
      }
    }
  }

  // --- Outgoing ring overlay ---

  Widget _ringingOverlay() {
    return Positioned.fill(
      child: Container(
        color: Colors.black.withValues(alpha: 0.88),
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 90,
                  height: 90,
                  decoration: BoxDecoration(
                    color: AppTheme.accentEmerald.withValues(alpha: 0.15),
                    shape: BoxShape.circle,
                  ),
                  child: const Center(
                    child: SizedBox(
                      width: 48,
                      height: 48,
                      child: CircularProgressIndicator(
                        color: AppTheme.accentEmerald,
                        strokeWidth: 4,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 32),
                Text(
                  'Calling ${_ringingName ?? 'your helper'}…',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 26,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Their phone is ringing. Please wait for them to answer.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 16),
                ),
                const SizedBox(height: 48),
                SizedBox(
                  width: 200,
                  height: 56,
                  child: OutlinedButton(
                    onPressed: _cancelRing,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppTheme.accentRose,
                      side: const BorderSide(color: AppTheme.accentRose, width: 2),
                    ),
                    child: const Text('Cancel Call', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // --- Incoming ring popup ---

  Widget _incomingPopup() {
    final call = _incomingCall!;
    final fromName = (call['from_name'] as String?) ?? 'Someone';
    final message = call['message'] as String?;
    return Positioned.fill(
      child: Container(
        color: Colors.black.withValues(alpha: 0.88),
        child: Center(
          child: Container(
            margin: const EdgeInsets.all(24),
            padding: const EdgeInsets.all(28),
            decoration: BoxDecoration(
              color: AppTheme.bgSecondary,
              borderRadius: BorderRadius.circular(28),
              border: Border.all(color: AppTheme.accentEmerald, width: 2),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(
                  Icons.ring_volume,
                  size: 60,
                  color: AppTheme.accentEmerald,
                ),
                const SizedBox(height: 20),
                Text(
                  '$fromName needs your help',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 24,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                if (message != null && message.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  Text(
                    '"$message"',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 16,
                      fontStyle: FontStyle.italic,
                    ),
                  ),
                ],
                const SizedBox(height: 32),
                SizedBox(
                  height: 60,
                  child: ElevatedButton.icon(
                    onPressed: () => _respondIncoming(accept: true),
                    icon: const Icon(Icons.call, size: 24),
                    label: const Text('Accept & Start Helping', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
                  ),
                ),
                const SizedBox(height: 14),
                SizedBox(
                  height: 52,
                  child: OutlinedButton(
                    onPressed: () => _respondIncoming(accept: false),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppTheme.accentRose,
                      side: const BorderSide(color: AppTheme.accentRose),
                    ),
                    child: const Text(
                      "Can't right now",
                      style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
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

  @override
  void dispose() {
    _heartbeatTimer?.cancel();
    _ringStatusTimer?.cancel();
    _codePollTimer?.cancel();
    _codeInputController.dispose();
    _channelSub?.cancel();
    _channel?.dispose();
    super.dispose();
  }
}
