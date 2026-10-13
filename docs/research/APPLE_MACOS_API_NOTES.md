# Apple API compatibility notes

Checked on 2026-10-13 against the installed Xcode 27.0 SDK, Swift 6.4, and Apple's online documentation.

- The package targets macOS 14.0. ScreenCaptureKit provides `SCWindow` identity/title/owner/frame, window-scoped `SCContentFilter`, and `SCScreenshotManager.captureImage(contentFilter:configuration:)` as an async single-frame API. The SDK marks `SCWindow.onScreen` as renamed for Swift to `isOnScreen`; implementation uses `isOnScreen`.
- `CGPreflightScreenCaptureAccess()` checks consent without prompting. The CLI only calls the preflight check and returns `SKIP` when false; it never invokes the permission request API.
- Vision `VNRecognizeTextRequest` is configured to Revision 3. The deprecated class-level language-query API is avoided; the request's supported-language method is used and configured languages are intersected with the installed OS's list.
- Vision returns normalized bounding rectangles in lower-left coordinates. `ScreenRegion` stores normalized x/y/width/height in that convention; conversion to CGImage crop pixels flips y once, and OCR boxes are mapped from an explicitly supplied crop back to the full frame.
- Screenshot image dimensions use window frame point size multiplied by ScreenCaptureKit's point-to-pixel scale, preserving Retina scale in metadata.
- Apple's `AXIsProcessTrusted()` checks current Accessibility trust without prompting. The CLI reports that preflight; it never requests the prompt option or changes Privacy & Security settings.
- `CGPreflightPostEventAccess()` checks whether the process can post events, and `CGPreflightListenEventAccess()` checks whether a listen-only event tap can monitor user activity. The monitor requires the latter and fails closed when unavailable; it does not request access.
- `CGEvent` supports creating and posting Quartz mouse events using global display coordinates, including posting to a specific PID. The adapter uses a PID-targeted event only after exact window/process validation, and the deprecated `CGPostMouseEvent` API is not used.
- `CGDisplayBounds()` and the selected `NSScreen.frame` provide Quartz and AppKit display coordinate frames. The adapter maps a window-relative Vision box through logical points into Quartz space and rejects pixel/point scale mismatches.

Primary references:

- [ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit)
- [SCWindow](https://developer.apple.com/documentation/screencapturekit/scwindow)
- [SCContentFilter window initializer](https://developer.apple.com/documentation/screencapturekit/sccontentfilter/init%28desktopindependentwindow%3A%29)
- [SCScreenshotManager single-frame API](https://developer.apple.com/documentation/screencapturekit/scscreenshotmanager/captureimage%28contentfilter%3Aconfiguration%3Acompletionhandler%3A%29)
- [Capture screen content in macOS](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos)
- [Vision text recognition](https://developer.apple.com/documentation/vision/vnrecognizetextrequest)
- [Vision supported languages](https://developer.apple.com/documentation/vision/vnrecognizetextrequest/supportedrecognitionlanguages%28%29)
- [AXIsProcessTrustedWithOptions](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions)
- [AXIsProcessTrusted](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions)
- [CGEvent](https://developer.apple.com/documentation/coregraphics/cgevent)
- [CGEvent mouse initializer](https://developer.apple.com/documentation/coregraphics/cgevent/init%28mouseeventsource%3Amousetype%3Amousecursorposition%3Amousebutton%3A)
- [CGPreflightPostEventAccess](https://developer.apple.com/documentation/coregraphics/cgpreflightposteventaccess())
- [CGPreflightListenEventAccess](https://developer.apple.com/documentation/coregraphics/cgpreflightlisteneventaccess())
- [CGDisplayBounds](https://developer.apple.com/documentation/coregraphics/cgdisplaybounds%28_%3A%29)

The core and CLI were directly compiled with Swift 6.4. SwiftPM itself could not run in the Codex sandbox because manifest evaluation failed at `sandbox-exec: sandbox_apply: Operation not permitted`; package test execution is recorded separately from direct compiler/synthetic smoke evidence.
