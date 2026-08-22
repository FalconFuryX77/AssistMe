import 'package:flutter/material.dart';
import 'core/config/app_config.dart';
import 'core/network/api_client.dart';
import 'core/security/secure_storage_service.dart';
import 'features/devices/trusted_devices_screen.dart';
import 'features/home/home_screen.dart';
import 'features/onboarding/onboarding_screen.dart';
import 'theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final secureStorage = SecureStorageService();

  // Restore the saved server address (Settings) if present.
  final savedUrl = await secureStorage.getServerUrl();
  if (savedUrl != null && savedUrl.isNotEmpty) {
    AppConfig.baseUrl = savedUrl;
  }

  final apiClient = ApiClient(
    baseUrl: AppConfig.baseUrl,
    secureStorage: secureStorage,
  );

  // Device-first identity: a token means onboarding already happened.
  final accessToken = await secureStorage.getAccessToken();
  final hasIdentity = accessToken != null && accessToken.isNotEmpty;

  runApp(AssistMeMobileApp(
    apiClient: apiClient,
    secureStorage: secureStorage,
    initialRoute: hasIdentity ? '/home' : '/onboarding',
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
      title: 'AssistMe',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      initialRoute: initialRoute,
      routes: {
        '/onboarding': (_) => OnboardingScreen(
              apiClient: apiClient,
              secureStorage: secureStorage,
            ),
        '/home': (_) => HomeScreen(
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
