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

  /// Same address as a WebSocket URL (http->ws, https->wss).
  static String get wsUrl {
    if (baseUrl.startsWith('https://')) {
      return 'wss://${baseUrl.substring(8)}';
    }
    return 'ws://${baseUrl.substring(7)}';
  }
}
