import 'dart:typed_data';
import 'dart:io';

import 'package:assistme/core/guides/local_guide_transcription_service.dart';
import 'package:assistme/core/guides/local_guide_audio_capture.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('LocalGuideTranscriptionService', () {
    test('removes both temporary audio files and allows repeat cleanup', () async {
      final directory = await Directory.systemTemp.createTemp(
        'assistme-guide-audio-test-',
      );
      final microphone = File('${directory.path}/mic.mp4');
      final playback = File('${directory.path}/playback.mp4');
      await microphone.writeAsBytes([1, 2, 3]);
      await playback.writeAsBytes([4, 5, 6]);
      final recording = LocalGuideAudioRecording(
        microphonePath: microphone.path,
        remoteAudioPath: playback.path,
      );

      await recording.delete();
      await recording.delete();

      expect(await microphone.exists(), isFalse);
      expect(await playback.exists(), isFalse);
      await directory.delete();
    });

    test('splits long PCM into 30-second windows with a 1-second overlap', () {
      const sampleRate = 16000;
      const bytesPerSecond = sampleRate * 2;
      final pcm = Uint8List(30 * bytesPerSecond + 5 * bytesPerSecond);

      final chunks = LocalGuideTranscriptionService.splitPcm16kMono(pcm);

      expect(chunks, hasLength(2));
      expect(chunks.first.length, 30 * bytesPerSecond);
      expect(chunks.last.length, 6 * bytesPerSecond);
      expect(chunks.last.length.isEven, isTrue);
    });

    test('keeps one fixed window for audio of 30 seconds or less', () {
      const sampleRate = 16000;
      final pcm = Uint8List(8 * sampleRate * 2);

      final chunks = LocalGuideTranscriptionService.splitPcm16kMono(pcm);

      expect(chunks, hasLength(1));
      expect(chunks.single.length, pcm.length);
    });

    test('rejects partial PCM16 samples', () {
      expect(
        () => LocalGuideTranscriptionService.splitPcm16kMono(
          Uint8List.fromList([0x01]),
        ),
        throwsArgumentError,
      );
    });

    test('removes repeated words at overlapping chunk boundaries', () {
      final transcript = LocalGuideTranscriptionService.joinOverlappingChunks([
        'Open the settings menu and choose network',
        'choose network, then select Wi-Fi',
      ]);

      expect(
        transcript,
        'Open the settings menu and choose network, then select Wi-Fi',
      );
    });
  });
}
