import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'core/config/app_config.dart';
import 'core/network/api_client.dart';
import 'core/notifications/push_notification_service.dart';
import 'core/security/secure_storage_service.dart';
import 'features/devices/trusted_devices_screen.dart';
import 'features/home/home_screen.dart';
import 'features/onboarding/onboarding_screen.dart';
import 'theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final secureStorage = SecureStorageService();
  await secureStorage.init();

  // Restore the saved server address (Settings) if present.
  final savedUrl = await secureStorage.getServerUrl();
  if (savedUrl != null && savedUrl.isNotEmpty) {
    try {
      AppConfig.setBaseUrl(savedUrl);
    } catch (_) {
      // Ignore an invalid value left by an older build and use the compiled
      // default instead.
    }
  }

  // Firebase/FCM — closed-app ring notifications.
  try {
    await Firebase.initializeApp();
    await FirebaseMessaging.instance.requestPermission(provisional: false);
      await PushNotificationService.instance.initialize();
  } catch (_) {
    // Push unavailable (no google-services on this flavor) — app still works
    // over the live WebSocket channel.
  }

  final apiClient = ApiClient(
    baseUrl: AppConfig.baseUrl,
    secureStorage: secureStorage,
  );

  // Device-first identity: a token means onboarding already happened.
  final accessToken = await secureStorage.getAccessToken();
  final hasIdentity = accessToken != null && accessToken.isNotEmpty;

  runApp(
    AssistMeMobileApp(
      apiClient: apiClient,
      secureStorage: secureStorage,
      initialRoute: hasIdentity ? '/home' : '/onboarding',
    ),
  );
}

class AssistMeMobileApp extends StatelessWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;
  final String initialRoute;

  const AssistMeMobileApp({
    super.key,
    required this.apiClient,
    required this.secureStorage,
    required this.initialRoute,
  });

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
        '/home': (_) =>
            HomeScreen(apiClient: apiClient, secureStorage: secureStorage),
        '/trusted-devices': (_) => TrustedDevicesScreen(
          apiClient: apiClient,
          secureStorage: secureStorage,
        ),
      },
    );
  }
}
