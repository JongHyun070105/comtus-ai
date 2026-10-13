# comtus-ai

컴투스프로야구V26 랭킹챌린지를 위한 **로컬 전용·읽기 전용 전력 분석 기반**입니다. 현재 버전은 캡처/OCR 파이프라인의 첫 구현과 SQLite 증거 저장, 명시적으로 제공된 휴리스틱 점수로 5선발 순서를 비교하는 분석 도구입니다. 보정된 승률 예측기나 자동 게임 조작 기능은 포함하지 않습니다.

## 현재 구현

- Python 3 패키지: 카드·계정 모델, 버전 관리 SQLite 스키마, 불변 스냅샷 및 OCR 정정 이력
- JSON v1: OCR 관측과 휴리스틱 매치업 입력/출력
- 랭킹챌린지 최적화: 다섯 투수와 다섯 상대의 120개 일대일 배치를 모두 비교하고 동률·누락 점수를 보고
- 규칙 계산 기반: 모드·카드 종류·기준점·대상·출처·버전을 보존하며 기존 표시 능력치에 포함됐는지 모르면 보너스를 재적용하지 않음
- Swift Package: ScreenCaptureKit 창 탐색/단일 프레임 캡처, Vision 한국어/영어 OCR, 명시적 활성 패널 ROI
- 합성 캡처에서 Python OCR→SQLite→최적화→JSON 보고서까지 실행하는 테스트
- 삼성 라이온즈 참고 스냅샷: 사용자 설명에서 온 OVR 86.6, 세트덱 121, 특훈 총레벨 99/+0.7 및 선수 이름만 보존. 원본 스크린샷 OCR 자료가 아닙니다.

화면 분류기는 실제 화면 어휘/표본을 검증하기 전까지 `UNKNOWN`을 반환합니다. 현재 실제 게임 이미지, 상대 데이터, 경기 결과, 학습 데이터는 확인되지 않았습니다. 세부 규칙과 구현 경계는 [아키텍처 문서](docs/architecture/FOUNDATION.md)를 참고하십시오.

## 요구 환경

