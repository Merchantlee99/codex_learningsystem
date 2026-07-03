# 과목 확장 계획

이 공개 레포는 문제은행 마켓플레이스가 아니라 학습 하네스를 보여주는 포트폴리오 코드베이스입니다.

현재 공개 기본값은 `SQLD`, `ADSP`, `KR_INFO_PROCESSING_ENGINEER` 세 과목입니다. 세 과목 모두 실제 기출/족보 원문이 아니라 공식 출제 범위를 참고해서 만든 합성 훈련 문항입니다.

이 문항 수는 실전 학습용 충분량이 아니라 공개 데모용 1회분입니다. 실전 학습은 개인 문제은행을 로컬에서 키우고, 엔진이 미노출/약점/복습 우선순위로 출제하는 구조를 전제로 합니다.

## 왜 이렇게 나누는가

공개 레포에 실제 기출, 족보, 유료 문제집 원문을 넣으면 저작권과 시험 보안 문제가 생깁니다. 그래서 경계는 이렇게 둡니다.

- 공개 repo: 학습 엔진, 합성 문제은행, importer 구조, 테스트
- 개인 로컬: 사용자가 직접 정리한 오답, 요약, 개인 소유 문제은행
- 금지: 복사한 기출 원문, 시험 덤프, 유료 문제집 원문, 웹에서 긁은 문제 원문

즉, 포트폴리오에는 “이런 식으로 CBT 학습 시스템을 만들었다”가 남고, 실제 공부 자료는 로컬에서만 붙이는 구조입니다.

## 현재 공개 문제은행

| 내부 ID | 표시 이름 | 문항 수 | 성격 |
| --- | --- | ---: | --- |
| `SQLD` | SQLD | 50 | 공식 범위 기반 합성 훈련 문항 |
| `ADSP` | ADsP | 50 | 공식 범위 기반 합성 훈련 문항 |
| `KR_INFO_PROCESSING_ENGINEER` | 정보처리기사 | 100 | Q-Net 2026 출제기준 안내 범위 기반 합성 훈련 문항 |

## 실전 문제은행 목표

공개 seed는 “정규 1회분으로 CBT 하네스를 검증한다”가 목적입니다. 실전 학습용 개인 문제은행은 아래 정도를 목표로 잡습니다.

| 과목 | 최소 목표 | 권장 목표 |
| --- | ---: | ---: |
| SQLD | 250~300문항 | 500문항 이상 |
| ADsP | 250~300문항 | 500문항 이상 |
| 정보처리기사 | 500~600문항 | 1000문항 이상 |

중요한 것은 실제 문제 원문을 많이 쌓는 게 아니라, 개념별 변형 문항과 오답 이유를 충분히 쌓는 것입니다.

## 출제 우선순위

문제은행이 커지면 같은 문제를 반복하지 않는 것이 중요합니다. 엔진은 세션 생성 시 기존 풀이 기록과 복습 큐를 보고 우선순위를 정합니다.

| 모드 | 우선순위 |
| --- | --- |
| `custom-cbt` | 미노출 문제 -> 복습 예정 문제 -> 오답 이력 개념 -> 오래 전에 푼 문제 -> 최근에 본 문제 |
| `review-cbt` | 복습 예정 오답 -> 오답 이력 문제 -> 미노출 문제 -> 오래 전에 푼 문제 |
| `weak-cbt` | 자주 틀린 개념의 문항 -> 복습 예정 문제 -> 미노출 문제 -> 오래 전에 푼 문제 |
| `exam-ready` | `quality_status=active`이고 `source_tier`가 공식 샘플, 오픈 라이선스, 사용자 소유, 라이선스 보유 개인 자료인 문항만 출제 |

이렇게 해야 문제 수가 늘어났을 때 “랜덤으로 같은 것만 계속 푸는” 상태를 피할 수 있습니다.

실전 모드로 풀기 전에 coverage를 먼저 확인합니다.

```bash
python3 -m cert_study coverage --exam AWS_CLOUD_PRACTITIONER
python3 -m cert_study session start --exam AWS_CLOUD_PRACTITIONER --regular --mode exam-ready
```

`coverage`는 공식 도메인 비중 기준으로 현재 `exam-ready` 문항이 몇 개 있는지 보여줍니다. 부족한 영역은 문제 수를 늘리는 것보다 먼저 출처와 품질 상태를 정리해야 합니다.

