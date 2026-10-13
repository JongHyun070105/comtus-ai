import AppKit
import CoreGraphics
import Darwin
import Foundation
import MacCaptureCore

@main
struct MacCaptureCLI {
    private struct WindowListResponse: Encodable {
        let status: String
        let windows: [WindowDescriptor]
    }

    @MainActor
    static func main() async {
        do {
            let args = Array(CommandLine.arguments.dropFirst())
            guard let command = args.first else { throw CaptureFailure.invalidArguments("Expected doctor, windows, capture, or ocr.") }
            if command == "capture" { _ = NSApplication.shared }
            switch command {
            case "doctor":
                try printJSON(["status": "EXEC_PASS", "screen_recording_permission": CGPreflightScreenCaptureAccess(),
                               "macos": ProcessInfo.processInfo.operatingSystemVersionString,
                               "capture_backend": "ScreenCaptureKit", "ocr_backend": "Vision"])
            case "windows":
                let windows = try await ScreenCaptureFrameSource().listWindows()
                try printJSON(WindowListResponse(status: windows.isEmpty ? "NO_WINDOWS" : "EXEC_PASS", windows: windows))
            case "capture":
                let windowID = try uint32Option("--window-id", in: args)
                let output = try stringOption("--output", in: args)
                let image = try await ScreenCaptureFrameSource().capture(windowID: windowID)
                try ScreenCaptureFrameSource().savePNG(image, to: URL(fileURLWithPath: output))
                try printJSON(["status": "EXEC_PASS", "window_id": windowID, "width_pixels": image.width,
                               "height_pixels": image.height, "output": output, "source": "SCREEN_CAPTURE_VERIFIED"])
            case "ocr":
                let path = try stringOption("--image", in: args)
                let state = try stateOption(in: args)
                let image = try loadCGImage(at: URL(fileURLWithPath: path))
                let region = try regionOption(in: args)
                let result = try VisionOCRProcessor().process(image, activePanel: region, state: state)
                try printJSON(result)
            default:
                throw CaptureFailure.invalidArguments("Unknown command: \(command)")
            }
        } catch let error as CaptureFailure {
            let body: [String: Any] = ["status": error.code == "SCREEN_RECORDING_PERMISSION_DENIED" ? "SKIP" : "EXEC_FAIL",
                                       "error_code": error.code, "message": error.localizedDescription]
            try? printJSON(body, to: FileHandle.standardError)
            exit(error.code == "SCREEN_RECORDING_PERMISSION_DENIED" ? 3 : 2)
        } catch {
            try? printJSON(["status": "EXEC_FAIL", "error_code": "CAPTURE_ERROR", "message": error.localizedDescription], to: FileHandle.standardError)
            exit(2)
        }
    }

    private static func printJSON<T: Encodable>(_ value: T, to handle: FileHandle = .standardOutput) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(value)
        handle.write(data)
        handle.write(Data([0x0A]))
    }

    private static func printJSON(_ value: [String: Any], to handle: FileHandle = .standardOutput) throws {
        let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
        handle.write(data)
        handle.write(Data([0x0A]))
    }

    private static func stringOption(_ name: String, in args: [String]) throws -> String {
        guard let index = args.firstIndex(of: name), args.indices.contains(index + 1) else {
            throw CaptureFailure.invalidArguments("Missing \(name) value.")
        }
        return args[index + 1]
    }

    private static func uint32Option(_ name: String, in args: [String]) throws -> UInt32 {
        guard let value = UInt32(try stringOption(name, in: args)) else { throw CaptureFailure.invalidArguments("\(name) must be a positive integer.") }
        return value
    }

    private static func regionOption(in args: [String]) throws -> ScreenRegion? {
        guard let index = args.firstIndex(of: "--active-panel") else { return nil }
        guard args.count >= index + 5,
              let x = Double(args[index + 1]), let y = Double(args[index + 2]),
              let width = Double(args[index + 3]), let height = Double(args[index + 4]) else {
            throw CaptureFailure.invalidArguments("--active-panel needs four normalized values: x y width height.")
        }
        return try ScreenRegion(x: x, y: y, width: width, height: height)
    }

    private static func stateOption(in args: [String]) throws -> ScreenState {
        guard let index = args.firstIndex(of: "--screen-state") else { return .unknown }
        guard args.indices.contains(index + 1), let state = ScreenState(rawValue: args[index + 1]) else {
            throw CaptureFailure.invalidArguments("--screen-state must be one of the supported screen-state enum values.")
        }
        return state
    }
}
