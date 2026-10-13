import CoreGraphics
import Foundation

public enum ScreenProfileContract {
    public static let version = "screen-profiles-v3"
    public static let minimumAnchorConfidence = 0.3
    public static let verifiedConfidence = 0.85
}

public enum VisionOCRContract {
    public static let engineVersion = "Vision-VNRecognizeTextRequestRevision3"
}

public enum ScreenState: String, Codable, CaseIterable, Sendable {
    case home = "HOME"
    case rankingLobby = "RANKING_LOBBY"
    case pitcherOrder = "PITCHER_ORDER"
    case opponentLineup = "OPPONENT_LINEUP"
    case opponentStartingPitcherDetail = "OPPONENT_STARTING_PITCHER_DETAIL"
    case playerDetailBatter = "PLAYER_DETAIL_BATTER"
    case playerDetailPitcher = "PLAYER_DETAIL_PITCHER"
    case teamRoster = "TEAM_ROSTER"
    case synergy = "SYNERGY"
    case positionTraining = "POSITION_TRAINING"
    case matchResult = "MATCH_RESULT"
    case unknown = "UNKNOWN"
}

public enum ScreenClassificationStatus: String, Codable, Equatable, Sendable {
    case verified = "VERIFIED"
    case candidate = "CANDIDATE"
    case unknown = "UNKNOWN"
}

public struct ScreenClassification: Codable, Equatable, Sendable {
    public let state: ScreenState
    public let status: ScreenClassificationStatus
    public let confidence: Double?
    public let anchorIndices: [Int]
    public let profileVersion: String

    public init(state: ScreenState, status: ScreenClassificationStatus, confidence: Double?, anchorIndices: [Int],
                profileVersion: String = ScreenProfileContract.version) {
        self.state = state
        self.status = status
        self.confidence = confidence
        self.anchorIndices = anchorIndices
        self.profileVersion = profileVersion
    }
}

public enum PlayerDetailKind: String, Codable, Sendable {
    case batter
    case pitcher

    public var pageCount: Int { self == .batter ? 3 : 3 }
}

public enum DetailArrow: String, Codable, Sendable {
    case topLeftSwitchPlayerPrevious
    case topRightSwitchPlayerNext
    case bottomPreviousInfoPage
    case bottomNextInfoPage
}

public struct PlayerDetailNavigation: Codable, Equatable, Sendable {
    public let kind: PlayerDetailKind
    public private(set) var page: Int

    public init(kind: PlayerDetailKind, page: Int = 1) throws {
        guard (1...kind.pageCount).contains(page) else { throw CaptureFailure.invalidPage(page) }
        self.kind = kind
        self.page = page
    }

    public mutating func apply(_ arrow: DetailArrow) throws {
        switch arrow {
        case .topLeftSwitchPlayerPrevious, .topRightSwitchPlayerNext:
            return
        case .bottomPreviousInfoPage:
            guard page > 1 else { throw CaptureFailure.invalidPage(page - 1) }
            page -= 1
        case .bottomNextInfoPage:
            guard page < kind.pageCount else { throw CaptureFailure.invalidPage(page + 1) }
            page += 1
        }
    }
}

/// Normalized Vision coordinates use a bottom-left origin: x, y, width, height.
public struct ScreenRegion: Codable, Equatable, Sendable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double

    public init(x: Double, y: Double, width: Double, height: Double) throws {
        guard [x, y, width, height].allSatisfy({ $0.isFinite && $0 >= 0 && $0 <= 1 }),
              width > 0, height > 0, x + width <= 1.000001, y + height <= 1.000001 else {
            throw CaptureFailure.invalidRegion
        }
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }

    public static let fullFrame = try! ScreenRegion(x: 0, y: 0, width: 1, height: 1)

    public func pixelRect(imageWidth: Int, imageHeight: Int) -> CGRect {
        CGRect(x: x * Double(imageWidth),
               y: (1 - y - height) * Double(imageHeight),
               width: width * Double(imageWidth),
               height: height * Double(imageHeight))
    }

    public func mapFromCrop(x: Double, y: Double, width: Double, height: Double) -> ScreenRegion? {
        try? ScreenRegion(x: self.x + x * self.width,
                          y: self.y + y * self.height,
                          width: width * self.width,
                          height: height * self.height)
    }
}

public struct TextObservation: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let text: String
    public let confidence: Double
    public let bbox: [Double]
    public let source: String
    public let field: String?

    public init(text: String, confidence: Double, bbox: ScreenRegion, source: String = "vision", field: String? = nil) {
        self.schemaVersion = 1
        self.text = text
        self.confidence = confidence
        self.bbox = [bbox.x, bbox.y, bbox.width, bbox.height]
        self.source = source
        self.field = field
    }
}

