/// Persistent per-device WebSocket — the ring channel.
///
/// Connects once at app start (after onboarding) and stays connected. This is
/// how the helper's phone rings even when nobody is inside a session, and how
/// the helpee learns their call was accepted or denied.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../config/app_config.dart';

class DeviceChannelEvent {
  final String type;
  final Map<String, dynamic> data;

  DeviceChannelEvent(this.type, this.data);
}

class DeviceChannelService {
  WebSocket? _socket;
  StreamSubscription? _sub;
  Timer? _heartbeat;
  final _controller = StreamController<DeviceChannelEvent>.broadcast();
  bool _disposed = false;

  final String? accessToken;
  final Future<String?> Function()? accessTokenProvider;

  DeviceChannelService({this.accessToken, this.accessTokenProvider});

  Stream<DeviceChannelEvent> get events => _controller.stream;

  bool get isConnected => _socket != null;

  Future<void> connect() async {
    if (_socket != null || _disposed) return;
    if (!AppConfig.isConfigured) return;
    try {
      final token = await (accessTokenProvider?.call() ?? Future.value(accessToken));
      if (token == null || token.isEmpty) return;
      final uri = '${AppConfig.wsUrl}/ws/device?token=$token';
      _socket = await WebSocket.connect(
        uri,
        headers: {'ngrok-skip-browser-warning': 'true'},
      );
      _sub = _socket!.listen(
        (raw) {
          try {
            final data = jsonDecode(raw as String) as Map<String, dynamic>;
            _controller.add(DeviceChannelEvent(
              data['type'] as String? ?? 'unknown',
              data,
            ));
          } catch (_) {/* ignore malformed frames */}
        },
        onDone: _scheduleReconnect,
        onError: (err) {
          _scheduleReconnect();
        },
        cancelOnError: true,
      );
      _heartbeat = Timer.periodic(const Duration(seconds: 25), (_) {
        try {
          _socket?.add('heartbeat');
        } catch (_) {}
      });
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    _teardownSocket();
    if (_disposed) return;
    Future.delayed(const Duration(seconds: 2), () {
      if (!_disposed && _socket == null) connect();
    });
  }

  void _teardownSocket() {
    _heartbeat?.cancel();
    _heartbeat = null;
    _sub?.cancel();
    _sub = null;
    try {
      _socket?.close();
    } catch (_) {}
    _socket = null;
  }

  Future<void> dispose() async {
    _disposed = true;
    _teardownSocket();
    await _controller.close();
  }
}
