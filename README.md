# 코덱스 학습 시스템

사용자가 자기 과목과 문제은행을 붙여 확장할 수 있는 Codex CBT 학습 견본 플러그인입니다. 공개 기본값은 SQLD 하나이고, 공개 repo에는 시스템 동작을 보여주는 합성 데모 문항만 둡니다.

핵심은 “LLM이 문제를 만들어준다”가 아닙니다. 문제 출제, 답변 기록, 채점, 오답 리포트, 복습 큐를 로컬 Python 엔진과 SQLite가 관리하고, Codex는 사용자가 대화창에서 자연스럽게 시험을 풀 수 있게 연결합니다.

이 레포는 공개 포트폴리오용 코드베이스입니다. 실제 개인 문제은행, 풀이 기록, Obsidian 산출물, Notion 대상 DB 정보는 공개 repo에 넣지 않습니다.

## 왜 만들었나

자격증 공부를 AI로 도와준다고 하면 보통 “요약해줘”, “문제 내줘”에서 끝나기 쉽습니다. 그런데 실제 학습에서 더 중요한 것은 아래 루프입니다.

| 문제 | 이 프로젝트의 대응 |
| --- | --- |
| 채팅만 쓰면 풀이 상태가 사라짐 | 세션, 답변, 채점을 SQLite에 기록 |
| 정답만 보면 왜 틀렸는지 복구가 안 됨 | 내 답, 정답, 해설, 오답 이유를 리포트에 남김 |
| 같은 개념을 반복해서 틀려도 추적이 약함 | 반복 오답 개념과 복습 큐를 별도로 관리 |
| 노트 정리가 별도 일이 됨 | Obsidian에서 읽을 수 있는 Markdown 오답노트 생성 |
| 공개 repo에 문제 원문을 쌓기 쉬움 | 공개 seed는 SQLD 합성 데모 문항으로 제한 |
| 검수 전 문제와 실전용 문제가 섞임 | `source-backed`와 `exam-ready`를 분리하고, `exam-ready`는 gold 검수 통과 문항만 사용 |

```mermaid
flowchart TD
  A["사용자: SQLD 20문제 시작"] --> B["Codex 대화창"]
  B --> C["cert-study MCP 도구"]
  C --> D["로컬 Python CBT 엔진"]
  D --> E["SQLite 학습 원장"]
  D --> F["Markdown 세션 리포트"]
  F --> G["Obsidian 오답노트"]
  E --> H["복습 큐"]
  H --> G
```

## 만든 것

| 구성 | 위치 | 역할 |
| --- | --- | --- |
| 플러그인 매니페스트 | `.codex-plugin/plugin.json` | Codex가 설치 가능한 플러그인으로 인식하는 메타데이터 |
| MCP 설정 | `.mcp.json` | `cert-study` stdio MCP 서버 연결 |
| MCP 서버 | `cert_study/mcp_server.py` | `list_exams`, `start_session`, `submit_answer`, `finish_session`, `prepare_notion_sync` 도구 제공 |
| CLI | `cert_study/cli.py` | 같은 엔진을 터미널에서 실행하는 표면 |
| SQLite 스키마 | `cert_study/db.py` | 시험, 영역, 개념, 문제, 세션, 풀이, 복습 큐 저장 |
| CBT 엔진 | `cert_study/engine.py` | 미노출 우선 출제, 답변 기록, 채점, 복습 큐 갱신 |
| 리포트 | `cert_study/reporting.py` | 점수, 합격선, 오답, 복습 개념을 Markdown으로 생성 |
| Obsidian 내보내기 | `cert_study/obsidian.py` | 세션 노트, 개념 노트, 복습 큐 생성 |
| Notion 하네스 | `cert_study/notion_sync.py` | 기본 비활성. 실제 쓰기 전 계획만 생성 |
| Gold 검수 | `cert_study/gold.py` | 최종 학습용 문제은행의 해설, 오답 근거, 개념 매핑, 출제범위 참조를 점검 |
| 공개 seed | `cert_study/seed_sqld.py` | SQLD 합성 데모 문항 50개 |
| import 구조 | `cert_study/importer.py`, `cert_study/importers/` | 로컬 문제은행을 DB로 가져오는 확장 표면 |
| Codex skill | `skills/cert-study/SKILL.md` | 한 문제씩 출제하고 정답표를 미리 공개하지 않도록 하는 운영 규칙 |
| 테스트 | `tests/test_study_system.py` | 세션, 채점, 오답노트, 플러그인 형태 검증 |

## AI가 하는 일과 하지 않는 일

Codex는 인터페이스와 학습 코치 역할을 맡습니다. 사용자가 “SQLD 20문제 시작”이라고 말하면 MCP 도구를 호출하고, 문제를 하나씩 보여주고, 마지막에 결과를 요약합니다.

