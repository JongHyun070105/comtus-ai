import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

public enum SafeNavigationAction: String, Codable, Sendable {
    case openPlayerCard
    case nextInfoPage
    case previousInfoPage
}

/// These operations are modeled separately and are never accepted by the input adapter.
public enum AccountStateChangingAction: String, Codable, CaseIterable, Sendable {
    case startMatch
    case consumeChallengeAttempt
    case confirmPlayerSwap
    case saveStarterOrder
    case resetStarterOrder
    case enhancePlayer
    case trainPlayer
    case combinePlayer
    case releasePlayer
    case spendCurrency
    case purchaseItem
    case changeAccountSettings
}

public enum InputExecutionMode: String, Codable, Sendable {
    case dryRun
    case live
}

public struct DisplayCoordinateGeometry: Equatable, Sendable {
    public let appKitFrame: CGRect
    public let quartzFrame: CGRect
    public let backingScaleFactor: Double

    public init(appKitFrame: CGRect, quartzFrame: CGRect, backingScaleFactor: Double) throws {
        guard appKitFrame.width > 0, appKitFrame.height > 0,
              quartzFrame.width > 0, quartzFrame.height > 0,
              backingScaleFactor.isFinite, backingScaleFactor > 0 else {
            throw CaptureFailure.invalidRegion
        }
        self.appKitFrame = appKitFrame
        self.quartzFrame = quartzFrame
        self.backingScaleFactor = backingScaleFactor
    }

    /// Maps a Vision bottom-left normalized box through logical points into Quartz display space.
    public func quartzPoint(for region: ScreenRegion, window: WindowDescriptor,
                            imageWidth: Int, imageHeight: Int) throws -> CGPoint {
        guard window.widthPoints > 0, window.heightPoints > 0, imageWidth > 0, imageHeight > 0 else {
            throw CaptureFailure.invalidRegion
        }
        let scaleX = Double(imageWidth) / window.widthPoints
        let scaleY = Double(imageHeight) / window.heightPoints
        guard abs(scaleX - backingScaleFactor) <= 0.08,
              abs(scaleY - backingScaleFactor) <= 0.08 else {
            throw CaptureFailure.invalidRegion
        }
        let point = CGPoint(
            x: window.originXPoints + (region.x + region.width / 2) * window.widthPoints,
            y: window.originYPoints + (region.y + region.height / 2) * window.heightPoints
        )
        guard appKitFrame.contains(point) else { throw CaptureFailure.invalidRegion }
        let quartz = CGPoint(
            x: quartzFrame.minX + (point.x - appKitFrame.minX) * quartzFrame.width / appKitFrame.width,
            y: quartzFrame.minY + (appKitFrame.maxY - point.y) * quartzFrame.height / appKitFrame.height
        )
        guard quartzFrame.contains(quartz) else { throw CaptureFailure.invalidRegion }
        return quartz
    }
}

public struct NavigationFrameEvidence: Equatable, Sendable {
    public let window: WindowDescriptor
    public let imageWidth: Int
    public let imageHeight: Int
    public let screen: ScreenClassification
    public let playerKey: String?
    public let playerVerified: Bool
    public let page: Int?
    public let pageVerified: Bool
    public let frameSHA256: String

    public init(window: WindowDescriptor, imageWidth: Int, imageHeight: Int,
                screen: ScreenClassification, playerKey: String?, playerVerified: Bool,
                page: Int?, pageVerified: Bool, frameSHA256: String) {
        self.window = window
        self.imageWidth = imageWidth
        self.imageHeight = imageHeight
        self.screen = screen
        self.playerKey = playerKey
        self.playerVerified = playerVerified
        self.page = page
        self.pageVerified = pageVerified
        self.frameSHA256 = frameSHA256
    }
}

public struct VerifiedInputPlan: Equatable, Sendable {
    public let action: SafeNavigationAction
    public let targetID: String
    public let targetLabel: String
    public let region: ScreenRegion
    public let profileVersion: String
    public let expectedSourceState: ScreenState
    public let expectedSourcePlayer: String
    public let expectedSourcePage: Int?
    public let expectedTargetState: ScreenState
    public let expectedTargetPlayer: String
    public let expectedTargetPage: Int?
    public let sourceFrameSHA256: String
    public let sourceWindowID: UInt32
    public let sourceProcessID: Int32
    public let sourceBundleIdentifier: String
    public let sourceWindowFrame: CGRect
    public let sourceDisplayID: UInt32?
    public let sourceBackingScaleFactor: Double
    public let sourceImageWidth: Int
    public let sourceImageHeight: Int

