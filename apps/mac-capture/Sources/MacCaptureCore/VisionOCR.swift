import CoreGraphics
import Foundation
import Vision

public struct VisionOCRProcessor: FrameProcessor {
    public init() {}

    public func process(_ image: CGImage, activePanel: ScreenRegion?, state: ScreenState = .unknown) throws -> OCRDocument {
        if (state == .playerDetailBatter || state == .playerDetailPitcher), activePanel == nil {
            throw CaptureFailure.invalidRegion
        }
        let panel = activePanel ?? .fullFrame
        guard let cropped = image.cropping(to: panel.pixelRect(imageWidth: image.width, imageHeight: image.height)) else {
            throw CaptureFailure.invalidRegion
        }
        let request = VNRecognizeTextRequest()
        request.revision = VNRecognizeTextRequestRevision3
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        let supported = try request.supportedRecognitionLanguages()
        let languages = ["ko-KR", "en-US"].filter(supported.contains)
        guard !languages.isEmpty else { throw CaptureFailure.visionLanguageUnavailable }
        request.recognitionLanguages = languages
        request.customWords = ["컴프야V26", "랭킹챌린지", "후라도", "김영웅", "삼성 라이온즈"]
        try VNImageRequestHandler(cgImage: cropped).perform([request])
        var observations: [TextObservation] = []
        for result in request.results ?? [] {
            guard let candidate = result.topCandidates(1).first else { continue }
            let box = result.boundingBox
            guard let normalized = panel.mapFromCrop(x: Double(box.minX), y: Double(box.minY), width: Double(box.width), height: Double(box.height)) else { continue }
            observations.append(TextObservation(text: candidate.string, confidence: Double(candidate.confidence), bbox: normalized))
        }
        observations.sort(by: { (left: TextObservation, right: TextObservation) -> Bool in
            if abs(left.bbox[1] - right.bbox[1]) > 0.003 { return left.bbox[1] > right.bbox[1] }
            return left.bbox[0] < right.bbox[0]
        })
        let detected = ObservedScreenStateClassifier().recognition(observations)
        let resolved = state == .unknown || state == detected.state
            ? detected
            : ScreenClassification(state: .unknown, status: .unknown, confidence: nil, anchorIndices: [])
        return OCRDocument(screenState: resolved.state, frameSize: [image.width, image.height],
                           activePanel: activePanel, observations: observations,
                           screenStatus: resolved.status, screenConfidence: resolved.confidence,
                           screenAnchorIndices: resolved.anchorIndices)
    }
}
