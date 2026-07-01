# Notion Certification Gallery

This document describes the Notion gallery database to create under the user's target page.

Target page:

```text
https://app.notion.com/p/3905d8362204801a9c9efc5ce2ea8105
```

Current blocker:

```text
Notion MCP returned UNAUTHORIZED / reauthentication required.
```

After Notion reauthentication, create a database on the target page with this shape.

## Database

Title:

```text
Certification Study Hub
```

Schema:

```sql
CREATE TABLE (
  "Name" TITLE,
  "Provider" SELECT('KData':blue, 'Q-Net':green, 'AWS':orange, 'Google Cloud':red),
  "Track" SELECT('Data / SQL':teal, 'Data Analysis':purple, 'Software Engineering':blue, 'AI / Cloud':orange, 'Cloud Foundations':blue, 'Cloud Architecture':red, 'Generative AI':green),
  "Study Status" SELECT('Planned':gray, 'Studying':blue, 'Reviewing':yellow, 'Ready':green, 'Passed':purple),
  "Priority" NUMBER,
  "Recommended Order" NUMBER,
  "Plugin Exam ID" RICH_TEXT,
  "Thumbnail" URL,
  "Notes" RICH_TEXT
)
```

Recommended gallery view:

```text
Name: Gallery
Type: gallery
Configure: SORT BY "Recommended Order" ASC; SHOW "Provider", "Track", "Study Status", "Priority"
```

Use each page's cover image as the gallery card thumbnail. The `Thumbnail` URL property is included so the source URL is preserved even if the page cover needs to be refreshed.

## Cards

Use `config/cert_catalog.json` as the source of truth.

For each item:

- create one database page
- set page cover to `thumbnail`
- set page icon to a short text-related emoji or leave unset
- fill properties from the catalog
- add a short page body with:
  - purpose
  - current study status
  - plugin exam id
  - first suggested study action

## Thumbnail URLs

```text
SQLD
https://raw.githubusercontent.com/Merchantlee99/26_codex_learningsystem/main/assets/cert-thumbnails/sqld.svg

ADsP
https://raw.githubusercontent.com/Merchantlee99/26_codex_learningsystem/main/assets/cert-thumbnails/adsp.svg

정보처리기사
https://raw.githubusercontent.com/Merchantlee99/26_codex_learningsystem/main/assets/cert-thumbnails/engineer-info-processing.svg

AWS Certified AI Practitioner
https://raw.githubusercontent.com/Merchantlee99/26_codex_learningsystem/main/assets/cert-thumbnails/aws-ai-practitioner.svg

AWS Certified Cloud Practitioner
https://raw.githubusercontent.com/Merchantlee99/26_codex_learningsystem/main/assets/cert-thumbnails/aws-cloud-practitioner.svg

AWS Certified Solutions Architect Associate
https://raw.githubusercontent.com/Merchantlee99/26_codex_learningsystem/main/assets/cert-thumbnails/aws-solutions-architect-associate.svg

Google Cloud Generative AI Leader
https://raw.githubusercontent.com/Merchantlee99/26_codex_learningsystem/main/assets/cert-thumbnails/google-cloud-generative-ai-leader.svg
```