    public init(action: SafeNavigationAction, targetID: String, targetLabel: String,
                region: ScreenRegion, profileVersion: String, source: NavigationFrameEvidence,
                targetState: ScreenState, targetPlayer: String, targetPage: Int?) throws {
        guard source.screen.status == .verified,
              source.screen.profileVersion == ScreenProfileContract.version,
              source.playerVerified, let player = source.playerKey,
              source.window.processName == "V26",
              source.window.bundleIdentifier == MacGameInputAdapter.expectedV26BundleIdentifier,
              let processID = source.window.processID, processID > 0,
              source.window.onScreen,
              source.frameSHA256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else {
            throw InputAdapterFailure.unverifiedSource
        }
        guard action == .openPlayerCard, targetID == "pitcher-order:first-starter",
              source.screen.state == .pitcherOrder, targetState == .playerDetailPitcher,
              targetLabel == "후라도'26", player == targetLabel,
              targetPlayer == targetLabel,
              source.page == nil, targetPage == 1,
              profileVersion == "pitcher-order-layout-v1",
              region == (try ScreenRegion(x: 0.145, y: 0.600, width: 0.122, height: 0.2067)) else {
            throw InputAdapterFailure.targetNotAllowlisted
        }
        self.action = action
        self.targetID = targetID
        self.targetLabel = targetLabel
        self.region = region
        self.profileVersion = profileVersion
        self.expectedSourceState = source.screen.state
        self.expectedSourcePlayer = player
        self.expectedSourcePage = source.page
        self.expectedTargetState = targetState
        self.expectedTargetPlayer = targetPlayer
        self.expectedTargetPage = targetPage
        self.sourceFrameSHA256 = source.frameSHA256
        self.sourceWindowID = source.window.windowID
        self.sourceProcessID = source.window.processID ?? 0
        self.sourceBundleIdentifier = source.window.bundleIdentifier ?? ""
        self.sourceWindowFrame = CGRect(x: source.window.originXPoints, y: source.window.originYPoints,
                                        width: source.window.widthPoints, height: source.window.heightPoints)
        self.sourceDisplayID = source.window.displayID
        self.sourceBackingScaleFactor = source.window.backingScaleFactor
        self.sourceImageWidth = source.imageWidth
        self.sourceImageHeight = source.imageHeight
    }

    public func matchesSource(_ evidence: NavigationFrameEvidence) -> Bool {
        evidence.window.windowID == sourceWindowID
            && evidence.window.processID == sourceProcessID
            && evidence.window.bundleIdentifier == sourceBundleIdentifier
            && evidence.window.processName == "V26"
            && evidence.window.onScreen
            && evidence.window.displayID == sourceDisplayID
            && CGRect(x: evidence.window.originXPoints, y: evidence.window.originYPoints,
                      width: evidence.window.widthPoints, height: evidence.window.heightPoints) == sourceWindowFrame
            && evidence.window.backingScaleFactor == sourceBackingScaleFactor
            && evidence.imageWidth == sourceImageWidth && evidence.imageHeight == sourceImageHeight
            && evidence.screen.status == .verified
            && evidence.screen.profileVersion == profileVersionForScreen
            && evidence.screen.state == expectedSourceState
            && evidence.playerVerified && evidence.playerKey == expectedSourcePlayer
            && evidence.page == expectedSourcePage
            && evidence.frameSHA256 == sourceFrameSHA256
    }

    public func matchesTarget(_ evidence: NavigationFrameEvidence) -> Bool {
        evidence.screen.status == .verified
            && evidence.screen.profileVersion == profileVersionForScreen
            && evidence.screen.state == expectedTargetState
            && evidence.playerVerified && evidence.playerKey == expectedTargetPlayer
            && evidence.pageVerified && evidence.page == expectedTargetPage
    }

    private var profileVersionForScreen: String { ScreenProfileContract.version }
}

public enum TransitionObservation: Equatable, Sendable {
    case expected
    case unchanged
    case unexpected
}

public struct VerifiedNavigationResult: Equatable, Sendable {
    public let attempts: Int
    public let finalEvidence: NavigationFrameEvidence
}

