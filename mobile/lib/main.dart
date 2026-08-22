import 'package:flutter/material.dart';
import 'core/config/app_config.dart';
import 'core/network/api_client.dart';
import 'core/security/secure_storage_service.dart';
import 'features/auth/login_screen.dart';
import 'features/devices/trusted_devices_screen.dart';
import 'features/session/session_screen.dart';
import 'theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final secureStorage = SecureStorageService();

  // Load the saved server address (Settings) if present; fall back to the
  // compile-time default otherwise.
  final savedUrl = await secureStorage.getServerUrl();
  if (savedUrl != null && savedUrl.isNotEmpty) {
    AppConfig.baseUrl = savedUrl;
  }

  final apiClient = ApiClient(
    baseUrl: AppConfig.baseUrl,
    secureStorage: secureStorage,
  );

  final accessToken = await secureStorage.getAccessToken();

  runApp(AssistMeMobileApp(
    apiClient: apiClient,
    secureStorage: secureStorage,
    initialRoute: accessToken != null ? '/sessions' : '/login',
  ));
}

class AssistMeMobileApp extends StatelessWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;
  final String initialRoute;

  const AssistMeMobileApp({
    Key? key,
    required this.apiClient,
    required this.secureStorage,
    required this.initialRoute,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AssistMe Mobile',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      initialRoute: initialRoute,
      routes: {
        '/login': (_) => LoginScreen(
              apiClient: apiClient,
              secureStorage: secureStorage,
            ),
        '/sessions': (_) => SessionScreen(
              apiClient: apiClient,
              secureStorage: secureStorage,
            ),
        '/trusted-devices': (_) => TrustedDevicesScreen(
              apiClient: apiClient,
              secureStorage: secureStorage,
            ),
      },
    );
  }
}