- Python 3.11 이상 (현재 확인된 환경: Python 3.14.6)
- macOS 14 이상 및 Xcode Command Line Tools (현재 확인된 환경: macOS 27.0, Swift 6.4)
- SQLite는 Python 표준 라이브러리를 사용합니다. Python 런타임 의존성은 없습니다.
- Swift 캡처와 Vision OCR은 macOS에서만 동작합니다.

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/python
```

## 실행

아래 명령은 프로젝트 루트에서 실행합니다.

```bash
comtus-ai doctor
comtus-ai db init
comtus-ai db seed-reference
comtus-ai roster show --account reference:samsung-lions
comtus-ai roster diff --account reference:samsung-lions
comtus-ai report
comtus-ai test
```

The dependency-free CPU benchmark measures only the synthetic five-pitcher assignment calculation, checks output equivalence over repeated runs, and reports median/p95. It does not measure game capture or OCR:

```bash
python scripts/benchmark_core.py
```

설치하지 않고 모듈로도 실행할 수 있습니다.

```bash
PYTHONPATH=packages/python/src python -m comtus_ai doctor
PYTHONPATH=packages/python/src python -m comtus_ai db init
PYTHONPATH=packages/python/src python -m comtus_ai db seed-reference
```

기본 데이터베이스는 무시(ignore)되는 `data/comtus-ai.sqlite3`입니다. 참고 스냅샷은 읽기 전용 분석용 텍스트만 저장하고, 계정 식별정보·선수 능력치·포지션·카드 종류를 만들어내지 않습니다.

### 매치업 입력

점수는 호출자가 제공한 상대 평가 **휴리스틱**이어야 합니다. `scores`에서 빠진 조합은 `null`/미입력으로 두며 승리로 간주하지 않습니다. 예시는 [schemas/v1/matchup-input.schema.json](schemas/v1/matchup-input.schema.json)입니다.

```json
{
  "pitchers": [
    {"card_id": "instance-1", "display_name": "선발 A"},
    {"card_id": "instance-2", "display_name": "선발 B"},
    {"card_id": "instance-3", "display_name": "선발 C"},
    {"card_id": "instance-4", "display_name": "선발 D"},
    {"card_id": "instance-5", "display_name": "선발 E"}
  ],
  "opponents": [
    {"opponent_id": "team-1", "display_name": "상대 1"},
    {"opponent_id": "team-2", "display_name": "상대 2"},
    {"opponent_id": "team-3", "display_name": "상대 3"},
    {"opponent_id": "team-4", "display_name": "상대 4"},
    {"opponent_id": "team-5", "display_name": "상대 5"}
  ],
  "scores": {"instance-1": {"team-1": 0.4, "team-2": null}}
}
```

```bash
comtus-ai optimize --input ./matchup.json
comtus-ai matchup analyze --input ./matchup.json
```

결과는 `HEURISTIC_SCORE`, `probability_calibrated: false`로 표시합니다. 선발 추천은 게임에 적용하지 않습니다.

## macOS 캡처 및 OCR

Build the macOS capture CLI with SwiftPM (Xcode Command Line Tools required):

```bash
swift build --package-path apps/mac-capture -c release
```

```bash
comtus-ai capture list
comtus-ai capture once --window-id 123 --output data/captures/frame.png
comtus-ai capture ocr data/captures/frame.png --screen-state UNKNOWN
comtus-ai capture ocr data/captures/frame.png --screen-state PLAYER_DETAIL_BATTER --active-panel 0.2 0.1 0.6 0.8
comtus-ai capture ocr data/captures/frame.png --screen-state UNKNOWN --store --evidence-source SCREEN_CAPTURE_VERIFIED
```

캡처는 ScreenCaptureKit만 사용합니다. 권한을 자동으로 요청하거나 우회하지 않습니다. `doctor`, `capture list`, `capture once`는 시스템 설정의 사전 권한 상태를 확인하고 권한이 없으면 `SKIP`으로 끝납니다. `capture ocr`는 로컬 이미지에 Vision을 실행하므로 Screen Recording 권한이 필요하지 않습니다.

`--store`는 이미지 SHA-256과 파싱된 OCR 관측을 SQLite에 추가하고 같은 입력의 재실행을 중복 제거합니다. 저장 출처는 기본 `UNKNOWN`입니다. `SCREEN_CAPTURE_VERIFIED`는 이 CLI의 ScreenCaptureKit 캡처로 생성한 이미지에만 지정하십시오. `--database`로 통합 테스트용 별도 DB를 지정할 수 있습니다. Swift 실행 파일은 최신 Release 산출물을 탐색하며, 다른 빌드 위치를 써야 하면 `COMTUS_AI_SWIFT_BIN=/path/to/mac-capture`로 지정할 수 있습니다.

상세 화면 가장자리에는 이웃 페이지가 보일 수 있습니다. 상세 화면 OCR 전에 실제 화면에 맞는 `--active-panel x y width height`를 전달하십시오. 값은 프레임 기준 정규화 좌표이며 원점은 좌측 아래입니다. 현재 자동 분류기는 실제 캡처에서 확인한 상단 `랭킹 챌린지` 제목 앵커만 `RANKING_LOBBY`로 인식합니다. `--screen-state`로 요청한 값도 OCR 근거와 일치하지 않으면 `UNKNOWN`으로 낮춥니다. 라인업 상세와 선수 상세 프로필은 검증된 실제 표본이 없어 `UNKNOWN`으로 남습니다. `frame_size`, 관측 텍스트, 신뢰도, 프레임 기준 bbox, 스키마 버전이 JSON으로 출력됩니다. 원본 이미지는 기본적으로 Git에 추가하지 않습니다.

## 데이터와 검증 상태

- SQLite 외래키를 활성화하고 schema migration 버전을 저장합니다.
- 팀/선수 상태와 OCR 원본 관측은 append-only이며, OCR 교정은 별도 이력으로 추가합니다.
- 반복 입력은 콘텐츠 fingerprint, 캡처 SHA-256, 관측 dedupe key로 중복을 막습니다.
- 계정, 카드 마스터, 육성 카드 인스턴스, 당시 선수/팀 스냅샷을 분리합니다.
- `USER_PROVIDED_REFERENCE`, `SCREEN_CAPTURE_VERIFIED`, `OFFICIAL_RULE`, `COMMUNITY_RESEARCH`, `SYNTHETIC_TEST`, `UNKNOWN` 출처를 구분합니다.
- 현재 실전 경기 결과가 없으면 보고서는 `NO_REAL_MATCH_RESULTS`를 표시합니다. 합성 테스트 결과는 학습 데이터가 아닙니다.

테스트 결과와 보류 항목은 [진행 상태](docs/progress/IMPLEMENTATION_STATUS.md), [테스트 기록](docs/progress/TEST_RESULTS.md), [블로커](docs/progress/BLOCKERS.md)에 기록합니다.

## 연구 자료

검토한 사이트와 증거 분류는 [외부 출처 검토 기록](docs/research/EXTERNAL_SOURCE_AUDIT.md)에 적었습니다. CPBV LAB의 점수는 커뮤니티표를 바탕으로 한 참고 점수이며 실제 승리 공식으로 취급하지 않습니다. 훈련 확률 페이지는 사이트 계산기 가정일 뿐 공식 확률이 아닙니다. 출처 내용과 라이선스가 직접 검증되기 전에는 해당 사이트 코드를 재사용하지 않습니다.

- [CPBV Helper 스킬](https://cpbv-helper.vercel.app/skills)
- [CPBV Lab](https://www.cpbv-lab.com/)
- [CPBV Lab 훈련 재분배](https://www.cpbv-lab.com/training-redistribution/)
- [V26 Skill](https://v26-skill.com/)
- [Deck Manager](https://deck-manager.vercel.app/)
- [컴프야 갤러리](https://gall.dcinside.com/mgallery/board/lists/?id=cpyv22)
- [컴투스 공식 커뮤니티](https://cpbv-community.com2us.com/)

## 제한과 로드맵

- 실제 게임 화면 수집/OCR 정확도/화면 분류/창 후보는 검증 대기 상태입니다.
- 시너지/특훈 수치와 모드 규칙은 UI·공식 출처가 확인된 데이터만 사용할 수 있습니다. 초기 참고 화면 설명은 출처와 버전 미확인인 참고 규칙입니다.
- 승률, 득실점 또는 80% 목표에 대한 모델 성능 주장은 없습니다. 평가 함수는 라벨된 경기 결과가 모일 때만 계산합니다.
- 다음 단계: macOS 캡처 권한을 사용자가 허용한 뒤 창 탐색/ROI/실제 UI 확인, 연구 출처를 분류해 규칙 등록, 데이터가 확보되면 경기 스냅샷과 오프라인 검증을 확장합니다.
- 경기 시작/선수 교체/재화 사용 자동화, 프로세스 주입, 메모리 조작, 네트워크 변조는 구현하지 않습니다.

## English summary

`comtus-ai` is an offline, read-only foundation for Com2uS Baseball V26. It provides a versioned SQLite evidence store, source-aware snapshots, a macOS ScreenCaptureKit/Vision package, and an exhaustive five-pitcher rotation optimizer that labels uncalibrated inputs as heuristic scores. No actual game data, calibrated win probability, or automated gameplay is claimed.
