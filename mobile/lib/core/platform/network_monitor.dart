/// Reports when the phone's default network changes (Wi-Fi <-> mobile data),
/// so a live call can reconnect immediately instead of waiting for the old
/// network's sockets to time out.
library;

import 'dart:async';

import 'package:flutter/services.dart';

class NetworkChange {
  /// False when the phone lost its network and has none yet.
  final bool available;

  /// 'wifi', 'cellular', 'other', 'unknown' or 'none'.
  final String transport;

  const NetworkChange({required this.available, required this.transport});
}

class NetworkMonitor {
  static const MethodChannel _channel = MethodChannel('com.assistme/network');
  static final StreamController<NetworkChange> _changes =
      StreamController<NetworkChange>.broadcast();
  static bool _listening = false;

  static Stream<NetworkChange> get changes {
    if (!_listening) {
      _listening = true;
      _channel.setMethodCallHandler((call) async {
        if (call.method != 'changed') return;
        final args = call.arguments;
        if (args is! Map) return;
        _changes.add(
          NetworkChange(
            available: args['available'] == true,
            transport: '${args['transport'] ?? 'unknown'}',
          ),
        );
      });
    }
    return _changes.stream;
  }
}
