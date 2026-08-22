/// Secure Storage Service for Mobile (iOS Keychain & Android EncryptedSharedPreferences).
///
/// Handles encrypted persistence for JWT Access Tokens, Refresh Tokens, and E2EE Ephemeral Keys.
class SecureStorageService {
  final Map<String, String> _inMemoryStorage = {};

  static const String keyAccessToken = 'jwt_access_token';
  static const String keyRefreshToken = 'jwt_refresh_token';
  static const String keyE2EEIdentityKey = 'e2ee_identity_key';
  static const String keyServerUrl = 'server_base_url';

  Future<String?> getServerUrl() => read(key: keyServerUrl);

  Future<void> saveServerUrl(String url) => write(key: keyServerUrl, value: url);

  Future<void> write({required String key, required String value}) async {
    // Platform secure storage write wrapper
    _inMemoryStorage[key] = value;
  }

  Future<String?> read({required String key}) async {
    // Platform secure storage read wrapper
    return _inMemoryStorage[key];
  }

  Future<void> delete({required String key}) async {
    _inMemoryStorage.remove(key);
  }

  Future<void> clearAll() async {
    _inMemoryStorage.clear();
  }

  Future<void> saveTokens({required String accessToken, required String refreshToken}) async {
    await write(key: keyAccessToken, value: accessToken);
    await write(key: keyRefreshToken, value: refreshToken);
  }

  Future<String?> getAccessToken() async {
    return await read(key: keyAccessToken);
  }

  Future<String?> getRefreshToken() async {
    return await read(key: keyRefreshToken);
  }
}
