import AppKit
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit

public enum FrameVisualSignature {
    public static func make(_ image: CGImage, width: Int = 96, height: Int = 132) -> Data? {
        guard width > 0, height > 0 else { return nil }
        var pixels = [UInt8](repeating: 0, count: width * height)
        let created = pixels.withUnsafeMutableBytes { buffer -> Bool in
            guard let context = CGContext(
                data: buffer.baseAddress,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width,
                space: CGColorSpaceCreateDeviceGray(),
                bitmapInfo: CGImageAlphaInfo.none.rawValue
            ) else { return false }
            context.interpolationQuality = .low
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        return created ? Data(pixels) : nil
    }

    public static func makeKeyRegion(_ image: CGImage, width: Int = 192, height: Int = 264) -> Data? {
        let regionY = CGFloat(image.height) * 0.12
        let regionHeight = CGFloat(image.height) * 0.82
        let leftRegion = CGRect(x: CGFloat(image.width) * 0.12, y: regionY,
                                width: CGFloat(image.width) * 0.32, height: regionHeight).integral
        let rightRegion = CGRect(x: CGFloat(image.width) * 0.56, y: regionY,
                                 width: CGFloat(image.width) * 0.32, height: regionHeight).integral
        guard let leftCrop = image.cropping(to: leftRegion), let rightCrop = image.cropping(to: rightRegion),
              let leftSignature = make(leftCrop, width: width / 2, height: height),
              let rightSignature = make(rightCrop, width: width / 2, height: height) else { return nil }
        var signature = leftSignature
        signature.append(rightSignature)
        return signature
    }
}

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
                                 bundleIdentifier: window.owningApplication?.bundleIdentifier,
                                 widthPoints: window.frame.width,
                                 heightPoints: window.frame.height,
                                 onScreen: window.isOnScreen)
            }
            .sorted { ($0.processName ?? "", $0.title ?? "", $0.windowID) < ($1.processName ?? "", $1.title ?? "", $1.windowID) }
    }

    public func capture(windowID: UInt32) async throws -> CGImage {
        try await capture(windowID: windowID, expectedProcessID: nil, expectedBundleIdentifier: nil)
    }

    public func capture(windowID: UInt32, expectedProcessID: Int32?,
                        expectedBundleIdentifier: String?) async throws -> CGImage {
        try requireScreenRecordingPermission()
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let window = content.windows.first(where: { $0.windowID == windowID }) else {
            throw CaptureFailure.gameWindowNotFound(windowID)
        }
        guard CaptureWindowIdentity.matches(
            windowID: window.windowID,
            processID: window.owningApplication?.processID,
            bundleIdentifier: window.owningApplication?.bundleIdentifier,
            expectedWindowID: windowID,
            expectedProcessID: expectedProcessID,
            expectedBundleIdentifier: expectedBundleIdentifier
        ) else {
            throw CaptureFailure.windowIdentityChanged(windowID)
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
        do {
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        } catch {
            try? FileManager.default.removeItem(at: url)
            throw CaptureFailure.imageSaveFailed(url.path)
        }
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
