/// Decides, before anything is downloaded, whether this phone can run the
/// on-device guide AI (Gemma 4 E2B for steps, Whisper for transcripts).
///
/// LiteRT-LM and its speech backend ship native libraries for 64-bit ARM
/// Android only, and Gemma 4 E2B needs several GB of RAM. Older phones often
/// fail one of these, so the app reports the exact reason instead of a
/// generic "generation failed".
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

enum LocalAiCapability {
  /// Screenshot + transcript generation (vision model).
  full,

  /// Text-only generation: the phone has too little RAM for the vision encoder.
  textOnly,

  /// The model cannot run on this phone at all.
  unsupported,
}

@immutable
class LocalAiDeviceReport {
  final int sdkInt;
  final String release;
  final String model;
  final String nativeAbi;
  final bool hasLiteRtLm;
  final int totalRamBytes;
  final int freeStorageBytes;
  final bool isEmulator;
  final LocalAiCapability capability;

  /// Plain-language reason shown to the helper when [capability] is limited.
  final String? reason;

  const LocalAiDeviceReport({
    required this.sdkInt,
    required this.release,
    required this.model,
    required this.nativeAbi,
    required this.hasLiteRtLm,
    required this.totalRamBytes,
    required this.freeStorageBytes,
    required this.isEmulator,
    required this.capability,
    this.reason,
  });

  bool get canRunModel => capability != LocalAiCapability.unsupported;
  bool get canUseScreenshots => capability == LocalAiCapability.full;

  double get totalRamGiB => totalRamBytes / _gib;
  double get freeStorageGiB => freeStorageBytes / _gib;

  /// One line for diagnostics and the Settings screen.
  String get summary =>
      '$model · Android $release (API $sdkInt) · $nativeAbi · '
      '${totalRamGiB.toStringAsFixed(1)} GB RAM · '
      '${freeStorageGiB.toStringAsFixed(1)} GB free';
}

const double _gib = 1024 * 1024 * 1024;

class LocalAiDeviceSupport {
  static const MethodChannel _channel = MethodChannel(
    'com.assistme/local_ai_device',
  );

  // Android reports a little less than the marketed RAM: a 6 GB phone shows
  // about 5.4–5.6 GiB, a 4 GB phone about 3.6–3.8 GiB.
  static const double fullModeMinRamGiB = 5.0;
  static const double textModeMinRamGiB = 3.5;

  /// Gemma 4 E2B (~2.6 GB) plus Whisper tiny and working space.
  static const double requiredFreeStorageGiB = 3.2;

  static Map<Object?, Object?>? _cachedInfo;

  static Future<LocalAiDeviceReport> check({
    bool modelAlreadyInstalled = false,
  }) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) {
      return const LocalAiDeviceReport(
        sdkInt: 0,
        release: '',
        model: '',
        nativeAbi: '',
        hasLiteRtLm: false,
        totalRamBytes: 0,
        freeStorageBytes: 0,
        isEmulator: false,
        capability: LocalAiCapability.unsupported,
        reason: 'On-device guide AI is available on Android phones only.',
      );
    }
    var info = _cachedInfo;
    if (info == null) {
      try {
        info = await _channel.invokeMapMethod<Object?, Object?>(
          'getDeviceInfo',
        );
        _cachedInfo = info;
      } on PlatformException {
        info = null;
      } on MissingPluginException {
        info = null;
      }
    }
    return evaluate(
      info ?? const {},
      modelAlreadyInstalled: modelAlreadyInstalled,
    );
  }

  /// Pure decision logic, separated so it can be unit tested.
  @visibleForTesting
  static LocalAiDeviceReport evaluate(
    Map<Object?, Object?> info, {
    bool modelAlreadyInstalled = false,
  }) {
    int readInt(String key) => (info[key] as num?)?.toInt() ?? 0;
    final sdkInt = readInt('sdk_int');
    final release = info['release'] as String? ?? '';
    final model = info['model'] as String? ?? 'This phone';
    final nativeAbi = info['native_abi'] as String? ?? '';
    final hasLiteRtLm = info['has_litert_lm'] == true;
    final totalRam = readInt('total_ram_bytes');
    final freeStorage = readInt('free_storage_bytes');
    final isEmulator = info['is_emulator'] == true;

    LocalAiDeviceReport report(LocalAiCapability capability, [String? reason]) =>
        LocalAiDeviceReport(
          sdkInt: sdkInt,
          release: release,
          model: model,
          nativeAbi: nativeAbi,
          hasLiteRtLm: hasLiteRtLm,
          totalRamBytes: totalRam,
          freeStorageBytes: freeStorage,
          isEmulator: isEmulator,
          capability: capability,
          reason: reason,
        );

    if (info.isEmpty) {
      return report(
        LocalAiCapability.unsupported,
        'This build cannot read the phone details the guide AI needs.',
      );
    }
    if (sdkInt != 0 && sdkInt < 30) {
      return report(
        LocalAiCapability.unsupported,
        'The guide AI needs Android 11 or newer. This phone runs Android $release.',
      );
    }
    if (nativeAbi != 'arm64-v8a' || !hasLiteRtLm) {
      final why = isEmulator
          ? 'This is an emulator ($nativeAbi). The AI engine only ships for real 64-bit ARM phones.'
          : nativeAbi == 'armeabi-v7a'
          ? 'This phone runs 32-bit Android. The AI engine (Gemma and Whisper) only ships for 64-bit ARM Android.'
          : 'The AI engine is not installed for this phone\'s processor ($nativeAbi). It needs 64-bit ARM Android.';
      return report(LocalAiCapability.unsupported, why);
    }
    final ramGiB = totalRam / _gib;
    if (totalRam > 0 && ramGiB < textModeMinRamGiB) {
      return report(
        LocalAiCapability.unsupported,
        'Gemma 4 needs about 4 GB of RAM. This phone has ${ramGiB.toStringAsFixed(1)} GB.',
      );
    }
    if (!modelAlreadyInstalled &&
        freeStorage > 0 &&
        freeStorage / _gib < requiredFreeStorageGiB) {
      return report(
        LocalAiCapability.unsupported,
        'The AI models need about ${requiredFreeStorageGiB.toStringAsFixed(1)} GB of free space. '
        'This phone has ${(freeStorage / _gib).toStringAsFixed(1)} GB free.',
      );
    }
    if (totalRam > 0 && ramGiB < fullModeMinRamGiB) {
      return report(
        LocalAiCapability.textOnly,
        'This phone has ${ramGiB.toStringAsFixed(1)} GB of RAM, so Gemma will write steps '
        'from the notes and transcript without reading the screenshots.',
      );
    }
    return report(LocalAiCapability.full);
  }
}
