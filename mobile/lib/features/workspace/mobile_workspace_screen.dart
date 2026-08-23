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
  final bool autoStartScreenShare;

  const MobileWorkspaceScreen({
    Key? key,
    required this.sessionId,
    required this.sessionCode,
    required this.apiClient,
    required this.secureStorage,
    this.isHelpee = true,
    this.autoStartScreenShare = false,
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

  void _handleLeaveSession() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Leave help session?'),
        content: const Text('The call will end for both of you.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Stay')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Leave')),
        ],
      ),
    );
    if (confirm != true) return;
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
              autoStartScreenShare: widget.autoStartScreenShare,
              remoteStreamSink: _remoteStreamNotifier,
            ),
          ),

          // Floating Voice Control - just mic + leave
          Positioned(
            bottom: 24,
            left: 0,
            right: 0,
            child: Center(
              child: MobileVoiceControlBar(
                sessionId: widget.sessionId,
                apiClient: widget.apiClient,
                onLeaveSession: _handleLeaveSession,
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