public enum NavigationTransitionVerifier {
    public static func verify(plan: VerifiedInputPlan, before: NavigationFrameEvidence,
                              after: NavigationFrameEvidence) -> TransitionObservation {
        if plan.matchesTarget(after) { return .expected }
        if after.screen.status == .verified,
           after.screen.state == before.screen.state,
           after.playerKey == before.playerKey,
           after.page == before.page {
            return .unchanged
        }
        return .unexpected
    }
}

public enum InputAdapterFailure: Error, LocalizedError, Equatable {
    case inputFlagRequired
    case idleOnlyRequired
    case userNotIdle
    case gameNotFrontmost
    case emergencyStop
    case accessibilityOrPostEventPermissionRequired
    case inputMonitorPermissionRequired
    case unverifiedSource
    case targetNotAllowlisted
    case preActionScreenChanged
    case unexpectedScreenTransition
    case transitionDidNotOccur
    case clickRetryLimitReached
    case gameWindowIdentityChanged
    case displayGeometryUnavailable
    case dispatchFailed(String)

    public var errorDescription: String? {
        switch self {
        case .inputFlagRequired: "Live input requires --allow-ui-input."
        case .idleOnlyRequired: "Live input requires --idle-only."
        case .userNotIdle: "User input was detected; navigation is paused at the current checkpoint."
        case .gameNotFrontmost: "The verified V26 window is not frontmost; focus was not changed."
        case .emergencyStop: "Emergency stop requested."
        case .accessibilityOrPostEventPermissionRequired: "Accessibility or Post Event permission is unavailable. Use the official macOS Privacy & Security settings; no permission was requested automatically."
        case .inputMonitorPermissionRequired: "A listen-only user-input monitor could not be created. Enable the official macOS Input Monitoring permission; no permission was requested automatically."
        case .unverifiedSource: "The source screen, player identity, or capture evidence is not verified."
        case .targetNotAllowlisted: "The target/action pair is not in the versioned safe-navigation profile."
        case .preActionScreenChanged: "The game screen changed before input; the click was cancelled."
        case .unexpectedScreenTransition: "The post-click screen did not match the expected player and page; navigation stopped."
        case .transitionDidNotOccur: "The screen did not change after the click."
        case .clickRetryLimitReached: "The bounded click retry limit was reached."
        case .gameWindowIdentityChanged: "The selected V26 window identity changed."
        case .displayGeometryUnavailable: "The selected window display geometry is unavailable."
        case .dispatchFailed(let detail): "The standard macOS UI action failed: \(detail)"
        }
    }
}

public struct UserActivityGate: Equatable, Sendable {
    public let minimumIdleSeconds: Double
    public private(set) var lastInputTime: Double
    public private(set) var emergencyStopped: Bool

    public init(minimumIdleSeconds: Double = 5, lastInputTime: Double = 0,
                emergencyStopped: Bool = false) throws {
        guard minimumIdleSeconds.isFinite, minimumIdleSeconds > 0,
              lastInputTime.isFinite else { throw CaptureFailure.invalidRegion }
        self.minimumIdleSeconds = minimumIdleSeconds
        self.lastInputTime = lastInputTime
        self.emergencyStopped = emergencyStopped
    }

    public mutating func noteUserInput(at time: Double) {
        if time.isFinite { lastInputTime = max(lastInputTime, time) }
    }

    public mutating func requestEmergencyStop() { emergencyStopped = true }

    public func isIdle(at time: Double) -> Bool {
        time.isFinite && time - lastInputTime >= minimumIdleSeconds
    }
}

private final class InputActivityState: @unchecked Sendable {
    private let lock = NSLock()
    private var lastActivity = Date()
    private var emergencyStopRequested = false

    func record(emergencyStop: Bool = false) {
        lock.lock()
        lastActivity = Date()
        emergencyStopRequested = emergencyStopRequested || emergencyStop
        lock.unlock()
    }

    func secondsSinceActivity() -> TimeInterval {
        lock.lock(); defer { lock.unlock() }
        return Date().timeIntervalSince(lastActivity)
    }

    var shouldStop: Bool {
        lock.lock(); defer { lock.unlock() }
        return emergencyStopRequested
    }
}

@MainActor
public final class UserInputActivityMonitor {
    private let state = InputActivityState()
    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?

    public init() {}

    public var secondsSinceUserInput: TimeInterval { state.secondsSinceActivity() }
    public var emergencyStopRequested: Bool { state.shouldStop }

