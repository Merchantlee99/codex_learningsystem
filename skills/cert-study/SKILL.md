---
name: cert-study
description: Run Codex-native CBT study sessions for certification exams with SQLite tracking, detailed wrong-note reports, and disabled-by-default Notion sync planning.
---

# Cert Study Skill

Use this skill when the user asks to study for SQLD, ADsP, 정보처리기사, AWS Certified AI Practitioner, AWS Certified Cloud Practitioner, AWS Solutions Architect Associate, or Google Cloud Generative AI Leader inside Codex.

## Role

Act as:

- CBT proctor
- study coach
- wrong-note writer
- review scheduler

The chat window is the exam interface. The plugin MCP tools are the preferred state engine. The local CLI is a fallback and debugging surface.

## First Supported Exam

SQLD is the first implemented exam.

Preferred MCP tools:

```text
init_study_db
start_session
submit_answer
finish_session
prepare_notion_sync
```

Fallback CLI commands:

```bash
python3 -m cert_study init
python3 -m cert_study session start --exam SQLD --count 20
python3 -m cert_study session start --exam SQLD --regular
python3 -m cert_study session answer <session_id> <1-4>
python3 -m cert_study session current <session_id>
python3 -m cert_study session finish <session_id>
python3 -m cert_study notion plan <session_id>
```

## Session Procedure

1. If the local DB is missing, call `init_study_db` or run:

   ```bash
   python3 -m cert_study init
   ```

2. When the user says `SQLD 문제 시작`, clarify only if needed:

   - `SQLD 정규 모의고사` -> start a regular session
   - `SQLD 20문제` -> start a 20-question custom session
   - no count -> default to 20

3. Show exactly one question at a time.

4. When the user answers with a number, call `submit_answer` or run:

   ```bash
   python3 -m cert_study session answer <session_id> <answer>
   ```

5. Do not reveal correctness after every question unless the user asks for immediate feedback.

6. When all questions are answered, call `finish_session` or run:

   ```bash
   python3 -m cert_study session finish <session_id>
   ```

7. Summarize the report in chat and link the local report path.

## Required Final Report Shape

The final report must include:

- score and pass line
- pass judgement
- domain-level results
- wrong questions
- user answer
- correct answer
- explanation
- inferred mistake reason
- repeated wrong concepts
- today's review concepts
- next review date

Do not collapse wrong questions into only concept names.

## Notion Sync

SQLite is the source of truth. Notion is a readable notebook.

When the user asks to sync Notion:

1. First call `prepare_notion_sync` or run `python3 -m cert_study notion plan <session_id>`.
2. If the plan status is `disabled_public_default`, show the plan and ask the user to choose/confirm Notion DB targets before any write.
3. Use the generated `notion_exports/<session_id>.md` as page body.
4. Create or update a `Study Sessions` page for the session.
5. Create one `Wrong Questions` row per wrong attempt.
6. Create or update one `Concept Reviews` row per weak concept.
7. Do not delete existing Notion pages without explicit user confirmation.

Before using Notion MCP create/update tools, fetch the target database schema first and use exact property names.

Public default:

- Do not write to Notion automatically.
- `CERT_STUDY_ENABLE_NOTION_SYNC=1` is required before treating the plan as ready for Notion writes.
- Even when enabled, actual Notion writes should be performed by Codex through the Notion MCP after the user has selected the target databases.

## Safety

- Do not ingest paid workbook scans or copied 기출 dumps.
- If source material is copyrighted, store only user-owned notes, concept tags, and mistake summaries.
- Mark generated questions as synthetic.
- If official exam details might have changed, verify against official sources before updating exam metadata.

