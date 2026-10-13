import AppKit
import CoreGraphics
import Foundation

@main
struct InputAdapterSmoke {
    private static let bundleID = MacGameInputAdapter.expectedV26BundleIdentifier

    @MainActor
    static func main() {
        do {
            try run()
            print("EXEC_PASS: coordinate mapping, stale-plan rejection, transition identity, idle pause, emergency stop; no UI event sent")
        } catch {
            print("EXEC_FAIL: \(error)")
            exit(1)
        }
    }

    @MainActor
    private static func run() throws {
        _ = NSApplication.shared
        let window = WindowDescriptor(
            windowID: 12, title: "컴프야V26", processName: "V26", processID: 81562,
            bundleIdentifier: bundleID, displayID: 1, originXPoints: 100, originYPoints: 50,
            widthPoints: 800, heightPoints: 700, backingScaleFactor: 2, onScreen: true)
        let source = NavigationFrameEvidence(
            window: window, imageWidth: 1600, imageHeight: 1400,
            screen: ScreenClassification(state: .pitcherOrder, status: .verified,
                                         confidence: 1, anchorIndices: Array(0...9)),
            playerKey: "후라도'26", playerVerified: true, page: nil, pageVerified: false,
            frameSHA256: String(repeating: "a", count: 64))
        let plan = try VerifiedInputPlan(
            action: .openPlayerCard, targetID: "pitcher-order:first-starter", targetLabel: "후라도'26",
            region: ScreenRegion(x: 0.145, y: 0.600, width: 0.122, height: 0.2067),
            profileVersion: "pitcher-order-layout-v1", source: source,
            targetState: .playerDetailPitcher, targetPlayer: "후라도'26", targetPage: 1)
        let display = try DisplayCoordinateGeometry(
            appKitFrame: CGRect(x: 0, y: 0, width: 1440, height: 900),
            quartzFrame: CGRect(x: 0, y: 0, width: 1440, height: 900), backingScaleFactor: 2)
        let point = try MacGameInputAdapter.dryRunPoint(plan: plan, evidence: source, display: display)
        try require(abs(point.x - 264.8) < 0.001 && abs(point.y - 357.655) < 0.001,
                    "Window-relative plan mapping mismatch: \(point)")
        let mappingPoint = try display.quartzPoint(
            for: ScreenRegion(x: 0.25, y: 0.25, width: 0.1, height: 0.1),
            window: window, imageWidth: 1600, imageHeight: 1400)
        try require(abs(mappingPoint.x - 340) < 0.001 && abs(mappingPoint.y - 640) < 0.001,
                    "Retina Vision-to-Quartz mapping mismatch: \(mappingPoint)")

        let moved = NavigationFrameEvidence(
            window: WindowDescriptor(
                windowID: 12, title: "컴프야V26", processName: "V26", processID: 81562,
                bundleIdentifier: bundleID, displayID: 1, originXPoints: 101, originYPoints: 50,
                widthPoints: 800, heightPoints: 700, backingScaleFactor: 2, onScreen: true),
            imageWidth: 1600, imageHeight: 1400, screen: source.screen,
            playerKey: source.playerKey, playerVerified: true, page: nil, pageVerified: false,
            frameSHA256: source.frameSHA256)
        try require(!plan.matchesSource(moved), "A stale plan survived a window move")
        let secondaryDisplay = try DisplayCoordinateGeometry(
            appKitFrame: CGRect(x: -1280, y: 0, width: 1280, height: 1024),
            quartzFrame: CGRect(x: -1280, y: 0, width: 1280, height: 1024),
            backingScaleFactor: 2)
        let secondaryWindow = WindowDescriptor(
            windowID: 13, title: "컴프야V26", processName: "V26", processID: 81562,
            bundleIdentifier: bundleID, displayID: 37, originXPoints: -1200,
            originYPoints: 100, widthPoints: 800, heightPoints: 700,
            backingScaleFactor: 2, onScreen: true)
        let secondaryPoint = try secondaryDisplay.quartzPoint(
            for: ScreenRegion(x: 0.25, y: 0.25, width: 0.1, height: 0.1),
            window: secondaryWindow, imageWidth: 1600, imageHeight: 1400)
        try require(abs(secondaryPoint.x + 960) < 0.001 && abs(secondaryPoint.y - 714) < 0.001,
                    "Negative-origin display mapping mismatch: \(secondaryPoint)")

        let expected = NavigationFrameEvidence(
            window: window, imageWidth: 1600, imageHeight: 1400,
            screen: ScreenClassification(state: .playerDetailPitcher, status: .verified,
                                         confidence: 1, anchorIndices: Array(0...4)),
            playerKey: "후라도'26", playerVerified: true, page: 1, pageVerified: true,
            frameSHA256: String(repeating: "b", count: 64))
        let wrongPlayer = NavigationFrameEvidence(
            window: window, imageWidth: 1600, imageHeight: 1400, screen: expected.screen,
            playerKey: "다른 선수", playerVerified: true, page: 1, pageVerified: true,
            frameSHA256: expected.frameSHA256)
        try require(NavigationTransitionVerifier.verify(plan: plan, before: source, after: expected) == .expected,
                    "Verified transition was rejected")
        try require(NavigationTransitionVerifier.verify(plan: plan, before: source, after: wrongPlayer) == .unexpected,
                    "Wrong-player transition was accepted")

        var idle = try UserActivityGate(minimumIdleSeconds: 5, lastInputTime: 10)
        try require(!idle.isIdle(at: 14.9) && idle.isIdle(at: 15), "Idle threshold mismatch")
        idle.noteUserInput(at: 16)
        try require(!idle.isIdle(at: 20.9), "User activity did not reset idle time")
        idle.requestEmergencyStop()
        try require(idle.emergencyStopped, "Emergency stop was not retained")
    }

    private static func require(_ condition: Bool, _ message: String) throws {
        guard condition else { throw SmokeFailure(message: message) }
    }

    private struct SmokeFailure: Error, CustomStringConvertible {
        let message: String
        var description: String { message }
    }
}