    public func start() throws {
        guard eventTap == nil else { return }
        guard CGPreflightListenEventAccess() else {
            throw InputAdapterFailure.inputMonitorPermissionRequired
        }
        var mask: CGEventMask = 0
        for type: CGEventType in [.mouseMoved, .leftMouseDown, .leftMouseUp, .rightMouseDown,
                                  .rightMouseUp, .otherMouseDown, .otherMouseUp,
                                  .keyDown, .keyUp, .flagsChanged] {
            mask |= CGEventMask(1) << type.rawValue
        }
        let context = Unmanaged.passUnretained(state).toOpaque()
        guard let tap = CGEvent.tapCreate(tap: .cgSessionEventTap, place: .headInsertEventTap,
                                          options: .listenOnly, eventsOfInterest: mask,
                                          callback: Self.eventTapCallback, userInfo: context),
              let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0) else {
            throw InputAdapterFailure.inputMonitorPermissionRequired
        }
        eventTap = tap
        runLoopSource = source
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
        state.record()
    }

    public func stop() {
        if let source = runLoopSource { CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes) }
        if let eventTap { CGEvent.tapEnable(tap: eventTap, enable: false) }
        runLoopSource = nil
        eventTap = nil
    }

    public var isMonitoring: Bool {
        guard let eventTap else { return false }
        return CGEvent.tapIsEnabled(tap: eventTap)
    }

    public func waitUntilIdle(minimumIdleSeconds: TimeInterval = 5,
                              emergencyStop: () -> Bool = { false }) async throws {
        guard minimumIdleSeconds.isFinite, minimumIdleSeconds > 0 else {
            throw CaptureFailure.invalidRegion
        }
        while true {
            guard isMonitoring else { throw InputAdapterFailure.inputMonitorPermissionRequired }
            guard !state.shouldStop, !emergencyStop() else { throw InputAdapterFailure.emergencyStop }
            if secondsSinceUserInput >= minimumIdleSeconds { return }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
    }

    private static let eventTapCallback: CGEventTapCallBack = { _, type, event, refcon in
        guard let refcon else { return Unmanaged.passUnretained(event) }
        let state = Unmanaged<InputActivityState>.fromOpaque(refcon).takeUnretainedValue()
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            state.record()
            return Unmanaged.passUnretained(event)
        }
        if event.getIntegerValueField(.eventSourceUserData) != MacGameInputAdapter.syntheticEventMarker {
            let escapePressed = type == .keyDown
                && event.getIntegerValueField(.keyboardEventKeycode) == 53
            state.record(emergencyStop: escapePressed)
        }
        return Unmanaged.passUnretained(event)
    }
}

public struct MacInputPermissionStatus: Codable, Equatable, Sendable {
    public let accessibilityTrusted: Bool
    public let postEventAllowed: Bool
    public let listenEventAllowed: Bool

    public var canSendInput: Bool { accessibilityTrusted || postEventAllowed }

    public static var current: MacInputPermissionStatus {
        MacInputPermissionStatus(accessibilityTrusted: AXIsProcessTrusted(),
                                 postEventAllowed: CGPreflightPostEventAccess(),
                                 listenEventAllowed: CGPreflightListenEventAccess())
    }
}

public struct AccessibilityProbeResult: Codable, Equatable, Sendable {
    public let trusted: Bool
    public let windowCount: Int
    public let elementCount: Int
    public let pressableButtonCount: Int
    public let exactTargetAvailable: Bool
}

public enum MacGameInputAdapter {
    public static let expectedV26BundleIdentifier = "com.com2us.futurecpb.ios.apple.global.normal"
    fileprivate static let syntheticEventMarker: Int64 = 0x434F4D545553
    public static let maximumClickRetries = 1

    /// Reads the accessibility tree only; it never focuses an element or performs an action.
    public static func probeAccessibility(pid: Int32, exactTargetLabel: String) -> AccessibilityProbeResult {
        guard AXIsProcessTrusted() else {
            return AccessibilityProbeResult(trusted: false, windowCount: 0, elementCount: 0,
                                            pressableButtonCount: 0, exactTargetAvailable: false)
        }
        let windows = accessibilityWindows(pid: pid)
        var pending = windows
        var visited = 0
        var pressableButtons = 0
        var exactTarget = false
        while let element = pending.popLast(), visited < 1_000 {
            visited += 1
            if readAXString(element, attribute: kAXRoleAttribute as String) == (kAXButtonRole as String) {
                var actions: CFArray?
                if AXUIElementCopyActionNames(element, &actions) == .success,
                   (actions as? [String])?.contains(kAXPressAction as String) == true {
                    pressableButtons += 1
                    let labels = [kAXTitleAttribute, kAXDescriptionAttribute, kAXIdentifierAttribute]
                        .compactMap { readAXString(element, attribute: $0 as String) }
                    exactTarget = exactTarget || labels.contains(exactTargetLabel)
                }
            }
            pending.append(contentsOf: accessibilityChildren(of: element))
        }
        return AccessibilityProbeResult(trusted: true, windowCount: windows.count,
                                        elementCount: visited, pressableButtonCount: pressableButtons,
                                        exactTargetAvailable: exactTarget)
    }

