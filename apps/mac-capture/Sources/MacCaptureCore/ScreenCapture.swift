import AppKit
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit

public struct ScreenCaptureFrameSource: FrameSource {
    public init() {}

    public func listWindows() async throws -> [WindowDescriptor] {
        try requireScreenRecordingPermission()
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        return content.windows
            .filter { $0.frame.width > 0 && $0.frame.height > 0 }
            .map { window in
                WindowDescriptor(windowID: window.windowID,
                                 title: window.title,
                                 processName: window.owningApplication?.applicationName,
                                 processID: window.owningApplication?.processID,
                                 widthPoints: window.frame.width,
                                 heightPoints: window.frame.height,
                                 onScreen: window.isOnScreen)
            }
            .sorted { ($0.processName ?? "", $0.title ?? "", $0.windowID) < ($1.processName ?? "", $1.title ?? "", $1.windowID) }
    }

    public func capture(windowID: UInt32) async throws -> CGImage {
        try requireScreenRecordingPermission()
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let window = content.windows.first(where: { $0.windowID == windowID }) else {
            throw CaptureFailure.gameWindowNotFound(windowID)
        }
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let configuration = SCStreamConfiguration()
        let scale = max(CGFloat(filter.pointPixelScale), 1)
        configuration.width = max(1, Int((window.frame.width * scale).rounded(.up)))
        configuration.height = max(1, Int((window.frame.height * scale).rounded(.up)))
        configuration.showsCursor = false
        return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
    }

    public func savePNG(_ image: CGImage, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard let destination = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil) else {
            throw CaptureFailure.imageSaveFailed(url.path)
        }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination) else { throw CaptureFailure.imageSaveFailed(url.path) }
    }
}

public func requireScreenRecordingPermission() throws {
    guard CGPreflightScreenCaptureAccess() else { throw CaptureFailure.screenRecordingPermissionDenied }
}

public func loadCGImage(at url: URL) throws -> CGImage {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil), let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw CaptureFailure.imageLoadFailed(url.path)
    }
    return image
}
