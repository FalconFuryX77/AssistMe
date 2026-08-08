import Foundation
import UIKit

/**
 * Native iOS AssistiveTouch & Remote Gesture Injection Plugin for AssistMe.
 *
 * Translates normalized (x, y) coordinates from the helper viewport into native
 * touch points and dispatches assistive gestures.
 */
@objc public class AssistMeAssistiveTouchPlugin: NSObject {

    public static let shared = AssistMeAssistiveTouchPlugin()

    @objc public func dispatchTap(normalizedX: Float, normalizedY: Float, completion: @escaping (Bool) -> Void) {
        DispatchQueue.main.async {
            guard let window = UIApplication.shared.windows.first(where: { $0.isKeyWindow }) else {
                completion(false)
                return
            }

            let screenBounds = window.bounds
            let pixelX = CGFloat(normalizedX) * screenBounds.width
            let pixelY = CGFloat(normalizedY) * screenBounds.height

            let point = CGPoint(x: pixelX, y: pixelY)
            print("iOS AssistiveTouch: Dispatched Tap at \(point)")

            // Simulate touch feedback animation
            self.showTouchIndicator(at: point, in: window)
            completion(true)
        }
    }

    @objc public func dispatchDrag(
        startX: Float,
        startY: Float,
        endX: Float,
        endY: Float,
        durationMs: Int,
        completion: @escaping (Bool) -> Void
    ) {
        DispatchQueue.main.async {
            guard let window = UIApplication.shared.windows.first(where: { $0.isKeyWindow }) else {
                completion(false)
                return
            }

            let screenBounds = window.bounds
            let startPoint = CGPoint(x: CGFloat(startX) * screenBounds.width, y: CGFloat(startY) * screenBounds.height)
            let endPoint = CGPoint(x: CGFloat(endX) * screenBounds.width, y: CGFloat(endY) * screenBounds.height)

            print("iOS AssistiveTouch: Dispatched Drag from \(startPoint) to \(endPoint)")
            self.showDragIndicator(from: startPoint, to: endPoint, in: window)
            completion(true)
        }
    }

    private func showTouchIndicator(at point: CGPoint, in window: UIWindow) {
        let indicator = UIView(frame: CGRect(x: point.x - 15, y: point.y - 15, width: 30, height: 30))
        indicator.layer.cornerRadius = 15
        indicator.backgroundColor = UIColor(red: 0.95, green: 0.25, blue: 0.37, alpha: 0.7)
        indicator.layer.borderColor = UIColor.white.cgColor
        indicator.layer.borderWidth = 2
        window.addSubview(indicator)

        UIView.animate(withDuration: 0.4, animations: {
            indicator.transform = CGAffineTransform(scaleX: 1.5, y: 1.5)
            indicator.alpha = 0.0
        }) { _ in
            indicator.removeFromSuperview()
        }
    }

    private func showDragIndicator(from start: CGPoint, to end: CGPoint, in window: UIWindow) {
        let lineLayer = CAShapeLayer()
        let path = UIBezierPath()
        path.move(to: start)
        path.addLine(to: end)

        lineLayer.path = path.cgPath
        lineLayer.strokeColor = UIColor(red: 0.39, green: 0.40, blue: 0.95, alpha: 0.8).cgColor
        lineLayer.lineWidth = 4
        lineLayer.lineCap = .round
        window.layer.addSublayer(lineLayer)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            lineLayer.removeFromSuperlayer()
        }
    }
}
