/// App configuration.
///
/// Runtime configuration for the backend used by the mobile client.
class AppConfig {
  AppConfig._();

  /// Compile-time default. The emulator host is useful for local Android
  /// development; release builds should provide DEFAULT_SERVER_URL.
  static const String defaultBackendHost = String.fromEnvironment(
    'BACKEND_HOST',
    defaultValue: '192.168.1.39',
  );

  static const String defaultServerUrl = String.fromEnvironment(
    'DEFAULT_SERVER_URL',
    defaultValue: '',
  );

  static const int backendPort = 8000;

  /// Runtime server address. A saved value may override the compile-time
  /// default after the app has been initialized.
  static String baseUrl = _initialBaseUrl();

  static String _initialBaseUrl() {
    final configured = defaultServerUrl.trim();
    if (configured.isNotEmpty) return normalize(configured);
    if (defaultBackendHost.trim().isNotEmpty) {
      return normalize('http://${defaultBackendHost.trim()}:$backendPort');
    }
    return '';
  }

  /// Normalize a backend address once so REST and WebSocket clients use the
  /// same origin. Host-only values are treated as local HTTP endpoints.
  static String normalize(String value) {
    var result = value.trim();
    if (result.isEmpty) return '';
    if (!result.contains('://')) result = 'http://$result';
    final uri = Uri.tryParse(result);
    if (uri == null || uri.host.isEmpty || !{'http', 'https'}.contains(uri.scheme)) {
      throw FormatException('Use an http:// or https:// backend URL');
    }
    return uri.replace(path: uri.path.replaceFirst(RegExp(r'/+$'), '')).toString();
  }

  static void setBaseUrl(String value) {
    baseUrl = normalize(value);
  }

  static bool get isConfigured => baseUrl.trim().isNotEmpty;

  /// Same address as a WebSocket URL (http->ws, https->wss).
  static String get wsUrl {
    if (!isConfigured) {
      throw StateError('AssistMe backend is not configured');
    }
    final uri = Uri.parse(baseUrl);
    return uri.replace(scheme: uri.scheme == 'https' ? 'wss' : 'ws').toString();
  }
}
