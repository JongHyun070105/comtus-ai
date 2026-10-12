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
    /// No title/keyword profiles are enabled until they are verified against real game screens.
    public init() {}
    public func classify(_: [TextObservation]) -> ScreenState { .unknown }
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
