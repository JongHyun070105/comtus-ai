# Apple API compatibility notes

Checked on 2026-10-13 against the installed Xcode 27.0 SDK, Swift 6.4, and Apple's online documentation.

- The package targets macOS 14.0. ScreenCaptureKit provides `SCWindow` identity/title/owner/frame, window-scoped `SCContentFilter`, and `SCScreenshotManager.captureImage(contentFilter:configuration:)` as an async single-frame API. The SDK marks `SCWindow.onScreen` as renamed for Swift to `isOnScreen`; implementation uses `isOnScreen`.
- `CGPreflightScreenCaptureAccess()` checks consent without prompting. The CLI only calls the preflight check and returns `SKIP` when false; it never invokes the permission request API.
- Vision `VNRecognizeTextRequest` is configured to Revision 3. The deprecated class-level language-query API is avoided; the request's supported-language method is used and configured languages are intersected with the installed OS's list.
- Vision returns normalized bounding rectangles in lower-left coordinates. `ScreenRegion` stores normalized x/y/width/height in that convention; conversion to CGImage crop pixels flips y once, and OCR boxes are mapped from an explicitly supplied crop back to the full frame.
- Screenshot image dimensions use window frame point size multiplied by ScreenCaptureKit's point-to-pixel scale, preserving Retina scale in metadata.
- Apple's `AXIsProcessTrustedWithOptions` can check whether the current process is a trusted Accessibility client; its prompt option can notify the user asynchronously. This project does not request that prompt or check/claim the current Accessibility trust state.
- `CGEvent` supports creating and posting Quartz mouse events using global display coordinates. The deprecated `CGPostMouseEvent` API is not suitable for new code. Neither API is called by this project; only a pure coordinate mapper and mock UI adapter exist.

Primary references:

- [ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit)
- [SCWindow](https://developer.apple.com/documentation/screencapturekit/scwindow)
- [SCContentFilter window initializer](https://developer.apple.com/documentation/screencapturekit/sccontentfilter/init%28desktopindependentwindow%3A%29)
- [SCScreenshotManager single-frame API](https://developer.apple.com/documentation/screencapturekit/scscreenshotmanager/captureimage%28contentfilter%3Aconfiguration%3Acompletionhandler%3A%29)
- [Capture screen content in macOS](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos)
- [Vision text recognition](https://developer.apple.com/documentation/vision/vnrecognizetextrequest)
- [Vision supported languages](https://developer.apple.com/documentation/vision/vnrecognizetextrequest/supportedrecognitionlanguages%28%29)
- [AXIsProcessTrustedWithOptions](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions)
- [CGEvent](https://developer.apple.com/documentation/coregraphics/cgevent)
- [CGEvent mouse initializer](https://developer.apple.com/documentation/coregraphics/cgevent/init%28mouseeventsource%3Amousetype%3Amousecursorposition%3Amousebutton%3A)

The XCTest target was compiled directly with Swift 6.4. SwiftPM itself could not run in the Codex sandbox because manifest evaluation failed at `sandbox-exec: sandbox_apply: Operation not permitted`; package test execution is recorded separately from direct compiler/synthetic smoke evidence.
