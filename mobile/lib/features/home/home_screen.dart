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
import '../devices/trusted_devices_screen.dart';
import '../workspace/mobile_workspace_screen.dart';

class HomeScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;

  const HomeScreen({
    Key? key,
    required this.apiClient,
    required this.secureStorage,
  }) : super(key: key);

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
  bool _showRingPopup = false;
  Map<String, dynamic>? _incomingCall;
  bool _incomingDialogOpen = false;
  Map<String, dynamic>? _activeSession;

  bool get _isBusy =>
      _ringingRequestId != null ||
      _showRingPopup ||
      _incomingCall != null ||
      _incomingDialogOpen;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    _myName = await widget.secureStorage.getDisplayName() ?? '';
    _activeSession = await widget.secureStorage.getActiveSession();
    await [Permission.microphone, Permission.notification].request();
    await _loadLists();
    await _connectChannel();
    await _registerPushToken();
    await _checkMissedCalls();
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
      setState(() {
        _incomingCall = {
          'request_id': first['request_id'],
          'session_id': first['session_id'],
          'from_name': first['from_name'],
          'message': first['message'],
        };
      });
    } catch (_) {
      /* offline — try again next bootstrap */
    }
  }

  Future<void> _loadLists() async {
    try {
      final helpersResp = await widget.apiClient.listTrustedDevices();
      if (helpersResp.statusCode == 200) {
        setState(
          () => _myHelpers = List<Map<String, dynamic>>.from(
            jsonDecode(helpersResp.body)['devices'],
          ),
        );
      }
      final helpingResp = await widget.apiClient.listHelping();
      if (helpingResp.statusCode == 200) {
        setState(
          () => _iHelp = List<Map<String, dynamic>>.from(
            jsonDecode(helpingResp.body)['entries'],
          ),
        );
      }
    } catch (_) {
      /* offline: lists stay empty */
    }
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
  // Ring channel events (work anywhere in the app)
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
        } catch (_) {
          // The live full-screen dialog below remains the source of truth if
          // notifications are unavailable on this device/build.
        }
        if (ModalRoute.of(context)?.isCurrent != true) {
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
              SnackBar(content: Text('$name can\'t help right now')),
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
    if (_isBusy) return;

    final message = await _askForMessage(device);
    if (message == null) return; // cancelled

    setState(() {
      _ringingName =
          (device['helper_display_name'] as String?) ??
          (device['friendly_name'] as String?) ??
          'your helper';
    });

    try {
      final fingerprint = await DeviceIdentity.getFingerprint(
        widget.secureStorage,
      );
      // NOTE: we ring the HELPER's fingerprint stored in our trusted list.
      final resp = await widget.apiClient.placeHelpCall(
        helperDeviceFingerprint:
            (device['device_fingerprint'] as String?) ?? fingerprint,
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
        if (data['helper_online'] == false && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('They are not online right now — calling anyway…'),
            ),
          );
        }
      } else {
        _clearOutgoing();
        if (mounted) {
          final detail = _responseDetail(resp.body, fallback: 'Call failed');
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(detail.toString())));
        }
      }
    } catch (e) {
      _clearOutgoing();
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Network error: $e')));
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
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'No response yet. You can try again when they are available.',
            ),
          ),
        );
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
          if (mounted)
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('$name can\'t help right now')),
            );
        }
      } catch (_) {
        // Keep the overlay while transient connectivity recovers.
      }
    });
  }

  void _openLiveSession(
    String sessionId, {
    required bool isHelpee,
    String? peerName,
  }) {
    if (!mounted) return;
    final resolvedPeerName = peerName ?? _ringingName ?? 'your contact';
    widget.secureStorage.saveActiveSession(
      sessionId: sessionId,
      peerName: resolvedPeerName,
      isHelpee: isHelpee,
    );
    Navigator.of(context).push(
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
  }

  /// Optional context before ringing; empty string rings immediately.
  Future<String?> _askForMessage(Map<String, dynamic> device) async {
    final controller = TextEditingController();
    final name =
        (device['helper_display_name'] as String?) ??
        (device['friendly_name'] as String?) ??
        'them';
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: Text('Call $name?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Tell them what you need help with (or skip it).',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              maxLines: 2,
              maxLength: 500,
              autofocus: true,
              style: const TextStyle(color: AppTheme.textPrimary),
              decoration: const InputDecoration(
                hintText: 'e.g. My WhatsApp won\'t open',
              ),
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
            child: const Text('Just ring'),
          ),
        ],
      ),
    );
  }

  Future<void> _cancelRing() async {
    final requestId = _ringingRequestId;
    if (requestId != null) {
      try {
        final response = await widget.apiClient.cancelHelpCall(requestId);
        if (response.statusCode != 200 && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(_responseDetail(response.body, fallback: 'Could not cancel the call'))),
          );
        }
      } catch (_) {
        // Clear the local ring even if the network is temporarily unavailable.
      }
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
          SnackBar(content: Text('Could not respond (${resp.statusCode})')),
        );
        return;
      }
      if (accept && mounted) {
        await widget.secureStorage.saveActiveSession(
          sessionId: call['session_id'] as String,
          peerName: (call['from_name'] as String?) ?? 'your contact',
          isHelpee: false,
        );
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => MobileWorkspaceScreen(
              sessionId: call['session_id'] as String,
              sessionCode: 'LIVE',
              apiClient: widget.apiClient,
              secureStorage: widget.secureStorage,
              isHelpee: false,
              peerName: (call['from_name'] as String?) ?? 'your contact',
              onSessionClosed: _clearActiveSession,
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Network error: $e')));
      }
    }
    // Surface the next missed ring, if any.
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
      title: const Text('Incoming help request'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('$fromName needs your help', textAlign: TextAlign.center),
          if (message != null && message.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('"$message"', textAlign: TextAlign.center),
          ],
        ],
      ),
      actions: [
        TextButton(onPressed: onDeny, child: const Text('Can\'t right now')),
        ElevatedButton(onPressed: onAccept, child: const Text('Accept')),
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
        actions: [
          IconButton(
            icon: const Icon(Icons.people_outline),
            tooltip: 'Trusted people',
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => TrustedDevicesScreen(
                    apiClient: widget.apiClient,
                    secureStorage: widget.secureStorage,
                  ),
                ),
              );
              _loadLists();
            },
          ),
        ],
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
          if (_incomingCall != null) _incomingPopup(),
          if (_activeSession != null) _activeSessionBanner(),
        ],
      ),
    );
  }

  Widget _roleSwitch() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 4),
      child: Container(
        decoration: BoxDecoration(
          color: AppTheme.bgSecondary,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppTheme.borderGlass),
        ),
        child: Row(
          children: [
            Expanded(
              child: _roleTab(_tabNeedHelp, 'I need help', Icons.help_outline),
            ),
            Expanded(
              child: _roleTab(
                _tabHelping,
                'I\'m helping',
                Icons.volunteer_activism,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _roleTab(int index, String label, IconData icon) {
    final selected = _tab == index;
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: () => setState(() => _tab = index),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14),
        decoration: BoxDecoration(
          color: selected ? AppTheme.accentPrimary.withOpacity(0.15) : null,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              size: 20,
              color: selected ? AppTheme.accentPrimary : AppTheme.textSecondary,
            ),
            const SizedBox(width: 8),
            Text(
              label,
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: selected
                    ? AppTheme.accentPrimary
                    : AppTheme.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _needHelpTab() {
    if (_myHelpers.isEmpty) {
      return _emptyState(
        icon: Icons.person_add_alt_1,
        text:
            'No trusted helpers yet.\nOpen "Trusted people" to add someone — '
            'they just type your code once.',
      );
    }
    return RefreshIndicator(
      onRefresh: _loadLists,
      child: ListView.separated(
        padding: const EdgeInsets.all(20),
        itemCount: _myHelpers.length,
        separatorBuilder: (_, __) => const SizedBox(height: 14),
        itemBuilder: (ctx, i) {
          final d = _myHelpers[i];
          final name =
              (d['helper_display_name'] as String?) ??
              (d['friendly_name'] as String?) ??
              'Helper';
          final tag = d['device_tag']?.toString();
          final platform = d['device_platform']?.toString();
          final identity = [
            if (platform != null && platform.isNotEmpty) platform,
            if (tag != null && tag.isNotEmpty) '#$tag',
          ].join(' · ');
          return SizedBox(
            height: 84,
            child: ElevatedButton.icon(
              onPressed: _isBusy ? null : () => _ringHelper(d),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.bgSecondary,
                foregroundColor: AppTheme.textPrimary,
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                  side: BorderSide(
                    color: AppTheme.accentEmerald.withOpacity(0.5),
                  ),
                ),
                alignment: Alignment.centerLeft,
                padding: const EdgeInsets.symmetric(horizontal: 18),
              ),
              icon: CircleAvatar(
                backgroundColor: AppTheme.accentEmerald,
                child: Text(
                  name.isNotEmpty ? name[0].toUpperCase() : '?',
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              label: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name,
                    style: const TextStyle(
                      fontSize: 19,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  Text(
                    identity.isEmpty
                        ? 'Tap to ask for help'
                        : 'Tap to ask for help · $identity',
                    style: TextStyle(
                      fontSize: 12,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _activeSessionBanner() {
    final active = _activeSession!;
    final name = active['peer_name'] as String? ?? 'your contact';
    return Positioned(
      left: 20,
      right: 20,
      bottom: 20,
      child: Card(
        color: AppTheme.bgSecondary,
        child: ListTile(
          leading: const Icon(
            Icons.phone_in_talk,
            color: AppTheme.accentEmerald,
          ),
          title: Text('Reconnect to $name'),
          subtitle: const Text(
            'This session can recover after a brief disconnect.',
          ),
          trailing: IconButton(
            icon: const Icon(Icons.arrow_forward),
            onPressed: _reconnectActiveSession,
          ),
        ),
      ),
    );
  }

  Future<void> _reconnectActiveSession() async {
    final active = _activeSession;
    if (active == null || !mounted) return;
    final sessionId = active['session_id'] as String;
    try {
      final response = await widget.apiClient.post(
        '/sessions/recover',
        body: {'session_id': sessionId},
      );
      if (response.statusCode != 200) {
        // A process can be killed after the server has already observed the
        // disconnect and another reconnect may have restored the participant
        // row.  In that case recovery returns 400 even though the live room
        // is still valid, so verify the durable session before discarding it.
        final session = await widget.apiClient.get('/sessions/$sessionId');
        if (session.statusCode != 200) {
          await widget.secureStorage.clearActiveSession();
          if (mounted) setState(() => _activeSession = null);
          return;
        }
      }
      _openLiveSession(
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
    }
  }

  Widget _helpingTab() {
    if (_iHelp.isEmpty) {
      return _emptyState(
        icon: Icons.favorite_border,
        text:
            'You are not set up as a helper yet.\nAsk your family member to '
            'show you their code, then add it under "Trusted people".',
      );
    }
    return RefreshIndicator(
      onRefresh: _loadLists,
      child: ListView.separated(
        padding: const EdgeInsets.all(20),
        itemCount: _iHelp.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (ctx, i) {
          final e = _iHelp[i];
          final name = (e['owner_display_name'] as String?) ?? 'Someone';
          return Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppTheme.bgSecondary,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppTheme.borderGlass),
            ),
            child: Row(
              children: [
                CircleAvatar(
                  backgroundColor: AppTheme.accentPrimary,
                  child: Text(
                    name.isNotEmpty ? name[0].toUpperCase() : '?',
                    style: const TextStyle(color: Colors.white),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        name,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      Text(
                        'They can ring you any time',
                        style: TextStyle(
                          fontSize: 12,
                          color: AppTheme.textSecondary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _emptyState({required IconData icon, required String text}) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(36),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 56, color: AppTheme.textMuted),
            const SizedBox(height: 18),
            Text(
              text,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AppTheme.textSecondary,
                fontSize: 15,
                height: 1.5,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // --- Outgoing ring overlay ---

  Widget _ringingOverlay() {
    return Positioned.fill(
      child: Container(
        color: Colors.black87,
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const CircularProgressIndicator(color: AppTheme.accentEmerald),
              const SizedBox(height: 28),
              Text(
                'Connecting to ${_ringingName ?? 'your helper'}…',
                style: const TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 40),
              OutlinedButton(
                onPressed: _cancelRing,
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppTheme.accentRose,
                  side: BorderSide(color: AppTheme.accentRose),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 32,
                    vertical: 14,
                  ),
                ),
                child: const Text('Cancel', style: TextStyle(fontSize: 16)),
              ),
            ],
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
        color: Colors.black87,
        child: Center(
          child: Container(
            margin: const EdgeInsets.all(24),
            padding: const EdgeInsets.all(26),
            decoration: BoxDecoration(
              color: AppTheme.bgSecondary,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: AppTheme.accentEmerald, width: 2),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Icon(
                  Icons.ring_volume,
                  size: 54,
                  color: AppTheme.accentEmerald,
                ),
                const SizedBox(height: 16),
                Text(
                  '$fromName needs your help',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 21,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                if (message != null && message.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(
                    '"$message"',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 15,
                      fontStyle: FontStyle.italic,
                    ),
                  ),
                ],
                const SizedBox(height: 30),
                SizedBox(
                  height: 58,
                  child: ElevatedButton.icon(
                    onPressed: () => _respondIncoming(accept: true),
                    icon: const Icon(Icons.call),
                    label: const Text('Accept', style: TextStyle(fontSize: 18)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.accentEmerald,
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  height: 50,
                  child: OutlinedButton(
                    onPressed: () => _respondIncoming(accept: false),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppTheme.accentRose,
                      side: BorderSide(color: AppTheme.accentRose),
                    ),
                    child: const Text(
                      'Can\'t right now',
                      style: TextStyle(fontSize: 16),
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
    _ringStatusTimer?.cancel();
    _channelSub?.cancel();
    _channel?.dispose();
    super.dispose();
  }
}
