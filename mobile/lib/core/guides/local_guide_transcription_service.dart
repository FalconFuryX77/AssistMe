/// Local Whisper transcription and decoding for temporary Android call audio.
library;

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_edge_ai/flutter_edge_ai.dart';

import 'local_guide_ai_service.dart';
import 'local_guide_audio_capture.dart';

class LocalGuideTranscriptionService {
  static const MethodChannel _decoder = MethodChannel(
    'com.assistme/local_guide_audio',
  );
  static const int sampleRate = 16000;
  static const int bytesPerSample = 2;
  static const int windowDurationSeconds = 30;
  static const int overlapDurationSeconds = 1;
  static const int maxRecordingDurationSeconds = 20 * 60;
  static const int _windowBytes =
      sampleRate * bytesPerSample * windowDurationSeconds;
  static const int _overlapBytes =
      sampleRate * bytesPerSample * overlapDurationSeconds;

  static Future<void> installModel({
    required void Function(int progress) onProgress,
    required CancelToken cancelToken,
  }) async {
    await LocalGuideAiService.initialize();
    if (FlutterEdgeAi.activeSttSpec?.sttModelType == SttModelType.whisper) {
      return;
    }
    await FlutterEdgeAi.installStt()
        .modelFromNetwork(
          'https://huggingface.co/litert-community/whisper-tiny/resolve/main/whisper_tiny_30s_f32.tflite',
        )
        .tokenizerFromNetwork(
          'https://huggingface.co/openai/whisper-tiny/resolve/main/tokenizer.json',
        )
        .ofType(SttModelType.whisper)
        .withModelProgress((progress) => onProgress(progress ~/ 2))
        .withTokenizerProgress((progress) => onProgress(50 + progress ~/ 2))
        .withCancelToken(cancelToken)
        .install();
  }

  /// Transcribes two temporary native recordings locally and deletes both
  /// files whether decoding or inference succeeds or fails.
  static Future<String> transcribeRecording(
    LocalGuideAudioRecording recording, {
    required String language,
  }) async {
    try {
      if (!Platform.isAndroid) {
        throw UnsupportedError('Call-audio transcription is Android only.');
      }
      await LocalGuideAiService.initialize();
      if (FlutterEdgeAi.activeSttSpec?.sttModelType != SttModelType.whisper) {
        throw StateError('Install the on-device speech model first.');
      }
      final recognizer = await FlutterEdgeAi.getActiveStt(language: language);
      final microphoneText = await _transcribeFile(
        recording.microphonePath,
        recognizer,
      );
      final remoteText = await _transcribeFile(
        recording.remoteAudioPath,
        recognizer,
      );
      return [
        if (microphoneText.isNotEmpty) 'Microphone audio:\n$microphoneText',
        if (remoteText.isNotEmpty) 'Call playback audio:\n$remoteText',
      ].join('\n\n');
    } finally {
      await recording.delete();
    }
  }

  static Future<Uint8List> _decode(String path) async {
    final pcm = await _decoder.invokeMethod<Uint8List>('decodeToPcm16kMono', {
      'path': path,
    });
    if (pcm == null || pcm.isEmpty || pcm.length.isOdd) {
      throw StateError('Could not decode the temporary call audio.');
    }
    return pcm;
  }

  static Future<String> _transcribeFile(
    String path,
    SpeechRecognizer recognizer,
  ) async {
    final pcm = await _decode(path);
    return transcribePcm16kMono(pcm, recognizer: recognizer);
  }

  /// Splits little-endian 16 kHz mono PCM into fixed Whisper windows, using a
  /// 1 second overlap to reduce cut-off words at chunk boundaries.
  static List<Uint8List> splitPcm16kMono(Uint8List pcm) {
    if (pcm.length.isOdd) {
      throw ArgumentError('PCM16 audio must have an even number of bytes.');
    }
    if (pcm.isEmpty) return const [];
    final chunks = <Uint8List>[];
    var start = 0;
    while (start < pcm.length) {
      final end = (start + _windowBytes).clamp(0, pcm.length);
      chunks.add(Uint8List.sublistView(pcm, start, end));
      if (end == pcm.length) break;
      start = end - _overlapBytes;
    }
    return chunks;
  }

  static Future<String> transcribePcm16kMono(
    Uint8List pcm, {
    SpeechRecognizer? recognizer,
  }) async {
    if (pcm.length.isOdd) {
      throw ArgumentError('PCM16 audio must have an even number of bytes.');
    }
    if (pcm.isEmpty) return '';
    final activeRecognizer =
        recognizer ?? await FlutterEdgeAi.getActiveStt(language: 'en');
    final chunks = splitPcm16kMono(pcm);
    final textChunks = <String>[];
    for (final chunk in chunks) {
      final text = (await activeRecognizer.transcribe(chunk)).trim();
      if (text.isEmpty) continue;
      textChunks.add(text);
    }
    return joinOverlappingChunks(textChunks);
  }

  static String joinOverlappingChunks(List<String> chunks) {
    if (chunks.isEmpty) return '';
    final words = chunks.first.split(RegExp(r'\s+')).toList();
    for (final chunk in chunks.skip(1)) {
      final next = chunk.split(RegExp(r'\s+'));
      final maxOverlap = words.length < next.length
          ? words.length
          : next.length;
      var overlap = 0;
      for (var count = maxOverlap; count > 0; count--) {
        final left = words.skip(words.length - count).toList();
        final right = next.take(count).toList();
        if (List.generate(count, (index) => index).every(
          (index) => _normalize(left[index]) == _normalize(right[index]),
        )) {
          overlap = count;
          break;
        }
      }
      if (overlap > 0) {
        final previousWord = words.last;
        final overlappedWord = next[overlap - 1];
        final trailingPunctuation = RegExp(
          r'[^\p{L}\p{N}]+$',
          unicode: true,
        ).stringMatch(overlappedWord);
        if (trailingPunctuation != null &&
            !RegExp(r'[^\p{L}\p{N}]+$', unicode: true).hasMatch(previousWord)) {
          words[words.length - 1] = '$previousWord$trailingPunctuation';
        }
      }
      words.addAll(next.skip(overlap));
    }
    return words.join(' ').trim();
  }

  static String _normalize(String word) => word.toLowerCase().replaceAll(
    RegExp(r'[^\p{L}\p{N}]', unicode: true),
    '',
  );
}
