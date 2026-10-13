# comtus-ai

컴투스프로야구V26 랭킹챌린지를 위한 **로컬 전용·읽기 전용 전력 분석 기반**입니다. 캡처/OCR 관측, 근거가 연결된 필드 후보, 안전한 모의 탐색을 제공합니다. 선수 데이터는 화면·선수·페이지 식별을 검증하기 전까지 선수 스냅샷으로 승격하지 않습니다. 보정된 승률 예측기나 실제 게임 입력 기능은 포함하지 않습니다.

## 현재 구현

- Python 3 패키지: 카드·계정 모델, 버전 관리 SQLite 스키마, 불변 스냅샷, OCR 필드 후보 및 정정 이력
- JSON v1: OCR 관측과 휴리스틱 매치업 입력/출력
- 랭킹챌린지 최적화: 다섯 투수와 다섯 상대의 120개 일대일 배치를 모두 비교하고 동률·누락 점수를 보고
- 규칙 계산 기반: 모드·카드 종류·기준점·대상·출처·버전을 보존하며 기존 표시 능력치에 포함됐는지 모르면 보너스를 재적용하지 않음
- Swift Package: ScreenCaptureKit 창 탐색/단일 프레임 캡처, Vision 한국어/영어 OCR, 명시적 활성 패널 ROI, 다중 앵커 선발 순서 화면 분류
- 캡처 세션은 정확한 `V26` 프로세스명과 확인된 번들 ID를 사용하고 PID·창 ID를 캡처 직전에 다시 검사합니다. 여러 게임 창이 동시에 보이면 캡처하지 않습니다.
- OCR 필드는 토큰별 신뢰도·출처·좌표·패널 후보를 유지합니다. 같은 이름의 카드 후보는 자동으로 합치지 않고, 계정 소유 카드 인스턴스 키는 추측하지 않습니다.
- 모의 화면 전환 플래너, 상태/선수/페이지 추적기, 중지·일시정지·깊이·재시도 안전 제어와 좌표 변환 테스트
- 합성 fixture에서 OCR 후보→SQLite 정규화→합성 선수 스냅샷까지 실행하는 테스트
- 삼성 라이온즈 참고 스냅샷: 사용자 설명에서 온 OVR 86.6, 세트덱 121, 특훈 총레벨 99/+0.7 및 선수 이름만 보존. 원본 스크린샷 OCR 자료가 아닙니다.

## v0.2.2 현재 로컬 검증 — 2026-10-13

로컬 SQLite schema v4에는 캡처 20건, OCR 관측 1,835건, 화면 관측 20건, 필드 후보 144건, 비공개 PNG 16개, OCR 정정 2건이 있습니다. 선수 마스터·계정 카드 인스턴스·실제 선수 스냅샷은 모두 0건입니다. 비공개 이미지와 SQLite는 Git 무시 경로에 남아 있습니다.