GCP Generative AI Leader처럼 공식 문서 URL이 붙은 오픈 라이선스 문항은 import 직후 `needs_review` 상태입니다. 공식 도메인 매핑과 문항별 공식 문서 URL을 확인한 뒤 아래 명령으로 내부 CBT 실전 후보로 승격합니다.

```bash
python3 -m cert_study bank promote-gcp-gail --checked-at 2026-07-03
```

정보처리기사처럼 ZIP/PDF 원천이 있는 과목은 먼저 private archive inspector로 후보 구조를 확인합니다. 이 단계는 원문을 DB로 가져오지 않고, 다음 parser 입력 후보만 확인합니다.

```bash
python3 -m pip install -e ".[pdf]"
python3 -m cert_study bank inspect-info-processing private_banks/raw_sources/info_processing/sinagong
```

구현 파일은 아래처럼 둡니다.

```text
cert_study/seed_sqld.py
cert_study/seed_adsp.py
cert_study/seed_info_processing.py
cert_study/seed_public.py
```

`seed_public.py`는 공개 기본 문제은행을 한 번에 넣는 entrypoint입니다. CLI와 MCP 서버는 DB 준비 시 이 entrypoint를 호출합니다.

## 개인 문제은행 가져오기

실제 공부를 하면서 모은 개인 문제은행은 공개 repo에 커밋하지 않습니다. `private_banks/` 아래에 두고 importer로 가져옵니다.

```bash
mkdir -p private_banks
python3 -m cert_study bank import private_banks/my-bank.json --private
python3 -m cert_study bank import private_banks/my-bank.yaml --private
```

`private_banks/`는 `.gitignore`에 들어가 있습니다.

## JSON/YAML 데이터팩 형태

기본 schema는 SQLite 테이블과 바로 매핑되도록 잡습니다.

```yaml
exam:
  id: MY_PRIVATE_SQLD
  name: 나의 SQLD 오답 복습
  official_question_count: 50
  official_duration_minutes: 90
  pass_score: 60
  domain_min_score: 40
  source_policy: user_owned_only
  official_guide_url: "https://www.dataq.or.kr/www/sub/a_04.do"
  verified_at: "2026-07-01"
  private: true

domains:
  - id: MY-SQLD-D1
    name: 데이터 모델링의 이해
    official_weight: 20
    official_question_count: 10

concepts:
  - id: MY-SQLD-C001
    domain_id: MY-SQLD-D1
    name: 식별자
    review_note: "본질식별자와 인조식별자를 구분한다."

questions:
  - id: MY-SQLD-Q001
    domain_id: MY-SQLD-D1
    concept_id: MY-SQLD-C001
    question_text: "사용자가 직접 요약해 만든 복습 문제."
    choices:
      - "보기 1"
      - "보기 2"
      - "보기 3"
      - "보기 4"
    answer: 1
    explanation: "정답 근거를 사용자의 말로 정리한다."
    difficulty: medium
    source_type: user_owned_summary
    source_ref: "개인 오답노트 기반 요약. 원문 복사 아님."
```

JSON 예시는 `examples/private_bank.example.json`에 있습니다.

## importer 검증 규칙

문제은행을 가져오기 전에 최소한 아래를 확인합니다.

- exam ID가 중복되지 않고 안정적인지
- 공식 메타데이터에 `verified_at` 날짜와 가이드 URL이 있는지
- 시험이 공개 가중치를 제공한다면 domain weight 합이 100인지
- 모든 문제가 존재하는 domain과 concept을 참조하는지
- 정답이 1~4 사이인지
- 엔진을 확장하지 않았다면 모든 문제가 보기 4개인지
- 정규 모드나 커스텀 모드에 필요한 문항 수가 충분한지
- 공개 repo source type은 `synthetic`, `synthetic_recent_scope`, `official_sample_link`, `official_public_sample`, `public_license`, `open_license` 중 하나인지
- 개인 source type은 `user_owned_summary`, `user_owned_raw`, `licensed_private`, `personal_wrong_note`, `restored_summary` 중 하나인지
- 개인 source type은 반드시 `--private` 옵션으로만 import되는지
- `actual_exam_dump`, `credential_assessment_material`, `commercial_book_verbatim`, `web_scraped_verbatim`은 거부되는지
- 가능하면 `question_type`, `answer_json`, `source_license`, `source_tier`, `storage_policy`, `validity_status`, `quality_status`, `scope_version`, `official_checked_at`, `provenance`가 남아 있는지

