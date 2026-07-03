---
name: cert-study
description: Codex 안에서 자격증 CBT 학습 세션을 진행하고, SQLite 학습 기록과 Obsidian용 오답노트를 생성한다. Notion 동기화는 선택 기능이며 기본값은 비활성이다.
---

# Cert Study Skill

사용자가 Codex 안에서 자격증 CBT 학습, 문제 풀이, 오답노트, 복습 세션을 요청하면 이 skill을 사용한다.

## 역할

Codex는 아래 역할을 맡는다.

- CBT 감독관
- 학습 코치
- 오답노트 작성자
- 복습 일정 관리자

시험 인터페이스는 채팅창이다. 상태 관리는 플러그인 MCP 도구를 우선 사용한다. 로컬 CLI는 대체 수단과 디버깅 표면이다.

## 핵심 가드레일

이 plugin은 문제 생성기가 아니라 CBT 세션 관리자다.

- 사용자가 `문제 N개 줘`, `시험 문제 내줘`, `출제해줘`, `모의고사 시작`처럼 말하면 일반 답변으로 문제를 만들지 말고 CBT 세션으로 라우팅한다.
- 세션 시작은 반드시 `start_session` MCP 도구 또는 `python3 -m cert_study session start ...`로 한다.
- 세션 중에는 한 번에 한 문제만 보여준다.
- 세션 종료 전에는 정답표, 해설, 정답 번호를 공개하지 않는다.
- 사용자가 즉시 피드백을 명시적으로 요청한 경우를 제외하면, 매 문제마다 정답 여부도 공개하지 않는다.
- 공개 repo에 기본 포함된 합성 문제은행은 SQLD, ADsP, 정보처리기사다.
- 공개 합성 문제은행은 포트폴리오 데모용 1회분 수준이다. 실전 학습은 `private_banks/`로 개인 문제은행을 확장하는 전제를 설명한다.
- 실전 대비 요청이면 먼저 `coverage_report`로 `exam-ready` 가능 여부를 확인한다.
- `exam-ready` 세션은 내부 CBT 방식 그대로 진행하되, `quality_status=active`이고 비합성 `source_tier`인 문제만 출제한다.
- AWS, GCP 등 추가 과목은 로컬 DB에 import되어 `list_exams`의 `available`에 있을 때만 CBT 세션을 시작한다.
- 요청한 과목이 `available`에 없으면 문제를 임의 생성하지 말고 “아직 문제은행이 없어 CBT 세션을 시작할 수 없다”고 말한다.
- 실제 기출, 족보, 유료 문제집 원문은 공개 repo 문제은행으로 가져오지 않는다. 사용자가 개인 소유 요약/오답 기반 문제은행을 가져오려면 `python3 -m cert_study bank import <path> --private`를 안내한다.
- 지원 여부가 애매하면 먼저 `list_exams`를 호출한다.

## 지원 과목

공개 repo에 기본 포함된 합성 문제은행은 아래 세 과목이다.

```text
SQLD
ADSP
KR_INFO_PROCESSING_ENGINEER
```

우선 사용할 MCP 도구:

```text
init_study_db
list_exams
start_session
submit_answer
finish_session
prepare_notion_sync
coverage_report
```

CLI 대체 명령:

```bash
python3 -m cert_study init
python3 -m cert_study session start --exam SQLD --count 20
python3 -m cert_study session start --exam ADSP --count 20
python3 -m cert_study session start --exam KR_INFO_PROCESSING_ENGINEER --count 20
python3 -m cert_study session start --exam SQLD --count 10 --mode weak-cbt
python3 -m cert_study session start --exam SQLD --count 10 --mode review-cbt
python3 -m cert_study coverage --exam SQLD
python3 -m cert_study session start --exam SQLD --regular --mode exam-ready
python3 -m cert_study session start --exam SQLD --regular
python3 -m cert_study session answer <session_id> <1-4>
python3 -m cert_study session current <session_id>
python3 -m cert_study session finish <session_id>
python3 -m cert_study bank convert-gcp-gail private_banks/raw_sources/gcp/gail_exam_preparation/lib/exam-data.ts private_banks/import_ready/gcp/gcp_generative_ai_leader_gail_exam_preparation.json
python3 -m cert_study bank promote-gcp-gail --checked-at 2026-07-03
python3 -m cert_study bank inspect-info-processing private_banks/raw_sources/info_processing/sinagong
python3 -m cert_study bank import private_banks/my-bank.json --private
python3 -m cert_study notion plan <session_id>
```

## 세션 진행 방식

1. 로컬 DB가 없으면 `init_study_db`를 호출하거나 아래 명령을 실행한다.

   ```bash
   python3 -m cert_study init
   ```

2. 사용자가 문제 풀이를 요청하면 먼저 과목이 실제 지원되는지 판단한다.

   - 지원 여부가 애매하면 `list_exams`를 호출한다.
   - 공개 기본 과목은 `SQLD`, `ADSP`, `KR_INFO_PROCESSING_ENGINEER`다.
   - AWS/GCP 등 추가 과목은 `list_exams`의 `available`에 있는 경우에만 시작한다.
   - 아직 bank가 없는 과목은 임의로 문제를 만들지 않는다.

