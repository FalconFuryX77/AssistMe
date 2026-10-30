/// Post-session guide delivery.
///
/// The live call is the fast path: the helper's finished guide goes over the
/// peer data channel. When that fails (the helpee hung up, the network
/// dropped, Gemma took a few minutes), the helper's phone encrypts the guide
/// and leaves it on the backend for the helpee's phone to collect whenever it
/// is next online, minutes or hours later.
///
/// Privacy: the key is generated on the helper's phone and sent to the
/// helpee only over the call's DTLS-encrypted data channel. The backend
/// stores AES-GCM ciphertext it cannot read and deletes it once collected.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../network/api_client.dart';
import '../security/secure_storage_service.dart'
    show SecureStorageService, SecureValueStore;
import 'guide_models.dart';
import 'local_guide_store.dart';
import 'session_keyframe_manager.dart';

class GuideDeliveryService {
  static final AesGcm _cipher = AesGcm.with256bits();
  static const int _maxRememberedKeys = 30;
  static bool _checkingInbox = false;
  static bool _flushingOutbox = false;

  // ------------------------------------------------------------------
  // Per-call key
  // ------------------------------------------------------------------

  static List<int> newKey() {
    final random = Random.secure();
    return List<int>.generate(32, (_) => random.nextInt(256));
  }

