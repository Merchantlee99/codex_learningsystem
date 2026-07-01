# Exam Expansion Plan

This repo intentionally ships with one default subject: `SQLD`.

The public codebase is a portfolio example of the learning harness, not a full public question-bank marketplace. Extra subjects should be added carefully because certification metadata changes and copied workbook or exam-dump content creates copyright and integrity risk.

## Recommended Path

Use the current Python seed pattern while the project has only one or two subjects.

```text
cert_study/seed_sqld.py
cert_study/seed_adsp.py
```

Once the system has two or three real subjects, switch to a data-pack importer instead of adding more `seed_*.py` files.

```text
question_banks/
  sqld.yaml
  adsp.yaml
  kr-info-processing-engineer.yaml
  aws-ai-practitioner.yaml
  aws-cloud-practitioner.yaml
  aws-solutions-architect-associate.yaml
  gcp-generative-ai-leader.yaml
```

The importer can be implemented later as:

```bash
python3 -m cert_study bank validate question_banks/adsp.yaml
python3 -m cert_study bank import question_banks/adsp.yaml
```

Do not build the importer until the second or third bank makes the Python seed pattern painful. The current repo stays small by default.

## Target Subject Catalog

Planned personal study catalog:

| Internal ID | Display name | Group | Notes |
| --- | --- | --- | --- |
| `SQLD` | SQLD | Korea data/IT | Current default synthetic bank |
| `ADSP` | ADsP | Korea data/IT | Add after SQLD to test the second-bank pattern |
| `KR_INFO_PROCESSING_ENGINEER` | 정보처리기사 | Korea data/IT | Larger bank; should use importer format if ADsP already exists |
| `AWS_AI_PRACTITIONER` | AWS Certified AI Practitioner | Cloud/AI | Verify current AWS exam guide before metadata import |
| `AWS_CLOUD_PRACTITIONER` | AWS Certified Cloud Practitioner | Cloud fundamentals | Verify current AWS exam guide before metadata import |
| `AWS_SOLUTIONS_ARCHITECT_ASSOCIATE` | AWS Certified Solutions Architect Associate | Cloud architecture | Verify current AWS exam guide before metadata import |
| `GCP_GENERATIVE_AI_LEADER` | Google Cloud Generative AI Leader | Cloud/AI | Verify current Google Cloud exam guide before metadata import |

Keep internal IDs stable even if official exam codes change. Store official exam codes, versions, and guide URLs as metadata fields inside the bank file.

## Data Pack Shape

A future YAML/JSON bank should map directly to the existing SQLite tables.

```yaml
exam:
  id: ADSP
  name: ADsP
  official_question_count: 50
  official_duration_minutes: 90
  pass_score: 60
  domain_min_score: 0
  source_policy: synthetic_or_user_owned_only
  official_guide_url: ""
  verified_at: "YYYY-MM-DD"

domains:
  - id: ADSP-D1
    name: 데이터 이해
    official_weight: 20
    official_question_count: 10

concepts:
  - id: ADSP-C001
    domain_id: ADSP-D1
    name: 데이터의 유형
    review_note: "정형, 반정형, 비정형 데이터의 차이를 구분한다."

questions:
  - id: ADSP-Q001
    domain_id: ADSP-D1
    concept_id: ADSP-C001
    question_text: "Synthetic practice question text."
    choices:
      - "Choice 1"
      - "Choice 2"
      - "Choice 3"
      - "Choice 4"
    answer: 1
    explanation: "Why the answer is correct."
    difficulty: easy
    source_type: synthetic
    source_ref: "Original practice question; not copied from a paid workbook or exam dump."
```

## Importer Validation Rules

Before importing a bank, validate:

- Exam ID is unique and stable.
- Official metadata has a `verified_at` date and guide URL.
- Domain weights add up to 100, unless the exam has no stable public weighting.
- Every question references an existing domain and concept.
- Every answer is between 1 and 4.
- Every question has exactly four choices unless the engine is extended.
- Question count is enough for the requested regular or custom CBT mode.
- `source_type` is one of `synthetic`, `user_owned_note`, `official_sample_allowed`.
- No paid workbook scans, copied 기출, braindumps, or commercial question-bank text is committed.

## Suggested Build Order

1. Keep `SQLD` as the default repo demo.
2. Add `ADSP` as the second subject using the current Python seed pattern.
3. If `정보처리기사` is added next, introduce the YAML/JSON importer first.
4. Add AWS and GCP banks as data packs, not Python source files.
5. Add one shared harness test that imports every bank and runs a small CBT session for each.

## Public Repo Boundary

Public repo should contain:

- the learning engine
- one small default synthetic bank
- importer schema or examples
- tests that prove the harness works
- docs explaining how to add private banks

Public repo should not contain:

- personal study records
- Obsidian generated notes
- paid workbook content
- copied 기출 or exam dumps
- private Notion database IDs

For personal use, keep real study banks local or in a private repo.
