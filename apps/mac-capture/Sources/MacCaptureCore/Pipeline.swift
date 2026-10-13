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
                return observation.confidence >= 0.3 && predicate(text, x, y)
            }
        }

        // This multi-anchor profile is based on the locally stored real
        // pitcher-order screen. The lobby title alone also appears behind
        // overlays, so it cannot safely identify the active screen.
        let title = matching { $0.contains("선발투수변경") && (0.34...0.66).contains($1) && (0.78...0.89).contains($2) }
        let instruction = matching { $0.contains("내선발투수의순서를변경할수있습니다") && (0.25...0.75).contains($1) && (0.74...0.84).contains($2) }
        let reset = matching { $0 == "원래대로" && $1 < 0.42 && $2 < 0.12 }
        let save = matching { $0 == "저장" && $1 > 0.58 && $2 < 0.12 }
        if let title, let instruction, let reset, let save {
            let anchors = [title, instruction, reset, save]
            let confidence = anchors.map { $0.1.confidence }.min()
            if let confidence, confidence >= 0.3 {
                return ScreenClassification(
                    state: .pitcherOrder,
                    status: confidence >= 0.85 ? .verified : .candidate,
                    confidence: confidence,
                    anchorIndices: anchors.map(\.0)
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