  static Future<Map<String, String>> _readKeys(SecureValueStore storage) async {
    final raw = await storage.read(key: SecureStorageService.keyGuideSyncKeys);
    if (raw == null || raw.isEmpty) return {};
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map) {
        return decoded.map((key, value) => MapEntry('$key', '$value'));
      }
    } catch (_) {}
    return {};
  }

  /// Stores the key for [sessionId]; keeps only the most recent calls.
  static Future<void> rememberKey(
    SecureValueStore storage,
    String sessionId,
    List<int> key,
  ) async {
    final keys = await _readKeys(storage);
    keys.remove(sessionId);
    keys[sessionId] = base64Encode(key);
    while (keys.length > _maxRememberedKeys) {
      keys.remove(keys.keys.first);
    }
    await storage.write(
      key: SecureStorageService.keyGuideSyncKeys,
      value: jsonEncode(keys),
    );
  }

  static Future<List<int>?> keyFor(
    SecureValueStore storage,
    String sessionId,
  ) async {
    final encoded = (await _readKeys(storage))[sessionId];
    if (encoded == null) return null;
    try {
      final key = base64Decode(encoded);
      return key.length == 32 ? key : null;
    } catch (_) {
      return null;
    }
  }

  // ------------------------------------------------------------------
  // Encoding and encryption
  // ------------------------------------------------------------------

  @visibleForTesting
  static Uint8List encodeGuide({
    required String title,
    required String summary,
    required String transcript,
    required List<CapturedKeyframe> frames,
  }) => Uint8List.fromList(
    utf8.encode(
      jsonEncode({
        'v': 1,
        'title': title,
        'summary': summary,
        'transcript': transcript,
        'steps': [
          for (final frame in frames)
            {
              'id': frame.id,
              'title': frame.title,
              'instruction': frame.instruction,
              if (frame.imageBytes.isNotEmpty)
                'image': base64Encode(frame.imageBytes),
            },
        ],
      }),
    ),
  );

  @visibleForTesting
  static ({
    String title,
    String summary,
    String transcript,
    List<CapturedKeyframe> frames,
  })
  decodeGuide(List<int> bytes) {
    final data = jsonDecode(utf8.decode(bytes));
    if (data is! Map || data['v'] != 1) {
      throw const FormatException('Unknown guide format.');
    }
    final title = (data['title'] as String? ?? '').trim();
    if (title.isEmpty || title.length > 100) {
      throw const FormatException('Invalid guide title.');
    }
    final now = DateTime.now();
    final frames = <CapturedKeyframe>[];
    for (final raw in (data['steps'] as List? ?? const [])) {
      if (raw is! Map) continue;
      final image = raw['image'];
      frames.add(
        CapturedKeyframe(
          id: '${raw['id'] ?? frames.length}',
          timestamp: now,
          imageBytes: image is String ? base64Decode(image) : Uint8List(0),
          title: '${raw['title'] ?? ''}',
          instruction: '${raw['instruction'] ?? ''}',
          perceptualHash: null,
          colorSignature: null,
          privacyReviewed: true,
        ),
      );
    }
    return (
      title: title,
      summary: '${data['summary'] ?? ''}',
      transcript: '${data['transcript'] ?? ''}',
      frames: frames,
    );
  }

  /// nonce (12) || ciphertext || tag (16)
  @visibleForTesting
  static Future<Uint8List> seal(List<int> key, List<int> plaintext) async {
    final box = await _cipher.encrypt(plaintext, secretKey: SecretKey(key));
    return Uint8List.fromList(box.concatenation());
  }

  @visibleForTesting
  static Future<Uint8List> open(List<int> key, List<int> sealed) async {
    final box = SecretBox.fromConcatenation(
      sealed,
      nonceLength: _cipher.nonceLength,
      macLength: _cipher.macAlgorithm.macLength,
    );
    return Uint8List.fromList(
      await _cipher.decrypt(box, secretKey: SecretKey(key)),
    );
  }

  // ------------------------------------------------------------------
  // Helper: send after the call
  // ------------------------------------------------------------------

  static Future<Directory> _outbox() async {
    final support = await getApplicationSupportDirectory();
    final dir = Directory('${support.path}${Platform.pathSeparator}guide_outbox');
    if (!await dir.exists()) await dir.create(recursive: true);
    return dir;
  }

  /// Encrypts the guide, keeps the sealed copy in the outbox, then tries to
  /// upload it. Returns true once the backend accepted it; otherwise the
  /// outbox copy is retried by [flushOutbox].
  static Future<bool> sendAfterCall({
    required ApiClient apiClient,
    required String sessionId,
    required List<int> key,
    required String title,
    required String summary,
    required String transcript,
    required List<CapturedKeyframe> frames,
  }) async {
    final sealed = await seal(
      key,
      encodeGuide(
        title: title,
        summary: summary,
        transcript: transcript,
        frames: frames,
      ),
    );
    final file = File(
      '${(await _outbox()).path}${Platform.pathSeparator}$sessionId.enc',
    );
    await file.writeAsBytes(sealed, flush: true);
    return _upload(apiClient, sessionId, file);
  }

  static Future<bool> _upload(
    ApiClient apiClient,
    String sessionId,
    File file,
  ) async {
    try {
      final response = await apiClient.post(
        '/guide-deliveries',
        body: {
          'session_id': sessionId,
          'ciphertext': base64Encode(await file.readAsBytes()),
        },
      );
      debugPrint('[AssistMe][GUIDE] post-call upload $sessionId: ${response.statusCode}');
      if (response.statusCode == 201) {
        await file.delete();
        return true;
      }
      // 403/409/413 will never succeed; drop them instead of retrying forever.
      if (response.statusCode >= 400 && response.statusCode < 500) {
        await file.delete();
      }
    } catch (error) {
      debugPrint('[AssistMe][GUIDE] post-call upload $sessionId failed: $error');
    }
    return false;
  }

  /// Retries uploads that failed earlier (no network, backend offline).
  static Future<int> flushOutbox(ApiClient apiClient) async {
    if (_flushingOutbox) return 0;
    _flushingOutbox = true;
    var sent = 0;
    try {
      await for (final entity in (await _outbox()).list(followLinks: false)) {
        if (entity is! File || !entity.path.endsWith('.enc')) continue;
        final name = entity.uri.pathSegments.last;
        final sessionId = name.substring(0, name.length - '.enc'.length);
        if (await _upload(apiClient, sessionId, entity)) sent++;
      }
    } catch (_) {
      // Try again next time.
    } finally {
      _flushingOutbox = false;
    }
    return sent;
  }

  // ------------------------------------------------------------------
  // Helpee: collect guides
  // ------------------------------------------------------------------

  /// Downloads, decrypts and saves every guide waiting for this phone.
  /// Returns the titles of the guides saved.
  static Future<List<String>> checkInbox({
    required ApiClient apiClient,
    required SecureValueStore storage,
  }) async {
    if (_checkingInbox) return const [];
    _checkingInbox = true;
    final saved = <String>[];
    try {
      final listing = await apiClient.get('/guide-deliveries/pending');
      if (listing.statusCode != 200) return saved;
      final items = jsonDecode(listing.body);
      if (items is! List || items.isEmpty) return saved;
      final store = LocalGuideStore(secureStorage: storage);
      final existing = await store.listGuides();
      for (final item in items) {
        if (item is! Map) continue;
        final id = '${item['id']}';
        final sessionId = '${item['session_id']}';
        if (alreadySaved(existing, sessionId)) {
          // The live call delivered it after all; just clear the copy.
          await apiClient.delete('/guide-deliveries/$id');
          continue;
        }
        final key = await keyFor(storage, sessionId);
        if (key == null) {
          debugPrint('[AssistMe][GUIDE] no key for delivery $id (session $sessionId)');
          continue;
        }
        final response = await apiClient.get('/guide-deliveries/$id');
        if (response.statusCode != 200) continue;
        final body = jsonDecode(response.body) as Map;
        final guide = decodeGuide(
          await open(key, base64Decode('${body['ciphertext']}')),
        );
        final stored = await store.saveSession(
          title: guide.title,
          summary: guide.summary,
          transcript: guide.transcript,
          frames: guide.frames,
          sessionId: sessionId,
        );
        await apiClient.delete('/guide-deliveries/$id');
        saved.add(stored.title);
        debugPrint('[AssistMe][GUIDE] post-call guide saved: ${guide.frames.length} steps');
      }
    } catch (error) {
      debugPrint('[AssistMe][GUIDE] inbox check failed: $error');
    } finally {
      _checkingInbox = false;
    }
    return saved;
  }

  /// True when a guide from this session is already saved, so a late
  /// delivery does not create a duplicate.
  static bool alreadySaved(List<SessionGuideItem> guides, String sessionId) =>
      guides.any((guide) => guide.sessionId == sessionId);
}
