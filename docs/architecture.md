# 아키텍처

이 시스템은 일부러 웹앱으로 만들지 않았습니다. Codex 대화창을 인터페이스로 쓰고, 레포는 사용자가 자기 문제은행을 붙일 수 있는 Codex 플러그인 견본 형태로 패키징합니다.

```text
사용자가 채팅에서 답변
  -> Codex가 플러그인 MCP 도구 호출
  -> SQLite가 답변 기록
  -> MCP 도구가 다음 문제 반환
  -> 세션 종료 시 리포트 생성
  -> Obsidian용 Markdown 오답노트 생성
  -> 사용자가 원할 때만 Notion 동기화 계획 생성
```

## 구성 요소

```text
.codex-plugin/plugin.json
  Codex 플러그인 매니페스트

.mcp.json
  로컬 stdio MCP 서버 선언

cert_study/
  cli.py          명령줄 인터페이스
  db.py           SQLite 스키마와 연결
  engine.py       세션 선택, 답변 기록, 채점, 복습 일정 처리
  gold.py         최종 학습용 gold 문제은행 검수와 승격
  importer.py     개인 JSON/YAML 문제은행 import
  mcp_server.py   Codex 플러그인이 쓰는 stdio MCP 서버
  notion_sync.py  기본 비활성 Notion 쓰기 계획 하네스
  obsidian.py     Obsidian 세션/개념/복습 큐 노트 생성
  reporting.py    Markdown 리포트 렌더링
  seed_public.py  공개 SQLD 데모 seed entrypoint
  seed_sqld.py    SQLD 합성 문제 seed

skills/cert-study/SKILL.md
  Codex가 CBT 감독관처럼 행동하기 위한 규칙

scripts/sync_notion.py
  기본 비활성 Notion 동기화 계획 helper

tests/
  핵심 동작 검증용 하네스
```

## 원장

원장은 SQLite입니다.

Obsidian/Markdown은 사람이 읽는 기본 노트입니다. 플러그인은 `obsidian_vault/` 아래에 세션 노트, 개념 노트, 복습 큐를 씁니다. 기존 Obsidian vault에 바로 쓰고 싶으면 `CERT_STUDY_OBSIDIAN_VAULT`에 경로를 지정하면 됩니다.

Notion은 선택 기능입니다. CBT 중에 Notion 조회가 느리거나 실패해도 학습이 막히지 않도록, Notion은 원장이 아니라 보조 DB 뷰로만 둡니다.

공개 플러그인은 Notion에 자동으로 쓰지 않습니다. `prepare_notion_sync`로 계획만 만들고, 실제 Notion MCP 쓰기는 사용자가 대상 DB를 고르고 `CERT_STUDY_ENABLE_NOTION_SYNC=1`을 켠 뒤에만 진행합니다.

## 과목 확장

새 과목을 추가할 때 필요한 것은 아래입니다.

1. 시험 메타데이터
2. 도메인 메타데이터
3. 개념 메타데이터
4. 합성 데모 또는 사용자 소유 문제은행
5. 시험별 채점 규칙이 다르면 해당 규칙
6. 정규 문항 수와 합격선 리포트 검증 테스트

과목이 2~3개 이상으로 늘어나면 Python seed 파일을 계속 추가하기보다 JSON/YAML 가져오기 도구로 바꾸는 게 맞습니다. 공개 repo는 SQLD 데모 하나만 기본 seed로 유지하고, 자세한 설계는 `docs/exam-expansion-plan.md`에 둡니다.

## 출제 선택

세션 생성은 단순 랜덤이 아닙니다. 엔진은 도메인별 문항 비율을 먼저 맞추고, 각 도메인 안에서는 풀이 이력을 보고 우선순위를 정합니다.

```text
custom-cbt: 미노출 -> 복습 예정 -> 오답 이력 개념 -> 오래 전에 푼 문제 -> 최근에 본 문제
review-cbt: 복습 예정 오답 -> 오답 이력 문제 -> 미노출 -> 오래 전에 푼 문제
weak-cbt: 자주 틀린 개념 -> 복습 예정 -> 미노출 -> 오래 전에 푼 문제
```

공개 seed는 SQLD 데모 수준이라 금방 반복됩니다. 이 우선순위는 로컬 문제은행을 키웠을 때 같은 문제만 푸는 문제를 줄이기 위한 장치입니다.
같은 세션 안에서는 정규화한 지문이 같은 문항을 가능한 한 피하고, 대체 문항이 부족할 때만 중복 지문을 허용합니다.

## 문제은행 품질 단계

문제은행은 한 번에 최종 상태가 되었다고 보지 않습니다.

```text
import_ready
  원천에서 파싱된 문제. 출처 기반이지만 해설과 개념 매핑은 부족할 수 있음

source-backed
  합성 문항은 제외하고 원천 기반 문제만 푸는 학습/정제 단계

gold candidate
  정답 근거, 오답 선택지 해설, 복습 개념, 공식 출제범위 참조를 채운 후보

gold / exam-ready
  final audit을 통과해 바로 시험 대비용으로 풀 수 있는 문항
```

`exam-ready` 모드는 `quality_status=active`, `validity_status=current`, `gold_status=gold`인 문항만 사용합니다. 그래서 단순히 문제 수가 많아도 placeholder 해설, 임시 개념 매핑, 공식 출제범위 참조 누락이 있으면 실전 모드로 승격하지 않습니다.

최종 검수 명령:

```bash
python3 -m cert_study audit final --exam SQLD
```

검수용 템플릿을 만들고 보강하는 흐름:

```bash
python3 -m cert_study bank export-gold-template --exam SQLD private_banks/gold_banks/sqld_gold_review.json
python3 -m cert_study bank import private_banks/gold_banks/sqld_gold_review.json --private
python3 -m cert_study bank promote-gold --exam SQLD --checked-at 2026-07-04
```

## 검증 기준

변경을 공개하기 전 최소로 확인할 명령입니다.

```bash
python3 -m unittest discover -s tests
python3 /Users/isanginn/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

기대하는 검증 범위:

- DB 초기화
- SQLD 공개 seed 크기
- 도메인별 문항 배분
- 미노출 우선 출제
- 복습 예정/오답 우선 출제
- 세션 답변 진행
- 채점
- 리포트 내용
- Obsidian 세션/개념/복습 큐 노트 생성
- 플러그인 매니페스트 형태
- Notion 동기화 기본 비활성 동작
- gold 문제은행 검수
- exam-ready 모드가 gold 문항만 사용하는지
