import 'dart:convert';
import 'package:flutter/material.dart';
import '../../core/network/api_client.dart';
import '../../theme/app_theme.dart';

class MobileChatMessage {
  final String id;
  final String content;
  final bool isEncrypted;
  final bool isMe;

  MobileChatMessage({
    required this.id,
    required this.content,
    this.isEncrypted = false,
    this.isMe = true,
  });
}

class MobileChatDrawer extends StatefulWidget {
  final String sessionId;
  final ApiClient apiClient;

  const MobileChatDrawer({
    Key? key,
    required this.sessionId,
    required this.apiClient,
  }) : super(key: key);

  @override
  State<MobileChatDrawer> createState() => _MobileChatDrawerState();
}

class _MobileChatDrawerState extends State<MobileChatDrawer> {
  final List<MobileChatMessage> _messages = [];
  final _inputController = TextEditingController();
  bool _isEncrypted = false;
  double? _uploadProgress;

  Future<void> _handleSendMessage() async {
    final text = _inputController.text.trim();
    if (text.isEmpty) return;

    final newMsg = MobileChatMessage(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      content: text,
      isEncrypted: _isEncrypted,
      isMe: true,
    );

    setState(() {
      _messages.add(newMsg);
      _inputController.clear();
    });

    try {
      await widget.apiClient.post(
        '/sessions/${widget.sessionId}/chat/messages',
        body: {
          'content': text,
          'is_encrypted': _isEncrypted,
        },
      );
    } catch (e) {
      debugPrint('Chat error notice: $e');
    }
  }

  Future<void> _simulateChunkedFileUpload() async {
    setState(() => _uploadProgress = 0.1);
    try {
      final dummyChecksum = 'a' * 64;
      final initResp = await widget.apiClient.post(
        '/sessions/${widget.sessionId}/files/initiate',
        body: {
          'filename': 'mobile_debug_log.txt',
          'file_size_bytes': 2048,
          'checksum_sha256': dummyChecksum,
        },
      );

      if (initResp.statusCode == 200) {
        final data = jsonDecode(initResp.body);
        setState(() => _uploadProgress = 0.6);

        await widget.apiClient.post(
          '/sessions/${widget.sessionId}/files/${data['id']}/chunks',
          body: {
            'chunk_index': 0,
            'chunk_payload': 'bW9iaWxlX2ZpbGVfcGF5bG9hZA==',
          },
        );

        setState(() => _uploadProgress = 0.9);

        await widget.apiClient.post(
          '/sessions/${widget.sessionId}/files/${data['id']}/complete',
        );

        setState(() => _uploadProgress = 1.0);
        await Future.delayed(const Duration(seconds: 2));
      }
    } catch (e) {
      debugPrint('File upload notice: $e');
    } finally {
      if (mounted) setState(() => _uploadProgress = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: AppTheme.bgCard,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: Column(
        children: [
          // Drawer Header
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 12.0),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'In-App Chat & Files',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                ),
                Row(
                  children: [
                    const Text('E2EE', style: TextStyle(fontSize: 12, color: AppTheme.textSecondary)),
                    Switch(
                      value: _isEncrypted,
                      activeColor: AppTheme.accentEmerald,
                      onChanged: (val) => setState(() => _isEncrypted = val),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const Divider(height: 1, color: AppTheme.borderGlass),

          // Upload Progress Bar
          if (_uploadProgress != null)
            LinearProgressIndicator(
              value: _uploadProgress,
              backgroundColor: AppTheme.bgSecondary,
              valueColor: const AlwaysStoppedAnimation(AppTheme.accentEmerald),
            ),

          // Messages List
          Expanded(
            child: _messages.isEmpty
                ? const Center(
                    child: Text(
                      'No messages yet. Send guidance notes here!',
                      style: TextStyle(color: AppTheme.textMuted, fontSize: 13),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _messages.length,
                    itemBuilder: (ctx, i) {
                      final m = _messages[i];
                      return Align(
                        alignment: m.isMe ? Alignment.centerRight : Alignment.centerLeft,
                        child: Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                          decoration: BoxDecoration(
                            color: m.isMe ? AppTheme.accentPrimary : AppTheme.bgSecondary,
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(color: AppTheme.borderGlass),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (m.isEncrypted) ...[
                                const Icon(Icons.lock, size: 12, color: Colors.white70),
                                const SizedBox(width: 4),
                              ],
                              Text(
                                m.content,
                                style: const TextStyle(color: Colors.white, fontSize: 14),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),

          // Input Bar
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(12.0),
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.attach_file, color: AppTheme.textSecondary),
                    onPressed: _simulateChunkedFileUpload,
                  ),
                  Expanded(
                    child: TextField(
                      controller: _inputController,
                      style: const TextStyle(color: AppTheme.textPrimary),
                      decoration: const InputDecoration(
                        hintText: 'Type guidance message...',
                        contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    icon: const Icon(Icons.send, color: AppTheme.accentPrimary),
                    onPressed: _handleSendMessage,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