실제 화면은 `선발 투수 변경` 목록으로 분류됐고 `CANDIDATE` 신뢰도는 0.5입니다. 첫 선발 카드의 `후라도'26`, LIVE V2, 별 5개, +5는 한 화면에서 보이는 후보일 뿐입니다. `100*`는 카드 표시값이며 OVR로 승격하지 않았습니다. 투수 기본 능력치, 스킬, 잠재력, 구종은 아직 상세 화면에서 확인되지 않았습니다. 현재 최신 상태는 [구현 진행표](docs/progress/IMPLEMENTATION_STATUS.md)와 [검증 기록](docs/progress/TEST_RESULTS.md)에 있습니다.

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
comtus-ai capture session --interval 0.5 --stable-samples 2 --preserve-images
comtus-ai db analyze-ocr
```

캡처는 ScreenCaptureKit만 사용합니다. 권한을 자동으로 요청하거나 우회하지 않습니다. `doctor`, `capture list`, `capture once`는 시스템 설정의 사전 권한 상태를 확인하고 권한이 없으면 `SKIP`으로 끝납니다. `capture ocr`는 로컬 이미지에 Vision을 실행하므로 Screen Recording 권한이 필요하지 않습니다.

`--store`는 이미지 SHA-256, OCR 관측, 다중 앵커 화면 분류, 버전이 붙은 필드 후보를 SQLite에 추가하고 같은 입력을 중복 제거합니다. 저장 출처는 기본 `UNKNOWN`입니다. `SCREEN_CAPTURE_VERIFIED`는 이 CLI의 ScreenCaptureKit 캡처로 생성한 이미지에만 지정하십시오. `db analyze-ocr`는 기존 로컬 OCR 행을 분석하고 요약만 출력합니다. 원문 OCR 텍스트는 JSON 출력에 포함하지 않습니다. DB는 schema v4로 append-only 마이그레이션합니다. `--database`로 별도 DB를 지정할 수 있습니다.

`capture session`은 정확히 확인된 화면 창만 읽습니다. 전체 화면 서명은 안정 프레임을 고르는 데 쓰고, 중복 판단은 고정 콘텐츠 ROI 서명, 화면 상태, 신뢰도 높은 OCR 텍스트와 좌표, 추출된 선수·페이지 후보를 함께 사용합니다. 유사 프레임만으로 숫자나 카드 변경을 버리지 않습니다. p50/p95 캡처·OCR 지연, 프로세스 CPU 사용률, 누락 프레임을 출력하며 게임 입력이나 화면 이동은 하지 않습니다. `--max-polls`로 세션 길이를 제한할 수 있고 기본은 Ctrl-C까지 대기합니다. `--preserve-images`는 원본 PNG를 `data/private-fixtures/`에 SHA-256 이름으로 저장합니다. 디렉터리·파일 권한은 각각 0700·0600이며 총 용량 기본 상한은 1 GiB입니다.

선수 메뉴 탐색 계획은 다음처럼 실행합니다.

```bash
comtus-ai navigate collect --dry-run
comtus-ai navigate collect --allow-ui-input --idle-only
comtus-ai capture session --preserve-images
```

`--dry-run`은 현재 V26 창과 화면 근거만 읽고 입력을 보내지 않습니다. 실입력 경로는 별도 V26 화면·선수·페이지 프로필과 사용자 유휴/포커스 게이트가 모두 확인되어야 합니다. 현재 선수 상세 화면 프로필이 없거나 창을 식별하지 못하면 `BLOCKED`를 출력하며 클릭하지 않습니다. macOS 권한은 OS API 사용 권한일 뿐 게임 서비스 정책 허가를 뜻하지 않습니다. `capture session`은 입력 없이 계속 실행되는 별도 모드입니다.

Swift 실행은 먼저 현재 소스 해시별 격리 경로에 표준 SwiftPM Release 빌드를 시도합니다. 호스트가 manifest 실행을 막으면 재현 가능한 직접 `swiftc` 대체 경로를 사용합니다. 바이너리와 인접 매니페스트의 소스 SHA-256·실행 파일 SHA-256이 모두 현재 소스와 일치해야 실행됩니다. `COMTUS_AI_SWIFT_BIN` 경로도 같은 매니페스트 검증을 거칩니다. 라이브러리 경로는 해당 바이너리 디렉터리의 동적 라이브러리에서 설정합니다.

상세 화면 가장자리에는 이웃 페이지가 보일 수 있습니다. 화면을 잘라 Vision OCR을 실행할 때는 실제 화면에서 확인한 `--active-panel x y width height`를 사용합니다. 전체 화면 OCR 결과에서 카드 하나만 파싱할 때는 `--field-panel`을 사용합니다. 두 값 모두 프레임 기준 정규화 좌표이며 원점은 좌측 아래입니다. OCR 박스 전체가 패널 안쪽 안전 마진에 들어오지 않으면 해당 필드를 버립니다. 기본 패널 경계는 추측하지 않습니다. 보존된 선발 순서 화면은 v3 프로필로 제목·설명·양쪽 라인업 역할·하단 컨트롤의 구조를 확인할 수 있지만, 첫 카드 이름은 여전히 `CANDIDATE`입니다. 선수 상세·페이지 프로필은 검증되지 않아 `UNKNOWN`이며, 불명확한 선수 신원이나 화면 전환은 입력 대상으로 사용할 수 없습니다. 랭킹 로비, 상대 라인업, 시너지, 특훈도 별도 화면 표본이 없어 `UNKNOWN`입니다.

## 데이터와 검증 상태

- SQLite 외래키를 활성화하고 schema migration 버전을 저장합니다.
- 팀/선수 상태, OCR 원본 관측, 화면 판정과 필드 추출 후보는 append-only이며, OCR 교정은 별도 이력으로 추가합니다.
- 실제 캡처 스냅샷 저장은 같은 선수가 확인된 상세 페이지 2개 이상, 일치하는 카드 마스터/계정 인스턴스, 보존된 원본 이미지, 활성 패널에 놓인 이미지 검토 필드를 요구합니다. UNKNOWN 필드는 생략해 부분 스냅샷을 만들 수 있습니다.
- 반복 입력은 콘텐츠 fingerprint, 캡처 SHA-256, 관측 dedupe key로 중복을 막습니다.
- 계정, 카드 마스터, 육성 카드 인스턴스, 당시 선수/팀 스냅샷을 분리합니다.
- 실제 전체 화면과 최소 영역 fixture는 Git 무시 대상인 `data/captures/` 및 `data/private-fixtures/`에만 보관하십시오. 자동 삭제는 없습니다. 보존 기간은 사용자가 별도로 정하고, 공개 테스트에는 `SYNTHETIC_TEST` fixture만 둡니다.
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

- 기존 4개 실제 프레임의 캡처/OCR 적재는 `EXEC PASS`; 현재 UI 상태 재확인 및 한국어 선수·능력치 정확도는 `SKIP / NOT_VERIFIABLE`입니다.
- 선발 순서 화면의 다중 앵커 판정은 실행됐으나 `CANDIDATE`입니다. 다른 화면 분류와 active-panel 좌표는 `UNKNOWN / SKIP`입니다.
- 실제 게임 입력은 Com2uS의 한국 사용자용 적용 약관에서 허용 범위를 확인하지 못해 `BLOCKED`입니다. 탐색은 합성 모의 어댑터에서만 실행합니다.
- 시너지/특훈 수치와 모드 규칙은 UI·공식 출처가 확인된 데이터만 사용할 수 있습니다. 초기 참고 화면 설명은 출처와 버전 미확인인 참고 규칙입니다.
- 승률, 득실점 또는 80% 목표에 대한 모델 성능 주장은 없습니다. 평가 함수는 라벨된 경기 결과가 모일 때만 계산합니다.
- 다음 단계: 읽기 전용 캡처로 타자/투수 상세와 양쪽 미리보기를 따로 수집하고 active-panel 경계를 검증합니다. Com2uS가 해당 계정·지역·게임의 자동 UI 입력을 명시적으로 허용하지 않는 한 실제 입력 어댑터는 추가하지 않습니다.
- 경기 시작/선수 교체/재화 사용 자동화, 프로세스 주입, 메모리 조작, 네트워크 변조는 구현하지 않습니다.

## English summary

`comtus-ai` is an offline, read-only foundation for Com2uS Baseball V26. It provides a versioned SQLite evidence store, source-aware snapshots, a macOS ScreenCaptureKit/Vision package, and an exhaustive five-pitcher rotation optimizer that labels uncalibrated inputs as heuristic scores. No actual game data, calibrated win probability, or automated gameplay is claimed.
