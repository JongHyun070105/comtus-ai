import CoreGraphics
import Foundation

public protocol FrameSource: Sendable {
    func listWindows() async throws -> [WindowDescriptor]
    func capture(windowID: UInt32) async throws -> CGImage
}

public protocol FrameProcessor: Sendable {
    func process(_ image: CGImage, activePanel: ScreenRegion?, state: ScreenState) throws -> OCRDocument
}

public protocol InferenceEngine: Sendable {
    func infer(_ image: CGImage, frameIndex: Int, timestampSeconds: Double) async throws -> [ObjectObservation]
}

public struct UnknownScreenStateClassifier: Sendable {
    public init() {}
    public func classify(_: [TextObservation]) -> ScreenState { .unknown }
}

public struct ObservedScreenStateClassifier: Sendable {
    public init() {}

    public func classify(_ observations: [TextObservation]) -> ScreenState {
        recognition(observations).state
    }

    public func recognition(_ observations: [TextObservation]) -> ScreenClassification {
        func matching(_ predicate: (String, Double, Double) -> Bool) -> (Int, TextObservation)? {
            observations.enumerated().first { _, observation in
                let text = observation.text.filter { !$0.isWhitespace }
                let box = observation.bbox
                guard box.count == 4 else { return false }
                let x = box[0] + box[2] / 2
                let y = box[1] + box[3] / 2
                return observation.confidence >= ScreenProfileContract.minimumAnchorConfidence && predicate(text, x, y)
            }
        }

        // This multi-anchor profile is based on the locally stored real
        // pitcher-order screen. The lobby title alone also appears behind
        // overlays, so it cannot safely identify the active screen.
        let title = matching { $0.contains("선발투수변경") && (0.34...0.66).contains($1) && (0.78...0.89).contains($2) }
        let instruction = matching { $0.contains("내선발투수의순서를변경할수있습니다") && (0.25...0.75).contains($1) && (0.74...0.84).contains($2) }
        let reset = matching { $0 == "원래대로" && $1 < 0.42 && $2 < 0.12 }
        let save = matching { $0 == "저장" && $1 > 0.58 && $2 < 0.12 }
        let swap = matching { $0 == "선수교체" && (0.40...0.60).contains($1) && $2 < 0.10 }
        let back = matching { $0.contains("뒤로가기") && (0.35...0.65).contains($1) && $2 < 0.05 }
        var ownStarterRoles: [Int: (Int, TextObservation)] = [:]
        var opponentStarterRoles: [Int: (Int, TextObservation)] = [:]
        for (index, observation) in observations.enumerated() {
            let text = observation.text.filter { !$0.isWhitespace }
            let box = observation.bbox
            guard box.count == 4, observation.confidence >= 0.9,
                  (text.hasSuffix("R") || text.hasSuffix("L")),
                  let number = Int(text.prefix(1)), (1...5).contains(number),
                  text.hasPrefix("\(number)선발"),
                  (0.15...0.78).contains(box[1] + box[3] / 2) else { continue }
            let centerX = box[0] + box[2] / 2
            if (0.18...0.30).contains(centerX) {
                ownStarterRoles[number] = ownStarterRoles[number] ?? (index, observation)
            } else if (0.34...0.44).contains(centerX) {
                opponentStarterRoles[number] = opponentStarterRoles[number] ?? (index, observation)
            }
        }
        if let title, let instruction, let reset, let save {
            let legacyAnchors = [title, instruction, reset, save]
            let roleAnchors = ownStarterRoles.keys.sorted().compactMap { ownStarterRoles[$0] }
            let opponentRoleAnchors = opponentStarterRoles.keys.sorted().compactMap { opponentStarterRoles[$0] }
            let structurallyVerified = roleAnchors.count >= 2
                && ownStarterRoles[1] != nil
                && opponentRoleAnchors.count >= 2
                && swap != nil && back != nil
                && instruction.1.confidence >= ScreenProfileContract.verifiedConfidence
                && reset.1.confidence >= ScreenProfileContract.verifiedConfidence
            let anchors: [(Int, TextObservation)]
            let confidence: Double
            let status: ScreenClassificationStatus
            if structurallyVerified {
                anchors = legacyAnchors + roleAnchors + opponentRoleAnchors + [swap, back].compactMap { $0 }
                confidence = min(instruction.1.confidence, reset.1.confidence,
                                 roleAnchors.map { $0.1.confidence }.min() ?? 0,
                                 opponentRoleAnchors.map { $0.1.confidence }.min() ?? 0)
                status = confidence >= ScreenProfileContract.verifiedConfidence ? .verified : .candidate
            } else {
                anchors = legacyAnchors
                confidence = legacyAnchors.map { $0.1.confidence }.min() ?? 0
                status = confidence >= ScreenProfileContract.verifiedConfidence ? .verified : .candidate
            }
            if confidence >= ScreenProfileContract.minimumAnchorConfidence {
                return ScreenClassification(
                    state: .pitcherOrder,
                    status: status,
                    confidence: confidence,
                    anchorIndices: anchors.map(\.0),
                    profileVersion: ScreenProfileContract.version
                )
            }
        }
        return ScreenClassification(state: .unknown, status: .unknown, confidence: nil, anchorIndices: [])
    }
}

public struct LatencyStatistics: Codable, Equatable, Sendable {
    public let sampleCount: Int
    public let p50Milliseconds: Double?
    public let p95Milliseconds: Double?
    public let p99Milliseconds: Double?
    public let missedFrames: Int
}

public actor LatencyProfiler {
    private var stageDurations: [String: [Double]] = [:]
    private var missedFrames = 0

    public init() {}

    public func record(stage: String, durationMilliseconds: Double) {
        guard durationMilliseconds.isFinite, durationMilliseconds >= 0 else { return }
        stageDurations[stage, default: []].append(durationMilliseconds)
    }

    public func recordMissedFrame() { missedFrames += 1 }

    public func statistics(for stage: String) -> LatencyStatistics {
        let values = (stageDurations[stage] ?? []).sorted()
        func percentile(_ p: Double) -> Double? {
            guard !values.isEmpty else { return nil }
            let index = max(0, Int(ceil(p * Double(values.count))) - 1)
            return values[index]
        }
        return LatencyStatistics(sampleCount: values.count, p50Milliseconds: percentile(0.50),
                                 p95Milliseconds: percentile(0.95), p99Milliseconds: percentile(0.99),
                                 missedFrames: missedFrames)
    }
}
