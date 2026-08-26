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
        // VISION §12.6: helper workspace must remain inside the app. No immersive
        // fullscreen – viewport is bounded, controls stay visible.
        backgroundColor: AppTheme.bgPrimary,
        appBar: AppBar(
          title: Text('Help session · ${widget.peerName}'),
          backgroundColor: AppTheme.bgSecondary,
        ),
        body: SafeArea(
          child: Column(
            children: [
              // ── Bounded remote viewport (VISION §12.6) ──
              // Helper sees live helpee screen at useful bounded size, not
              // consuming entire screen. Black letterbox keeps aspect correct.
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(16),
                    child: Container(
                      color: Colors.black,
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          // Remote Screen Viewport – bounded, not fullscreen
                          ValueListenableBuilder<bool>(
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

                          // Assistance flow coordinator – its Stack is now
                          // constrained to this bounded viewport, so drawing
                          // coordinates map exactly to the video rect (no
                          // full-screen mismatch). Coordinator still owns
                          // realtime + popups + overlay routing.
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

                          // NOTE: Control/Guide switch removed from floating position per user request.
                          // It now lives in the bottom bar near Request control (see _helperAnnotationRow).
                          // Only the annotation dock (pen/eraser/color) remains floating.

                          // Status banner for helpee – always visible, never
                          // obscurable by drawing per VISION §6.
                          if (widget.isHelpee)
                            Positioned(
                              top: 8,
                              left: 8,
                              right: 8,
                              child: ValueListenableBuilder<dynamic>(
                                valueListenable: _remoteStreamNotifier,
                                builder: (context, stream, _) => _helpeeStatusBanner(stream != null),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),

              // ── Helper annotation toolbar BELOW viewport (VISION §12.6) ──
              // Always visible, not hidden. Helper can also drag it via handle;
              // viewport remains bounded so toolbar never needs to cover video.
              if (!widget.isHelpee) _helperAnnotationRow(),

              // ── Voice controls – always visible, movable via handle ──
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                child: Center(
                  child: Transform.translate(
                    offset: _voiceBarOffset,
                    child: GestureDetector(
                      behavior: HitTestBehavior.translucent,
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
      ),
    );
  }

  Widget _helpeeStatusBanner(bool sharing) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: sharing ? AppTheme.accentEmerald.withValues(alpha: 0.92) : AppTheme.accentAmber.withValues(alpha: 0.95),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(sharing ? Icons.videocam : Icons.videocam_off, size: 16, color: Colors.white),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              sharing ? 'Sharing your screen — helper can see it' : 'Tap Start Sharing to let helper see your screen',
              style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }

  Widget _helperAnnotationRow() {
    // Bottom bar: View/Guide status + Control/Guide switch + Request control – all non-floating per user request.
    // Only the annotation dock (pen/eraser/color inside viewport) remains floating.
    return ValueListenableBuilder<bool>(
      valueListenable: _remoteControlNotifier,
      builder: (context, granted, _) => ValueListenableBuilder<bool>(
        valueListenable: _annotationModeNotifier,
        builder: (context, annotationMode, _) => Container(
          margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            color: AppTheme.bgSecondary.withValues(alpha: 0.97),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppTheme.borderGlass),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (!granted) ...[
                const Icon(Icons.edit, size: 16, color: AppTheme.accentEmerald),
                const SizedBox(width: 6),
                const Text('View', style: TextStyle(color: AppTheme.textPrimary, fontSize: 12, fontWeight: FontWeight.w700)),
                const SizedBox(width: 10),
                ElevatedButton.icon(
                  icon: const Icon(Icons.open_in_full, size: 14),
                  label: const Text('Request control', style: TextStyle(fontSize: 11)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.accentPrimary,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  onPressed: () => _flowCoordinatorKey.currentState?.requestControl(),
                ),
              ] else ...[
                // When control granted, show Control/Guide toggle right here at bottom near Request control position
                _modeButton(
                  label: 'Control',
                  icon: Icons.touch_app,
                  selected: !annotationMode,
                  onPressed: () => _annotationModeNotifier.value = false,
                ),
                const SizedBox(width: 4),
                _modeButton(
                  label: 'Guide',
                  icon: Icons.edit,
                  selected: annotationMode,
                  onPressed: () => _annotationModeNotifier.value = true,
                ),
              ],
            ],
          ),
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
        color: AppTheme.bgSecondary.withValues(alpha: 0.96),
        borderRadius: BorderRadius.circular(18),
        elevation: 8,
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
            ? AppTheme.accentEmerald.withValues(alpha: 0.16)
            : null,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      ),
    );
  }
}
