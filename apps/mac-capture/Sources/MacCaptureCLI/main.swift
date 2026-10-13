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
            guard let command = args.first else { throw CaptureFailure.invalidArguments("Expected doctor, windows, capture, ocr, or navigate.") }
            if command == "capture" || command == "navigate" { _ = NSApplication.shared }
            switch command {
            case "doctor":
                try printJSON(["status": "EXEC_PASS", "screen_recording_permission": CGPreflightScreenCaptureAccess(),
                               "accessibility_permission": MacInputPermissionStatus.current.accessibilityTrusted,
                               "post_event_permission": MacInputPermissionStatus.current.postEventAllowed,
                               "input_monitor_permission": MacInputPermissionStatus.current.listenEventAllowed,
                               "macos": ProcessInfo.processInfo.operatingSystemVersionString,
                               "capture_backend": "ScreenCaptureKit", "ocr_backend": "Vision"])
            case "windows":
                let windows = try await ScreenCaptureFrameSource().listWindows()
                try printJSON(WindowListResponse(status: windows.isEmpty ? "NO_WINDOWS" : "EXEC_PASS", windows: windows))
            case "capture":
                let windowID = try uint32Option("--window-id", in: args)
                let expectedProcessID = try int32Option("--expected-process-id", in: args)
                let expectedBundleIdentifier = optionalStringOption("--expected-bundle-id", in: args)
                let output = try stringOption("--output", in: args)
                let image = try await ScreenCaptureFrameSource().capture(
                    windowID: windowID, expectedProcessID: expectedProcessID,
                    expectedBundleIdentifier: expectedBundleIdentifier)
                try ScreenCaptureFrameSource().savePNG(image, to: URL(fileURLWithPath: output))
                let capturedAt = ISO8601DateFormatter().string(from: Date())
                var response: [String: Any] = ["status": "EXEC_PASS", "window_id": windowID,
                                               "width_pixels": image.width, "height_pixels": image.height,
                                               "captured_at": capturedAt, "output": output,
                                               "source": "SCREEN_CAPTURE_VERIFIED"]
                if args.contains("--visual-signature") {
                    response["visual_signature"] = FrameVisualSignature.make(image)?.base64EncodedString() ?? ""
                    response["key_region_signature"] = FrameVisualSignature.makeKeyRegion(image)?.base64EncodedString() ?? ""
                }
                try printJSON(response)
            case "ocr":
                let path = try stringOption("--image", in: args)
                let state = try stateOption(in: args)
                let image = try loadCGImage(at: URL(fileURLWithPath: path))
                let region = try regionOption(in: args)
                let result = try VisionOCRProcessor().process(image, activePanel: region, state: state)
                try printJSON(result)
            case "navigate":
                try await runNavigation(args)
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

    @MainActor
    private static func runNavigation(_ args: [String]) async throws {
        guard args.count >= 2, args[1] == "collect" else {
            throw CaptureFailure.invalidArguments("Expected navigate collect --dry-run or --allow-ui-input --idle-only.")
        }
        let dryRun = args.contains("--dry-run")
        let allowInput = args.contains("--allow-ui-input")
        guard dryRun != allowInput else {
            throw CaptureFailure.invalidArguments("Choose exactly one of --dry-run or --allow-ui-input.")
        }
        if allowInput && !args.contains("--idle-only") {
            throw CaptureFailure.invalidArguments("--allow-ui-input requires --idle-only.")
        }
        let candidates = try await ScreenCaptureFrameSource().listWindows().filter {
            $0.processName == "V26"
                && $0.bundleIdentifier == MacGameInputAdapter.expectedV26BundleIdentifier
                && ($0.processID ?? 0) > 0 && $0.onScreen
        }
        guard candidates.count == 1, let window = candidates.first,
              let pid = window.processID else {
            try printJSON(["status": "BLOCKED", "input_sent": false,
                           "reason": candidates.isEmpty ? "V26_WINDOW_NOT_FOUND" : "V26_WINDOW_AMBIGUOUS"])
            return
        }
        let image = try await ScreenCaptureFrameSource().capture(
            windowID: window.windowID, expectedProcessID: pid,
            expectedBundleIdentifier: MacGameInputAdapter.expectedV26BundleIdentifier)
        let document = try VisionOCRProcessor().process(image, activePanel: nil, state: .unknown)
        let accessibility = MacGameInputAdapter.probeAccessibility(pid: pid, exactTargetLabel: "후라도'26")
        let name = document.observations
            .filter { $0.text.replacingOccurrences(of: " ", with: "").contains("후라도") }
            .max(by: { $0.confidence < $1.confidence })
        let playerIdentityConfidence = name?.confidence ?? 0
        let profileBounds = [0.145, 0.600, 0.122, 0.2067]
        let targetCanBeLocalized = document.screenState == .pitcherOrder
            && document.screenStatus == .verified
            && document.screenProfileVersion == ScreenProfileContract.version
        let targetIdentityVerified = targetCanBeLocalized && playerIdentityConfidence >= 0.90
        if allowInput {
            // The Korean V26 terms remain unreadable and no detail-page OCR
            // profile exists. Policy status is reported without inferring
            // permission; live input is blocked by missing screen evidence.
            try printJSON([
                "status": "BLOCKED", "input_sent": false,
                "reason_codes": ["DETAIL_SCREEN_PROFILE_NOT_VERIFIED",
                                 targetIdentityVerified ? "LIVE_INPUT_GATE_CLOSED" : "PLAYER_IDENTITY_NOT_VERIFIED"],
                "publisher_policy_status": "NOT_VERIFIABLE",
                "screen_state": document.screenState.rawValue,
                "screen_status": document.screenStatus.rawValue,
                "screen_confidence": document.screenConfidence as Any? ?? NSNull(),
                "screen_profile_version": document.screenProfileVersion,
                "screen_anchor_indices": document.screenAnchorIndices,
                "target_label": name?.text ?? "",
                "target_identity_confidence": playerIdentityConfidence,
                "window_id": window.windowID, "process_id": pid,
                "bundle_identifier": window.bundleIdentifier ?? "",
                "accessibility_tree_trusted": accessibility.trusted,
                "accessibility_window_count": accessibility.windowCount,
                "accessibility_element_count": accessibility.elementCount,
                "accessibility_pressable_button_count": accessibility.pressableButtonCount,
                "accessibility_exact_target_available": accessibility.exactTargetAvailable,
            ])
            return
        }
        try printJSON([
            "status": "EXEC_PASS", "mode": "DRY_RUN", "input_sent": false,
            "plan_status": targetIdentityVerified ? "READY_BUT_NOT_EXECUTED" : "BLOCKED",
            "reason": targetIdentityVerified ? "DRY_RUN_ONLY" : "PLAYER_IDENTITY_NOT_VERIFIED",
            "screen_state": document.screenState.rawValue,
            "screen_status": document.screenStatus.rawValue,
            "screen_confidence": document.screenConfidence as Any? ?? NSNull(),
            "screen_profile_version": document.screenProfileVersion,
            "screen_anchor_indices": document.screenAnchorIndices,
            "target_id": "pitcher-order:first-starter",
            "target_label": name?.text ?? "",
            "target_identity_confidence": playerIdentityConfidence,
            "target_bounds_vision_bottom_left_normalized": profileBounds,
            "window_id": window.windowID, "process_id": pid,
            "bundle_identifier": window.bundleIdentifier ?? "",
            "window_frame_points": [window.originXPoints, window.originYPoints,
                                    window.widthPoints, window.heightPoints],
            "backing_scale_factor": window.backingScaleFactor,
            "accessibility_permission": MacInputPermissionStatus.current.accessibilityTrusted,
            "accessibility_element_count": accessibility.elementCount,
            "accessibility_pressable_button_count": accessibility.pressableButtonCount,
            "accessibility_exact_target_available": accessibility.exactTargetAvailable,
            "post_event_permission": MacInputPermissionStatus.current.postEventAllowed,
        ])
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

    private static func optionalStringOption(_ name: String, in args: [String]) -> String? {
        guard let index = args.firstIndex(of: name), args.indices.contains(index + 1) else { return nil }
        return args[index + 1]
    }

    private static func uint32Option(_ name: String, in args: [String]) throws -> UInt32 {
        guard let value = UInt32(try stringOption(name, in: args)) else { throw CaptureFailure.invalidArguments("\(name) must be a positive integer.") }
        return value
    }

    private static func int32Option(_ name: String, in args: [String]) throws -> Int32? {
        guard args.contains(name) else { return nil }
        guard let value = Int32(try stringOption(name, in: args)), value > 0 else {
            throw CaptureFailure.invalidArguments("\(name) must be a positive integer.")
        }
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
