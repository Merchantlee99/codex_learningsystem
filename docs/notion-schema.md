# Notion Schema

Use Notion as the readable notebook, not the source of truth. SQLite remains the canonical study record.

## Database 1: Study Sessions

One row per CBT session.

Recommended properties:

```text
Name                 title
Exam                 select
Mode                 select
Date                 date
Total                number
Correct              number
Score                number
Pass Line            number
Judgement            select
Weak Concepts        multi_select
Next Review          date
Local Session ID     rich_text
Report Path          rich_text
```

Recommended page title:

```text
YYYY-MM-DD SQLD 20문제 CBT
YYYY-MM-DD SQLD 정규 모의고사
```

Recommended page body:

```markdown
## 결과 요약
- 점수: 14/20
- 환산 점수: 70점
- 합격선: 60점 이상
- 판정: 합격권
- 취약 영역: OUTER JOIN, HAVING, NULL 처리

## 틀린 문제

### 5번. OUTER JOIN
- 문제: ...
- 내 답: 2번. ...
- 정답: 4번. ...
- 영역: SQL 기본 및 활용
- 해설: ...
- 내가 틀린 이유: ...
- 다음 복습: 2026-07-04

## 반복 오답
- NULL 처리: 누적 오답 2회

## 오늘 복습할 개념
### OUTER JOIN
...

## 다음 액션
- 2026-07-04: 오늘 틀린 문제 재시험
```

## Database 2: Wrong Questions

One row per wrong attempt.

Recommended properties:

```text
Name                 title
Exam                 select
Session              relation -> Study Sessions
Domain               select
Concept              select or multi_select
Attempt Date         date
Question ID          rich_text
Position             number
My Answer            rich_text
Correct Answer       rich_text
Mistake Type         select
Review Status        select
Next Review          date
Local Session ID     rich_text
```

Recommended `Review Status` values:

```text
예정
복습 완료
재오답
해결
```

## Database 3: Concept Reviews

One row per concept that needs review.

Recommended properties:

```text
Name                 title
Exam                 select
Domain               select
Wrong Count          number
Last Wrong Date      date
Next Review          date
Status               select
Review Note          rich_text
```

Recommended `Status` values:

```text
대기
복습 예정
복습 완료
강화 필요
```

## Sync Rule

At session finish:

1. Create one `Study Sessions` page.
2. Append the Markdown report to the page body.
3. Create one `Wrong Questions` row for each wrong question.
4. Create or update `Concept Reviews` for repeated weak concepts.

Do not make Notion calculate scoring. Keep scoring in SQLite and export final values to Notion.

