# Com2uS V26 UI input policy review

Checked: 2026-10-13

## Finding

**NOT_VERIFIABLE for the user's Korean V26 service terms.** No game input was sent. This repository now contains a narrowly allowlisted Accessibility/CGEvent adapter, but the supported CLI keeps live navigation fail-closed until the live V26 screen, target identity, and expected detail transition are verified. OS permission does not establish publisher authorization.

The official V26 App Store listing directs users to the in-game or Com2uS Mobile Game Service Terms for conditions of use, but it does not itself clarify third-party UI automation. The linked mobile policy page did not return readable policy text during this review.

The official HIVE terms at `M14` contain a clause against unauthorized third-party software designed to modify, interfere with, or provide automated access to Com2uS services. That document expressly applies to people residing **outside the Republic of Korea**, so it does not establish the Korean user's applicable rule. It also does not answer whether a read-only, user-triggered accessibility workflow is authorized for V26.

The unresolved policy scope is material because a local Accessibility/CGEvent permission only enables an operating-system API; it does not grant permission from the game publisher. This review found no clearly applicable prohibition and no confirmation that this read-only workflow is allowed. Do not describe the policy as either allowed or prohibited. The current command does not send input while its live evidence gates are unresolved.

## Evidence

- [Official V26 App Store listing](https://apps.apple.com/kr/app/%EC%BB%B4%ED%88%AC%EC%8A%A4%ED%94%84%EB%A1%9C%EC%95%BC%EA%B5%ACv26/id1458848044?platform=mac): directs users to the in-game or Com2uS Mobile Game Service Terms.
- [Com2uS Terms M14](https://terms.withhive.com/terms/policy/view/M14): automated-access clause; scope says residents outside Korea.
- [Com2uS mobile terms landing page](https://terms.withhive.com/terms/mobile/policy.html): linked by the V26 listing, but the page content was not readable in this check.
- [Apple AXIsProcessTrustedWithOptions](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions), [CGEvent](https://developer.apple.com/documentation/coregraphics/cgevent), and [CGPreflightListenEventAccess](https://developer.apple.com/documentation/coregraphics/cgpreflightlisteneventaccess()): document OS capabilities only, not Com2uS authorization.

## Implementation boundary

`MacGameInputAdapter` is separate from the Python mock navigator. It only constructs plans for opening the first verified Hurado starter card, checks exact V26 process/window identity, frontmost focus, idle input monitoring, screen/frame identity, and post-action transition, and excludes account-changing actions from its safe-action type. The CLI's live path is fail-closed; no Accessibility action or CGEvent was sent in this review. No process injection, memory access, packet manipulation, or anti-cheat bypass is present.
