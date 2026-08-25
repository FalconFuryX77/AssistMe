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
    defaultValue: '10.0.2.2',
  );

  /// Public internet URL used as the default when the user has not set one.
  /// Set to a Cloudflare/ngrok tunnel or a deployed host so the app works
  /// over the internet without any configuration.
  static const String defaultServerUrl = String.fromEnvironment(
    'DEFAULT_SERVER_URL',
    defaultValue: 'https://ivory-pulse-broke-pounds.trycloudflare.com',
  );

  static const int backendPort = 8000;

  /// Runtime-editable server address. Seeded from [defaultServerUrl] (or the
  /// older LAN-style host/port) and overridden by whatever the user saves in
  /// Settings.
  static String baseUrl = defaultServerUrl.isNotEmpty
      ? defaultServerUrl
      : 'http://$defaultBackendHost:$backendPort';

  /// Same address as a WebSocket URL (http->ws, https->wss).
  static String get wsUrl {
    if (baseUrl.startsWith('https://')) {
      return 'wss://${baseUrl.substring(8)}';
    }
    return 'ws://${baseUrl.substring(7)}';
  }
}
