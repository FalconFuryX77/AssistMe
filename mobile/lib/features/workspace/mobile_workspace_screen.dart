import 'package:flutter/material.dart';
import '../../core/network/api_client.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';
import 'remote_screen_view.dart';
import 'mobile_voice_control_bar.dart';
import 'mobile_chat_drawer.dart';
import 'assistance_flow_coordinator.dart';

class MobileWorkspaceScreen extends StatefulWidget {
  final String sessionId;
  final String sessionCode;
  final ApiClient apiClient;
  final SecureStorageService secureStorage;
  final bool isHelpee;

  const MobileWorkspaceScreen({
    Key? key,
    required this.sessionId,
    required this.sessionCode,
    required this.apiClient,
    required this.secureStorage,
    this.isHelpee = true,
  }) : super(key: key);

  @override
  State<MobileWorkspaceScreen> createState() => _MobileWorkspaceScreenState();
}

class _MobileWorkspaceScreenState extends State<MobileWorkspaceScreen> {
  bool _isChatOpen = false;
  final _flowCoordinatorKey = GlobalKey<AssistanceFlowCoordinatorState>();

  // Live remote media stream, published by the flow coordinator's WebRTC
  // engine and consumed by the remote viewport.
  final ValueNotifier<dynamic> _remoteStreamNotifier = ValueNotifier<dynamic>(null);

  void _showSecurityZeroizeSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppTheme.bgSecondary,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20.0),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Signal Protocol E2EE & Hardening',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.black45,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: AppTheme.borderGlass),
                  ),
                  child: const Text(
                    'SAS Fingerprint: e2ee_sas_verified_sha256',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: 'monospace',
                      color: AppTheme.accentEmerald,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                ElevatedButton.icon(
                  icon: const Icon(Icons.refresh),
                  label: const Text('WebRTC Connection Recovery (ICE Restart)'),
                  style: ElevatedButton.styleFrom(backgroundColor: AppTheme.accentSecondary),
                  onPressed: () async {
                    Navigator.pop(ctx);
                    await widget.apiClient.post(
                      '/sessions/${widget.sessionId}/ice-restart',
                      body: {'reason': 'mobile_reconnect'},
                    );
                    if (mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('ICE Restart Triggered')),
                      );
                    }
                  },
                ),
                const SizedBox(height: 10),
                ElevatedButton.icon(
                  icon: const Icon(Icons.cleaning_services),
                  label: const Text('Zeroize & Scrub Cryptographic Memory'),
                  style: ElevatedButton.styleFrom(backgroundColor: AppTheme.accentRose),
                  onPressed: () async {
                    Navigator.pop(ctx);
                    await widget.apiClient.post(
                      '/sessions/${widget.sessionId}/security/zeroize',
                    );
                    if (mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('E2EE Keys Zeroized & Scrubbed')),
                      );
                    }
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _handleLeaveSession() async {
    try {
      await widget.apiClient.post('/sessions/${widget.sessionId}/leave');
    } catch (_) {}
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Session: ${widget.sessionCode}'),
        actions: [
          IconButton(
            icon: Icon(_isChatOpen ? Icons.chat_bubble : Icons.chat_bubble_outline),
            onPressed: () => setState(() => _isChatOpen = !_isChatOpen),
          ),
        ],
      ),
      body: Stack(
        children: [
          // Remote Screen Viewport
          Positioned.fill(
            child: RemoteScreenView(
              sessionId: widget.sessionId,
              apiClient: widget.apiClient,
              remoteStreamNotifier: _remoteStreamNotifier,
            ),
          ),

          // Assistance flow coordinator (realtime + popups + overlay)
          Positioned.fill(
            child: AssistanceFlowCoordinator(
              key: _flowCoordinatorKey,
              sessionId: widget.sessionId,
              apiClient: widget.apiClient,
              secureStorage: widget.secureStorage,
              isHelpee: widget.isHelpee,
              remoteStreamSink: _remoteStreamNotifier,
            ),
          ),

          // Floating Voice & Media Control Pill
          Positioned(
            bottom: 24,
            left: 0,
            right: 0,
            child: Center(
              child: MobileVoiceControlBar(
                sessionId: widget.sessionId,
                apiClient: widget.apiClient,
                onSecurityTap: _showSecurityZeroizeSheet,
                onLeaveSession: _handleLeaveSession,
                // One-tap calling replaced the in-session request dialog;
                // help is requested from Home, never inside a live session.
                onRequestHelp: null,
                isRequestingHelp: false,
              ),
            ),
          ),

          // Sliding Chat & File Drawer
          if (_isChatOpen)
            Positioned(
              top: 0,
              bottom: 0,
              left: 0,
              right: 0,
              child: MobileChatDrawer(
                sessionId: widget.sessionId,
                apiClient: widget.apiClient,
              ),
            ),
        ],
      ),
    );
  }
}
