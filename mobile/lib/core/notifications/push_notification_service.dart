import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Presents FCM rings when the app is already open.
///
/// Android displays notification payloads itself when the app is backgrounded;
/// foreground messages need an explicit local notification.
class PushNotificationService {
  static const _channel = AndroidNotificationChannel(
    'assistme_calls',
    'Help requests',
    description: 'Incoming AssistMe help requests',
    importance: Importance.max,
  );

  final FlutterLocalNotificationsPlugin _local =
      FlutterLocalNotificationsPlugin();

  static final PushNotificationService instance = PushNotificationService._();
  final Map<String, DateTime> _recentRingIds = {};

  PushNotificationService._();

  Future<void> initialize() async {
    const settings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    );
    await _local.initialize(settings);
    await _local
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >()
        ?.createNotificationChannel(_channel);

    FirebaseMessaging.onMessage.listen((message) async {
      final notification = message.notification;
      final data = message.data;
      if (data['type'] != 'incoming_call' && notification == null) return;
      await showIncomingCall(
        title: notification?.title,
        body: notification?.body,
        requestId: data['request_id'],
      );
    });
  }

  /// Show a heads-up notification for live device-channel rings too.  FCM is
  /// the closed-app path; the persistent WebSocket is the instant path while
  /// the app is open.  Both must produce the same user-visible notification.
  Future<void> showIncomingCall({
    String? title,
    String? body,
    String? requestId,
  }) async {
    if (requestId != null && requestId.isNotEmpty) {
      final now = DateTime.now();
      _recentRingIds.removeWhere(
        (_, seenAt) => now.difference(seenAt) > const Duration(minutes: 2),
      );
      if (_recentRingIds.containsKey(requestId)) return;
      _recentRingIds[requestId] = now;
    }
    await _local.show(
      DateTime.now().millisecondsSinceEpoch.remainder(1 << 31),
      title ?? 'AssistMe help request',
      body ?? 'Someone you trust is asking for help.',
      const NotificationDetails(
        android: AndroidNotificationDetails(
          'assistme_calls',
          'Help requests',
          channelDescription: 'Incoming AssistMe help requests',
          importance: Importance.max,
          priority: Priority.high,
          icon: '@mipmap/ic_launcher',
        ),
      ),
    );
  }
}