3. 사용자가 `SQLD 문제 시작`, `ADsP 문제 5개 줘`, `정보처리기사 시험 문제 내줘`라고 말하면 필요한 경우에만 확인한다.

   - `SQLD 정규 모의고사` -> 정규 세션 시작
   - `SQLD 20문제` -> 20문제 커스텀 세션 시작
   - `SQLD 약점 세트`, `자주 틀린 개념 위주` -> `mode: weak-cbt`
   - `SQLD 복습 세트`, `오답 다시 풀기` -> `mode: review-cbt`
   - `SQLD 실전 모드`, `시험 직전 모드`, `실전처럼` -> 먼저 `coverage_report`, 충분하면 `mode: exam-ready`
   - 문제 수가 없으면 기본값 20문제

4. 기본 `custom-cbt` 세션은 미노출 문제를 먼저 고른다. 같은 문제를 외우지 않도록 최근에 본 문제는 뒤로 밀린다.

5. 문제는 한 번에 하나만 보여준다.

6. 사용자가 숫자로 답하면 `submit_answer`를 호출하거나 아래 명령을 실행한다.

   ```bash
   python3 -m cert_study session answer <session_id> <answer>
   ```

7. 사용자가 즉시 피드백을 원하지 않는 한, 매 문제마다 정답 여부를 공개하지 않는다.

8. 모든 문제에 답하면 `finish_session`을 호출하거나 아래 명령을 실행한다.

   ```bash
   python3 -m cert_study session finish <session_id>
   ```

9. 채팅에 리포트를 요약하고 로컬 리포트 경로를 알려준다.
10. 생성된 Obsidian 세션 노트와 복습 큐 경로도 함께 알려준다.

## 최종 리포트에 반드시 포함할 것

최종 리포트에는 아래가 들어가야 한다.

- 점수와 합격선
- 합격권 판정
- 영역별 결과
- 틀린 문제
- 사용자가 고른 답
- 정답
- 해설
- 추정 오답 이유
- 반복 오답 개념
- 오늘 복습할 개념
- 다음 복습일

틀린 문제를 개념명만으로 뭉개지 않는다.

## Obsidian 노트

원장은 SQLite다. 사람이 읽는 기본 노트는 Obsidian Markdown이다.

`finish_session` 후 플러그인은 아래 파일을 쓴다.

- `reports/sessions/<session_id>.md`
- `obsidian_vault/certifications/<EXAM>/sessions/*.md`
- `obsidian_vault/certifications/<EXAM>/concepts/*.md`
- `obsidian_vault/certifications/<EXAM>/review-queue.md`

사용자가 기존 Obsidian vault를 쓰고 있다면 세션 시작 전에 `CERT_STUDY_OBSIDIAN_VAULT`에 절대 경로를 지정한다.

## Notion 동기화

Notion은 선택 기능이다. 사용자가 명시적으로 Notion 동기화를 요청하지 않으면 Obsidian/Markdown을 우선한다.

사용자가 Notion 동기화를 요청하면:

1. 먼저 `prepare_notion_sync`를 호출하거나 `python3 -m cert_study notion plan <session_id>`를 실행한다.
2. 계획 상태가 `disabled_public_default`라면 계획을 보여주고, Notion DB 대상을 사용자가 고르기 전에는 쓰지 않는다.
3. 생성된 로컬 세션 리포트를 페이지 본문으로 사용한다.
4. 세션용 `Study Sessions` 페이지를 만들거나 갱신한다.
5. 틀린 문제마다 `Wrong Questions` row를 하나씩 만든다.
6. 취약 개념마다 `Concept Reviews` row를 만들거나 갱신한다.
7. 사용자가 명시적으로 확인하지 않는 한 기존 Notion 페이지를 삭제하지 않는다.

Notion MCP create/update 도구를 쓰기 전에는 대상 DB schema를 먼저 조회하고 정확한 property 이름을 사용한다.

공개 기본값:

- Notion에 자동으로 쓰지 않는다.
- `CERT_STUDY_ENABLE_NOTION_SYNC=1`이 있어야 Notion 쓰기 준비 상태로 본다.
- 환경변수를 켜도 실제 Notion 쓰기는 사용자가 대상 DB를 고른 뒤 Codex가 MCP로 수행한다.

## 안전 규칙

- 유료 문제집 스캔이나 복사한 기출 덤프를 가져오지 않는다.
- 저작권이 있는 자료라면 원문이 아니라 사용자 소유 노트, 개념 태그, 오답 요약만 저장한다.
- 허용 라이선스나 사용자 소유가 확인된 로컬 자료만 `private_banks/`에서 변환/import한다.
- 외부 사이트에서 풀고 답만 기록하는 external CBT 방식으로 우회하지 않는다. 문제 출제, 답변, 채점, 오답노트는 이 시스템 내부에서 진행한다.
- GCP GAIL 문항은 변환 직후 `needs_review`다. 공식 문서 URL과 도메인 매핑 확인 후 `promote-gcp-gail`로만 `active` 승격한다.
- 정보처리기사 ZIP/PDF는 먼저 `inspect-info-processing`으로 후보 구조를 확인하고, 원문 import parser는 별도 검수 후 붙인다.
- 생성 문제는 합성 문항임을 표시한다.
- 공식 시험 세부 정보가 바뀌었을 가능성이 있으면 exam metadata를 업데이트하기 전 공식 출처로 확인한다.
