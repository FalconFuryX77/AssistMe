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

  void updateBaseUrl(String url) => baseUrl = url;

  void _ensureConfigured() {
    if (baseUrl.trim().isEmpty) {
      throw StateError(
        'Server not configured — open Settings and enter your server URL (e.g. http://192.168.1.39:8000)',
      );
    }
    final uri = Uri.tryParse(baseUrl);
    if (uri == null || uri.host.isEmpty) {
      throw FormatException('No host specified in URI $baseUrl');
    }
  }

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

  bool _refreshing = false;

  /// Exchange the stored refresh token for a fresh access token.
  Future<bool> _tryRefresh() async {
    if (_refreshing) return false;
    if (baseUrl.trim().isEmpty) return false;
    final uri = Uri.tryParse('$baseUrl/auth/refresh');
    if (uri == null || uri.host.isEmpty) return false;
    _refreshing = true;
    try {
      final refreshToken = await secureStorage.getRefreshToken();
      if (refreshToken == null || refreshToken.isEmpty) return false;
      final resp = await httpClient.post(
        uri,
        headers: const {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: jsonEncode({'refresh_token': refreshToken}),
      );
      if (resp.statusCode != 200) return false;
      final data = jsonDecode(resp.body);
      final access = data['access_token'];
      if (access is! String || access.isEmpty) return false;
      await secureStorage.write(
        key: SecureStorageService.keyAccessToken,
        value: access,
      );
      return true;
    } catch (_) {
      return false;
    } finally {
      _refreshing = false;
    }
  }

  /// Send with auth; on 401 refresh once and retry transparently.
  Future<http.Response> _send(
    Future<http.Response> Function(Map<String, String> headers) run, {
    bool requireAuth = true,
  }) async {
    var headers = await _getHeaders(requireAuth: requireAuth);
    var resp = await run(headers);
    if (resp.statusCode == 401 && requireAuth) {
      if (await _tryRefresh()) {
        headers = await _getHeaders(requireAuth: requireAuth);
        resp = await run(headers);
      }
    }
    return resp;
  }

  Future<http.Response> get(String endpoint, {bool requireAuth = true}) {
    _ensureConfigured();
    return _send(
      (headers) =>
          httpClient.get(Uri.parse('$baseUrl$endpoint'), headers: headers),
      requireAuth: requireAuth,
    );
  }

  Future<http.Response> post(
    String endpoint, {
    Map<String, dynamic>? body,
    bool requireAuth = true,
  }) {
    _ensureConfigured();
    return _send(
      (headers) => httpClient.post(
        Uri.parse('$baseUrl$endpoint'),
        headers: headers,
        body: body != null ? jsonEncode(body) : null,
      ),
      requireAuth: requireAuth,
    );
  }

  Future<http.Response> patch(
    String endpoint, {
    Map<String, dynamic>? body,
    bool requireAuth = true,
  }) {
    _ensureConfigured();
    return _send(
      (headers) => httpClient.patch(
        Uri.parse('$baseUrl$endpoint'),
        headers: headers,
        body: body != null ? jsonEncode(body) : null,
      ),
      requireAuth: requireAuth,
    );
  }

  Future<http.Response> delete(
    String endpoint, {
    Map<String, dynamic>? query,
    bool requireAuth = true,
  }) {
    _ensureConfigured();
    return _send(
      (headers) => httpClient.delete(
        Uri.parse('$baseUrl$endpoint').replace(queryParameters: query),
        headers: headers,
      ),
      requireAuth: requireAuth,
    );
  }

  // ---------------------------------------------------------------------------
  // Trusted device endpoints
  // ---------------------------------------------------------------------------

  Future<http.Response> listTrustedDevices() {
    return get('/devices/');
  }

  Future<http.Response> revokeDevice(String deviceId) {
    return delete('/devices/$deviceId');
  }

  Future<http.Response> checkDeviceIdentity(String deviceFingerprint) {
    return post(
      '/devices/identity',
      body: {'device_fingerprint': deviceFingerprint},
    );
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
    return post(
      '/devices/pairing/claim',
      body: {
        'setup_code': setupCode,
        'device_fingerprint': deviceFingerprint,
        'friendly_name': friendlyName,
        'device_platform': devicePlatform,
      },
    );
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
    return post(
      '/help/call',
      body: {
        'helper_device_fingerprint': helperDeviceFingerprint,
        'message': message,
      },
    );
  }

  /// Durable call state. The device channel may deliver this faster, but it
  /// must never be the only way a caller learns that the helper responded.
  Future<http.Response> getHelpCallStatus(String requestId) {
    return get('/help/call/$requestId');
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
    return post(
      '/sessions/$sessionId/assistance/request',
      body: {
        'helper_user_id': helperUserId,
        'helper_device_fingerprint': helperDeviceFingerprint,
      },
    );
  }

  Future<http.Response> respondToHelpRequest({
    required String sessionId,
    required String requestId,
    required bool accept,
    String? helperDeviceFingerprint,
  }) {
    return post(
      '/sessions/$sessionId/assistance/request/$requestId/respond',
      body: {
        'accept': accept,
        'helper_device_fingerprint': helperDeviceFingerprint,
      },
    );
  }

  Future<http.Response> requestEscalation({
    required String sessionId,
    required List<String> targetCapabilities,
  }) {
    return post(
      '/sessions/$sessionId/assistance/escalation',
      body: {'target_capabilities': targetCapabilities},
    );
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
    return post(
      '/sessions/$sessionId/assistance/escalation/$escalationId/respond',
      body: {'accept': accept, 'accept_disclaimer': acceptDisclaimer},
    );
  }
}
