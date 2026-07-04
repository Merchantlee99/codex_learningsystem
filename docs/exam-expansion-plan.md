# 과목 확장 계획

이 공개 레포는 문제은행 보관소가 아니라 학습 하네스를 보여주는 포트폴리오 코드베이스입니다.

공개 기본값은 `SQLD` 하나입니다. SQLD 50문항은 실제 기출/족보 원문이 아니라, CBT 흐름을 검증하기 위한 합성 데모 문항입니다.

## 공개/로컬 경계

| 위치 | 역할 |
| --- | --- |
| 공개 repo | SQLD 데모 seed, 학습 엔진, MCP/CLI, Obsidian/Notion 하네스, 테스트 |
| 로컬 작업 폴더 | 개인 문제은행, import-ready JSON, 실제 풀이 기록, Obsidian 산출물 |
| private repo 또는 개인 vault | 장기 보관할 개인 학습 자료 |

공개 repo에 넣지 않는 것:

- 실제 기출 원문
- 유료 문제집 내용
- 웹에서 복사한 문제 원문
- 개인 풀이 기록
- 개인 Notion DB ID
- 개인 학습 로드맵이나 현재 사용 중인 문제 출처

## 확장 방식

과목이나 문항 수를 늘릴 때 Python seed 파일을 계속 늘리는 방식은 공개 repo에 문제를 쌓게 되기 쉽습니다. 확장할 때는 JSON/YAML import를 기본 경로로 둡니다.

```bash
python3 -m cert_study bank import private_banks/my-bank.json --private
```

로컬에서 import된 과목은 `list_exams`의 `available`에 나타나고, 그때부터 CBT 세션을 시작할 수 있습니다.

## 문제은행 품질 상태

`exam-ready` 세션은 내부 CBT를 그대로 쓰되, 실전 후보로 표시된 문제만 고릅니다.

| 필드 | 의미 |
| --- | --- |
| `source_tier=synthetic` | 공개 데모 또는 개념 보강 문항 |
| `source_tier=user_owned` | 사용자가 직접 만든 개인 문제은행 |
| `source_tier=licensed_private` | 사용자가 로컬에서 보관하는 개인 학습 자료 |
| `source_tier=open_license` | 재사용 가능한 공개 라이선스 자료 |
| `quality_status=active` | 내부 실전 후보로 사용 가능 |
| `quality_status=needs_review` | 공식 범위/정답 검수 전 |
| `quality_status=outdated` | 시험 범위 변경으로 제외 |

공개 SQLD seed는 합성 데모이므로 `exam-ready`가 아니라 일반 CBT 데모에 가깝습니다. 실제 학습용 source-backed 문항은 로컬에서만 import합니다.

## 권장 데이터팩 형태

```yaml
exam:
  id: SQLD
  name: SQLD
  official_question_count: 50
  official_duration_minutes: 90
  pass_score: 60
  domain_min_score: 40
  private: true

domains:
  - id: SQLD-D1
    name: 데이터 모델링의 이해
    official_weight: 20
    official_question_count: 10

concepts:
  - id: SQLD-C-NULL
    domain_id: SQLD-D2
    name: NULL 처리
    review_note: "NULL 비교와 집계 제외 규칙을 구분한다."

questions:
  - id: MY-SQLD-Q001
    domain_id: SQLD-D2
    concept_id: SQLD-C-NULL
    question_text: "사용자가 직접 정리한 복습 문항"
    choices:
      - "보기 1"
      - "보기 2"
      - "보기 3"
      - "보기 4"
    answer: 1
    explanation: "정답 근거를 사용자 말로 정리한다."
    source_type: user_owned_summary
    source_ref: "개인 오답노트 기반 요약"
```

## 가져오기 전 확인할 것

- exam ID가 안정적인지
- 공식 문항 수와 합격선이 맞는지
- domain weight 합이 100인지
- 모든 문제가 존재하는 domain과 concept을 참조하는지
- 정답이 1~4 사이인지
- 현재 엔진이 지원하는 `single_choice` 문항인지
- 개인 source type은 반드시 `--private` 옵션으로만 import되는지
- 공개 repo에 원문 문제가 들어가지 않는지

## 출제 우선순위

문제은행이 커지면 같은 문제를 반복하지 않는 것이 중요합니다.

| 모드 | 우선순위 |
| --- | --- |
| `custom-cbt` | 미노출 문제 -> 복습 예정 문제 -> 오답 이력 개념 -> 오래 전에 푼 문제 |
| `review-cbt` | 복습 예정 오답 -> 오답 이력 문제 -> 미노출 문제 |
| `weak-cbt` | 자주 틀린 개념의 문항 -> 복습 예정 문제 -> 미노출 문제 |
| `source-backed` | 합성 seed를 제외하고 출처가 있는 로컬 문항 |
| `exam-ready` | `quality_status=active`이고 비합성 source tier인 문항 |

## 공개 repo에서 보여줄 것

포트폴리오에서는 아래까지만 보여주는 편이 좋습니다.

- SQLD 데모 seed
- CBT 세션 엔진
- 한 문제씩 출제하는 MCP 흐름
- 채점과 오답 리포트
- Obsidian Markdown 내보내기
- Notion 동기화 계획 하네스
- 로컬 import 구조
- 테스트

실제 개인 문제은행의 크기, 어떤 문제를 어디서 확보했는지, 지금 어떤 시험을 준비 중인지는 공개 repo가 아니라 로컬 환경의 문제입니다.