채점과 상태 관리는 LLM에게 맡기지 않습니다. 정답 여부, 점수, 합격선, 반복 오답, 다음 복습일은 Python 코드와 SQLite가 처리합니다. 같은 입력이면 같은 결과가 나와야 하기 때문입니다.

## 실행

```bash
git clone https://github.com/Merchantlee99/26_codex_learningsystem.git
cd 26_codex_learningsystem
python3 -m cert_study init
python3 -m cert_study stats
python3 -m cert_study session start --exam SQLD --count 20
```

답변:

```bash
python3 -m cert_study session answer <session_id> 3
```

종료와 리포트 생성:

```bash
python3 -m cert_study session finish <session_id>
```

약점/복습 세트:

```bash
python3 -m cert_study session start --exam SQLD --count 10 --mode weak-cbt
python3 -m cert_study session start --exam SQLD --count 10 --mode review-cbt
```

최종 학습용 gold 문제은행 점검:

```bash
python3 -m cert_study audit final --exam SQLD
python3 -m cert_study audit readiness --min-rounds 3
python3 -m cert_study audit state --min-rounds 3
python3 -m cert_study session start --exam SQLD --count 20 --mode exam-ready
python3 -m cert_study session start --exam SQLD --regular --mode final-mock
```

## 견본 플러그인으로 쓰는 방법

처음 보는 사람은 이 repo를 문제은행이 아니라 플러그인 골격으로 보면 됩니다.

1. SQLD 데모 seed로 CBT 흐름이 어떻게 동작하는지 확인합니다.
2. `examples/private_bank.example.json` 형식으로 자기 과목의 JSON/YAML 문제은행을 만듭니다.
3. 실제 학습 자료는 `private_banks/` 아래에서 로컬 import하고 공개 repo에는 올리지 않습니다.
4. 검수 전에는 `source-backed`, 최종 검수 후에는 `exam-ready`로 풉니다.

```bash
python3 -m cert_study bank import private_banks/my-bank.json --private
python3 -m cert_study session start --exam MY_EXAM --count 20 --mode source-backed
```

과목이 여러 개로 늘어나면 Python seed 파일을 추가로 만드는 대신, JSON/YAML import 경로를 유지하는 편이 좋습니다. 그래야 공개 코드와 개인 학습 자료가 섞이지 않습니다.

## Gold 문제은행 기준

이 프로젝트에서 `exam-ready`는 “출처가 있다” 정도가 아닙니다. 아래 조건을 통과한 `gold_status=gold` 문항만 실전 모드에 들어갑니다.

| 필드 | 의미 |
| --- | --- |
| `correct_rationale` | 정답 선택지가 맞는 이유 |
| `distractor_rationales` | 오답 선택지별로 틀린 이유 |
| `review_concepts` | 오답노트와 복습 큐에 연결할 세부 개념 |
| `official_scope_refs` | 공식 출제범위 또는 시험 가이드 기준 참조 |
| `gold_status` | `candidate`에서 검수 후 `gold`로 승격 |
| `gold_checked_at` | 마지막 gold 검수일 |

권장 흐름:

```bash
python3 -m cert_study bank export-gold-template --exam SQLD private_banks/gold_banks/sqld_gold_review.json
# JSON을 보강한 뒤
python3 -m cert_study bank import private_banks/gold_banks/sqld_gold_review.json --private
python3 -m cert_study bank promote-gold --exam SQLD --checked-at 2026-07-04
python3 -m cert_study audit final --exam SQLD
```

`audit final`에서 부족한 해설, 임시 개념 매핑, 공식 출제범위 참조 누락, 영역별 문항 수 부족이 나오면 아직 최종 학습용으로 보지 않습니다.

`audit readiness`는 한 과목만 보는 것이 아니라 전체 과목을 대상으로 최소 몇 회분의 gold 문항이 있는지 보여줍니다.

`audit state`는 최종 사용 가능 상태를 더 엄격하게 봅니다. 과목별로 `gold` 문항이 몇 개 부족한지, 이미 수집된 source-backed 문항 중 몇 개를 보강해야 하는지, 추가 수집이 몇 개 필요한지를 같이 보여줍니다.

```bash
python3 -m cert_study audit state --min-rounds 3
python3 -m cert_study audit state --exam SQLD --min-rounds 3
python3 -m cert_study audit state --min-rounds 3 --json --output private_banks/final_state.json
```

정규시험 대비 최종 상태는 `audit final` 통과만으로 보지 않습니다. 모든 대상 과목이 `audit state --min-rounds 3`에서 `GREEN`이어야 최종 사용 가능 상태로 봅니다.

SQLD처럼 로컬에 실제 출처 기반 HTML/PDF를 모아둔 경우에는 아래 흐름으로 import-ready 파일을 만들고, 검수 가능한 gold 파일로 분리합니다. 이 파일들은 모두 `private_banks/` 아래에 두며 공개 repo에는 올라가지 않습니다.

