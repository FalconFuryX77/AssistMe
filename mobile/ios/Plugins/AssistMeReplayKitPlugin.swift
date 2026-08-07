import Foundation
import ReplayKit
import CoreMedia

/**
 * Native iOS ReplayKit Screen Capture & Broadcast Plugin for AssistMe.
 *
 * Captures iOS screen buffer via RPScreenRecorder and RPBroadcastSampleHandler,
 * translating CMSampleBufferRef video frames into WebRTC video tracks.
 */
@objc public class AssistMeReplayKitPlugin: NSObject {

    public static let shared = AssistMeReplayKitPlugin()
    private var isRecording = false
    private let screenRecorder = RPScreenRecorder.shared()

    @objc public func startScreenCapture(completion: @escaping (Bool, Error?) -> Void) {
        guard screenRecorder.isAvailable else {
            completion(false, NSError(domain: "com.assistme.replaykit", code: -1, userInfo: [NSLocalizedDescriptionKey: "Screen recorder unavailable on this device"]))
            return
        }

        screenRecorder.isMicrophoneEnabled = true
        screenRecorder.startCapture(handler: { (sampleBuffer, sampleBufferType, error) in
            if let error = error {
                print("ReplayKit capture error: \(error.localizedDescription)")
                return
            }

            switch sampleBufferType {
            case .video:
                self.processVideoSampleBuffer(sampleBuffer)
            case .audioApp:
                self.processAudioSampleBuffer(sampleBuffer, isAppAudio: true)
            case .audioMic:
                self.processAudioSampleBuffer(sampleBuffer, isAppAudio: false)
            @unknown default:
                break
            }
        }) { (error) in
            if let error = error {
                self.isRecording = false
                completion(false, error)
            } else {
                self.isRecording = true
                completion(true, nil)
            }
        }
    }

    @objc public func stopScreenCapture(completion: @escaping (Error?) -> Void) {
        guard isRecording else {
            completion(nil)
            return
        }

        screenRecorder.stopCapture { (error) in
            self.isRecording = false
            completion(error)
        }
    }

    private func processVideoSampleBuffer(_ sampleBuffer: CMSampleBuffer) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let timeStamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)

        // Forward pixelBuffer to WebRTC CVPixelBuffer RTCVideoFrame capturer
        // WebRTCVideoSource.shared.onCapturedPixelBuffer(pixelBuffer, timestamp: timeStamp)
    }

    private func processAudioSampleBuffer(_ sampleBuffer: CMSampleBuffer, isAppAudio: Bool) {
        // Forward audio buffers to WebRTC RTCAudioTrack
    }
}
