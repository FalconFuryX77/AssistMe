/// Encrypted, app-private persistence for transcripts and session guides.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import '../security/secure_storage_service.dart'
    show SecureValueStore, SecureStorageService;
import 'guide_models.dart';
import 'session_keyframe_manager.dart';

class LocalGuideStore {
  static const int _maxGuideBytes = 32 * 1024 * 1024;
  static const int _maxTranscriptCharacters = 200000;
  static const MethodChannel _iosStorageChannel = MethodChannel(
    'assistme/local_guides',
  );

  final SecureValueStore secureStorage;
  final Future<Directory> Function()? directoryProvider;
  final AesGcm _cipher = AesGcm.with256bits();
  Future<Directory>? _directoryFuture;
  Future<SecretKey>? _keyFuture;

  LocalGuideStore({required this.secureStorage, this.directoryProvider});

  Future<Directory> _directory() => _directoryFuture ??= _openDirectory();

  Future<Directory> _openDirectory() async {
    final support =
        await (directoryProvider?.call() ?? getApplicationSupportDirectory());
    final directory = Directory(
      '${support.path}${Platform.pathSeparator}local_guides_v1',
    );
    if (!await directory.exists()) await directory.create(recursive: true);
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      await _iosStorageChannel.invokeMethod<void>('protectDirectory', {
        'path': directory.path,
      });
    }
    return directory;
  }

  Future<SecretKey> _key() => _keyFuture ??= _loadOrCreateKey();

  Future<SecretKey> _loadOrCreateKey() async {
    final encoded = await secureStorage.read(
      key: SecureStorageService.keyGuideEncryptionKey,
    );
    if (encoded != null) {
      final bytes = base64Url.decode(base64Url.normalize(encoded));
      if (bytes.length != 32) {
        throw StateError('Stored guide encryption key has an invalid length.');
      }
      return SecretKey(bytes);
    }
    final random = Random.secure();
    final bytes = List<int>.generate(32, (_) => random.nextInt(256));
    final key = base64UrlEncode(bytes);
    await secureStorage.write(
      key: SecureStorageService.keyGuideEncryptionKey,
      value: key,
    );
    return SecretKey(bytes);
  }

  Future<Uint8List> _encrypt(List<int> cleartext) async {
    final box = await _cipher.encrypt(cleartext, secretKey: await _key());
    return Uint8List.fromList(box.concatenation());
  }

  Future<Uint8List> _decrypt(List<int> encrypted) async {
    final box = SecretBox.fromConcatenation(
      encrypted,
      nonceLength: _cipher.nonceLength,
      macLength: _cipher.macAlgorithm.macLength,
    );
    final cleartext = await _cipher.decrypt(box, secretKey: await _key());
    return Uint8List.fromList(cleartext);
  }

  Future<void> _writeAtomic(File target, List<int> bytes) async {
    final temporary = File('${target.path}.${_newId()}.tmp');
    try {
      await temporary.writeAsBytes(bytes, flush: true);
      await temporary.rename(target.path);
    } catch (_) {
      if (await temporary.exists()) await temporary.delete();
      rethrow;
    }
  }

  String _newId() {
    final random = Random.secure();
    final suffix = List<int>.generate(
      12,
      (_) => random.nextInt(256),
    ).map((value) => value.toRadixString(16).padLeft(2, '0')).join();
    return '${DateTime.now().microsecondsSinceEpoch}_$suffix';
  }

  Future<SessionGuideItem> saveSession({
    required String title,
    required String summary,
    required String transcript,
    required List<CapturedKeyframe> frames,
    String? sessionId,
    String category = 'general',
    bool madeByMe = false,
  }) async {
    final cleanedTitle = title.trim();
    if (cleanedTitle.isEmpty) throw ArgumentError('A guide title is required.');
    if (transcript.length > _maxTranscriptCharacters) {
      throw ArgumentError('Transcript exceeds the local guide size limit.');
    }
    final selectedFrames = List<CapturedKeyframe>.of(frames);
    final totalImageBytes = selectedFrames.fold<int>(
      0,
      (total, frame) => total + frame.imageBytes.length,
    );
    final metadataBytes = utf8
        .encode('$cleanedTitle\n$summary\n$transcript')
        .length;
    if (totalImageBytes + metadataBytes > _maxGuideBytes) {
      throw ArgumentError('Guide is larger than the supported 32 MiB limit.');
    }

    final directory = await _directory();
    final guideId = _newId();
    final createdAt = DateTime.now();
    final writtenFiles = <File>[];
    final steps = <GuideStepItem>[];
    try {
      for (var i = 0; i < selectedFrames.length; i++) {
        final frame = selectedFrames[i];
        if (frame.imageBytes.isEmpty) {
          // A written step with no screenshot.
          steps.add(
            GuideStepItem(
              id: frame.id,
              stepNumber: i + 1,
              title: frame.title,
              instruction: frame.instruction,
              createdAt: frame.timestamp,
            ),
          );
          continue;
        }
        final imageName = '${guideId}_$i.frame.enc';
        final imageFile = File(
          '${directory.path}${Platform.pathSeparator}$imageName',
        );
        final encryptedImage = await _encrypt(frame.imageBytes);
        await _writeAtomic(imageFile, encryptedImage);
        writtenFiles.add(imageFile);
        steps.add(
          GuideStepItem(
            id: frame.id,
            stepNumber: i + 1,
            title: frame.title,
            instruction: frame.instruction,
            localImagePath: imageFile.path,
            createdAt: frame.timestamp,
          ),
        );
      }

      final guide = SessionGuideItem(
        id: guideId,
        sessionId: sessionId,
        title: cleanedTitle,
        summary: summary.trim(),
        category: category,
        stepsCount: steps.length,
        createdAt: createdAt,
        steps: steps,
        transcript: transcript.trim(),
        isLocal: true,
        madeByMe: madeByMe,
      );
      final metadataFile = File(
        '${directory.path}${Platform.pathSeparator}$guideId.guide.enc',
      );
      final encryptedMetadata = await _encrypt(
        utf8.encode(jsonEncode(guide.toJson())),
      );
      await _writeAtomic(metadataFile, encryptedMetadata);
      return guide;
    } catch (_) {
      for (final file in writtenFiles) {
        if (await file.exists()) await file.delete();
      }
      rethrow;
    }
  }

  Future<List<SessionGuideItem>> listGuides() async {
    final directory = await _directory();
    final guides = <SessionGuideItem>[];
    await for (final entity in directory.list(followLinks: false)) {
      if (entity is! File || !entity.path.endsWith('.guide.enc')) continue;
      try {
        final cleartext = await _decrypt(await entity.readAsBytes());
        final decoded = jsonDecode(utf8.decode(cleartext));
        if (decoded is Map<String, dynamic>) {
          guides.add(SessionGuideItem.fromJson(decoded));
        }
      } on Object {
        // Ignore a damaged guide instead of failing the entire library. The
        // file remains so the user may recover it after a later key restore.
      }
    }
    guides.sort((left, right) => right.createdAt.compareTo(left.createdAt));
    return guides;
  }

  Future<Uint8List?> readImage(String? path) async {
    if (path == null || path.isEmpty) return null;
    final directory = await _directory();
    final normalizedRoot = '${directory.path}${Platform.pathSeparator}';
    final file = File(path);
    if (!file.path.startsWith(normalizedRoot) ||
        !file.path.endsWith('.frame.enc')) {
      throw ArgumentError('Image path is outside the local guide store.');
    }
    if (!await file.exists()) return null;
    return _decrypt(await file.readAsBytes());
  }

  Future<void> deleteGuide(SessionGuideItem guide) async {
    final directory = await _directory();
    final normalizedRoot = '${directory.path}${Platform.pathSeparator}';
    for (final step in guide.steps) {
      final path = step.localImagePath;
      if (path == null) continue;
      final image = File(path);
      if (image.path.startsWith(normalizedRoot) && await image.exists()) {
        await image.delete();
      }
    }
    final metadata = File(
      '${directory.path}${Platform.pathSeparator}${guide.id}.guide.enc',
    );
    if (await metadata.exists()) await metadata.delete();
  }
}
