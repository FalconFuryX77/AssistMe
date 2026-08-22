/// Realtime WebSocket client for the assistance flow.
///
/// Connects to `/ws/session/{sessionId}?token=<JWT>` and emits parsed events
/// for the one-click help flow (request/respond/escalation) and drawing.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../config/app_config.dart';

class RealtimeEvent {
  final String type;
  final Map<String, dynamic> data;

  RealtimeEvent(this.type, this.data);
}

class RealtimeService {
  final String sessionId;
  final String accessToken;

  WebSocket? _socket;
  final _controller = StreamController<RealtimeEvent>.broadcast();
  StreamSubscription? _sub;

  RealtimeService({required this.sessionId, required this.accessToken});

  Stream<RealtimeEvent> get events => _controller.stream;

  bool get isConnected => _socket != null;

  Future<void> connect() async {
    final uri = '${AppConfig.wsUrl}/ws/session/$sessionId?token=$accessToken';
    final socket = await WebSocket.connect(uri);
    _socket = socket;
    _sub = socket.listen(
      (raw) {
        try {
          final data = jsonDecode(raw as String) as Map<String, dynamic>;
          final type = data['type'] as String? ?? 'unknown';
          _controller.add(RealtimeEvent(type, data));
        } catch (_) {
          // ignore malformed frames
        }
      },
      onDone: () => _close(),
      onError: (_) => _close(),
    );
  }

  void send(Map<String, dynamic> payload) {
    _socket?.add(jsonEncode(payload));
  }

  void _close() {
    _sub?.cancel();
    _socket = null;
    if (!_controller.isClosed) {
      _controller.close();
    }
  }

  Future<void> disconnect() async {
    _close();
  }
}