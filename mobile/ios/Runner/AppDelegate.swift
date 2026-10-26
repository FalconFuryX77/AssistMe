import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GeneratedPluginRegistrant.register(with: self)
    if let controller = window?.rootViewController as? FlutterViewController {
      let guideChannel = FlutterMethodChannel(
        name: "assistme/local_guides",
        binaryMessenger: controller.binaryMessenger
      )
      guideChannel.setMethodCallHandler { call, result in
        guard call.method == "protectDirectory",
              let arguments = call.arguments as? [String: String],
              let requestedPath = arguments["path"] else {
          result(FlutterMethodNotImplemented)
          return
        }
        do {
          let supportDirectory = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
          ).standardizedFileURL
          let guideDirectory = supportDirectory.appendingPathComponent("local_guides_v1", isDirectory: true)
          let requestedDirectory = URL(fileURLWithPath: requestedPath, isDirectory: true).standardizedFileURL
          guard requestedDirectory == guideDirectory else {
            result(FlutterError(code: "invalid_path", message: "Invalid guide directory", details: nil))
            return
          }
          try FileManager.default.createDirectory(at: guideDirectory, withIntermediateDirectories: true)
          var values = URLResourceValues()
          values.isExcludedFromBackup = true
          var protectedDirectory = guideDirectory
          try protectedDirectory.setResourceValues(values)
          try FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: guideDirectory.path
          )
          result(nil)
        } catch {
          result(FlutterError(code: "guide_storage", message: "Could not secure local guide storage", details: nil))
        }
      }
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
