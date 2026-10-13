import XCTest
import CoreGraphics
import CoreText
@testable import MacCaptureCore

final class CaptureCoreTests: XCTestCase {
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

    func testObservedScreenClassifierUsesOnlyTheCapturedRankingChallengeTitleAnchor() {
        let classifier = ObservedScreenStateClassifier()
        let titleBox = try! ScreenRegion(x: 0.433, y: 0.932, width: 0.098, height: 0.018)
        let offscreenTitleBox = try! ScreenRegion(x: 0.433, y: 0.5, width: 0.098, height: 0.018)
        XCTAssertEqual(classifier.classify([TextObservation(text: "랭킹 챌린지", confidence: 1, bbox: titleBox)]), .rankingLobby)
        XCTAssertEqual(classifier.classify([TextObservation(text: "라인업", confidence: 1, bbox: titleBox)]), .unknown)
        XCTAssertEqual(classifier.classify([TextObservation(text: "랭킹 챌린지", confidence: 0.8, bbox: titleBox)]), .unknown)
        XCTAssertEqual(classifier.classify([TextObservation(text: "랭킹 챌린지", confidence: 1, bbox: offscreenTitleBox)]), .unknown)
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
        XCTAssertEqual(document.frameSize, [width, height])
        XCTAssertEqual(try processor.process(image, activePanel: .fullFrame, state: .rankingLobby).screenState, .unknown)
        XCTAssertFalse(document.observations.isEmpty)
        XCTAssertTrue(document.observations.allSatisfy { observation in
            observation.schemaVersion == 1 && observation.source == "vision" && observation.confidence >= 0 && observation.confidence <= 1
                && observation.bbox.count == 4 && observation.bbox.allSatisfy { $0 >= 0 && $0 <= 1 }
        })
        XCTAssertThrowsError(try processor.process(image, activePanel: nil, state: .playerDetailBatter))
    }
}