```bash
python3 -m cert_study bank inspect-kdata --exam SQLD private_banks/raw_sources/sqld
python3 -m cert_study bank convert-kdata --exam SQLD private_banks/raw_sources/sqld private_banks/import_ready/sqld/source_backed.json --mark-active --checked-at 2026-07-04
python3 -m cert_study bank enrich-sqld-gold private_banks/import_ready/sqld/source_backed.json private_banks/gold_banks/sqld_gold.json --checked-at 2026-07-04 --prefer-source-contains sqld_2025_58.html --limit 50
python3 -m cert_study bank import private_banks/gold_banks/sqld_gold.json --private
python3 -m cert_study audit final --exam SQLD
```

`enrich-sqld-gold`는 SQLD 전용 보강기입니다. HTML 안에 문항/선택지/정답/해설/SQL 코드가 분리돼 있을 때 이를 CBT 지문으로 합치고, 세부 개념과 정답/오답 근거를 채워 `exam-ready` 후보를 만듭니다. 다른 과목은 같은 기준을 만족하는 별도 보강기나 수동 gold JSON을 만들어야 합니다.

## Codex에서 쓰는 흐름

```text
SQLD 20문제 시작해줘
```

그러면 시스템은 첫 문제만 보여줍니다. 사용자가 답을 입력하면 다음 문제로 넘어갑니다. 세션 종료 전에는 정답표나 해설을 먼저 공개하지 않습니다.

단일정답은 `3`처럼 입력하고, 복수정답은 `1,3`처럼 쉼표로 입력합니다. 복수정답 문항은 정답 선택지를 모두 맞혀야 정답으로 처리합니다.

최종 리포트에는 아래가 들어갑니다.

- 점수와 합격선
- 합격권 판정
- 영역별 결과
- 틀린 문제
- 내가 고른 답
- 정답
- 해설
- 추정 오답 이유
- 반복 오답 개념
- 오늘 복습할 개념
- 다음 복습일

## 공개 repo 경계

이 repo는 문제 저장소가 아니라 확장 가능한 견본 플러그인입니다.

| 들어가는 것 | 들어가지 않는 것 |
| --- | --- |
| SQLD 합성 데모 문항 | 실제 기출 원문 |
| CBT 엔진과 MCP 도구 | 유료 문제집 내용 |
| SQLite/Obsidian/Notion 하네스 코드 | 개인 풀이 기록 |
| 테스트 코드 | 개인 Notion DB ID |
| 로컬 import 구조 | 로컬 private 문제은행 |

추가 문제은행은 로컬에서만 import합니다. `private_banks/`, `data/study.sqlite`, `reports/`, `obsidian_vault/`는 공개 repo에 올리지 않습니다.

공개 SQLD 문항은 실제 기출, 공식 샘플, 유료 문제집, 웹 문제 원문을 복제한 것이 아니라 CBT 흐름 확인을 위해 새로 작성한 합성 문항입니다. 시험 구조는 공개된 SQLD 문항 수와 과목 비중을 참고하지만, 문항 원문은 공식/상업 문제를 가져오지 않습니다.

## 문항 수를 늘리는 방식

공개 seed 50문항은 시스템 동작을 보여주는 데모입니다. 실제 학습용으로 문항 수를 늘릴 때는 공개 repo에 문제를 쌓지 않고, 로컬 JSON/YAML 문제은행을 import합니다.

```bash
python3 -m cert_study bank import private_banks/my-sqld-bank.json --private
python3 -m cert_study session start --exam SQLD --count 20 --mode source-backed
```

문항 수가 늘어나면 엔진은 미노출 문제를 먼저 내고, 최근에 본 문제는 뒤로 밀며, 복습/약점 모드에서는 오답 이력이 있는 개념을 우선합니다.

검수 전 문항을 바로 실전 모드로 쓰지는 않습니다. `source-backed`는 원천 기반 학습과 정제 단계, `exam-ready`는 gold 검수 통과 후 최종 학습 단계입니다.

## 검증

```bash
python3 -m pytest -q
```

검증 범위:

- SQLD 공개 seed 50문항 로드
- 한 번에 한 문제만 출제
- 세션 답변 기록
- 정답 수와 점수 계산
- 합격선 표시
- 오답 리포트 생성
- Obsidian Markdown 내보내기
- Notion 동기화 기본 비활성
- 공개 repo에 개인 문제은행 없이도 플러그인 구조가 동작함
- gold 문제은행 최종 검수
- `exam-ready`가 gold 문항만 출제하는지 확인

## 포트폴리오 포인트

이 프로젝트가 보여주는 것은 “AI가 문제를 만들어줬다”가 아닙니다.

> Codex를 개인 학습 워크플로우의 인터페이스로 붙이고, 채점과 상태 관리는 재현 가능한 로컬 하네스로 분리했다.

즉, LLM은 사용자 경험과 설명을 맡고, 신뢰가 필요한 채점/기록/복습 로직은 코드가 맡는 구조입니다.
