/// Mobile API Client with Automatic JWT Bearer Token Injection & Token Refresh.
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../security/secure_storage_service.dart';

class ApiClient {
  String baseUrl;
  final SecureStorageService secureStorage;
  final http.Client httpClient;

  ApiClient({
    required this.baseUrl,
    required this.secureStorage,
    http.Client? httpClient,
  }) : httpClient = httpClient ?? http.Client();

  Future<Map<String, String>> _getHeaders({bool requireAuth = true}) async {
    final headers = <String, String>{
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };

    if (requireAuth) {
      final token = await secureStorage.getAccessToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
    }
    return headers;
  }

  Future<http.Response> get(String endpoint, {bool requireAuth = true}) async {
    final headers = await _getHeaders(requireAuth: requireAuth);
    final uri = Uri.parse('$baseUrl$endpoint');
    return await httpClient.get(uri, headers: headers);
  }

  Future<http.Response> post(
    String endpoint, {
    Map<String, dynamic>? body,
    bool requireAuth = true,
  }) async {
    final headers = await _getHeaders(requireAuth: requireAuth);
    final uri = Uri.parse('$baseUrl$endpoint');
    return await httpClient.post(
      uri,
      headers: headers,
      body: body != null ? jsonEncode(body) : null,
    );
  }

  Future<http.Response> patch(
    String endpoint, {
    Map<String, dynamic>? body,
    bool requireAuth = true,
  }) async {
    final headers = await _getHeaders(requireAuth: requireAuth);
    final uri = Uri.parse('$baseUrl$endpoint');
    return await httpClient.patch(
      uri,
      headers: headers,
      body: body != null ? jsonEncode(body) : null,
    );
  }

  Future<http.Response> delete(
    String endpoint, {
    Map<String, dynamic>? query,
    bool requireAuth = true,
  }) async {
    final headers = await _getHeaders(requireAuth: requireAuth);
    final uri = Uri.parse('$baseUrl$endpoint').replace(queryParameters: query);
    return await httpClient.delete(uri, headers: headers);
  }

  // ---------------------------------------------------------------------------
  // Trusted device endpoints
  // ---------------------------------------------------------------------------

  Future<http.Response> initiatePairing({
    required String deviceFingerprint,
    String? friendlyName,
    String? devicePlatform,
  }) {
    return post('/devices/pairing/initiate', body: {
      'device_fingerprint': deviceFingerprint,
      'friendly_name': friendlyName,
      'device_platform': devicePlatform,
    });
  }

  Future<http.Response> confirmPairing({
    required String pairingCode,
    required String password,
  }) {
    return post('/devices/pairing/confirm', body: {
      'pairing_code': pairingCode,
      'password': password,
    });
  }

  Future<http.Response> listTrustedDevices() {
    return get('/devices/');
  }

  Future<http.Response> revokeDevice(String deviceId, String password) {
    return delete('/devices/$deviceId', query: {'password': password});
  }

  Future<http.Response> checkDeviceIdentity(String deviceFingerprint) {
    return post('/devices/identity', body: {'device_fingerprint': deviceFingerprint});
  }

  Future<http.Response> generateSetupCode() {
    return post('/devices/pairing/setup-code', body: {});
  }

  Future<http.Response> claimSetupCode({
    required String setupCode,
    required String deviceFingerprint,
    String? friendlyName,
    String? devicePlatform,
  }) {
    return post('/devices/pairing/claim', body: {
      'setup_code': setupCode,
      'device_fingerprint': deviceFingerprint,
      'friendly_name': friendlyName,
      'device_platform': devicePlatform,
    });
  }

  Future<http.Response> listPendingPairings() {
    return get('/devices/pairing/pending');
  }

  Future<http.Response> approvePairing(String pairingId) {
    return post('/devices/pairing/approve', body: {'pairing_id': pairingId});
  }

  Future<http.Response> getIceServers(String sessionId) {
    return get('/sessions/$sessionId/ice-servers');
  }

  // ---------------------------------------------------------------------------
  // Device-first identity + one-tap help flow
  // ---------------------------------------------------------------------------

  /// Device-first bootstrap: no email/password. Returns tokens + (on first
  /// launch only) the one-time recovery code.
  Future<http.Response> deviceBootstrap({
    required String deviceFingerprint,
    String? displayName,
    bool requireAuth = false,
  }) {
    return post(
      '/auth/device',
      body: {
        'device_fingerprint': deviceFingerprint,
        if (displayName != null) 'display_name': displayName,
      },
      requireAuth: requireAuth,
    );
  }

  /// One-tap help call: rings a trusted helper, session forms silently.
  Future<http.Response> placeHelpCall({
    required String helperDeviceFingerprint,
    String? message,
  }) {
    return post('/help/call', body: {
      'helper_device_fingerprint': helperDeviceFingerprint,
      'message': message,
    });
  }

  /// The helper's address book — people this user has been trusted to help.
  Future<http.Response> listHelping() {
    return get('/devices/helping');
  }

  /// Respond to an assistance request (accept/deny) from the ring popup.
  Future<http.Response> respondToRequestSimple({
    required String sessionId,
    required String requestId,
    required bool accept,
  }) {
    return post(
      '/sessions/$sessionId/assistance/request/$requestId/respond',
      body: {'accept': accept},
    );
  }

  /// Missed rings addressed to me (helper) — shown on app open.
  Future<http.Response> listPendingCalls() {
    return get('/help/pending');
  }

  /// Reclaim an identity with a recovery code after reinstall/phone loss.
  Future<http.Response> reclaimIdentity({
    required String deviceFingerprint,
    required String recoveryCode,
  }) {
    return post(
      '/auth/device/reclaim',
      body: {
        'device_fingerprint': deviceFingerprint,
        'recovery_code': recoveryCode,
      },
      requireAuth: false,
    );
  }

  /// Register this device's FCM token for closed-app rings.
  Future<http.Response> registerPushToken(String token) {
    return post('/help/push-token', body: {'token': token});
  }

  // ---------------------------------------------------------------------------
  // Assistance request / escalation endpoints
  // ---------------------------------------------------------------------------

  Future<http.Response> requestHelp({
    required String sessionId,
    required String helperUserId,
    required String helperDeviceFingerprint,
  }) {
    return post('/sessions/$sessionId/assistance/request', body: {
      'helper_user_id': helperUserId,
      'helper_device_fingerprint': helperDeviceFingerprint,
    });
  }

  Future<http.Response> respondToHelpRequest({
    required String sessionId,
    required String requestId,
    required bool accept,
    String? helperDeviceFingerprint,
  }) {
    return post('/sessions/$sessionId/assistance/request/$requestId/respond', body: {
      'accept': accept,
      'helper_device_fingerprint': helperDeviceFingerprint,
    });
  }

  Future<http.Response> requestEscalation({
    required String sessionId,
    required List<String> targetCapabilities,
  }) {
    return post('/sessions/$sessionId/assistance/escalation', body: {
      'target_capabilities': targetCapabilities,
    });
  }

  Future<http.Response> getEscalation(String sessionId, String escalationId) {
    return get('/sessions/$sessionId/assistance/escalation/$escalationId');
  }

  Future<http.Response> respondToEscalation({
    required String sessionId,
    required String escalationId,
    required bool accept,
    required bool acceptDisclaimer,
  }) {
    return post('/sessions/$sessionId/assistance/escalation/$escalationId/respond', body: {
      'accept': accept,
      'accept_disclaimer': acceptDisclaimer,
    });
  }
}
