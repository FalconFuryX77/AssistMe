import 'package:flutter/material.dart';
import '../../core/network/api_client.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';
import 'remote_screen_view.dart';
import 'mobile_voice_control_bar.dart';
import 'assistance_flow_coordinator.dart';

class MobileWorkspaceScreen extends StatefulWidget {
  final String sessionId;
  final String sessionCode;
  final ApiClient apiClient;
  final SecureStorageService secureStorage;
  final bool isHelpee;
  final bool autoStartScreenShare;
  final String peerName;
  final Future<void> Function()? onSessionClosed;
  final Future<void> Function()? onSessionEnded;

  const MobileWorkspaceScreen({
    Key? key,
    required this.sessionId,
    required this.sessionCode,
    required this.apiClient,
    required this.secureStorage,
    this.isHelpee = true,
    this.autoStartScreenShare = false,
    this.peerName = 'your contact',
    this.onSessionClosed,
    this.onSessionEnded,
  }) : super(key: key);

  @override
  State<MobileWorkspaceScreen> createState() => _MobileWorkspaceScreenState();
}

class _MobileWorkspaceScreenState extends State<MobileWorkspaceScreen> {
  final _flowCoordinatorKey = GlobalKey<AssistanceFlowCoordinatorState>();

  // Live remote media stream, published by the flow coordinator's WebRTC
  // engine and consumed by the remote viewport.
  final ValueNotifier<dynamic> _remoteStreamNotifier = ValueNotifier<dynamic>(
    null,
  );
  final ValueNotifier<bool> _remoteControlNotifier = ValueNotifier<bool>(false);
  final ValueNotifier<bool> _annotationModeNotifier = ValueNotifier<bool>(
    false,
  );
  bool _leaving = false;
  bool _allowPop = false;
  Offset _modeSwitcherOffset = Offset.zero;
  Offset _voiceBarOffset = Offset.zero;

  Offset _boundedOffset(Offset offset) => Offset(
    offset.dx.clamp(-180.0, 180.0).toDouble(),
    offset.dy.clamp(-320.0, 320.0).toDouble(),
  );

  Future<void> _handleLeaveSession() async {
    if (_leaving) return;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Leave help session?'),
        content: const Text('The call will end for both of you.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Stay'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Leave'),
          ),
        ],
      ),
    );
    if (confirm != true) return;
    _leaving = true;
    try {
      await widget.apiClient.post('/sessions/${widget.sessionId}/leave');
    } catch (_) {}
    await widget.onSessionClosed?.call();
    if (!mounted) return;
    setState(() => _allowPop = true);
    Navigator.of(context).pop();
  }

  Future<void> _handleRemoteSessionEnded() async {
    await widget.onSessionClosed?.call();
    if (!mounted) return;
    setState(() => _allowPop = true);
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _allowPop,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _handleLeaveSession();
      },
      child: Scaffold(
        // Keep the helper workspace inside the app. Hiding the app bar and
        // switching to immersive mode makes the remote viewport overlap the
        // Android navigation area and also hides the helper's controls.
        appBar: AppBar(title: Text('Help session · ${widget.peerName}')),
        body: Stack(
          children: [
            // Remote Screen Viewport
            Positioned.fill(
              child: ValueListenableBuilder<bool>(
                valueListenable: _remoteControlNotifier,
                builder: (context, allowRemoteControl, _) =>
                    ValueListenableBuilder<bool>(
                      valueListenable: _annotationModeNotifier,
                      builder: (context, annotationMode, _) => RemoteScreenView(
                        sessionId: widget.sessionId,
                        apiClient: widget.apiClient,
                        remoteStreamNotifier: _remoteStreamNotifier,
                        allowRemoteControl:
                            allowRemoteControl &&
                            !annotationMode &&
                            !widget.isHelpee,
                        onRemoteInput: (event) {
                          _flowCoordinatorKey.currentState?.sendRemoteInput(
                            event,
                          );
                        },
                      ),
                    ),
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
                peerName: widget.peerName,
                onSessionClosed: widget.onSessionClosed,
                onSessionEnded: _handleRemoteSessionEnded,
                remoteStreamSink: _remoteStreamNotifier,
                remoteControlSink: _remoteControlNotifier,
                annotationModeSink: _annotationModeNotifier,
              ),
            ),

            if (!widget.isHelpee)
              ValueListenableBuilder<bool>(
                valueListenable: _remoteControlNotifier,
                builder: (context, granted, _) {
                  if (!granted) return const SizedBox.shrink();
                  return Positioned(
                    top: 12,
                    left: 0,
                    right: 0,
                    child: Center(
                      child: Transform.translate(
                        offset: _modeSwitcherOffset,
                        child: GestureDetector(
                          onPanUpdate: (details) => setState(() {
                            _modeSwitcherOffset = _boundedOffset(
                              _modeSwitcherOffset + details.delta,
                            );
                          }),
                          child: _phaseModeSwitcher(),
                        ),
                      ),
                    ),
                  );
                },
              ),

            // Floating Voice Control - just mic + leave
            Positioned(
              bottom: 24,
              left: 0,
              right: 0,
              child: Center(
                child: Transform.translate(
                  offset: _voiceBarOffset,
                  child: GestureDetector(
                    onPanUpdate: (details) => setState(() {
                      _voiceBarOffset = _boundedOffset(
                        _voiceBarOffset + details.delta,
                      );
                    }),
                    child: MobileVoiceControlBar(
                      sessionId: widget.sessionId,
                      apiClient: widget.apiClient,
                      onLeaveSession: _handleLeaveSession,
                      onMuteChanged: (muted) async {
                        await _flowCoordinatorKey.currentState?.toggleAudioMute(
                          muted,
                        );
                      },
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _remoteStreamNotifier.dispose();
    _remoteControlNotifier.dispose();
    _annotationModeNotifier.dispose();
    super.dispose();
  }

  Widget _phaseModeSwitcher() {
    return ValueListenableBuilder<bool>(
      valueListenable: _annotationModeNotifier,
      builder: (context, annotationMode, _) => Material(
        color: AppTheme.bgSecondary.withOpacity(0.94),
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.all(4),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              _modeButton(
                label: 'Control',
                icon: Icons.touch_app,
                selected: !annotationMode,
                onPressed: () => _annotationModeNotifier.value = false,
              ),
              _modeButton(
                label: 'Guide',
                icon: Icons.edit,
                selected: annotationMode,
                onPressed: () => _annotationModeNotifier.value = true,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _modeButton({
    required String label,
    required IconData icon,
    required bool selected,
    required VoidCallback onPressed,
  }) {
    return TextButton.icon(
      onPressed: onPressed,
      icon: Icon(icon, size: 17),
      label: Text(label),
      style: TextButton.styleFrom(
        foregroundColor: selected
            ? AppTheme.accentEmerald
            : AppTheme.textSecondary,
        backgroundColor: selected
            ? AppTheme.accentEmerald.withOpacity(0.16)
            : null,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      ),
    );
  }
}
