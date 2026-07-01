# Codex Learning System

Codex chat window를 CBT 시험장처럼 쓰기 위한 로컬 학습 시스템입니다.

첫 버전은 SQLD를 대상으로 합니다. 앱 UI는 만들지 않고, Python CLI와 SQLite로 다음 루프를 처리합니다.

```text
문제 시작 -> Codex가 한 문제씩 출제 -> 사용자가 채팅으로 답변
-> 채점 -> 오답/약점/복습일 저장 -> Markdown/Notion 오답노트 생성
```

## What This Is

- Codex-native study workflow
- SQLite-backed CBT session tracker
- SQLD synthetic training question bank
- Wrong-note report generator
- Notion MCP-ready Markdown export
- Harness tests for scoring, selection, and report integrity

## What This Is Not

- Commercial 기출/족보 저장소
- Web app
- Notion-only database
- Actual exam dump

The included SQLD questions are synthetic practice questions generated for concept training. Do not paste paid workbooks or actual exam dumps into this repo.

## Quick Start

```bash
python3 -m cert_study init
python3 -m cert_study stats
python3 -m cert_study session start --exam SQLD --count 20
```

After Codex shows a question, answer with:

```bash
python3 -m cert_study session answer <session_id> 3
```

When all questions are answered:

```bash
python3 -m cert_study session finish <session_id>
```

Reports are written to:

```text
reports/sessions/<session_id>.md
notion_exports/<session_id>.md
```

These generated reports are ignored by git because they are personal learning records.

## Regular SQLD Mode

```bash
python3 -m cert_study session start --exam SQLD --regular
```

This uses 50 questions:

- 데이터 모델링의 이해: 10
- SQL 기본 및 활용: 40

The system marks 60+ as pass-line reference. Domain minimum checks are only treated as exact when the session uses the official 50-question count.

## Codex Chat Usage

Use the included skill instructions in `skills/cert-study/SKILL.md`.

Example user commands:

```text
SQLD 20문제 시작해줘.
SQLD 정규 모의고사 시작해줘.
SQLD 오답 재시험 시작해줘.
SQLD 최근 성적 보여줘.
SQLD 오늘 복습할 개념 알려줘.
```

Codex should call the local CLI, show one question at a time, record each user answer, and finish with a report that includes:

- score and pass line
- domain-level result
- every wrong question
- user answer and correct answer
- explanation
- inferred mistake reason
- repeated wrong concepts
- today's review concepts
- next review date

## Notion Workflow

Local SQLite remains the source of truth. Notion is the readable study notebook.

Recommended Notion databases:

1. `Study Sessions`
2. `Wrong Questions`
3. `Concept Reviews`

See `docs/notion-schema.md` for the exact schema and page-writing style.

## Verification

Run:

```bash
python3 -m unittest discover -s tests
```

The harness checks:

- SQLD seed bank count
- 20-question session domain allocation
- answer recording
- scoring and pass judgement
- wrong-note report details
- Notion-ready export creation

