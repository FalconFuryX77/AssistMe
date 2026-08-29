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
    super.key,
    required this.sessionId,
    required this.sessionCode,
    required this.apiClient,
    required this.secureStorage,
    this.isHelpee = true,
    this.autoStartScreenShare = false,
    this.peerName = 'your contact',
    this.onSessionClosed,
    this.onSessionEnded,
  });

  @override
  State<MobileWorkspaceScreen> createState() => _MobileWorkspaceScreenState();
}

class _MobileWorkspaceScreenState extends State<MobileWorkspaceScreen> with WidgetsBindingObserver {
  final _flowCoordinatorKey = GlobalKey<AssistanceFlowCoordinatorState>();

  // Live remote media stream, published by the flow coordinator's WebRTC
  // engine and consumed by the remote viewport.
  final ValueNotifier<dynamic> _remoteStreamNotifier = ValueNotifier<dynamic>(null);
  final ValueNotifier<bool> _remoteControlNotifier = ValueNotifier<bool>(false);
  final ValueNotifier<bool> _annotationModeNotifier = ValueNotifier<bool>(false);
  final ValueNotifier<double> _aspectRatioNotifier = ValueNotifier<double>(9 / 16);
  bool _leaving = false;
  bool _allowPop = false;
  Offset _voiceBarOffset = Offset.zero;

  Offset _boundedOffset(Offset offset) => Offset(
    offset.dx.clamp(-180.0, 180.0).toDouble(),
    offset.dy.clamp(-320.0, 320.0).toDouble(),
  );

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Process kept alive by Android foreground service
  }

  Future<void> _handleLeaveSession() async {
    if (_leaving) return;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Leave Help Session?'),
        content: const Text(
          'Ending this call will end the assistance session for both of you.',
          style: TextStyle(color: AppTheme.textSecondary, fontSize: 16),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Stay in call', style: TextStyle(fontSize: 16)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.accentRose),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('End Call'),
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
        backgroundColor: AppTheme.bgPrimary,
        appBar: AppBar(
          title: Text(
            widget.isHelpee ? 'Help from ${widget.peerName}' : 'Helping ${widget.peerName}',
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
          ),
          backgroundColor: AppTheme.bgSecondary,
        ),
        body: SafeArea(
          child: Column(
            children: [
              // Bounded remote viewport (VISION §12.6)
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(20),
                    child: Container(
                      color: Colors.black,
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          if (!widget.isHelpee)
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
                                      onAspectRatioChanged: (aspect) {
                                        _aspectRatioNotifier.value = aspect;
                                      },
                                      onRemoteInput: (event) {
                                        _flowCoordinatorKey.currentState?.sendRemoteInput(
                                          event,
                                        );
                                      },
                                    ),
                                  ),
                            )
                          else
                            Container(
                              color: AppTheme.bgPrimary,
                              child: Center(
                                child: ValueListenableBuilder<dynamic>(
                                  valueListenable: _remoteStreamNotifier,
                                  builder: (context, stream, _) => _helpeeSharingPlaceholder(stream != null),
                                ),
                              ),
                            ),

                          // Assistance flow coordinator
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
                              contentAspectRatioNotifier: _aspectRatioNotifier,
                            ),
                          ),

                          // Status banner for helpee
                          if (widget.isHelpee)
                            Positioned(
                              top: 14,
                              left: 14,
                              right: 14,
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

              // Helper annotation toolbar BELOW viewport
              if (!widget.isHelpee) _helperAnnotationRow(),

              // Voice controls
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
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: sharing ? AppTheme.accentEmerald.withValues(alpha: 0.95) : AppTheme.accentAmber.withValues(alpha: 0.95),
        borderRadius: BorderRadius.circular(16),
        boxShadow: const [BoxShadow(color: Colors.black38, blurRadius: 8, offset: Offset(0, 2))],
      ),
      child: Row(
        children: [
          Icon(sharing ? Icons.videocam : Icons.videocam_off, size: 20, color: Colors.white),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              sharing ? 'Your screen is live — helper can see and guide you' : 'Tap Start Sharing below to begin',
              style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w800),
            ),
          ),
        ],
      ),
    );
  }

  Widget _helpeeSharingPlaceholder(bool sharing) {
    return Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: (sharing ? AppTheme.accentEmerald : AppTheme.accentAmber).withValues(alpha: 0.15),
              shape: BoxShape.circle,
            ),
            child: Icon(
              sharing ? Icons.check_circle : Icons.screen_share,
              size: 56,
              color: sharing ? AppTheme.accentEmerald : AppTheme.accentAmber,
            ),
          ),
          const SizedBox(height: 20),
          Text(
            sharing ? 'Screen Sharing Active' : 'Ready to Start',
            style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 10),
          Text(
            sharing
                ? 'Your helper can see your screen. You can use your phone normally.\nUse DRAW to point, and STOP to end.'
                : 'Tap the green Start Sharing button to let your helper see your screen.',
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppTheme.textSecondary, fontSize: 15, height: 1.4),
          ),
        ],
      ),
    );
  }

  Widget _helperAnnotationRow() {
    return ValueListenableBuilder<bool>(
      valueListenable: _remoteControlNotifier,
      builder: (context, granted, _) => ValueListenableBuilder<bool>(
        valueListenable: _annotationModeNotifier,
        builder: (context, annotationMode, _) => Container(
          margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: AppTheme.bgSecondary.withValues(alpha: 0.98),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: AppTheme.borderGlassStrong),
          ),
          child: Row(
            children: [
              if (!granted) ...[
                const Icon(Icons.visibility, size: 18, color: AppTheme.accentEmerald),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'Viewing Screen',
                    style: TextStyle(color: AppTheme.textPrimary, fontSize: 14, fontWeight: FontWeight.w700),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 8),
                ElevatedButton.icon(
                  icon: const Icon(Icons.touch_app, size: 16),
                  label: const Text('Request Control', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.accentPrimary,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    minimumSize: Size.zero,
                  ),
                  onPressed: () => _flowCoordinatorKey.currentState?.requestControl(),
                ),
              ] else ...[
                Expanded(
                  child: _modeButton(
                    label: 'Touch Control',
                    icon: Icons.touch_app,
                    selected: !annotationMode,
                    onPressed: () => _annotationModeNotifier.value = false,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _modeButton(
                    label: 'Draw / Guide',
                    icon: Icons.edit,
                    selected: annotationMode,
                    onPressed: () => _annotationModeNotifier.value = true,
                  ),
                ),
              ],
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
    return ElevatedButton.icon(
      onPressed: onPressed,
      icon: Icon(icon, size: 16),
      label: Text(
        label,
        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
        overflow: TextOverflow.ellipsis,
      ),
      style: ElevatedButton.styleFrom(
        foregroundColor: selected ? Colors.white : AppTheme.textSecondary,
        backgroundColor: selected ? AppTheme.accentEmerald : AppTheme.bgCard,
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 10),
        minimumSize: Size.zero,
        elevation: selected ? 2 : 0,
      ),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _remoteStreamNotifier.dispose();
    _remoteControlNotifier.dispose();
    _annotationModeNotifier.dispose();
    super.dispose();
  }
}