public struct OCRDocument: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let source: String
    public let screenState: ScreenState
    public let screenStatus: ScreenClassificationStatus
    public let screenConfidence: Double?
    public let screenAnchorIndices: [Int]
    public let screenProfileVersion: String
    public let ocrEngineVersion: String
    public let frameSize: [Int]
    public let activePanel: [Double]?
    public let observations: [TextObservation]

    public init(screenState: ScreenState, frameSize: [Int], activePanel: ScreenRegion?, observations: [TextObservation],
                screenStatus: ScreenClassificationStatus = .unknown, screenConfidence: Double? = nil,
                screenAnchorIndices: [Int] = [], screenProfileVersion: String = ScreenProfileContract.version,
                ocrEngineVersion: String = VisionOCRContract.engineVersion) {
        self.schemaVersion = 1
        self.source = "vision"
        self.screenState = screenState
        self.screenStatus = screenStatus
        self.screenConfidence = screenConfidence
        self.screenAnchorIndices = screenAnchorIndices
        self.screenProfileVersion = screenProfileVersion
        self.ocrEngineVersion = ocrEngineVersion
        self.frameSize = frameSize
        self.activePanel = activePanel.map { [$0.x, $0.y, $0.width, $0.height] }
        self.observations = observations
    }
}

public struct WindowDescriptor: Codable, Equatable, Sendable {
    public let windowID: UInt32
    public let title: String?
    public let processName: String?
    public let processID: Int32?
    public let bundleIdentifier: String?
    public let displayID: UInt32?
    public let originXPoints: Double
    public let originYPoints: Double
    public let widthPoints: Double
    public let heightPoints: Double
    public let backingScaleFactor: Double
    public let onScreen: Bool
}

public enum CaptureWindowIdentity {
    public static func matches(windowID: UInt32, processID: Int32?, bundleIdentifier: String?,
                               expectedWindowID: UInt32, expectedProcessID: Int32?,
                               expectedBundleIdentifier: String?) -> Bool {
        guard windowID == expectedWindowID else { return false }
        if let expectedProcessID, processID != expectedProcessID { return false }
        if let expectedBundleIdentifier, bundleIdentifier != expectedBundleIdentifier { return false }
        return true
    }
}

public struct ObjectObservation: Codable, Equatable, Sendable {
    public let label: String
    public let confidence: Double?
    public let bbox: ScreenRegion
    public let frameIndex: Int
    public let timestampSeconds: Double
}

public enum CaptureFailure: Error, LocalizedError, Equatable {
    case screenRecordingPermissionDenied
    case gameWindowNotFound(UInt32)
    case windowIdentityChanged(UInt32)
    case imageLoadFailed(String)
    case imageSaveFailed(String)
    case invalidRegion
    case invalidPage(Int)
    case invalidArguments(String)
    case visionLanguageUnavailable

    public var errorDescription: String? {
        switch self {
        case .screenRecordingPermissionDenied: "Screen Recording permission is not granted. Enable it in System Settings > Privacy & Security > Screen & System Audio Recording, then restart this command."
        case .gameWindowNotFound(let id): "No on-screen window with ID \(id) was found."
        case .windowIdentityChanged(let id): "Window ID \(id) no longer belongs to the process selected during discovery."
        case .imageLoadFailed(let path): "Unable to load image at \(path)."
        case .imageSaveFailed(let path): "Unable to write image at \(path)."
        case .invalidRegion: "ROI must be a non-empty normalized rectangle inside the frame."
        case .invalidPage(let page): "Player detail page \(page) is outside the supported 1...3 range."
        case .invalidArguments(let detail): detail
        case .visionLanguageUnavailable: "Vision does not support either Korean or English on this OS build."
        }
    }

    public var code: String {
        switch self {
        case .screenRecordingPermissionDenied: "SCREEN_RECORDING_PERMISSION_DENIED"
        case .gameWindowNotFound: "WINDOW_NOT_FOUND"
        case .windowIdentityChanged: "WINDOW_IDENTITY_CHANGED"
        case .imageLoadFailed: "IMAGE_LOAD_FAILED"
        case .imageSaveFailed: "IMAGE_SAVE_FAILED"
        case .invalidRegion: "INVALID_ROI"
        case .invalidPage: "INVALID_PAGE"
        case .invalidArguments: "INVALID_ARGUMENTS"
        case .visionLanguageUnavailable: "VISION_LANGUAGE_UNAVAILABLE"
        }
    }
}
