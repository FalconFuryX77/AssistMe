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
  final String? accessToken;
  final Future<String?> Function()? accessTokenProvider;

  WebSocket? _socket;
  final _controller = StreamController<RealtimeEvent>.broadcast();
  StreamSubscription? _sub;
  Timer? _heartbeat;
  Timer? _reconnectTimer;
  bool _connecting = false;
  bool _disposed = false;
  bool _hasConnected = false;
  final List<Map<String, dynamic>> _pendingMessages = [];

  RealtimeService({
    required this.sessionId,
    this.accessToken,
    this.accessTokenProvider,
  });

  /// Called after every successful socket connection, including recovery
  /// connections. The workspace uses this to restart WebRTC negotiation when
  /// the signaling transport comes back.
  FutureOr<void> Function()? onConnected;

  /// Called when an established socket drops. This is informational; the
  /// service continues its bounded reconnect loop automatically.
  void Function()? onDisconnected;

  Stream<RealtimeEvent> get events => _controller.stream;

  bool get isConnected => _socket != null;

  Future<void> connect() async {
    if (_disposed || _connecting || _socket != null) return;
    if (!AppConfig.isConfigured) return;
    _connecting = true;
    try {
      final token = await (accessTokenProvider?.call() ?? Future.value(accessToken));
      if (token == null || token.isEmpty) return;
      final uri = '${AppConfig.wsUrl}/ws/session/$sessionId?token=$token';
      final socket = await WebSocket.connect(uri);
      if (_disposed) {
        await socket.close();
        return;
      }
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
        onDone: _handleClosed,
        onError: (_) => _handleClosed(),
        cancelOnError: true,
      );
      _heartbeat?.cancel();
      _heartbeat = Timer.periodic(const Duration(seconds: 10), (_) {
        final liveSocket = _socket;
        if (liveSocket == null) return;
        try {
          liveSocket.add(jsonEncode({'type': 'heartbeat'}));
        } catch (_) {
          _handleClosed();
        }
      });
      for (final message in List<Map<String, dynamic>>.from(_pendingMessages)) {
        socket.add(jsonEncode(message));
      }
      _pendingMessages.clear();
      _hasConnected = true;
      await onConnected?.call();
    } catch (_) {
      _scheduleReconnect();
    } finally {
      _connecting = false;
    }
  }

  void send(Map<String, dynamic> payload) {
    final socket = _socket;
    if (socket == null) {
      _queuePending(payload);
      return;
    }
    try {
      socket.add(jsonEncode(payload));
    } catch (_) {
      // A socket can close between the null check and add(). Preserve the
      // message so the reconnect path can deliver it after Android returns
      // from a permission or system UI activity.
      _socket = null;
      _queuePending(payload);
      _scheduleReconnect();
    }
  }

  void _queuePending(Map<String, dynamic> payload) {
    // A preview is ephemeral. Keeping every frame behind a dead socket would
    // replay stale drawings and delay the committed stroke after recovery.
    if (payload['type'] == 'draw_preview') {
      _pendingMessages.removeWhere((item) => item['type'] == 'draw_preview');
    }
    if (_pendingMessages.length < 32) _pendingMessages.add(payload);
  }

  void _handleClosed() {
    final wasConnected = _socket != null || _hasConnected;
    _sub?.cancel();
    _sub = null;
    _heartbeat?.cancel();
    _heartbeat = null;
    _socket = null;
    if (wasConnected) {
      _hasConnected = false;
      onDisconnected?.call();
    }
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (_disposed || _reconnectTimer?.isActive == true) return;
    _reconnectTimer = Timer(const Duration(seconds: 2), () {
      _reconnectTimer = null;
      connect();
    });
  }

  Future<void> disconnect() async {
    _disposed = true;
    _reconnectTimer?.cancel();
    _heartbeat?.cancel();
    await _sub?.cancel();
    _sub = null;
    await _socket?.close();
    _socket = null;
    if (!_controller.isClosed) await _controller.close();
  }
}
