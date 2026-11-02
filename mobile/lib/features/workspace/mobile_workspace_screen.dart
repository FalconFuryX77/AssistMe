import 'dart:io';

import 'package:flutter/material.dart';
import '../../core/guides/local_guide_audio_capture.dart';
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

class _MobileWorkspaceScreenState extends State<MobileWorkspaceScreen>
    with WidgetsBindingObserver {
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
  final ValueNotifier<double> _aspectRatioNotifier = ValueNotifier<double>(
    9 / 16,
  );
  final ValueNotifier<bool> _screenShareNotifier = ValueNotifier<bool>(false);
  final ValueNotifier<bool> _guideStepBusy = ValueNotifier<bool>(false);
  final ValueNotifier<GuideAudioCaptureStatus> _guideAudioStatusNotifier =
      ValueNotifier<GuideAudioCaptureStatus>(GuideAudioCaptureStatus.off);
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
        content: Text(
          'Ending this call will end the assistance session for both of you.',
          style: TextStyle(
            color: AppTheme.textSecondary,
            fontSize: AppTypography.body,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text(
              'Stay in call',
              style: TextStyle(fontSize: AppTypography.body),
            ),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.accentRose,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('End Call'),
          ),
        ],
      ),
    );
    if (confirm != true) return;
    _leaving = true;
    try {
      await _flowCoordinatorKey.currentState?.leave();
    } catch (_) {}
    try {
      await widget.apiClient.post('/sessions/${widget.sessionId}/leave');
    } catch (_) {}
    await widget.secureStorage.clearActiveSession();
    await widget.onSessionClosed?.call();
    if (!mounted) return;
    setState(() => _allowPop = true);
    if (Navigator.of(context).canPop()) {
      Navigator.of(context).pop();
    }
  }

  Future<void> _handleRemoteSessionEnded() async {
    if (_leaving) return;
    _leaving = true;
    await widget.secureStorage.clearActiveSession();
    await widget.onSessionClosed?.call();
    if (!mounted) return;
    setState(() => _allowPop = true);
    if (Navigator.of(context).canPop()) {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    Theme.of(
      context,
    ); // Rebuild legacy color-token widgets when the app theme changes.
    return PopScope(
      canPop: _allowPop,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _handleLeaveSession();
      },
      child: Scaffold(
        backgroundColor: AppTheme.bgPrimary,
        appBar: AppBar(
          title: Text(
            widget.isHelpee
                ? 'Help from ${widget.peerName}'
                : 'Helping ${widget.peerName}',
            style: const TextStyle(
              fontSize: AppTypography.heading,
              fontWeight: FontWeight.w700,
            ),
          ),
          backgroundColor: AppTheme.bgSecondary,
        ),
        body: SafeArea(
          child: Column(
            children: [
              // Keep sharing status outside the remote viewport so it never
              // covers the controls or the disconnect/reconnect banner.
              if (widget.isHelpee)
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
                  child: ValueListenableBuilder<bool>(
                    valueListenable: _screenShareNotifier,
                    builder: (context, sharing, _) =>
                        _helpeeStatusBanner(sharing),
                  ),
                ),
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
                                    builder: (context, annotationMode, _) =>
                                        RemoteScreenView(
                                          sessionId: widget.sessionId,
                                          apiClient: widget.apiClient,
                                          remoteStreamNotifier:
                                              _remoteStreamNotifier,
                                          allowRemoteControl:
                                              allowRemoteControl &&
                                              !annotationMode &&
                                              !widget.isHelpee,
                                          onAspectRatioChanged: (aspect) {
                                            _aspectRatioNotifier.value = aspect;
                                          },
                                          onRemoteInput: (event) {
                                            _flowCoordinatorKey.currentState
                                                ?.sendRemoteInput(event);
                                          },
                                        ),
                                  ),
                            )
                          else
                            Container(
                              color: AppTheme.bgPrimary,
                              child: Center(
                                child: ValueListenableBuilder<bool>(
                                  valueListenable: _screenShareNotifier,
                                  builder: (context, sharing, _) =>
                                      _helpeeSharingPlaceholder(sharing),
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
                              screenSharingSink: _screenShareNotifier,
                              guideAudioStatusSink: _guideAudioStatusNotifier,
                              guideStepBusySink: _guideStepBusy,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),

              // Helper annotation toolbar BELOW viewport
              if (!widget.isHelpee) ...[
                _helperAnnotationRow(),
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
                  child: SizedBox(
                    width: double.infinity,
                    child: ValueListenableBuilder<bool>(
                      valueListenable: _guideStepBusy,
                      builder: (context, busy, _) => FilledButton.icon(
                        // A closure: the coordinator's state does not exist
                        // yet on the first build, and a null tear-off would
                        // leave the button disabled for the whole call.
                        onPressed: busy
                            ? null
                            : () => _flowCoordinatorKey.currentState
                                  ?.captureGuideStep(),
                        icon: busy
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(strokeWidth: 2.5),
                              )
                            : const Icon(Icons.add_photo_alternate_outlined),
                        label: Text(
                          busy ? 'Capturing…' : 'Capture step for guide',
                        ),
                      ),
                    ),
                  ),
                ),
              ] else
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
                  child: SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () => _flowCoordinatorKey.currentState
                          ?.requestGuideScreenshot(),
                      icon: const Icon(Icons.add_a_photo_outlined),
                      label: const Text('Request a guide screenshot'),
                    ),
                  ),
                ),

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
                          await _flowCoordinatorKey.currentState
                              ?.toggleAudioMute(muted);
                        },
                        guideAudioStatus: _guideAudioStatusNotifier,
                        showGuideAudioControl: Platform.isAndroid,
                        isGuideAudioHelper: !widget.isHelpee,
                        onGuideAudioControl: () async {
                          await _flowCoordinatorKey.currentState
                              ?.toggleGuideAudioControl();
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
        color: sharing ? const Color(0xFF047857) : const Color(0xFFFFF3C4),
        borderRadius: BorderRadius.circular(16),
        boxShadow: const [
          BoxShadow(color: Colors.black38, blurRadius: 8, offset: Offset(0, 2)),
        ],
      ),
      child: Row(
        children: [
          Icon(
            sharing ? Icons.videocam : Icons.videocam_off,
            size: 20,
            color: sharing ? Colors.white : const Color(0xFF422006),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              sharing
                  ? 'Screen capture is active'
                  : 'Tap Start Sharing below to begin',
              style: TextStyle(
                color: sharing ? Colors.white : const Color(0xFF422006),
                fontSize: AppTypography.bodySmall,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _helpeeSharingPlaceholder(bool sharing) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxHeight < 400;
        final iconSize = compact ? 38.0 : 56.0;
        final gap = compact ? 8.0 : 18.0;
        final titleSize = compact
            ? AppTypography.bodyLarge
            : AppTypography.title;
        final bodySize = compact
            ? AppTypography.caption
            : AppTypography.bodySmall;
        return SingleChildScrollView(
          padding: EdgeInsets.all(compact ? 8 : 24),
          child: ConstrainedBox(
            constraints: BoxConstraints(
              minHeight: constraints.maxHeight - (compact ? 16 : 48),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  padding: EdgeInsets.all(compact ? 10 : 16),
                  decoration: BoxDecoration(
                    color:
                        (sharing
                                ? AppTheme.accentEmerald
                                : AppTheme.accentAmber)
                            .withValues(alpha: 0.15),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    sharing ? Icons.check_circle : Icons.screen_share,
                    size: iconSize,
                    color: sharing
                        ? AppTheme.accentEmerald
                        : AppTheme.accentAmber,
                  ),
                ),
                SizedBox(height: gap),
                Text(
                  sharing ? 'Screen Sharing Active' : 'Ready to Share',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: titleSize,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                SizedBox(height: compact ? 6 : 10),
                Text(
                  sharing
                      ? 'Your helper can see your screen. You can use your phone normally.\nTap Stop Sharing below to end sharing.'
                      : 'Tap Start Sharing below so your helper can view and guide your screen.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: bodySize,
                    height: 1.3,
                  ),
                ),
                SizedBox(height: compact ? 10 : 20),
                ElevatedButton.icon(
                  icon: Icon(
                    sharing ? Icons.stop_screen_share : Icons.screen_share,
                    size: compact ? 18 : 22,
                  ),
                  label: Text(
                    sharing ? 'Stop Sharing' : 'Start Sharing',
                    style: TextStyle(
                      fontSize: compact
                          ? AppTypography.bodySmall
                          : AppTypography.body,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: sharing
                        ? AppTheme.accentRose
                        : AppTheme.accentEmeraldAccessible,
                    foregroundColor: Colors.white,
                    padding: EdgeInsets.symmetric(
                      horizontal: compact ? 18 : 28,
                      vertical: compact ? 10 : 16,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16),
                    ),
                    elevation: 4,
                  ),
                  onPressed: () {
                    if (sharing) {
                      _flowCoordinatorKey.currentState?.stopScreenShare();
                    } else {
                      _flowCoordinatorKey.currentState?.startScreenShare();
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
                const Icon(
                  Icons.visibility,
                  size: 18,
                  color: AppTheme.accentEmerald,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Viewing Screen',
                    style: TextStyle(
                      color: AppTheme.textPrimary,
                      fontSize: AppTypography.bodySmall,
                      fontWeight: FontWeight.w600,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 8),
                ElevatedButton.icon(
                  icon: const Icon(Icons.touch_app, size: 16),
                  label: const Text(
                    'Request Control',
                    style: TextStyle(
                      fontSize: AppTypography.caption,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.accentPrimary,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 8,
                    ),
                    minimumSize: Size.zero,
                  ),
                  onPressed: () =>
                      _flowCoordinatorKey.currentState?.requestControl(),
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
        style: const TextStyle(
          fontSize: AppTypography.caption,
          fontWeight: FontWeight.w600,
        ),
        overflow: TextOverflow.ellipsis,
      ),
      style: ElevatedButton.styleFrom(
        foregroundColor: selected ? Colors.white : AppTheme.textSecondary,
        backgroundColor: selected
            ? AppTheme.accentEmeraldAccessible
            : AppTheme.bgCard,
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
    _screenShareNotifier.dispose();
    _guideAudioStatusNotifier.dispose();
    _guideStepBusy.dispose();
    super.dispose();
  }
}
