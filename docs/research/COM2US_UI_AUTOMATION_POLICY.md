# Com2uS V26 UI input policy review

Checked: 2026-10-13

## Finding

**NOT_VERIFIABLE for the user's Korean V26 service terms; real game input stays blocked.** No game input was sent, and the repository contains no Accessibility or CGEvent input implementation. Screen capture and mock navigation remain separate from game control.

The official V26 App Store listing directs users to the in-game or Com2uS Mobile Game Service Terms for conditions of use, but it does not itself clarify third-party UI automation. The linked mobile policy page did not return readable policy text during this review.

The official HIVE terms at `M14` contain a clause against unauthorized third-party software designed to modify, interfere with, or provide automated access to Com2uS services. That document expressly applies to people residing **outside the Republic of Korea**, so it does not establish the Korean user's applicable rule. It also does not answer whether a read-only, user-triggered accessibility workflow is authorized for V26.

The unresolved policy scope is material because a local Accessibility/CGEvent permission only enables an operating-system API; it does not grant permission from the game publisher. Keep any future real-input adapter out of the product until Com2uS provides written, game- and region-specific authorization or a clearly applicable policy expressly allows the proposed interaction.

## Evidence

- [Official V26 App Store listing](https://apps.apple.com/kr/app/%EC%BB%B4%ED%88%AC%EC%8A%A4%ED%94%84%EB%A1%9C%EC%95%BC%EA%B5%ACv26/id1458848044?platform=mac): directs users to the in-game or Com2uS Mobile Game Service Terms.
- [Com2uS Terms M14](https://terms.withhive.com/terms/policy/view/M14): automated-access clause; scope says residents outside Korea.
- [Com2uS mobile terms landing page](https://terms.withhive.com/terms/mobile/policy.html): linked by the V26 listing, but the page content was not readable in this check.
- [Apple AXIsProcessTrustedWithOptions](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions) and [CGEvent](https://developer.apple.com/documentation/coregraphics/cgevent): document OS capabilities only, not Com2uS authorization.

## Implementation boundary

`UIActionAdapter` is a protocol used by the simulated navigator. `MockUIActionAdapter` is the only implementation. The transition graph must be supplied by the caller; the simulator does not invent game paths. No CGEvent, Accessibility action call, process injection, memory access, packet manipulation, or anti-cheat bypass is present.