## 품질 상태 기준

`exam-ready` 세션은 내부 CBT를 그대로 쓰되, 실전 출제 가능한 문제만 고릅니다. 외부 CBT 링크나 외부 채점 흐름을 쓰지 않습니다.

| 필드 | 값 | 의미 |
| --- | --- | --- |
| `source_tier` | `official_sample` | 공식 샘플 문항 |
| `source_tier` | `open_license` | MIT 등 재사용 가능한 공개 라이선스 문항 |
| `source_tier` | `user_owned` | 사용자가 직접 정리하거나 소유한 개인 문제은행 |
| `source_tier` | `licensed_private` | 라이선스가 있는 개인 보관 자료 |
| `source_tier` | `synthetic` | 공개 데모/개념 보강용 합성 문항 |
| `quality_status` | `active` | 실전 CBT 출제 가능 |
| `quality_status` | `needs_review` | 공식 가이드 대조 전 |
| `quality_status` | `outdated` | 출제범위 변경으로 제외 |
| `quality_status` | `bad_answer` | 정답 의심 |
| `quality_status` | `weak_explanation` | 해설 보강 필요 |

## 추가하려는 과목

개인 학습 목록은 아래처럼 잡습니다.

| 내부 ID | 표시 이름 | 그룹 | 현재 상태 |
| --- | --- | --- | --- |
| `SQLD` | SQLD | 국내 데이터/IT | 공개 합성 문제은행 있음 |
| `ADSP` | ADsP | 국내 데이터/IT | 공개 합성 문제은행 있음 |
| `KR_INFO_PROCESSING_ENGINEER` | 정보처리기사 | 국내 데이터/IT | 공개 합성 문제은행 있음, private ZIP/PDF inspector 있음 |
| `AWS_AI_PRACTITIONER` | AWS Certified AI Practitioner | 클라우드/AI | catalog만 있음 |
| `AWS_CLOUD_PRACTITIONER` | AWS Certified Cloud Practitioner | 클라우드 기본 | catalog만 있음 |
| `AWS_SOLUTIONS_ARCHITECT_ASSOCIATE` | AWS Certified Solutions Architect Associate | 클라우드 아키텍처 | catalog만 있음 |
| `GCP_GENERATIVE_AI_LEADER` | Google Cloud Generative AI Leader | 클라우드/AI | 로컬 import-ready 변환기와 quality 승격 명령 있음 |

공식 시험 코드가 바뀌더라도 내부 ID는 안정적으로 유지합니다. 공식 코드, 버전, 가이드 URL, 확인 날짜는 문제은행 파일의 메타데이터로 따로 저장합니다.

## 추천 확장 순서

1. 국내 3개 과목은 현재 공개 합성 문제은행으로 CBT 흐름을 검증합니다.
2. 개인이 가진 실제 공부 자료는 `private_banks/`로 가져와 로컬에서만 씁니다.
3. AWS/GCP는 공개 repo에 원천 문항을 넣지 않고, 로컬 `private_banks/`에서 허용 라이선스 자료만 변환/import합니다.
4. 과목이 더 늘어나면 Python seed를 계속 늘리기보다 JSON/YAML 데이터팩을 기본 입력으로 삼습니다.
5. 새 과목을 추가할 때마다 작은 CBT 세션을 돌리는 공통 하네스 테스트를 추가합니다.

## 공개 repo 경계

공개 repo에 들어가도 되는 것:

- 학습 엔진
- 공식 범위 기반 합성 문제은행
- importer schema와 예시
- 하네스가 동작함을 보여주는 테스트
- private 문제은행을 어떻게 추가할지 설명하는 문서

공개 repo에 넣지 않는 것:

- 개인 학습 기록
- Obsidian 생성 노트
- 유료 문제집 내용
- 복사한 기출 또는 시험 덤프
- 개인 Notion DB ID

개인 학습용 실제 문제은행은 로컬이나 private repo에 두는 편이 맞습니다.
