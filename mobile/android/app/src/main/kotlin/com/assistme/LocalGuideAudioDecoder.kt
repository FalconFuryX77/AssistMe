package com.assistme

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.AudioFormat
import android.media.MediaFormat
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteOrder

/** Decode one app-cache audio recording to mono 16 kHz PCM16 for local STT. */
internal object LocalGuideAudioDecoder {
    private const val TARGET_RATE = 16_000
    private const val MAX_INPUT_BYTES = 32L * 1024L * 1024L
    private const val MAX_OUTPUT_BYTES = 20 * 60 * TARGET_RATE * 2

    fun decodeToPcm16kMono(cacheDirectory: File, path: String): ByteArray {
        val cacheRoot = cacheDirectory.canonicalFile.path + File.separator
        val input = File(path).canonicalFile
        require(input.path.startsWith(cacheRoot)) { "Audio must be in app cache." }
        require(input.name.startsWith("assistme-guide-") && input.extension == "mp4") {
            "Only temporary AssistMe guide recordings can be decoded."
        }
        require(input.isFile && input.length() in 1..MAX_INPUT_BYTES) {
            "Audio recording is missing or exceeds the temporary capture limit."
        }

        val extractor = MediaExtractor()
        var decoder: MediaCodec? = null
        try {
            extractor.setDataSource(input.path)
            var audioTrack = -1
            var inputFormat: MediaFormat? = null
            for (index in 0 until extractor.trackCount) {
                val format = extractor.getTrackFormat(index)
                val mime = format.getString(MediaFormat.KEY_MIME) ?: continue
                if (mime.startsWith("audio/")) {
                    audioTrack = index
                    inputFormat = format
                    break
                }
            }
            require(audioTrack >= 0 && inputFormat != null) {
                "The temporary recording has no audio track."
            }
            extractor.selectTrack(audioTrack)
            decoder = MediaCodec.createDecoderByType(
                inputFormat.getString(MediaFormat.KEY_MIME)!!
            )
            decoder.configure(inputFormat, null, null, 0)
            decoder.start()

            val output = ByteArrayOutputStream()
            val bufferInfo = MediaCodec.BufferInfo()
            var sourceRate = inputFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE)
            var channelCount = inputFormat.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
            var pcmEncoding = AudioFormat.ENCODING_PCM_16BIT
            var inputEnded = false
            var outputEnded = false
            var phase = 0
            var sampleSum = 0L
            var sampleCount = 0

            while (!outputEnded) {
                if (!inputEnded) {
                    val inputIndex = decoder.dequeueInputBuffer(10_000)
                    if (inputIndex >= 0) {
                        val buffer = decoder.getInputBuffer(inputIndex)
                            ?: throw IllegalStateException("Audio decoder input unavailable.")
                        buffer.clear()
                        val size = extractor.readSampleData(buffer, 0)
                        if (size < 0) {
                            decoder.queueInputBuffer(
                                inputIndex,
                                0,
                                0,
                                0,
                                MediaCodec.BUFFER_FLAG_END_OF_STREAM
                            )
                            inputEnded = true
                        } else {
                            decoder.queueInputBuffer(
                                inputIndex,
                                0,
                                size,
                                extractor.sampleTime,
                                0
                            )
                            extractor.advance()
                        }
                    }
                }

                when (val outputIndex = decoder.dequeueOutputBuffer(bufferInfo, 10_000)) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        val format = decoder.outputFormat
                        sourceRate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                        channelCount = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                        if (format.containsKey(MediaFormat.KEY_PCM_ENCODING)) {
                            pcmEncoding = format.getInteger(MediaFormat.KEY_PCM_ENCODING)
                        }
                    }
                    MediaCodec.INFO_TRY_AGAIN_LATER,
                    MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED -> Unit
                    else -> if (outputIndex >= 0) {
                        val buffer = decoder.getOutputBuffer(outputIndex)
                        if (buffer != null && bufferInfo.size > 0) {
                            require(sourceRate >= TARGET_RATE && channelCount > 0) {
                                "Unsupported audio format."
                            }
                            require(
                                pcmEncoding == AudioFormat.ENCODING_PCM_16BIT ||
                                    pcmEncoding == AudioFormat.ENCODING_PCM_FLOAT
                            ) { "Unsupported decoded PCM encoding." }
                            buffer.order(ByteOrder.LITTLE_ENDIAN)
                            buffer.position(bufferInfo.offset)
                            buffer.limit(bufferInfo.offset + bufferInfo.size)
                            val bytesPerPcmSample = if (
                                pcmEncoding == AudioFormat.ENCODING_PCM_FLOAT
                            ) 4 else 2
                            val totalSamples = bufferInfo.size / bytesPerPcmSample
                            var frame = 0
                            while (frame < totalSamples / channelCount) {
                                var mixed = 0.0
                                for (channel in 0 until channelCount) {
                                    mixed += if (
                                        pcmEncoding == AudioFormat.ENCODING_PCM_FLOAT
                                    ) {
                                        (buffer.float.coerceIn(-1f, 1f) * Short.MAX_VALUE).toDouble()
                                    } else {
                                        buffer.short.toDouble()
                                    }
                                }
                                val mono = (mixed / channelCount).toInt()
                                sampleSum += mono
                                sampleCount++
                                phase += TARGET_RATE
                                if (phase >= sourceRate) {
                                    phase -= sourceRate
                                    val filtered = (sampleSum / sampleCount).toInt()
                                        .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
                                    output.write(filtered and 0xff)
                                    output.write((filtered ushr 8) and 0xff)
                                    sampleSum = 0
                                    sampleCount = 0
                                    require(output.size() <= MAX_OUTPUT_BYTES) {
                                        "Recording exceeds the 20 minute guide limit."
                                    }
                                }
                                frame++
                            }
                        }
                        outputEnded = bufferInfo.flags and
                            MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                        decoder.releaseOutputBuffer(outputIndex, false)
                    }
                }
            }
            require(output.size() >= TARGET_RATE) { "Recording contains no usable speech audio." }
            return output.toByteArray()
        } finally {
            try {
                decoder?.stop()
            } catch (_: Exception) {}
            decoder?.release()
            extractor.release()
        }
    }
}