    public static func dryRunPoint(plan: VerifiedInputPlan, evidence: NavigationFrameEvidence,
                                   display: DisplayCoordinateGeometry) throws -> CGPoint {
        guard plan.matchesSource(evidence) else { throw InputAdapterFailure.preActionScreenChanged }
        return try display.quartzPoint(for: plan.region, window: evidence.window,
                                       imageWidth: evidence.imageWidth, imageHeight: evidence.imageHeight)
    }

    @MainActor
    public static func dispatch(_ plan: VerifiedInputPlan, evidence: NavigationFrameEvidence,
                                display: DisplayCoordinateGeometry, allowUIInput: Bool,
                                idleOnly: Bool, monitor: UserInputActivityMonitor,
                                emergencyStop: Bool = false,
                                logURL: URL? = nil) throws -> CGPoint {
        guard allowUIInput else { throw InputAdapterFailure.inputFlagRequired }
        guard idleOnly else { throw InputAdapterFailure.idleOnlyRequired }
        guard !emergencyStop else { throw InputAdapterFailure.emergencyStop }
        guard monitor.isMonitoring else { throw InputAdapterFailure.inputMonitorPermissionRequired }
        guard plan.matchesSource(evidence) else { throw InputAdapterFailure.preActionScreenChanged }
        guard evidence.window.bundleIdentifier == expectedV26BundleIdentifier,
              let pid = evidence.window.processID, pid > 0,
              evidence.window.onScreen,
              CaptureWindowIdentity.matches(windowID: evidence.window.windowID,
                                            processID: evidence.window.processID,
                                            bundleIdentifier: evidence.window.bundleIdentifier,
                                            expectedWindowID: evidence.window.windowID,
                                            expectedProcessID: pid,
                                            expectedBundleIdentifier: expectedV26BundleIdentifier) else {
            throw InputAdapterFailure.gameWindowIdentityChanged
        }
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == pid else {
            throw InputAdapterFailure.gameNotFrontmost
        }
        guard monitor.secondsSinceUserInput >= 5 else { throw InputAdapterFailure.userNotIdle }
        let permissions = MacInputPermissionStatus.current
        let point = try display.quartzPoint(for: plan.region, window: evidence.window,
                                            imageWidth: evidence.imageWidth, imageHeight: evidence.imageHeight)
        let auditURL = effectiveLogURL(logURL)
        if permissions.accessibilityTrusted,
           let element = findUniqueAccessibleButton(pid: pid, exactLabel: plan.targetLabel) {
            try appendLog(auditURL, target: plan.targetID, method: "AX_PRESS", result: "INTENT")
            let error = AXUIElementPerformAction(element, kAXPressAction as CFString)
            guard error == .success else {
                try appendLog(auditURL, target: plan.targetID, method: "AX_PRESS", result: "FAILED_\(error.rawValue)")
                throw InputAdapterFailure.dispatchFailed("Accessibility action \(error.rawValue)")
            }
            try appendLog(auditURL, target: plan.targetID, method: "AX_PRESS", result: "SENT")
            return point
        }
        guard permissions.postEventAllowed else {
            throw InputAdapterFailure.accessibilityOrPostEventPermissionRequired
        }
        let source = CGEventSource(stateID: .hidSystemState)
        guard let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown,
                                 mouseCursorPosition: point, mouseButton: .left),
              let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp,
                               mouseCursorPosition: point, mouseButton: .left) else {
            throw InputAdapterFailure.dispatchFailed("CGEvent creation failed")
        }
        try appendLog(auditURL, target: plan.targetID, method: "CGEVENT_POST_TO_PID", result: "INTENT")
        down.setIntegerValueField(.eventSourceUserData, value: syntheticEventMarker)
        up.setIntegerValueField(.eventSourceUserData, value: syntheticEventMarker)
        down.postToPid(pid_t(pid))
        usleep(10_000)
        up.postToPid(pid_t(pid))
        try appendLog(auditURL, target: plan.targetID, method: "CGEVENT_POST_TO_PID", result: "SENT")
        return point
    }

    @MainActor
    public static func performVerified(_ plan: VerifiedInputPlan,
                                       allowUIInput: Bool, idleOnly: Bool,
                                       monitor: UserInputActivityMonitor,
                                       emergencyStop: () -> Bool = { false },
                                       maximumPostCaptureSamples: Int = 10,
                                       logURL: URL? = nil,
                                       capture: () async throws -> NavigationFrameEvidence) async throws -> VerifiedNavigationResult {
        guard allowUIInput else { throw InputAdapterFailure.inputFlagRequired }
        guard idleOnly else { throw InputAdapterFailure.idleOnlyRequired }
        guard (2...20).contains(maximumPostCaptureSamples) else { throw CaptureFailure.invalidRegion }
        let auditURL = effectiveLogURL(logURL)
        try appendCheckpoint(auditURL, windowID: plan.sourceWindowID,
                             screen: plan.expectedSourceState, player: plan.expectedSourcePlayer,
                             page: plan.expectedSourcePage, target: plan.targetID, reason: "session start")
        try monitor.start()
        defer { monitor.stop() }

        for attempt in 0...maximumClickRetries {
            try await monitor.waitUntilIdle(emergencyStop: emergencyStop)
            guard NSWorkspace.shared.frontmostApplication?.processIdentifier == plan.sourceProcessID else {
                throw InputAdapterFailure.gameNotFrontmost
            }
            let before = try await capture()
            try appendCheckpoint(auditURL, evidence: before, target: plan.targetID, reason: "before action")
            guard plan.matchesSource(before) else { throw InputAdapterFailure.preActionScreenChanged }
            guard let display = displayGeometry(for: before.window) else {
                throw InputAdapterFailure.displayGeometryUnavailable
            }
            _ = try dispatch(plan, evidence: before, display: display,
                             allowUIInput: allowUIInput, idleOnly: idleOnly,
                             monitor: monitor, emergencyStop: emergencyStop(), logURL: auditURL)

            var previous: NavigationFrameEvidence?
            var stableEvidence: NavigationFrameEvidence?
            var stableCount = 0
            for _ in 0..<maximumPostCaptureSamples {
                try await Task.sleep(nanoseconds: 200_000_000)
                try await monitor.waitUntilIdle(emergencyStop: emergencyStop)
                guard NSWorkspace.shared.frontmostApplication?.processIdentifier == plan.sourceProcessID else {
                    throw InputAdapterFailure.gameNotFrontmost
                }
                let current = try await capture()
                try appendCheckpoint(auditURL, evidence: current, target: plan.targetID, reason: "post action capture")
                if current.frameSHA256 == previous?.frameSHA256 {
                    stableCount += 1
                } else {
                    stableCount = 1
                }
                previous = current
                if stableCount >= 2 {
                    stableEvidence = current
                    break
                }
            }
            guard let after = stableEvidence else { throw InputAdapterFailure.unexpectedScreenTransition }
            switch NavigationTransitionVerifier.verify(plan: plan, before: before, after: after) {
            case .expected:
                try appendLog(auditURL, target: plan.targetID, method: "POST_CAPTURE_VERIFY", result: "VERIFIED")
                try appendCheckpoint(auditURL, evidence: after, target: plan.targetID, reason: "verified transition")
                return VerifiedNavigationResult(attempts: attempt + 1, finalEvidence: after)
            case .unexpected:
                try appendLog(auditURL, target: plan.targetID, method: "POST_CAPTURE_VERIFY", result: "UNEXPECTED_SCREEN")
                throw InputAdapterFailure.unexpectedScreenTransition
            case .unchanged:
                if attempt == maximumClickRetries {
                    try appendLog(auditURL, target: plan.targetID, method: "POST_CAPTURE_VERIFY", result: "NO_TRANSITION")
                    throw InputAdapterFailure.transitionDidNotOccur
                }
            }
        }
        throw InputAdapterFailure.clickRetryLimitReached
    }

    @MainActor
    private static func displayGeometry(for window: WindowDescriptor) -> DisplayCoordinateGeometry? {
        guard let displayID = window.displayID,
              let screen = NSScreen.screens.first(where: {
                  ($0.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value == displayID
              }) else { return nil }
        return try? DisplayCoordinateGeometry(appKitFrame: screen.frame,
                                              quartzFrame: CGDisplayBounds(CGDirectDisplayID(displayID)),
                                              backingScaleFactor: window.backingScaleFactor)
    }

    private static func findUniqueAccessibleButton(pid: Int32, exactLabel: String) -> AXUIElement? {
        var pending = accessibilityWindows(pid: pid)
        var visited = 0
        var matches: [AXUIElement] = []
        while let element = pending.popLast(), visited < 1_000 {
            visited += 1
            if readAXString(element, attribute: kAXRoleAttribute as String) == (kAXButtonRole as String) {
                let labels = [kAXTitleAttribute, kAXDescriptionAttribute, kAXIdentifierAttribute]
                    .compactMap { readAXString(element, attribute: $0 as String) }
                var rawActions: CFArray?
                if labels.contains(exactLabel),
                   AXUIElementCopyActionNames(element, &rawActions) == .success,
                   (rawActions as? [String])?.contains(kAXPressAction as String) == true {
                    matches.append(element)
                }
            }
            pending.append(contentsOf: accessibilityChildren(of: element))
        }
        return matches.count == 1 ? matches[0] : nil
    }

    private static func accessibilityWindows(pid: Int32) -> [AXUIElement] {
        let app = AXUIElementCreateApplication(pid_t(pid))
        var rawWindows: CFTypeRef?
        guard AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &rawWindows) == .success,
              let windows = rawWindows as? [AXUIElement] else { return [] }
        return windows
    }

    private static func accessibilityChildren(of element: AXUIElement) -> [AXUIElement] {
        var rawChildren: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &rawChildren) == .success,
              let children = rawChildren as? [AXUIElement] else { return [] }
        return children
    }

    private static func readAXString(_ element: AXUIElement, attribute: String) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else { return nil }
        return value as? String
    }

    private static func appendLog(_ url: URL?, target: String, method: String, result: String) throws {
        guard let url else { return }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        try FileManager.default.setAttributes([.posixPermissions: 0o700],
                                              ofItemAtPath: url.deletingLastPathComponent().path)
        let entry: [String: String] = ["at": ISO8601DateFormatter().string(from: Date()),
                                       "target": target, "method": method, "result": result]
        var data = try JSONSerialization.data(withJSONObject: entry, options: [.sortedKeys])
        data.append(0x0A)
        if FileManager.default.fileExists(atPath: url.path) {
            let handle = try FileHandle(forWritingTo: url)
            defer { try? handle.close() }
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } else {
            try data.write(to: url, options: .atomic)
        }
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    private static func effectiveLogURL(_ url: URL?) -> URL {
        if let url { return url }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support", isDirectory: true)
        return support.appendingPathComponent("comtus-ai/private/ui-actions.jsonl")
    }

    private static func appendCheckpoint(_ url: URL?, evidence: NavigationFrameEvidence,
                                         target: String, reason: String) throws {
        try appendCheckpoint(url, windowID: evidence.window.windowID, screen: evidence.screen.state,
                             player: evidence.playerVerified ? evidence.playerKey : nil,
                             page: evidence.pageVerified ? evidence.page : nil,
                             target: target, reason: reason)
    }

    private static func appendCheckpoint(_ url: URL?, windowID: UInt32, screen: ScreenState,
                                         player: String?, page: Int?, target: String,
                                         reason: String) throws {
        guard let url else { return }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        try FileManager.default.setAttributes([.posixPermissions: 0o700],
                                              ofItemAtPath: url.deletingLastPathComponent().path)
        let entry: [String: Any] = ["at": ISO8601DateFormatter().string(from: Date()),
                                    "event": "CHECKPOINT", "window_id": windowID,
                                    "screen_state": screen.rawValue,
                                    "player_key": (player as Any?) ?? NSNull(),
                                    "page": (page as Any?) ?? NSNull(),
                                    "target": target, "reason": reason]
        var data = try JSONSerialization.data(withJSONObject: entry, options: [.sortedKeys])
        data.append(0x0A)
        if FileManager.default.fileExists(atPath: url.path) {
            let handle = try FileHandle(forWritingTo: url)
            defer { try? handle.close() }
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } else {
            try data.write(to: url, options: .atomic)
        }
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
}
