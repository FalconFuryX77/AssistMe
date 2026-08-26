import 'package:flutter/material.dart';
import '../../core/network/api_client.dart';
import '../../theme/app_theme.dart';

class MobileVoiceControlBar extends StatefulWidget {
  final String sessionId;
  final ApiClient apiClient;
  final VoidCallback onLeaveSession;
  final Future<void> Function(bool muted)? onMuteChanged;

  const MobileVoiceControlBar({
    Key? key,
    required this.sessionId,
    required this.apiClient,
    required this.onLeaveSession,
    this.onMuteChanged,
  }) : super(key: key);

  @override
  State<MobileVoiceControlBar> createState() => _MobileVoiceControlBarState();
}

class _MobileVoiceControlBarState extends State<MobileVoiceControlBar> {
  bool _isMuted = false;

  Future<void> _toggleMute() async {
    final nextMute = !_isMuted;
    try {
      await widget.onMuteChanged?.call(nextMute);
      await widget.apiClient.post(
        '/sessions/${widget.sessionId}/audio/mute',
        body: {'is_muted': nextMute},
      );
      if (mounted) setState(() => _isMuted = nextMute);
    } catch (e) {
      debugPrint('Mute toggle: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not change microphone state')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      decoration: BoxDecoration(
        color: AppTheme.bgSecondary.withOpacity(0.95),
        borderRadius: BorderRadius.circular(32),
        border: Border.all(color: AppTheme.borderGlass),
        boxShadow: const [
          BoxShadow(
            color: Colors.black54,
            blurRadius: 16,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Mic - big and obvious
          IconButton(
            icon: Icon(_isMuted ? Icons.mic_off : Icons.mic, size: 28),
            color: _isMuted ? AppTheme.accentRose : AppTheme.accentEmerald,
            tooltip: _isMuted ? 'Unmute' : 'Mute',
            onPressed: _toggleMute,
          ),
          const SizedBox(width: 16),
          Container(width: 1, height: 28, color: AppTheme.borderGlass),
          const SizedBox(width: 16),
          // Leave
          IconButton(
            icon: const Icon(Icons.call_end, size: 28),
            color: Colors.white,
            style: IconButton.styleFrom(backgroundColor: AppTheme.accentRose),
            onPressed: widget.onLeaveSession,
          ),
        ],
      ),
    );
  }
}
