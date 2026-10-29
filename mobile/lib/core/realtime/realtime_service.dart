/// Realtime WebSocket client for the assistance flow.
///
/// Connects to `/ws/session/{sessionId}` with a bearer auth header and emits parsed events
/// for the one-click help flow (request/respond/escalation) and drawing.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

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
  bool _everConnected = false;
  int _reconnectAttempt = 0;
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

  /// Called when signaling cannot connect or an established socket closes.
  void Function(String message)? onConnectionIssue;

  /// Called when an established socket drops. This is informational; the
  /// service continues its bounded reconnect loop automatically.
  void Function()? onDisconnected;

  Stream<RealtimeEvent> get events => _controller.stream;

  bool get isConnected => _socket != null;

  Future<void> connect() async {
    if (_disposed || _connecting || _socket != null) return;
    if (!AppConfig.isConfigured) {
      const message = 'Backend URL is not configured';
      debugPrint('[AssistMe][SIGNALING] $message');
      onConnectionIssue?.call(message);
      return;
    }
    _connecting = true;
    try {
      final token =
          await (accessTokenProvider?.call() ?? Future.value(accessToken));
      if (token == null || token.isEmpty) {
        const message = 'No access token available for session signaling';
        debugPrint('[AssistMe][SIGNALING] $message');
        onConnectionIssue?.call(message);
        return;
      }
      final uri = '${AppConfig.wsUrl}/ws/session/$sessionId';
      final socket = await WebSocket.connect(
        uri,
        headers: {
          'Authorization': 'Bearer $token',
          'ngrok-skip-browser-warning': 'true',
        },
      );
      if (_disposed) {
        await socket.close();
        return;
      }
      _socket = socket;
      _reconnectAttempt = 0;
      if (_everConnected) {
        var discardedSignals = 0;
        _pendingMessages.removeWhere((message) {
          final type = message['type'];
          final isStaleSignal = type == 'signal_offer' ||
              type == 'signal_answer' ||
              type == 'signal_ice_candidate';
          if (isStaleSignal) discardedSignals++;
          return isStaleSignal;
        });
        debugPrint(
          '[AssistMe][SIGNALING] discarded $discardedSignals stale SDP/ICE '
          'messages; call coordinator will renegotiate on reconnect',
        );
      }
      debugPrint(
        '[AssistMe][SIGNALING] session=${_shortSessionId()} websocket connected; '
        'replaying ${_pendingMessages.length} queued messages',
      );
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
      _everConnected = true;
      await onConnected?.call();
    } catch (error) {
      final message =
          'session=${_shortSessionId()} signaling connect failed: $error';
      debugPrint('[AssistMe][SIGNALING] $message');
      onConnectionIssue?.call(message);
      _scheduleReconnect();
    } finally {
      _connecting = false;
    }
  }

  /// Returns true only when the message was written to an open socket.
  /// Queued messages remain recoverable, but callers can avoid showing a
  /// misleading "sharing active" state until signaling is available.
  bool send(Map<String, dynamic> payload) {
    final socket = _socket;
    if (socket == null) {
      final type = payload['type'] ?? 'unknown';
      if (type != 'signal_ice_candidate' && type != 'draw_preview') {
        debugPrint(
          '[AssistMe][SIGNALING] session=${_shortSessionId()} queued $type '
          'because websocket is disconnected',
        );
      }
      _queuePending(payload);
      return false;
    }
    try {
      socket.add(jsonEncode(payload));
      return true;
    } catch (_) {
      // A socket can close between the null check and add(). Preserve the
      // message so the reconnect path can deliver it after Android returns
      // from a permission or system UI activity.
      _socket = null;
      _queuePending(payload);
      _scheduleReconnect();
      return false;
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
    final code = _socket?.closeCode;
    final reason = _socket?.closeReason;
    _sub?.cancel();
    _sub = null;
    _heartbeat?.cancel();
    _heartbeat = null;
    _socket = null;
    if (wasConnected) {
      debugPrint(
        '[AssistMe][SIGNALING] session=${_shortSessionId()} websocket closed '
        'code=$code reason=${reason ?? ''}',
      );
      _hasConnected = false;
      onDisconnected?.call();
    }
    _scheduleReconnect();
  }

  String _shortSessionId() =>
      sessionId.length > 6 ? sessionId.substring(0, 6) : sessionId;

  void _scheduleReconnect() {
    if (_disposed || _reconnectTimer?.isActive == true) return;
    final exponent = _reconnectAttempt.clamp(0, 4).toInt();
    final delaySeconds = (2 << exponent).clamp(2, 30).toInt();
    _reconnectAttempt++;
    _reconnectTimer = Timer(Duration(seconds: delaySeconds), () {
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
