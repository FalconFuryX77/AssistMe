/// Persistent storage for tokens, device identity, and settings.
///
/// Backed by SharedPreferences so identity survives app restarts (the
/// fingerprint MUST stay stable — it IS the account). Swap to encrypted
/// storage later without touching call sites: the async API is identical.
library;

import 'package:shared_preferences/shared_preferences.dart';

class SecureStorageService {
  static const String keyAccessToken = 'jwt_access_token';
  static const String keyRefreshToken = 'jwt_refresh_token';
  static const String keyDeviceSecret = 'device_auth_secret';
  static const String keyE2EEIdentityKey = 'e2ee_identity_key';
  static const String keyServerUrl = 'server_base_url';
  static const String keyDisplayName = 'device_display_name';
  static const String keyDeviceId = 'assistme_device_id';
  static const String keyRecoveryCode = 'user_recovery_code';
  static const String keyDarkMode = 'app_theme_dark_mode';
  static const String keyActiveSessionId = 'active_session_id';
  static const String keyActiveSessionPeerName = 'active_session_peer_name';
  static const String keyActiveSessionIsHelpee = 'active_session_is_helpee';

  late final Object _prefs;
  bool _ready = false;

  Future<void> init() async {
    final prefs = await _loadPrefs();
    _prefs = prefs;
    _ready = true;
  }

  Future<Object> _loadPrefs() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs;
  }

  SharedPreferences get prefs {
    assert(_ready, 'Call init() before using SecureStorageService');
    return _prefs as SharedPreferences;
  }

  Future<String?> getServerUrl() => read(key: keyServerUrl);

  Future<void> saveServerUrl(String url) =>
      write(key: keyServerUrl, value: url);

  Future<void> clearServerUrl() =>
      delete(key: keyServerUrl);

  Future<void> saveDisplayName(String name) =>
      write(key: keyDisplayName, value: name);

  Future<String?> getDisplayName() => read(key: keyDisplayName);

  Future<void> saveDeviceId(String id) =>
      write(key: keyDeviceId, value: id);

  Future<String?> getDeviceId() => read(key: keyDeviceId);

  Future<void> saveRecoveryCode(String code) =>
      write(key: keyRecoveryCode, value: code);

  Future<String?> getRecoveryCode() => read(key: keyRecoveryCode);

  Future<void> saveDarkMode(bool enabled) async {
    await prefs.setBool(keyDarkMode, enabled);
  }

  Future<bool?> getDarkMode() async {
    return prefs.getBool(keyDarkMode);
  }

  Future<void> saveActiveSession({
    required String sessionId,
    required String peerName,
    required bool isHelpee,
  }) async {
    await prefs.setString(keyActiveSessionId, sessionId);
    await prefs.setString(keyActiveSessionPeerName, peerName);
    await prefs.setBool(keyActiveSessionIsHelpee, isHelpee);
  }

  Future<Map<String, dynamic>?> getActiveSession() async {
    final sessionId = prefs.getString(keyActiveSessionId);
    if (sessionId == null || sessionId.isEmpty) return null;
    return {
      'session_id': sessionId,
      'peer_name': prefs.getString(keyActiveSessionPeerName) ?? 'your contact',
      'is_helpee': prefs.getBool(keyActiveSessionIsHelpee) ?? true,
    };
  }

  Future<void> clearActiveSession() async {
    await prefs.remove(keyActiveSessionId);
    await prefs.remove(keyActiveSessionPeerName);
    await prefs.remove(keyActiveSessionIsHelpee);
  }

  Future<void> write({required String key, required String value}) async {
    await prefs.setString(key, value);
  }

  Future<String?> read({required String key}) async {
    return prefs.getString(key);
  }

  Future<void> delete({required String key}) async {
    await prefs.remove(key);
  }

  Future<void> clearAll() async {
    await prefs.clear();
  }

  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    await write(key: keyAccessToken, value: accessToken);
    await write(key: keyRefreshToken, value: refreshToken);
  }

  Future<void> clearTokens() async {
    await delete(key: keyAccessToken);
    await delete(key: keyRefreshToken);
  }

  Future<String?> getAccessToken() async {
    return await read(key: keyAccessToken);
  }

  Future<String?> getRefreshToken() async {
    return await read(key: keyRefreshToken);
  }

  Future<void> saveDeviceSecret(String secret) async {
    await write(key: keyDeviceSecret, value: secret);
  }

  Future<String?> getDeviceSecret() async {
    return await read(key: keyDeviceSecret);
  }
}
