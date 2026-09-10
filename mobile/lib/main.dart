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

/// Global theme mode notifier accessible across the app.
final ValueNotifier<ThemeMode> appThemeModeNotifier =
    ValueNotifier<ThemeMode>(ThemeMode.dark);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final secureStorage = SecureStorageService();
  await secureStorage.init();

  // Restore theme preference
  final isDark = await secureStorage.getDarkMode();
  if (isDark != null) {
    appThemeModeNotifier.value = isDark ? ThemeMode.dark : ThemeMode.light;
  }

  // Restore the saved server address (Settings) if present.
  final savedUrl = await secureStorage.getServerUrl();
  if (savedUrl != null && savedUrl.isNotEmpty) {
    try {
      final isStaleLocal = savedUrl.contains('192.168.') ||
          savedUrl.contains('localhost') ||
          savedUrl.contains('127.0.0.1') ||
          savedUrl.contains('10.0.2.2');
      if (isStaleLocal && AppConfig.defaultServerUrl.startsWith('https://')) {
        await secureStorage.clearServerUrl();
        AppConfig.setBaseUrl(AppConfig.defaultServerUrl);
      } else {
        AppConfig.setBaseUrl(savedUrl);
      }
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

  // Device-first identity: token or stored device credentials means onboarding already happened.
  final accessToken = await secureStorage.getAccessToken();
  final refreshToken = await secureStorage.getRefreshToken();
  final deviceSecret = await secureStorage.getDeviceSecret();
  final displayName = await secureStorage.getDisplayName();
  final hasIdentity = (accessToken != null && accessToken.isNotEmpty) ||
      (refreshToken != null && refreshToken.isNotEmpty) ||
      (deviceSecret != null && deviceSecret.isNotEmpty) ||
      (displayName != null && displayName.isNotEmpty);

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
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: appThemeModeNotifier,
      builder: (context, currentMode, _) => MaterialApp(
        title: 'AssistMe',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.lightTheme,
        darkTheme: AppTheme.darkTheme,
        themeMode: currentMode,
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
      ),
    );
  }
}
