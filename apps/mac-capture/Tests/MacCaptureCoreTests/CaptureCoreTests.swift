import XCTest
import CoreGraphics
import CoreText
@testable import MacCaptureCore

private struct ScreenClassificationFixtureDocument: Decodable {
    let profileVersion: String
    let screenStates: [String]
    let cases: [ScreenClassificationFixtureCase]
}

private struct ScreenClassificationFixtureCase: Decodable {
    let name: String
    let observations: [ScreenClassificationFixtureObservation]
    let expected: ScreenClassificationFixtureExpected
}

private struct ScreenClassificationFixtureObservation: Decodable {
    let text: String
    let confidence: Double
    let bbox: [Double]
}

private struct ScreenClassificationFixtureExpected: Decodable {
    let state: String
    let status: String
    let confidence: Double?
    let anchorIndices: [Int]
}

final class CaptureCoreTests: XCTestCase {
    func testCaptureWindowMustKeepTheDiscoveredWindowProcessAndBundleIdentity() {
        XCTAssertTrue(CaptureWindowIdentity.matches(
            windowID: 12, processID: 81562, bundleIdentifier: "com.com2us.futurecpb.ios.apple.global.normal",
            expectedWindowID: 12, expectedProcessID: 81562,
            expectedBundleIdentifier: "com.com2us.futurecpb.ios.apple.global.normal"))
        XCTAssertFalse(CaptureWindowIdentity.matches(
            windowID: 12, processID: 81563, bundleIdentifier: "com.com2us.futurecpb.ios.apple.global.normal",
            expectedWindowID: 12, expectedProcessID: 81562,
            expectedBundleIdentifier: "com.com2us.futurecpb.ios.apple.global.normal"))
        XCTAssertFalse(CaptureWindowIdentity.matches(
            windowID: 12, processID: 81562, bundleIdentifier: "com.example.terminal",
            expectedWindowID: 12, expectedProcessID: 81562,
            expectedBundleIdentifier: "com.com2us.futurecpb.ios.apple.global.normal"))
    }

    func testDetailArrowSemanticsKeepPlayerSwitchSeparateFromPageChange() throws {
        var state = try PlayerDetailNavigation(kind: .pitcher, page: 1)
        try state.apply(.topRightSwitchPlayerNext)
        XCTAssertEqual(state.page, 1)
        try state.apply(.bottomNextInfoPage)
        XCTAssertEqual(state.page, 2)
    }

    func testBatterAndPitcherInitiallySupportFirstThreePages() throws {
        XCTAssertEqual(try PlayerDetailNavigation(kind: .batter).kind.pageCount, 3)
        XCTAssertEqual(try PlayerDetailNavigation(kind: .pitcher).kind.pageCount, 3)
        XCTAssertThrowsError(try PlayerDetailNavigation(kind: .pitcher, page: 4))
    }

    func testNormalizedVisionRegionMapsCropCoordinatesBackToFrame() throws {
        let panel = try ScreenRegion(x: 0.2, y: 0.1, width: 0.6, height: 0.8)
        guard let mapped = panel.mapFromCrop(x: 0.5, y: 0.5, width: 0.2, height: 0.1) else {
            XCTFail("Expected mapped crop coordinates")
            return
        }
        XCTAssertEqual(mapped.x, 0.5, accuracy: 0.000001)
        XCTAssertEqual(mapped.y, 0.5, accuracy: 0.000001)
        XCTAssertEqual(mapped.width, 0.12, accuracy: 0.000001)
        XCTAssertEqual(mapped.height, 0.08, accuracy: 0.000001)
        XCTAssertEqual(panel.pixelRect(imageWidth: 1000, imageHeight: 500).origin.y, 50)
    }

    func testInvalidRoiFailsClosedAndUnconfiguredScreenClassifierReturnsUnknown() throws {
        XCTAssertThrowsError(try ScreenRegion(x: 0.8, y: 0.1, width: 0.3, height: 0.2))
        XCTAssertEqual(UnknownScreenStateClassifier().classify([]), .unknown)
    }

    func testObservedScreenClassifierRequiresMultipleAnchorsAndScreenPlacement() throws {
        let classifier = ObservedScreenStateClassifier()
        let titleBox = try! ScreenRegion(x: 0.433, y: 0.932, width: 0.098, height: 0.018)
        XCTAssertEqual(classifier.classify([TextObservation(text: "랭킹 챌린지", confidence: 1, bbox: titleBox)]), .unknown)
        let pitcherOrder = [
            TextObservation(text: "{ 선발 투수 변경", confidence: 0.5,
                            bbox: try! ScreenRegion(x: 0.365, y: 0.825, width: 0.244, height: 0.028)),
            TextObservation(text: "좌측에 표시되는 내 선발 투수의 순서를 변경할 수 있습니다.", confidence: 1,
                            bbox: try! ScreenRegion(x: 0.289, y: 0.789, width: 0.435, height: 0.016)),
            TextObservation(text: "원래대로", confidence: 1,
                            bbox: try! ScreenRegion(x: 0.245, y: 0.056, width: 0.080, height: 0.019)),
            TextObservation(text: "저장", confidence: 0.5,
                            bbox: try! ScreenRegion(x: 0.696, y: 0.056, width: 0.042, height: 0.019)),
        ]
        XCTAssertEqual(classifier.classify(pitcherOrder), .pitcherOrder)
        let classification = classifier.recognition(pitcherOrder)
        XCTAssertEqual(classification.status, .candidate)
        XCTAssertEqual(classification.confidence, 0.5)
        XCTAssertEqual(classification.anchorIndices.count, 4)
        XCTAssertEqual(classifier.classify(Array(pitcherOrder.prefix(2))), .unknown)
        XCTAssertEqual(classifier.classify([TextObservation(text: "랭킹 챌린지", confidence: 0.8, bbox: titleBox)]), .unknown)
    }

