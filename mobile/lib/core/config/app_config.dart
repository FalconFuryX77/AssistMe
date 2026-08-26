/// App configuration.
///
/// The server address is editable during first-run setup.
/// and persisted on the device, so it can point to a LAN IP or a public
/// internet HTTPS URL without rebuilding the app.
class AppConfig {
  AppConfig._();

  /// Compile-time default (used only on first launch). Override via
  /// `--dart-define=BACKEND_HOST=...`, `--dart-define=DEFAULT_SERVER_URL=...`,
  /// or the in-app Settings screen.
  static const String defaultBackendHost = String.fromEnvironment(
    'BACKEND_HOST',
    defaultValue: '',
  );

  /// Public endpoint injected by the release environment. It is deliberately
  /// empty in source control: temporary tunnels and machine-local URLs must
  /// never be shipped as an app default.
  static const String defaultServerUrl = String.fromEnvironment(
    'DEFAULT_SERVER_URL',
    defaultValue: '',
  );

  static const int backendPort = 8000;

  /// Runtime-editable server address. Seeded from [defaultServerUrl] (or the
  /// older LAN-style host/port) and overridden by whatever the user saves in
  /// Settings.
  static String baseUrl = defaultServerUrl.isNotEmpty
      ? defaultServerUrl
      : (defaultBackendHost.isNotEmpty ? 'http://$defaultBackendHost:$backendPort' : '');

  static bool get isConfigured => baseUrl.trim().isNotEmpty;

  /// Normalise a user-entered server URL.
  /// - trims whitespace
  /// - ensures scheme (defaults to http:// for bare LAN IPs)
  /// - removes trailing slash
  /// - validates that a host is present — throws [FormatException] if not.
  static String normalizeUrl(String raw) {
    var v = raw.trim();
    if (v.isEmpty) throw const FormatException('Server URL is empty');
    if (!v.contains('://')) v = 'http://$v';
    final uri = Uri.tryParse(v);
    if (uri == null || uri.host.isEmpty) {
      throw FormatException('No host specified in URI $v');
    }
    if (uri.scheme != 'http' && uri.scheme != 'https') {
      throw FormatException('URL must start with http:// or https://');
    }
    // Re-serialize without trailing slash.
    var out = uri.toString();
    if (out.endsWith('/')) out = out.substring(0, out.length - 1);
    return out;
  }

  static void setBaseUrl(String url) {
    baseUrl = normalizeUrl(url);
  }

  /// Same address as a WebSocket URL (http->ws, https->wss).
  static String get wsUrl {
    if (baseUrl.startsWith('https://')) {
      return 'wss://${baseUrl.substring(8)}';
    }
    if (baseUrl.startsWith('http://')) {
      return 'ws://${baseUrl.substring(7)}';
    }
    // No host — callers should have checked isConfigured first.
    throw StateError('Server not configured: cannot build WebSocket URL');
  }
}
