/// App configuration.
///
/// The server address is editable during first-run setup.
/// and persisted on the device, so it can point to a LAN IP or a public
/// internet HTTPS URL without rebuilding the app.
class AppConfig {
  AppConfig._();

  /// Compile-time default (used only on first launch). Override via
  /// `--dart-define=BACKEND_HOST=...`, `--dart-define=DEFAULT_SERVER_URL=...`,
  /// or a future Settings screen. In source control we fall back to the
  /// Android emulator alias so the build never ships with an empty host
  /// (which previously surfaced as `No host specified in URI /devices/`).
  static const String defaultBackendHost = String.fromEnvironment(
    'BACKEND_HOST',
    defaultValue: '10.0.2.2',
  );

  /// Public endpoint injected by the release environment (e.g. production
  /// https://assistme.example.com or a LAN http://192.168.1.39:8000). Not
  /// committed: stable hosts are injected at build time.
  static const String defaultServerUrl = String.fromEnvironment(
    'DEFAULT_SERVER_URL',
    defaultValue: '',
  );

  static const int backendPort = 8000;

  /// Runtime-editable server address. Background-resolved: compile-time URL
  /// wins, otherwise the emulator alias, otherwise a persisted Settings value
  /// overrides both on next launch via `SecureStorageService`.
  static String baseUrl = defaultServerUrl.isNotEmpty
      ? defaultServerUrl
      : 'http://$defaultBackendHost:$backendPort';

  static bool get isConfigured => baseUrl.trim().isNotEmpty;

  /// Same address as a WebSocket URL (http->ws, https->wss).
  static String get wsUrl {
    if (baseUrl.startsWith('https://')) {
      return 'wss://${baseUrl.substring(8)}';
    }
    return 'ws://${baseUrl.substring(7)}';
  }
}
