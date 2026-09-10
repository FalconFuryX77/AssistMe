/// Stable device identity used for trusted-device pairing.
///
/// Generates a random fingerprint once and persists it in secure storage so the
/// same physical install always identifies as the same device.
library;

import 'dart:math';

import '../security/secure_storage_service.dart';

class DeviceIdentity {
  DeviceIdentity._();

  static const String _key = 'assistme_device_fingerprint';

  static String _generate() {
    final rand = Random.secure();
    const chars = 'abcdef0123456789';
    final sb = StringBuffer('assistme-');
    for (var i = 0; i < 32; i++) {
      sb.write(chars[rand.nextInt(chars.length)]);
    }
    return sb.toString();
  }

  /// Return this install's stable device fingerprint (creating on first call).
  static Future<String> getFingerprint(SecureStorageService storage) async {
    final existing = await storage.read(key: _key);
    if (existing != null && existing.isNotEmpty) {
      return existing;
    }
    final created = _generate();
    await storage.write(key: _key, value: created);
    return created;
  }

  /// Return this device's unique auto-assigned hardware Device ID (e.g., "Device-4B9F").
  static Future<String> getDeviceId(SecureStorageService storage) async {
    final existing = await storage.getDeviceId();
    if (existing != null && existing.isNotEmpty) {
      return existing;
    }
    final fp = await getFingerprint(storage);
    // Derive a clean, readable, unique 4-6 char identifier suffix from fingerprint
    final suffix = fp.replaceAll('assistme-', '').substring(0, 4).toUpperCase();
    final deviceId = 'Device-$suffix';
    await storage.saveDeviceId(deviceId);
    return deviceId;
  }
}