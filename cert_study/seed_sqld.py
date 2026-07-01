from __future__ import annotations

import json
import sqlite3


EXAM = {
    "id": "SQLD",
    "name": "SQLD",
    "official_question_count": 50,
    "official_duration_minutes": 90,
    "pass_score": 60.0,
    "domain_min_score": 40.0,
    "notes": "SQLD official-like training profile: 50 questions, 90 minutes, 60+ pass line, 40% domain minimum reference.",
}

DOMAINS = [
    ("SQLD-D1", "SQLD", "데이터 모델링의 이해", 20.0, 10),
    ("SQLD-D2", "SQLD", "SQL 기본 및 활용", 80.0, 40),
]

CONCEPTS = [
    ("SQLD-C-ENTITY", "SQLD", "SQLD-D1", "엔터티", "엔터티는 업무에서 관리해야 하는 독립적인 대상이다. 식별 가능성과 인스턴스 집합 여부를 확인한다."),
    ("SQLD-C-ATTR", "SQLD", "SQLD-D1", "속성", "속성은 엔터티가 가지는 더 이상 분리하기 어려운 업무상 의미 단위다."),
    ("SQLD-C-REL", "SQLD", "SQLD-D1", "관계", "관계는 엔터티 인스턴스 사이의 업무적 연관성이다. 존재 관계와 행위 관계를 구분한다."),
    ("SQLD-C-NORM", "SQLD", "SQLD-D1", "정규화", "정규화는 이상 현상을 줄이기 위해 함수 종속에 따라 데이터를 분해하는 과정이다."),
    ("SQLD-C-ID", "SQLD", "SQLD-D1", "식별자", "식별자는 인스턴스를 유일하게 구분한다. 주식별자 조건은 유일성, 최소성, 불변성, 존재성이다."),
    ("SQLD-C-SELECT", "SQLD", "SQLD-D2", "SELECT 처리 순서", "SQL 논리 처리 순서는 FROM, WHERE, GROUP BY, HAVING, SELECT, ORDER BY로 판단한다."),
    ("SQLD-C-JOIN", "SQLD", "SQLD-D2", "JOIN", "JOIN은 테이블 사이의 관련 행을 결합한다. OUTER JOIN은 기준 테이블의 행 보존 여부가 핵심이다."),
    ("SQLD-C-NULL", "SQLD", "SQLD-D2", "NULL 처리", "NULL은 알 수 없거나 적용 불가한 값이다. 비교 연산은 UNKNOWN이 될 수 있고 IS NULL로 판단한다."),
    ("SQLD-C-GROUP", "SQLD", "SQLD-D2", "GROUP BY/HAVING", "WHERE는 그룹화 전 행 조건, HAVING은 그룹화 후 집계 조건이다."),
    ("SQLD-C-SUBQUERY", "SQLD", "SQLD-D2", "서브쿼리", "서브쿼리는 다른 SQL 내부에 포함된 질의다. 단일행, 다중행, 상관 서브쿼리를 구분한다."),
    ("SQLD-C-WINDOW", "SQLD", "SQLD-D2", "윈도우 함수", "윈도우 함수는 행 집합을 유지하면서 순위, 누계, 이동 집계 등을 계산한다."),
    ("SQLD-C-DML", "SQLD", "SQLD-D2", "DML", "DML은 데이터 조회와 변경을 담당한다. INSERT, UPDATE, DELETE, MERGE를 구분한다."),
    ("SQLD-C-DDL", "SQLD", "SQLD-D2", "DDL/DCL/TCL", "DDL은 객체 정의, DCL은 권한 제어, TCL은 트랜잭션 제어다."),
]


def q(
    idx: int,
    domain_id: str,
    concept_id: str,
    text: str,
    choices: list[str],
    answer: int,
    explanation: str,
    difficulty: str = "medium",
) -> dict[str, object]:
    return {
        "id": f"SQLD-Q{idx:03d}",
        "exam_id": "SQLD",
        "domain_id": domain_id,
        "concept_id": concept_id,
        "question_text": text,
        "choices_json": json.dumps(choices, ensure_ascii=False),
        "answer": answer,
        "explanation": explanation,
        "difficulty": difficulty,
        "source_type": "synthetic",
        "source_ref": "Original training question generated for concept practice; not copied from a commercial question bank.",
    }


