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
    private func sampleV26Window(originX: Double = 100, originY: Double = 50,
                                 width: Double = 800, height: Double = 700,
                                 scale: Double = 2) -> WindowDescriptor {
        WindowDescriptor(windowID: 12, title: "컴프야V26", processName: "V26", processID: 81562,
                         bundleIdentifier: MacGameInputAdapter.expectedV26BundleIdentifier,
                         displayID: 1, originXPoints: originX, originYPoints: originY,
                         widthPoints: width, heightPoints: height,
                         backingScaleFactor: scale, onScreen: true)
    }

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

    func testVisionToQuartzMappingSeparatesRetinaPixelsAndLogicalPoints() throws {
        let window = sampleV26Window()
        let display = try DisplayCoordinateGeometry(appKitFrame: CGRect(x: 0, y: 0, width: 1440, height: 900),
                                                    quartzFrame: CGRect(x: 0, y: 0, width: 1440, height: 900),
                                                    backingScaleFactor: 2)
        let point = try display.quartzPoint(
            for: ScreenRegion(x: 0.25, y: 0.25, width: 0.1, height: 0.1),
            window: window, imageWidth: 1600, imageHeight: 1400)
        XCTAssertEqual(point.x, 340, accuracy: 0.001)
        XCTAssertEqual(point.y, 640, accuracy: 0.001)
        XCTAssertThrowsError(try display.quartzPoint(
            for: ScreenRegion(x: 0.25, y: 0.25, width: 0.1, height: 0.1),
            window: window, imageWidth: 800, imageHeight: 700))
    }

    func testVisionToQuartzMappingHandlesMovedWindowOnNegativeOriginDisplay() throws {
        let window = sampleV26Window(originX: -1200, originY: 100)
        let display = try DisplayCoordinateGeometry(appKitFrame: CGRect(x: -1280, y: 0, width: 1280, height: 1024),
                                                    quartzFrame: CGRect(x: -1280, y: 0, width: 1280, height: 1024),
                                                    backingScaleFactor: 2)
        let point = try display.quartzPoint(
            for: ScreenRegion(x: 0.25, y: 0.25, width: 0.1, height: 0.1),
            window: window, imageWidth: 1600, imageHeight: 1400)
        XCTAssertEqual(point.x, -960, accuracy: 0.001)
        XCTAssertEqual(point.y, 714, accuracy: 0.001)
    }

    func testSafeInputPlanIsBoundToVerifiedV26SourceAndFirstCardProfile() throws {
        let window = sampleV26Window()
        let source = NavigationFrameEvidence(
            window: window, imageWidth: 1600, imageHeight: 1400,
            screen: ScreenClassification(state: .pitcherOrder, status: .verified, confidence: 1,
                                         anchorIndices: Array(0...8)),
            playerKey: "후라도'26", playerVerified: true, page: nil, pageVerified: false,
            frameSHA256: String(repeating: "a", count: 64))
        let plan = try VerifiedInputPlan(
            action: .openPlayerCard, targetID: "pitcher-order:first-starter", targetLabel: "후라도'26",
            region: ScreenRegion(x: 0.145, y: 0.600, width: 0.122, height: 0.2067),
            profileVersion: "pitcher-order-layout-v1", source: source,
            targetState: .playerDetailPitcher, targetPlayer: "후라도'26", targetPage: 1)

        XCTAssertTrue(plan.matchesSource(source))
        let wrongWindow = NavigationFrameEvidence(
            window: WindowDescriptor(windowID: 12, title: "terminal", processName: "iTerm2", processID: 81562,
                                     bundleIdentifier: "com.googlecode.iterm2", displayID: 1,
                                     originXPoints: 100, originYPoints: 50, widthPoints: 800,
                                     heightPoints: 700, backingScaleFactor: 2, onScreen: true),
            imageWidth: 1600, imageHeight: 1400, screen: source.screen,
            playerKey: source.playerKey, playerVerified: true, page: nil, pageVerified: false,
            frameSHA256: source.frameSHA256)
        XCTAssertFalse(plan.matchesSource(wrongWindow))
        let movedWindow = NavigationFrameEvidence(
            window: sampleV26Window(originX: 101), imageWidth: 1600, imageHeight: 1400,
            screen: source.screen, playerKey: source.playerKey, playerVerified: true,
            page: nil, pageVerified: false, frameSHA256: source.frameSHA256)
        XCTAssertFalse(plan.matchesSource(movedWindow))
        let resizedImage = NavigationFrameEvidence(
            window: window, imageWidth: 1598, imageHeight: 1400,
            screen: source.screen, playerKey: source.playerKey, playerVerified: true,
            page: nil, pageVerified: false, frameSHA256: source.frameSHA256)
        XCTAssertFalse(plan.matchesSource(resizedImage))
        XCTAssertThrowsError(try VerifiedInputPlan(
            action: .openPlayerCard, targetID: "pitcher-order:save", targetLabel: "저장",
            region: ScreenRegion(x: 0.495, y: 0.03, width: 0.2, height: 0.06),
            profileVersion: "pitcher-order-layout-v1", source: source,
            targetState: .playerDetailPitcher, targetPlayer: "후라도'26", targetPage: 1))
        XCTAssertThrowsError(try VerifiedInputPlan(
            action: .openPlayerCard, targetID: "pitcher-order:first-starter", targetLabel: "후라도'26",
            region: ScreenRegion(x: 0.145, y: 0.600, width: 0.122, height: 0.2067),
            profileVersion: "pitcher-order-layout-v1", source: source,
            targetState: .playerDetailPitcher, targetPlayer: "다른 선수", targetPage: 1))
    }

    func testPostActionVerificationRequiresSamePlayerAndExpectedPage() throws {
        let window = sampleV26Window()
        let source = NavigationFrameEvidence(
            window: window, imageWidth: 1600, imageHeight: 1400,
            screen: ScreenClassification(state: .pitcherOrder, status: .verified, confidence: 1,
                                         anchorIndices: Array(0...8)),
            playerKey: "후라도'26", playerVerified: true, page: nil, pageVerified: false,
            frameSHA256: String(repeating: "a", count: 64))
        let plan = try VerifiedInputPlan(
            action: .openPlayerCard, targetID: "pitcher-order:first-starter", targetLabel: "후라도'26",
            region: ScreenRegion(x: 0.145, y: 0.600, width: 0.122, height: 0.2067),
            profileVersion: "pitcher-order-layout-v1", source: source,
            targetState: .playerDetailPitcher, targetPlayer: "후라도'26", targetPage: 1)
        let expected = NavigationFrameEvidence(
            window: window, imageWidth: 1600, imageHeight: 1400,
            screen: ScreenClassification(state: .playerDetailPitcher, status: .verified, confidence: 1,
                                         anchorIndices: Array(0...4)),
            playerKey: "후라도'26", playerVerified: true, page: 1, pageVerified: true,
            frameSHA256: String(repeating: "b", count: 64))
        let wrongPlayer = NavigationFrameEvidence(
            window: window, imageWidth: 1600, imageHeight: 1400,
            screen: expected.screen, playerKey: "다른 선수", playerVerified: true,
            page: 1, pageVerified: true, frameSHA256: expected.frameSHA256)
        let wrongPage = NavigationFrameEvidence(
            window: window, imageWidth: 1600, imageHeight: 1400,
            screen: expected.screen, playerKey: "후라도'26", playerVerified: true,
            page: 2, pageVerified: true, frameSHA256: expected.frameSHA256)

        XCTAssertEqual(NavigationTransitionVerifier.verify(plan: plan, before: source, after: expected), .expected)
        XCTAssertEqual(NavigationTransitionVerifier.verify(plan: plan, before: source, after: source), .unchanged)
        XCTAssertEqual(NavigationTransitionVerifier.verify(plan: plan, before: source, after: wrongPlayer), .unexpected)
        XCTAssertEqual(NavigationTransitionVerifier.verify(plan: plan, before: source, after: wrongPage), .unexpected)
        XCTAssertEqual(AccountStateChangingAction.allCases.count, 12)
    }

    func testIdleGatePausesOnUserInputAndHonorsEmergencyStop() throws {
        var gate = try UserActivityGate(minimumIdleSeconds: 5, lastInputTime: 10)
        XCTAssertFalse(gate.isIdle(at: 14.9))
        XCTAssertTrue(gate.isIdle(at: 15))
        gate.noteUserInput(at: 16)
        XCTAssertFalse(gate.isIdle(at: 20.9))
        gate.requestEmergencyStop()
        XCTAssertTrue(gate.emergencyStopped)
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

    func testPitcherOrderUsesBothLineupColumnsAndFooterAsLayoutEvidence() throws {
        let classifier = ObservedScreenStateClassifier()
        func box(_ x: Double, _ y: Double, _ width: Double = 0.05, _ height: Double = 0.012) throws -> ScreenRegion {
            try ScreenRegion(x: x, y: y, width: width, height: height)
        }
        let rows = [
            TextObservation(text: "선발 투수 변경", confidence: 0.5, bbox: try box(0.4, 0.82, 0.2, 0.03)),
            TextObservation(text: "좌측에 표시되는 내 선발 투수의 순서를 변경할 수 있습니다.", confidence: 1,
                            bbox: try box(0.289, 0.789, 0.435, 0.016)),
            TextObservation(text: "원래대로", confidence: 1, bbox: try box(0.245, 0.056, 0.080, 0.019)),
            TextObservation(text: "저장", confidence: 0.5, bbox: try box(0.696, 0.056, 0.042, 0.019)),
            TextObservation(text: "1선발 R", confidence: 1, bbox: try box(0.222, 0.737)),
            TextObservation(text: "3선발 L", confidence: 1, bbox: try box(0.222, 0.218)),
            TextObservation(text: "3선발 R", confidence: 1, bbox: try box(0.373, 0.735)),
            TextObservation(text: "5선발 R", confidence: 1, bbox: try box(0.373, 0.218)),
            TextObservation(text: "선수 교체", confidence: 0.5, bbox: try box(0.457, 0.053, 0.086, 0.021)),
            TextObservation(text: "< 뒤로가기", confidence: 0.5, bbox: try box(0.439, 0.012, 0.114, 0.019)),
        ]
        let result = classifier.recognition(rows)
        XCTAssertEqual(result.status, .verified)
        XCTAssertEqual(result.confidence, 1)
        XCTAssertEqual(result.anchorIndices, Array(0...9))
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