    func testSharedScreenContractMatchesSwiftStateAnchorConfidenceAndVersion() throws {
        var repo = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { repo.deleteLastPathComponent() }
        let fixtureURL = repo.appendingPathComponent("schemas/v1/screen-classification-fixtures.json")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let fixture = try decoder.decode(ScreenClassificationFixtureDocument.self, from: Data(contentsOf: fixtureURL))
        XCTAssertEqual(ScreenState.allCases.map(\.rawValue), fixture.screenStates)
        XCTAssertEqual(ScreenProfileContract.version, fixture.profileVersion)

        let classifier = ObservedScreenStateClassifier()
        for item in fixture.cases {
            let observations = try item.observations.map { item -> TextObservation in
                guard item.bbox.count == 4 else { throw CaptureFailure.invalidRegion }
                let region = try ScreenRegion(x: item.bbox[0], y: item.bbox[1],
                                             width: item.bbox[2], height: item.bbox[3])
                return TextObservation(text: item.text, confidence: item.confidence, bbox: region)
            }
            let result = classifier.recognition(observations)
            XCTAssertEqual(result.state.rawValue, item.expected.state, item.name)
            XCTAssertEqual(result.status.rawValue, item.expected.status, item.name)
            XCTAssertEqual(result.confidence, item.expected.confidence, item.name)
            XCTAssertEqual(result.anchorIndices, item.expected.anchorIndices, item.name)
            XCTAssertEqual(result.profileVersion, fixture.profileVersion, item.name)
        }
    }

    func testLatencyProfilerReportsTailPercentilesAndMissedFrames() async {
        let profiler = LatencyProfiler()
        await profiler.record(stage: "capture", durationMilliseconds: 8)
        await profiler.record(stage: "capture", durationMilliseconds: 20)
        await profiler.record(stage: "capture", durationMilliseconds: 10)
        await profiler.recordMissedFrame()
        let stats = await profiler.statistics(for: "capture")
        XCTAssertEqual(stats.p50Milliseconds, 10)
        XCTAssertEqual(stats.p95Milliseconds, 20)
        XCTAssertEqual(stats.p99Milliseconds, 20)
        XCTAssertEqual(stats.missedFrames, 1)
    }

    func testVisionOCRProducesV1ObservationsFromSyntheticImageAndRequiresDetailROI() throws {
        let width = 640
        let height = 240
        guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                      bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            XCTFail("Could not create a synthetic test frame")
            return
        }
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let font = CTFontCreateWithName("Helvetica" as CFString, 44, nil)
        let attributes: [NSAttributedString.Key: Any] = [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 0, alpha: 1),
        ]
        let line = CTLineCreateWithAttributedString(NSAttributedString(string: "TEST 123", attributes: attributes))
        context.textPosition = CGPoint(x: 100, y: 85)
        context.textMatrix = .identity
        CTLineDraw(line, context)
        guard let image = context.makeImage() else {
            XCTFail("Could not finish the synthetic test frame")
            return
        }

        let processor = VisionOCRProcessor()
        let document = try processor.process(image, activePanel: .fullFrame, state: .unknown)
        XCTAssertEqual(document.schemaVersion, 1)
        XCTAssertEqual(document.screenProfileVersion, ScreenProfileContract.version)
        XCTAssertEqual(document.ocrEngineVersion, VisionOCRContract.engineVersion)
        XCTAssertEqual(document.frameSize, [width, height])
        XCTAssertEqual(try processor.process(image, activePanel: .fullFrame, state: .rankingLobby).screenState, .unknown)
        XCTAssertEqual(document.screenStatus, .unknown)
        XCTAssertFalse(document.observations.isEmpty)
        XCTAssertTrue(document.observations.allSatisfy { observation in
            observation.schemaVersion == 1 && observation.source == "vision" && observation.confidence >= 0 && observation.confidence <= 1
                && observation.bbox.count == 4 && observation.bbox.allSatisfy { $0 >= 0 && $0 <= 1 }
        })
        XCTAssertThrowsError(try processor.process(image, activePanel: nil, state: .playerDetailBatter))
    }
}