QUESTIONS = [
    q(1, "SQLD-D1", "SQLD-C-ENTITY", "다음 중 엔터티의 설명으로 가장 적절한 것은?", ["업무에서 관리해야 하는 독립적인 대상이다.", "항상 물리 테이블과 1:1로 대응한다.", "하나의 속성만으로 구성되어야 한다.", "관계가 없으면 엔터티가 될 수 없다."], 1, "엔터티는 업무상 관리해야 하는 독립적인 대상이다. 물리 테이블 대응 여부는 설계 단계에 따라 달라질 수 있다.", "easy"),
    q(2, "SQLD-D1", "SQLD-C-ATTR", "속성에 대한 설명으로 옳은 것은?", ["인스턴스를 설명하는 업무상 의미 단위다.", "반드시 여러 값으로 구성되어야 한다.", "관계를 물리적으로 구현한 것이다.", "항상 후보 식별자가 된다."], 1, "속성은 엔터티 인스턴스를 설명하는 의미 단위다. 모든 속성이 식별자가 되지는 않는다.", "easy"),
    q(3, "SQLD-D1", "SQLD-C-REL", "관계에 대한 설명으로 가장 적절한 것은?", ["엔터티 인스턴스 사이의 업무적 연관성이다.", "속성의 물리 저장 위치다.", "정규화를 수행한 결과 테이블 수다.", "항상 1:1 관계만 표현한다."], 1, "관계는 엔터티 인스턴스 사이의 연관성을 의미한다. 1:1, 1:N, M:N 등 다양한 카디널리티가 가능하다.", "easy"),
    q(4, "SQLD-D1", "SQLD-C-NORM", "정규화를 수행하는 주된 목적은?", ["데이터 중복과 이상 현상을 줄이기 위해서", "항상 조회 성능을 최대로 높이기 위해서", "모든 테이블을 하나로 합치기 위해서", "NULL 값을 반드시 제거하기 위해서"], 1, "정규화는 삽입, 갱신, 삭제 이상을 줄이고 데이터 중복을 완화하는 논리 설계 과정이다.", "easy"),
    q(5, "SQLD-D1", "SQLD-C-ID", "주식별자의 조건으로 보기 어려운 것은?", ["유일성", "최소성", "불변성", "다중값 허용성"], 4, "주식별자는 인스턴스를 유일하게 식별해야 하며 최소성, 불변성, 존재성을 갖는 것이 바람직하다. 다중값 허용성은 조건이 아니다.", "easy"),
    q(6, "SQLD-D1", "SQLD-C-NORM", "제1정규형(1NF)에 대한 설명으로 옳은 것은?", ["속성 값이 원자값을 갖도록 한다.", "부분 함수 종속을 제거한다.", "이행 함수 종속을 제거한다.", "모든 조인을 제거한다."], 1, "1NF는 반복 그룹을 제거하고 각 속성이 원자값을 갖도록 하는 단계다.", "medium"),
    q(7, "SQLD-D1", "SQLD-C-NORM", "제2정규형(2NF)의 핵심은?", ["부분 함수 종속 제거", "이행 함수 종속 제거", "원자값 위반 허용", "모든 외래키 제거"], 1, "2NF는 기본키 전체에 완전 함수 종속되도록 부분 함수 종속을 제거한다.", "medium"),
    q(8, "SQLD-D1", "SQLD-C-NORM", "제3정규형(3NF)의 핵심은?", ["이행 함수 종속 제거", "부분 함수 종속 제거", "반복 속성 추가", "인덱스 제거"], 1, "3NF는 비식별자 속성이 다른 비식별자 속성에 종속되는 이행 함수 종속을 제거한다.", "medium"),
    q(9, "SQLD-D1", "SQLD-C-REL", "식별 관계에 대한 설명으로 옳은 것은?", ["부모 엔터티의 식별자가 자식 엔터티의 주식별자에 포함된다.", "부모 식별자는 자식 엔터티에 전혀 전달되지 않는다.", "항상 선택 관계만 표현한다.", "정규화와 무관하게 물리 인덱스만 의미한다."], 1, "식별 관계에서는 부모의 식별자가 자식의 주식별자 일부가 된다.", "medium"),
    q(10, "SQLD-D1", "SQLD-C-ID", "후보식별자에 대한 설명으로 옳은 것은?", ["인스턴스를 유일하게 식별할 수 있는 속성 또는 속성 집합이다.", "반드시 외래키로만 구성된다.", "업무적으로 변경이 잦아야 한다.", "NULL을 여러 개 허용해야 한다."], 1, "후보식별자는 유일성과 최소성을 만족해 인스턴스를 식별할 수 있는 후보 속성 집합이다.", "medium"),
    q(11, "SQLD-D2", "SQLD-C-SELECT", "SQL의 논리적 처리 순서로 가장 적절한 것은?", ["FROM -> WHERE -> GROUP BY -> HAVING -> SELECT -> ORDER BY", "SELECT -> FROM -> WHERE -> GROUP BY -> HAVING -> ORDER BY", "WHERE -> FROM -> SELECT -> GROUP BY -> HAVING -> ORDER BY", "ORDER BY -> SELECT -> FROM -> WHERE -> GROUP BY -> HAVING"], 1, "논리 처리 순서는 FROM에서 행 집합을 만들고 WHERE, GROUP BY, HAVING을 거친 뒤 SELECT와 ORDER BY가 수행된다.", "medium"),
    q(12, "SQLD-D2", "SQLD-C-GROUP", "집계 함수 결과에 조건을 적용할 때 주로 사용하는 절은?", ["WHERE", "HAVING", "FROM", "VALUES"], 2, "COUNT, SUM 같은 집계 결과에 대한 조건은 GROUP BY 이후 HAVING에서 판단한다.", "easy"),
    q(13, "SQLD-D2", "SQLD-C-JOIN", "LEFT OUTER JOIN의 설명으로 옳은 것은?", ["왼쪽 테이블의 모든 행을 보존하고 매칭되지 않는 오른쪽 컬럼은 NULL이 된다.", "오른쪽 테이블의 모든 행만 보존한다.", "양쪽에 모두 매칭되는 행만 남긴다.", "조인 조건 없이 항상 카테시안 곱을 만든다."], 1, "LEFT OUTER JOIN은 왼쪽 테이블을 기준으로 행을 보존한다. 오른쪽에 매칭이 없으면 오른쪽 컬럼은 NULL이다.", "easy"),
    q(14, "SQLD-D2", "SQLD-C-JOIN", "INNER JOIN의 결과로 가장 적절한 것은?", ["조인 조건을 만족하는 양쪽 매칭 행", "왼쪽 테이블의 모든 행", "오른쪽 테이블의 모든 행", "두 테이블의 모든 조합"], 1, "INNER JOIN은 조인 조건을 만족하는 매칭 행만 반환한다.", "easy"),
    q(15, "SQLD-D2", "SQLD-C-NULL", "NULL 비교에 대한 설명으로 옳은 것은?", ["NULL 여부는 IS NULL로 판단한다.", "NULL = NULL은 항상 TRUE다.", "NULL은 숫자 0과 같다.", "NULL은 빈 문자열과 항상 같다."], 1, "NULL은 알 수 없는 값이므로 일반 비교 연산 대신 IS NULL 또는 IS NOT NULL을 사용한다.", "easy"),
    q(16, "SQLD-D2", "SQLD-C-NULL", "NVL(col, 0)의 일반적인 의미로 옳은 것은?", ["col이 NULL이면 0으로 대체한다.", "col이 0이면 NULL로 바꾼다.", "col을 항상 문자열로 바꾼다.", "col을 기준으로 그룹화한다."], 1, "NVL은 첫 번째 인자가 NULL일 때 두 번째 인자를 반환하는 NULL 대체 함수다.", "easy"),
    q(17, "SQLD-D2", "SQLD-C-SUBQUERY", "단일행 서브쿼리에 사용할 수 있는 연산자로 가장 적절한 것은?", ["=", "IN만 가능", "EXISTS만 가능", "UNION만 가능"], 1, "단일행 서브쿼리는 하나의 값을 반환하므로 =, <, > 같은 단일행 비교 연산자를 사용할 수 있다.", "medium"),
    q(18, "SQLD-D2", "SQLD-C-SUBQUERY", "다중행 서브쿼리에 주로 사용하는 연산자는?", ["IN", "LIKE만 가능", "BETWEEN만 가능", "IS NULL만 가능"], 1, "다중행 서브쿼리는 여러 값을 반환할 수 있으므로 IN, ANY, ALL 등을 사용한다.", "medium"),
    q(19, "SQLD-D2", "SQLD-C-WINDOW", "ROW_NUMBER() 함수의 설명으로 옳은 것은?", ["동일 순위 없이 행마다 고유한 순번을 부여한다.", "동일 값에는 같은 순위를 부여하고 다음 순위는 건너뛴다.", "그룹별 합계를 하나의 행으로 축약한다.", "NULL 값을 모두 제거한다."], 1, "ROW_NUMBER는 정렬 기준에 따라 행마다 고유한 순번을 부여한다.", "medium"),
    q(20, "SQLD-D2", "SQLD-C-WINDOW", "RANK()와 DENSE_RANK()의 차이로 옳은 것은?", ["RANK는 동점 후 순위를 건너뛸 수 있고 DENSE_RANK는 건너뛰지 않는다.", "DENSE_RANK만 동점을 같은 순위로 본다.", "RANK는 집계 함수가 아니다.", "두 함수는 항상 완전히 같은 결과를 낸다."], 1, "RANK는 1,1,3처럼 순위를 건너뛸 수 있고 DENSE_RANK는 1,1,2처럼 건너뛰지 않는다.", "medium"),
    q(21, "SQLD-D2", "SQLD-C-DML", "UPDATE문에 대한 설명으로 옳은 것은?", ["기존 행의 컬럼 값을 변경한다.", "새 테이블 구조를 정의한다.", "사용자 권한을 부여한다.", "트랜잭션을 확정한다."], 1, "UPDATE는 기존 행의 값을 변경하는 DML이다.", "easy"),
    q(22, "SQLD-D2", "SQLD-C-DML", "DELETE문에 대한 설명으로 옳은 것은?", ["조건에 맞는 행을 삭제한다.", "테이블 정의를 삭제하지 않고 행을 대상으로 한다.", "항상 자동 COMMIT된다.", "컬럼 타입을 변경한다."], 1, "DELETE는 조건에 맞는 행을 삭제하는 DML이다. 트랜잭션 제어 가능 여부는 DBMS와 설정에 따라 달라진다.", "easy"),
    q(23, "SQLD-D2", "SQLD-C-DDL", "DDL에 해당하는 명령으로 가장 적절한 것은?", ["CREATE", "SELECT", "UPDATE", "COMMIT"], 1, "CREATE, ALTER, DROP, TRUNCATE 등은 데이터베이스 객체를 정의하거나 변경하는 DDL이다.", "easy"),
    q(24, "SQLD-D2", "SQLD-C-DDL", "TCL에 해당하는 명령으로 옳은 것은?", ["COMMIT", "GRANT", "CREATE", "SELECT"], 1, "COMMIT, ROLLBACK, SAVEPOINT는 트랜잭션을 제어하는 TCL이다.", "easy"),
    q(25, "SQLD-D2", "SQLD-C-DDL", "DCL에 해당하는 명령으로 옳은 것은?", ["GRANT", "INSERT", "GROUP BY", "ROLLBACK"], 1, "GRANT와 REVOKE는 권한을 제어하는 DCL이다.", "easy"),
    q(26, "SQLD-D2", "SQLD-C-GROUP", "GROUP BY에 대한 설명으로 옳은 것은?", ["지정한 컬럼 값이 같은 행들을 그룹으로 묶는다.", "항상 정렬 결과를 보장한다.", "WHERE보다 먼저 논리적으로 수행된다.", "집계 함수를 사용할 수 없게 한다."], 1, "GROUP BY는 지정한 기준으로 행을 그룹화한다. 정렬 보장은 ORDER BY가 담당한다.", "easy"),
    q(27, "SQLD-D2", "SQLD-C-GROUP", "SELECT 절에 그룹 기준이 아닌 일반 컬럼과 집계 함수를 함께 사용할 때 일반적으로 필요한 것은?", ["일반 컬럼을 GROUP BY에 포함한다.", "일반 컬럼을 ORDER BY에서 제거한다.", "집계 함수를 WHERE에 둔다.", "항상 DISTINCT를 붙인다."], 1, "집계 질의에서 집계되지 않은 일반 컬럼은 GROUP BY 기준에 포함되어야 한다.", "medium"),
    q(28, "SQLD-D2", "SQLD-C-NULL", "COUNT(*)와 COUNT(col)의 차이로 옳은 것은?", ["COUNT(*)는 행 수를 세고 COUNT(col)은 col의 NULL을 제외한다.", "COUNT(*)는 NULL을 제외하고 COUNT(col)은 모든 행을 센다.", "둘은 모든 상황에서 같다.", "COUNT(col)은 문자열만 셀 수 있다."], 1, "COUNT(*)는 행 자체를 세며, COUNT(col)은 해당 컬럼이 NULL이 아닌 행을 센다.", "medium"),
    q(29, "SQLD-D2", "SQLD-C-JOIN", "CROSS JOIN의 결과로 가장 적절한 것은?", ["두 테이블 행의 모든 조합", "조인 조건을 만족하는 행만", "왼쪽 테이블의 모든 행과 매칭 행", "중복 제거된 단일 컬럼"], 1, "CROSS JOIN은 카테시안 곱을 생성한다.", "medium"),
    q(30, "SQLD-D2", "SQLD-C-JOIN", "SELF JOIN에 대한 설명으로 옳은 것은?", ["같은 테이블을 서로 다른 별칭으로 조인한다.", "항상 외래키가 없어야만 가능하다.", "두 개 이상의 DBMS를 연결한다.", "집계 함수 전용 조인이다."], 1, "SELF JOIN은 하나의 테이블을 논리적으로 두 번 참조하기 위해 별칭을 사용한다.", "medium"),
    q(31, "SQLD-D2", "SQLD-C-SELECT", "ORDER BY에 대한 설명으로 옳은 것은?", ["최종 결과의 정렬 순서를 지정한다.", "그룹화 전 행을 필터링한다.", "집계 결과 조건을 지정한다.", "테이블 간 관계를 정의한다."], 1, "ORDER BY는 최종 결과 행의 표시 순서를 지정한다.", "easy"),
    q(32, "SQLD-D2", "SQLD-C-SELECT", "WHERE 절의 역할로 옳은 것은?", ["그룹화 전 개별 행을 필터링한다.", "그룹화 후 집계 결과만 필터링한다.", "결과 컬럼 별칭을 반드시 정의한다.", "최종 출력 순서를 보장한다."], 1, "WHERE는 GROUP BY 이전에 개별 행 단위 조건을 적용한다.", "easy"),
    q(33, "SQLD-D2", "SQLD-C-SUBQUERY", "상관 서브쿼리에 대한 설명으로 옳은 것은?", ["외부 쿼리의 컬럼을 참조할 수 있다.", "항상 한 번만 실행된다.", "FROM 절에는 사용할 수 없다.", "반드시 ORDER BY가 있어야 한다."], 1, "상관 서브쿼리는 외부 쿼리의 값을 참조하므로 외부 행에 따라 평가될 수 있다.", "hard"),
    q(34, "SQLD-D2", "SQLD-C-SUBQUERY", "EXISTS 연산자의 판단 기준으로 옳은 것은?", ["서브쿼리 결과 행의 존재 여부", "서브쿼리 첫 번째 컬럼의 최댓값", "서브쿼리 결과의 정렬 순서", "서브쿼리 SELECT 절의 별칭"], 1, "EXISTS는 서브쿼리가 하나 이상의 행을 반환하는지 여부를 판단한다.", "medium"),
    q(35, "SQLD-D2", "SQLD-C-DML", "INSERT문에 대한 설명으로 옳은 것은?", ["테이블에 새 행을 추가한다.", "기존 행을 삭제한다.", "객체 권한을 회수한다.", "트랜잭션을 되돌린다."], 1, "INSERT는 테이블에 새 행을 추가하는 DML이다.", "easy"),
    q(36, "SQLD-D2", "SQLD-C-DML", "MERGE문에 대한 설명으로 가장 적절한 것은?", ["조건에 따라 INSERT 또는 UPDATE 등을 수행할 수 있다.", "테이블 구조만 변경한다.", "권한만 부여한다.", "항상 SELECT만 수행한다."], 1, "MERGE는 대상과 원본의 매칭 여부에 따라 INSERT, UPDATE 등을 수행할 수 있다.", "medium"),
    q(37, "SQLD-D2", "SQLD-C-NULL", "COALESCE(a, b, c)의 일반적인 의미는?", ["NULL이 아닌 첫 번째 값을 반환한다.", "모든 값을 문자열로 연결한다.", "세 값의 평균을 계산한다.", "세 값이 모두 NULL일 때만 TRUE다."], 1, "COALESCE는 인자 목록에서 NULL이 아닌 첫 번째 값을 반환한다.", "medium"),
    q(38, "SQLD-D2", "SQLD-C-NULL", "NULL이 포함된 산술 연산 결과에 대한 일반적 설명으로 옳은 것은?", ["NULL과의 산술 연산 결과는 NULL이 될 수 있다.", "NULL은 항상 0으로 계산된다.", "NULL은 항상 1로 계산된다.", "NULL은 산술 연산에서 자동 제외된다."], 1, "NULL은 알 수 없는 값이므로 산술 연산 결과도 NULL이 될 수 있다.", "medium"),
    q(39, "SQLD-D2", "SQLD-C-JOIN", "FULL OUTER JOIN의 설명으로 옳은 것은?", ["양쪽 테이블의 미매칭 행까지 모두 보존한다.", "왼쪽 테이블의 매칭 행만 보존한다.", "오른쪽 테이블의 매칭 행만 보존한다.", "항상 중복을 제거한다."], 1, "FULL OUTER JOIN은 양쪽 테이블의 매칭 행과 미매칭 행을 모두 반환한다.", "medium"),
    q(40, "SQLD-D2", "SQLD-C-JOIN", "조인 조건을 누락했을 때 발생할 수 있는 결과로 가장 적절한 것은?", ["의도치 않은 카테시안 곱", "항상 0건 반환", "자동 외래키 생성", "자동 정규화 수행"], 1, "조인 조건이 없으면 모든 조합이 만들어져 의도치 않은 카테시안 곱이 될 수 있다.", "medium"),
    q(41, "SQLD-D2", "SQLD-C-WINDOW", "PARTITION BY의 역할로 옳은 것은?", ["윈도우 함수 계산 범위를 그룹처럼 나눈다.", "최종 결과를 반드시 정렬한다.", "테이블을 물리적으로 분할한다.", "NULL 값을 삭제한다."], 1, "PARTITION BY는 윈도우 함수가 계산될 행 집합을 논리적으로 나눈다.", "medium"),
    q(42, "SQLD-D2", "SQLD-C-WINDOW", "SUM(amount) OVER (PARTITION BY dept)의 결과로 옳은 것은?", ["각 행을 유지하면서 부서별 합계를 표시한다.", "부서별로 한 행만 남긴다.", "전체 테이블을 삭제한다.", "부서별 행을 무조건 정렬한다."], 1, "윈도우 집계는 GROUP BY와 달리 원래 행을 유지하면서 계산 결과를 붙일 수 있다.", "hard"),
    q(43, "SQLD-D2", "SQLD-C-SELECT", "DISTINCT의 역할로 옳은 것은?", ["조회 결과의 중복 행을 제거한다.", "NULL만 제거한다.", "항상 성능을 향상한다.", "테이블 구조를 변경한다."], 1, "DISTINCT는 SELECT 결과에서 중복된 행 조합을 제거한다.", "easy"),
    q(44, "SQLD-D2", "SQLD-C-SELECT", "LIKE 조건에서 '%'의 의미로 옳은 것은?", ["0개 이상의 임의 문자열", "정확히 한 글자", "숫자 하나", "NULL 값"], 1, "%는 0개 이상의 임의 문자열을 의미한다. 한 글자는 보통 _를 사용한다.", "easy"),
    q(45, "SQLD-D2", "SQLD-C-SELECT", "BETWEEN A AND B에 대한 일반적 설명으로 옳은 것은?", ["A와 B 경계값을 포함하는 범위 조건이다.", "A와 B를 제외한 범위 조건이다.", "문자열에는 사용할 수 없다.", "NULL만 조회한다."], 1, "BETWEEN은 일반적으로 양 끝 경계값을 포함한다.", "medium"),
    q(46, "SQLD-D2", "SQLD-C-DDL", "ALTER TABLE의 역할로 옳은 것은?", ["테이블 구조를 변경한다.", "행 데이터를 조회한다.", "트랜잭션을 취소한다.", "사용자 권한을 부여한다."], 1, "ALTER TABLE은 컬럼 추가, 변경, 삭제 등 테이블 구조 변경에 사용되는 DDL이다.", "easy"),
    q(47, "SQLD-D2", "SQLD-C-DDL", "ROLLBACK에 대한 설명으로 옳은 것은?", ["트랜잭션의 변경 내용을 취소한다.", "트랜잭션을 영구 반영한다.", "사용자 권한을 생성한다.", "테이블을 생성한다."], 1, "ROLLBACK은 아직 확정되지 않은 트랜잭션 변경을 취소한다.", "easy"),
    q(48, "SQLD-D2", "SQLD-C-DDL", "COMMIT에 대한 설명으로 옳은 것은?", ["트랜잭션 변경 내용을 확정한다.", "테이블을 삭제한다.", "권한을 회수한다.", "NULL 값을 대체한다."], 1, "COMMIT은 트랜잭션 변경 내용을 영구 반영한다.", "easy"),
    q(49, "SQLD-D2", "SQLD-C-GROUP", "HAVING COUNT(*) >= 2의 의미로 옳은 것은?", ["그룹별 행 수가 2 이상인 그룹만 남긴다.", "전체 테이블에서 두 번째 행만 남긴다.", "NULL이 2개 이상인 컬럼만 남긴다.", "두 개 이상의 테이블을 조인한다."], 1, "HAVING은 GROUP BY 이후 집계 결과 조건을 판단한다.", "medium"),
    q(50, "SQLD-D2", "SQLD-C-GROUP", "WHERE COUNT(*) > 1 이 일반적으로 부적절한 이유는?", ["WHERE는 그룹화 전 행 조건이라 집계 함수 조건을 둘 수 없기 때문이다.", "WHERE는 SELECT 뒤에만 쓸 수 있기 때문이다.", "COUNT는 문자열에만 사용할 수 있기 때문이다.", "GROUP BY가 없어도 항상 허용되기 때문이다."], 1, "집계 함수 결과에 대한 조건은 GROUP BY 이후 HAVING에서 처리한다.", "medium"),
]


def seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO exams
        (id, name, official_question_count, official_duration_minutes, pass_score, domain_min_score, notes)
        VALUES (:id, :name, :official_question_count, :official_duration_minutes, :pass_score, :domain_min_score, :notes)
        """,
        EXAM,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO domains (id, exam_id, name, official_weight, official_question_count) VALUES (?, ?, ?, ?, ?)",
        DOMAINS,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO concepts (id, exam_id, domain_id, name, review_note) VALUES (?, ?, ?, ?, ?)",
        CONCEPTS,
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO questions
        (id, exam_id, domain_id, concept_id, question_text, choices_json, answer, explanation, difficulty, source_type, source_ref)
        VALUES (:id, :exam_id, :domain_id, :concept_id, :question_text, :choices_json, :answer, :explanation, :difficulty, :source_type, :source_ref)
        """,
        QUESTIONS,
    )
    conn.commit()

