/// Persistent storage for credentials, device identity, and ordinary settings.
///
/// Authentication and cryptographic material live in the operating system's
/// key store. Non-sensitive UI settings remain in SharedPreferences. On the
/// first run after this change, legacy credential values are copied to secure
/// storage and verified before their plaintext preference entries are removed.
library;

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

abstract interface class SecureValueStore {
  Future<String?> read({required String key});
  Future<void> write({required String key, required String value});
}

class SecureStorageService implements SecureValueStore {
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
  static const String keyGuideEncryptionKey = 'local_guide_encryption_key_v1';
  static const String keyDeviceFingerprint = 'assistme_device_fingerprint';

  static const Set<String> _secureKeys = {
    keyAccessToken,
    keyRefreshToken,
    keyDeviceSecret,
    keyE2EEIdentityKey,
    keyDeviceId,
    keyDisplayName,
    keyRecoveryCode,
    keyGuideEncryptionKey,
    keyDeviceFingerprint,
    // Older ApiClient builds used this alternate key when re-bootstrapping.
    'device_fingerprint',
    keyActiveSessionId,
    keyActiveSessionPeerName,
    keyActiveSessionIsHelpee,
  };

  static const FlutterSecureStorage _secure = FlutterSecureStorage(
    iOptions: IOSOptions(
      accessibility: KeychainAccessibility.first_unlock_this_device,
      synchronizable: false,
    ),
  );
  late final SharedPreferences _prefs;
  bool _ready = false;

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    // Do not delete a legacy value until the secure write is readable. That
    // keeps upgrades recoverable if a platform key-store write fails.
    for (final key in _secureKeys) {
      final stored = _prefs.get(key);
      final legacyValue = stored is String
          ? stored
          : (stored is bool && key == keyActiveSessionIsHelpee
                ? stored.toString()
                : null);
      if (legacyValue == null || legacyValue.isEmpty) continue;
      final currentValue = await _secure.read(key: key);
      if (currentValue == null || currentValue.isEmpty) {
        await _secure.write(key: key, value: legacyValue);
      }
      final verifiedValue = await _secure.read(key: key);
      if (verifiedValue != null) await _prefs.remove(key);
    }
    _ready = true;
  }

  void _assertReady() {
    if (!_ready) {
      throw StateError('Call init() before using SecureStorageService');
    }
  }

  Future<String?> getServerUrl() => read(key: keyServerUrl);
  Future<void> saveServerUrl(String url) =>
      write(key: keyServerUrl, value: url);
  Future<void> clearServerUrl() => delete(key: keyServerUrl);
  Future<void> saveDisplayName(String name) =>
      write(key: keyDisplayName, value: name);
  Future<String?> getDisplayName() => read(key: keyDisplayName);
  Future<void> saveDeviceId(String id) => write(key: keyDeviceId, value: id);
  Future<String?> getDeviceId() => read(key: keyDeviceId);
  Future<void> saveRecoveryCode(String code) =>
      write(key: keyRecoveryCode, value: code);
  Future<String?> getRecoveryCode() => read(key: keyRecoveryCode);

  Future<void> saveDarkMode(bool enabled) async {
    _assertReady();
    await _prefs.setBool(keyDarkMode, enabled);
  }

  Future<bool?> getDarkMode() async {
    _assertReady();
    return _prefs.getBool(keyDarkMode);
  }

  Future<void> saveActiveSession({
    required String sessionId,
    required String peerName,
    required bool isHelpee,
  }) async {
    await write(key: keyActiveSessionId, value: sessionId);
    await write(key: keyActiveSessionPeerName, value: peerName);
    await write(key: keyActiveSessionIsHelpee, value: isHelpee.toString());
  }

  Future<Map<String, dynamic>?> getActiveSession() async {
    final sessionId = await read(key: keyActiveSessionId);
    if (sessionId == null || sessionId.isEmpty) return null;
    return {
      'session_id': sessionId,
      'peer_name': await read(key: keyActiveSessionPeerName) ?? 'your contact',
      'is_helpee': (await read(key: keyActiveSessionIsHelpee)) == 'true',
    };
  }

  Future<void> clearActiveSession() async {
    await delete(key: keyActiveSessionId);
    await delete(key: keyActiveSessionPeerName);
    await delete(key: keyActiveSessionIsHelpee);
  }

  @override
  Future<void> write({required String key, required String value}) async {
    _assertReady();
    if (_secureKeys.contains(key)) {
      await _secure.write(key: key, value: value);
    } else {
      await _prefs.setString(key, value);
    }
  }

  @override
  Future<String?> read({required String key}) async {
    _assertReady();
    if (_secureKeys.contains(key)) return _secure.read(key: key);
    return _prefs.getString(key);
  }

  Future<void> delete({required String key}) async {
    _assertReady();
    if (_secureKeys.contains(key)) {
      await _secure.delete(key: key);
    } else {
      await _prefs.remove(key);
    }
  }

  Future<void> clearAll() async {
    _assertReady();
    await _prefs.clear();
    for (final key in _secureKeys) {
      await _secure.delete(key: key);
    }
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

  Future<String?> getAccessToken() => read(key: keyAccessToken);
  Future<String?> getRefreshToken() => read(key: keyRefreshToken);
  Future<void> saveDeviceSecret(String secret) =>
      write(key: keyDeviceSecret, value: secret);
  Future<String?> getDeviceSecret() => read(key: keyDeviceSecret);
}
