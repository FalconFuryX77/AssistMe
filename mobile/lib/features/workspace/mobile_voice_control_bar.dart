import 'package:flutter/material.dart';
import '../../core/network/api_client.dart';
import '../../theme/app_theme.dart';

class MobileVoiceControlBar extends StatefulWidget {
  final String sessionId;
  final ApiClient apiClient;
  final VoidCallback onSecurityTap;
  final VoidCallback onLeaveSession;

  const MobileVoiceControlBar({
    Key? key,
    required this.sessionId,
    required this.apiClient,
    required this.onSecurityTap,
    required this.onLeaveSession,
  }) : super(key: key);

  @override
  State<MobileVoiceControlBar> createState() => _MobileVoiceControlBarState();
}

class _MobileVoiceControlBarState extends State<MobileVoiceControlBar> {
  bool _isMuted = false;
  String _audioRoute = 'speaker';

  Future<void> _toggleMute() async {
    final nextMute = !_isMuted;
    setState(() => _isMuted = nextMute);

    try {
      await widget.apiClient.post(
        '/sessions/${widget.sessionId}/audio/mute',
        body: {'is_muted': nextMute},
      );
    } catch (e) {
      debugPrint('Mute toggle notice: $e');
    }
  }

  Future<void> _showAudioRouteSheet() async {
    final selected = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: AppTheme.bgSecondary,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Padding(
                padding: EdgeInsets.all(16.0),
                child: Text(
                  'Audio Output Routing',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
              ),
              ListTile(
                leading: const Icon(Icons.volume_up, color: AppTheme.accentPrimary),
                title: const Text('Speaker'),
                trailing: _audioRoute == 'speaker' ? const Icon(Icons.check, color: AppTheme.accentEmerald) : null,
                onTap: () => Navigator.pop(ctx, 'speaker'),
              ),
              ListTile(
                leading: const Icon(Icons.phone_android, color: AppTheme.accentSecondary),
                title: const Text('Earpiece'),
                trailing: _audioRoute == 'earpiece' ? const Icon(Icons.check, color: AppTheme.accentEmerald) : null,
                onTap: () => Navigator.pop(ctx, 'earpiece'),
              ),
              ListTile(
                leading: const Icon(Icons.bluetooth_audio, color: AppTheme.accentAmber),
                title: const Text('Bluetooth'),
                trailing: _audioRoute == 'bluetooth' ? const Icon(Icons.check, color: AppTheme.accentEmerald) : null,
                onTap: () => Navigator.pop(ctx, 'bluetooth'),
              ),
              ListTile(
                leading: const Icon(Icons.headset, color: AppTheme.accentRose),
                title: const Text('Headset'),
                trailing: _audioRoute == 'headset' ? const Icon(Icons.check, color: AppTheme.accentEmerald) : null,
                onTap: () => Navigator.pop(ctx, 'headset'),
              ),
            ],
          ),
        );
      },
    );

    if (selected != null) {
      setState(() => _audioRoute = selected);
      try {
        await widget.apiClient.post(
          '/sessions/${widget.sessionId}/audio/route',
          body: {'audio_route': selected},
        );
      } catch (e) {
        debugPrint('Audio route notice: $e');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
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
          // Mute Button
          IconButton(
            icon: Icon(_isMuted ? Icons.mic_off : Icons.mic),
            color: _isMuted ? AppTheme.accentRose : AppTheme.textPrimary,
            onPressed: _toggleMute,
          ),
          const SizedBox(width: 8),

          // Route Button
          IconButton(
            icon: const Icon(Icons.speaker_phone),
            color: AppTheme.accentSecondary,
            onPressed: _showAudioRouteSheet,
          ),
          const SizedBox(width: 8),

          // Security / E2EE Button
          IconButton(
            icon: const Icon(Icons.shield_outlined),
            color: AppTheme.accentEmerald,
            onPressed: widget.onSecurityTap,
          ),
          const SizedBox(width: 8),

          // Leave Button
          IconButton(
            icon: const Icon(Icons.call_end),
            color: AppTheme.accentRose,
            onPressed: widget.onLeaveSession,
          ),
        ],
      ),
    );
  }
}
