import 'package:assistme/core/guides/local_ai_device_support.dart';
import 'package:flutter_test/flutter_test.dart';

const int _gib = 1024 * 1024 * 1024;

Map<Object?, Object?> _phone({
  int sdk = 34,
  String abi = 'arm64-v8a',
  bool hasLiteRt = true,
  double ramGiB = 7.5,
  double freeGiB = 20,
  bool emulator = false,
}) => {
  'sdk_int': sdk,
  'release': '$sdk',
  'model': 'Test Phone',
  'native_abi': abi,
  'has_litert_lm': hasLiteRt,
  'total_ram_bytes': (ramGiB * _gib).round(),
  'free_storage_bytes': (freeGiB * _gib).round(),
  'is_emulator': emulator,
};

void main() {
  test('a modern 64-bit phone with 8 GB gets screenshots and transcripts', () {
    final report = LocalAiDeviceSupport.evaluate(_phone());
    expect(report.capability, LocalAiCapability.full);
    expect(report.canUseScreenshots, isTrue);
    expect(report.reason, isNull);
  });

  test('32-bit Android is refused with the real reason', () {
    final report = LocalAiDeviceSupport.evaluate(
      _phone(abi: 'armeabi-v7a', hasLiteRt: false),
    );
    expect(report.capability, LocalAiCapability.unsupported);
    expect(report.reason, contains('32-bit'));
  });

  test('an x86_64 emulator is refused as an emulator', () {
    final report = LocalAiDeviceSupport.evaluate(
      _phone(abi: 'x86_64', hasLiteRt: false, emulator: true),
    );
    expect(report.capability, LocalAiCapability.unsupported);
    expect(report.reason, contains('emulator'));
  });

  test('a 4 GB phone gets text-only generation', () {
    final report = LocalAiDeviceSupport.evaluate(_phone(ramGiB: 3.7));
    expect(report.capability, LocalAiCapability.textOnly);
    expect(report.canRunModel, isTrue);
    expect(report.canUseScreenshots, isFalse);
  });

  test('a 3 GB phone is refused', () {
    final report = LocalAiDeviceSupport.evaluate(_phone(ramGiB: 2.8));
    expect(report.capability, LocalAiCapability.unsupported);
    expect(report.reason, contains('RAM'));
  });

  test('low storage blocks only before the model is downloaded', () {
    final before = LocalAiDeviceSupport.evaluate(_phone(freeGiB: 1));
    expect(before.capability, LocalAiCapability.unsupported);
    expect(before.reason, contains('free space'));

    final after = LocalAiDeviceSupport.evaluate(
      _phone(freeGiB: 1),
      modelAlreadyInstalled: true,
    );
    expect(after.capability, LocalAiCapability.full);
  });

  test('Android 10 is refused', () {
    final report = LocalAiDeviceSupport.evaluate(_phone(sdk: 29));
    expect(report.capability, LocalAiCapability.unsupported);
    expect(report.reason, contains('Android 11'));
  });

  test('missing phone details are reported, not guessed', () {
    final report = LocalAiDeviceSupport.evaluate(const {});
    expect(report.capability, LocalAiCapability.unsupported);
  });
}
