# -*- coding: utf-8 -*-
"""
정보처리산업기사 실기 학습 서버
Flask + SQLite (SQLAlchemy)

로컬 실행:  python app.py  ->  http://localhost:5000
배포(Render 등): gunicorn app:app
"""
import hmac
import os
import random
import re
from datetime import datetime

from flask import Flask, jsonify, request, render_template
from flask_sqlalchemy import SQLAlchemy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

_db_url = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'study.db')}")
# Neon/Render 등 일부 서비스는 'postgres://'로 URL을 주는데, SQLAlchemy는 'postgresql://'을 요구함
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}  # 유휴 연결 끊김 방지
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# ---------------------------------------------------------------
# 모델
# ---------------------------------------------------------------
class Problem(db.Model):
    __tablename__ = "problems"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), nullable=False)   # code | sql | term
    lang = db.Column(db.String(20))                    # Python/Java/C (code용) or None
    prompt = db.Column(db.Text, nullable=False)         # 코드/질문/용어
    answer = db.Column(db.Text, nullable=False)
    explain = db.Column(db.Text)
    template_key = db.Column(db.String(50))             # 템플릿 생성 문제면 템플릿 이름
    active = db.Column(db.Boolean, default=True)


class Attempt(db.Model):
    __tablename__ = "attempts"
    id = db.Column(db.Integer, primary_key=True)
    # 문자열: 템플릿 자동생성 문제는 "tpl-<key>-<n>" 같은 비숫자 id를 쓰므로 Integer면 Postgres에서 INSERT 실패함
    problem_id = db.Column(db.String(50))
    kind = db.Column(db.String(10))
    tag = db.Column(db.String(30))
    correct = db.Column(db.Boolean)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Session(db.Model):
    __tablename__ = "sessions"
    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(30))
    total = db.Column(db.Integer)
    correct = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------
# 템플릿 기반 코드 문제 자동 생성 (숫자만 바뀜)
# ---------------------------------------------------------------
def gen_factorial():
    n = random.randint(3, 7)
    result = 1
    for i in range(1, n + 1):
        result *= i
    code = f"""int result = 1;
for (int i = 1; i <= {n}; i++) result *= i;
printf("%d", result);"""
    return code, str(result), f"{n}! = {result}"


def gen_sum_even(): 
    n = random.randint(6, 14)
    total = sum(x for x in range(1, n + 1) if x % 2 == 0)
    code = f"""a = total = 0
while a < {n}:
    a += 1
    if a % 2 == 1:
        continue
    total += a
print(total)"""
    return code, str(total), f"1~{n} 중 짝수만 누적 합: {total}"


def gen_bit_and():
    a, b = random.randint(1, 15), random.randint(1, 15)
    r = a & b
    code = f"""a, b = {a}, {b}
c = a & b
print(c)"""
    return code, str(r), f"{a}({bin(a)}) & {b}({bin(b)}) = {r}"


def gen_array_ref_java():
    vals = random.sample(range(1, 20), 3)
    a, b, c = vals
    result = c  # arr2[1] = arr1[2] -> arr1도 변경
    code = f"""int[] arr1 = {{{a}, {b}, {c}}};
int[] arr2 = arr1;
arr2[1] = arr1[2];
System.out.print(arr1[1]);"""
    return code, str(result), "Java 배열은 참조형이라 arr2 변경이 arr1에도 반영됨"


TEMPLATES = {
    "factorial": gen_factorial,
    "sum_even": gen_sum_even,
    "bit_and": gen_bit_and,
    "array_ref_java": gen_array_ref_java,
}


def generate_from_template(key):
    fn = TEMPLATES.get(key)
    if not fn:
        return None
    code, answer, explain = fn()
    return {"code": code, "answer": answer, "explain": explain}


# ---------------------------------------------------------------
# 초기 데이터 시딩
# ---------------------------------------------------------------
def seed():
    """서버 기동 때마다 호출됨. 이미 있는 (kind, prompt)는 건너뛰고
    새로 추가된 항목만 넣는다 — 그래야 이 함수에 문제를 계속 추가해도
    기존 DB(풀이 기록 포함)를 지우지 않고 재배포/재시작만으로 반영된다."""
    existing = {(k, p) for k, p in db.session.query(Problem.kind, Problem.prompt).all()}
    added = 0

    def add(kind, prompt, answer="", explain="", lang=None, template_key=None):
        nonlocal added
        if (kind, prompt) in existing:
            return
        db.session.add(Problem(kind=kind, lang=lang, prompt=prompt, answer=answer,
                                explain=explain, template_key=template_key))
        existing.add((kind, prompt))
        added += 1

    code_problems = [
        ("Python", '''a = total = 0
while a < 10:
    a += 1
    if a % 2 == 1:
        continue
    total += a
print(total)''', "30", "홀수는 continue로 건너뛰고 짝수만 누적: 2+4+6+8+10=30"),
        ("Python", '''a, b = 2, 3
c = a & b
print(c)''', "2", "비트 AND: 2(10)&3(11)=10(2)"),
        ("Java", '''int a, b = 10;
a = 20 % 11 / 3 * 5 - b;
System.out.printf("%d", a);''', "5", "20%11=9, 9/3=3, 3*5=15, 15-10=5"),
        ("Python", '''def af(a, b): return a + b
def sf(a, b): return a - b
print(sf(af(4, 5), 6))''', "3", "af(4,5)=9, sf(9,6)=3"),
        ("Java", '''int a = 0, ss = 0;
while(true) {
  if(ss > 100) break;
  ++a; ss += a;
}
System.out.print(a + ss);''', "119", "a=14일때 ss=105(>100)로 break. 14+105=119"),
        ("C", '''char a[3][5] = { "KOR", "HUM", "RES" };
char* pa[] = { a[0], a[1], a[2] };
for (int i = 0; i < 3; i++)
  printf("%c", pa[i][i]);''', "KUS", "pa[0][0]='K', pa[1][1]='U', pa[2][2]='S'"),
        ("Java", '''int[] a = new int[8];
int i=0, n=11;
while(n>0){ a[i++]=n%2; n/=2; }
for(i=7;i>=0;i--) System.out.printf("%d", a[i]);''', "00001011", "11의 이진수는 1011, 8자리로 채우면 00001011"),
        ("C", '''int result = 1;
for (int i = 1; i <= 5; i++) result *= i;
printf("%d", result);''', "120", "5! = 120"),
        ("Java", '''int[] arr1 = {1, 2, 3};
int[] arr2 = arr1;
arr2[1] = arr1[2];
System.out.print(arr1[1]);''', "3", "Java 배열은 참조형. arr2와 arr1은 같은 배열을 가리켜 arr1[1]도 바뀜"),
        ("C", '''int k[] = {1, 2, 3};
int *p = k + 1;
printf("%d ", *p + *(p - 1));''', "3", "p는 k[1](=2)를 가리킴. *(p-1)=k[0](=1). 2+1=3"),
        ("Python", '''a = [1, 2, 3, 4, 5]
b = [x * 2 for x in a if x % 2 == 0]
print(b)''', "[4, 8]", "짝수(2, 4)만 골라 2배: [4, 8]"),
        ("Java", '''int[][] arr = {{1,2,3},{4,5,6}};
int sum = 0;
for(int i=0;i<2;i++)
  for(int j=0;j<3;j++)
    sum += arr[i][j];
System.out.print(sum);''', "21", "2차원 배열 전체 합: 1+2+3+4+5+6=21"),
        ("Python", '''def fact(n):
    if n <= 1:
        return 1
    return n * fact(n - 1)
print(fact(5))''', "120", "5*4*3*2*1=120 (재귀 호출)"),
        ("C", '''struct Point { int x, y; };
struct Point p = {3, 4};
p.x += p.y;
printf("%d", p.x);''', "7", "p.x = 3 + p.y(4) = 7"),
        ("Java", '''int sum = 0;
for(int i=1; i<=10; i++){
  if(i % 3 == 0) continue;
  if(i > 8) break;
  sum += i;
}
System.out.print(sum);''', "27", "3의 배수(3,6,9)는 건너뛰고, i=10에서 8보다 커 종료. 1+2+4+5+7+8=27"),
        ("Python", '''d = {"a": 1, "b": 2, "c": 3}
total = 0
for k, v in d.items():
    if v % 2 == 0:
        total += v
print(total)''', "2", "값이 짝수인 것은 b(2)뿐이라 total=2"),
    ]
    for lang, code, answer, explain in code_problems:
        add("code", code, answer, explain, lang=lang)

    # 템플릿 기반 문제 (실제 저장은 안 하고 /api/problems 에서 즉석 생성)
    for key in TEMPLATES:
        add("code", f"[자동생성] {key}", "", "", lang="템플릿", template_key=key)

    sql_problems = [
        ("이름(NAME)이 '김'으로 시작하는 학생을 조회하는 WHERE절을 작성하세요.",
         "WHERE NAME LIKE '김%'", "특정 문자로 시작 → LIKE '문자%'"),
        ("부서별(DEPT) 급여(SALARY) 합계가 3000 이상인 부서만 조회하는 조건절을 작성하세요. (GROUP BY DEPT 사용)",
         "HAVING SUM(SALARY) >= 3000", "그룹화 후 조건은 HAVING, 그룹화 전 조건은 WHERE"),
        ("EMP 테이블에 COMMENT 컬럼을 VARCHAR(100)으로 추가하는 명령문을 작성하세요.",
         "ALTER TABLE EMP ADD COMMENT VARCHAR(100);", "컬럼 추가는 ALTER TABLE ... ADD"),
        ("두 테이블 A, B에서 A.ID = B.ID 조건으로 INNER JOIN 하는 쿼리를 작성하세요. (컬럼은 *로)",
         "SELECT * FROM A INNER JOIN B ON A.ID = B.ID;", "INNER JOIN ... ON 조건"),
        ("EXAM_B 테이블에서 EXAM_A 테이블의 모든 점수보다 큰 점수를 조회할 때 쓰는 서브쿼리 키워드는?",
         "ALL", "모든 서브쿼리 값보다 커야 하면 > ALL"),
        ("컬럼명 DEPT의 중복을 제외한 값의 개수를 세는 표현을 작성하세요.",
         "COUNT(DISTINCT DEPT)", "중복 제외 개수는 COUNT(DISTINCT 컬럼명)"),
        ("EMP 테이블의 SAL 컬럼에 IDX_SAL이라는 인덱스를 생성하는 명령문을 작성하세요.",
         "CREATE INDEX IDX_SAL ON EMP(SAL);", "인덱스 생성: CREATE INDEX 이름 ON 테이블(컬럼)"),
        ("트랜잭션 작업을 취소하는 명령어는?",
         "ROLLBACK", "완료는 COMMIT, 취소는 ROLLBACK"),
        ("EMP 테이블에서 부서번호(DEPTNO)가 10인 사원의 이름과 급여를 조회하는 쿼리를 작성하세요.",
         "SELECT NAME, SALARY FROM EMP WHERE DEPTNO = 10;", "조건은 WHERE, 조회할 컬럼만 SELECT 뒤에 나열"),
        ("학생(STUDENT) 테이블을 나이(AGE)가 많은 순으로 정렬해서 조회하는 쿼리를 작성하세요.",
         "SELECT * FROM STUDENT ORDER BY AGE DESC;", "내림차순 정렬은 ORDER BY 컬럼 DESC"),
        ("EMP 테이블 자체를 완전히 삭제(구조까지 제거)하는 명령문을 작성하세요.",
         "DROP TABLE EMP;", "DROP은 테이블 구조까지 삭제. DELETE/TRUNCATE는 데이터만 삭제"),
        ("EMP 테이블에서 중복을 제거한 부서번호(DEPTNO) 목록을 조회하는 쿼리를 작성하세요.",
         "SELECT DISTINCT DEPTNO FROM EMP;", "중복 제거 조회는 SELECT DISTINCT"),
        ("두 테이블 A, B를 합집합으로 합치되 중복은 제거해서 조회하는 집합 연산자를 작성하세요.",
         "UNION", "중복 제거 합집합은 UNION, 중복 허용은 UNION ALL"),
        ("EMP 테이블에서 급여(SALARY)가 NULL인 사원을 조회하는 조건절을 작성하세요.",
         "WHERE SALARY IS NULL", "NULL 비교는 = 이 아니라 IS NULL 사용"),
        ("사용자 KIM에게 EMP 테이블의 SELECT 권한을 부여하는 명령문을 작성하세요.",
         "GRANT SELECT ON EMP TO KIM;", "권한 부여는 GRANT ... TO, 회수는 REVOKE ... FROM"),
        ("EMP 테이블에서 이름(NAME) 컬럼 값을 대문자로 변환해서 조회하는 쿼리를 작성하세요.",
         "SELECT UPPER(NAME) FROM EMP;", "대문자 변환 함수는 UPPER(), 소문자는 LOWER()"),
        ("두 테이블 A, B의 모든 튜플 조합(순서쌍)을 조건 없이 조회하는 조인을 작성하세요.",
         "SELECT * FROM A CROSS JOIN B;", "모든 튜플 조합 반환은 CROSS JOIN(교차 조인)"),
        ("두 테이블 A, B를 동등 조인하되, 조인에 참여한 중복 속성을 자동으로 제거해서 조회하는 조인을 작성하세요.",
         "SELECT * FROM A NATURAL JOIN B;", "동등조인에서 중복 속성 제거는 NATURAL JOIN"),
        ("학생 테이블에서 점수(SCORE)가 90 이상 100 이하인 학생을 조회하는 조건절을 작성하세요.",
         "WHERE SCORE BETWEEN 90 AND 100", "범위 조회는 BETWEEN 값1 AND 값2"),
        ("EMP 테이블에서 부서번호(DEPTNO)가 10, 20, 30 중 하나인 사원을 조회하는 조건절을 작성하세요.",
         "WHERE DEPTNO IN (10, 20, 30)", "여러 값 중 하나와 일치하면 IN (값1, 값2, ...)"),
        ("EXAM_B 테이블에서 EXAM_A 테이블의 점수 중 어느 하나보다 크면 조회되는 서브쿼리 키워드를 작성하세요. (ALL 제외)",
         "ANY", "서브쿼리 값 중 하나보다 크면 반환은 ANY(=SOME), 모든 값보다 커야 하면 ALL"),
        ("서브쿼리 결과 중 일치하는 튜플이 하나라도 존재하는지 여부만 확인해서 조회하는 서브쿼리 키워드를 작성하세요.",
         "EXISTS", "서브쿼리 값 중 하나라도 일치하는 튜플이 있으면 반환"),
        ("두 테이블 A, B를 합치되 중복도 포함해서 모두 조회하는 쿼리를 작성하세요.",
         "SELECT * FROM A UNION ALL SELECT * FROM B;", "중복 포함 합집합은 UNION ALL, 중복 제거는 UNION"),
        ("두 테이블 A, B의 교집합을 조회하는 쿼리를 작성하세요.",
         "SELECT * FROM A INTERSECT SELECT * FROM B;", "교집합은 INTERSECT"),
        ("테이블 A에서 테이블 B에 있는 튜플을 제외하고 조회하는 쿼리를 작성하세요. (Oracle에서는 다른 이름 사용)",
         "SELECT * FROM A EXCEPT SELECT * FROM B;", "차집합은 EXCEPT (Oracle에서는 MINUS)"),
        ("학생 테이블에서 학년이 3인 학생만 보여주는 V_3학년이라는 뷰를 생성하는 명령문을 작성하세요.",
         "CREATE VIEW V_3학년 AS SELECT * FROM 학생 WHERE 학년 = 3;", "뷰 생성은 CREATE VIEW 뷰이름 AS SELECT ..."),
    ]
    for q, a, e in sql_problems:
        add("sql", q, a, e)

    term_problems = [
        ("DDL", "CREATE, ALTER, DROP 등 테이블/스키마 구조를 정의하는 언어"),
        ("DML", "SELECT, INSERT, UPDATE, DELETE 등 데이터를 조작하는 언어"),
        ("DCL", "GRANT, REVOKE, COMMIT, ROLLBACK 등 권한/트랜잭션을 제어하는 언어"),
        ("CRUD", "Create, Read, Update, Delete — 데이터베이스 기본 4대 연산"),
        ("응집도", "모듈 내부 요소들이 얼마나 밀접하게 관련되어 있는지의 정도 (높을수록 좋음)"),
        ("결합도", "모듈과 모듈 간의 상호 의존 정도 (낮을수록 좋음)"),
        ("서브넷 마스크", "IP주소를 네트워크 주소와 호스트 주소로 구분하는 값"),
        ("OSI 7계층", "물리-데이터링크-네트워크-전송-세션-표현-응용 계층으로 구성된 통신 표준 모델"),
        ("형상관리", "소스코드/문서 등의 변경 이력을 체계적으로 관리하는 활동 (예: Git)"),
        ("쉘 스크립트", "유닉스/리눅스 명령어를 순차적으로 실행하도록 작성한 스크립트 파일"),
        ("정규화", "데이터 중복을 최소화하고 무결성을 유지하도록 테이블을 분해하는 과정"),
        ("이상현상(Anomaly)", "정규화되지 않은 테이블에서 삽입/삭제/갱신 시 발생하는 데이터 불일치 문제"),
        ("인덱스", "테이블 검색 속도를 높이기 위해 만드는 자료구조 (단, 삽입/삭제 시 오버헤드 발생)"),
        ("TCP", "연결형이며 신뢰성 있는 데이터 전송을 보장하는 전송계층 프로토콜"),
        ("UDP", "비연결형이며 신뢰성보다 속도를 우선하는 전송계층 프로토콜"),
        ("프로세스", "실행 중인 프로그램의 인스턴스로, 운영체제로부터 자원을 할당받는 작업의 단위"),
        ("스레드", "프로세스 내에서 실행되는 흐름의 단위로, 자원을 공유해 프로세스보다 가벼움"),
        ("데드락(교착상태)", "두 개 이상의 프로세스가 서로 자원을 기다리며 무한 대기에 빠지는 상태"),
        ("블랙박스 테스트", "내부 구조를 모르는 상태에서 입력과 출력만으로 기능을 검증하는 테스트 기법"),
        ("화이트박스 테스트", "내부 로직/구조를 알고 코드의 실행 경로를 검증하는 테스트 기법"),
        ("후보키", "튜플을 유일하게 식별할 수 있는 최소한의 속성 집합 (유일성 + 최소성 모두 만족)"),
        ("슈퍼키", "튜플을 유일하게 식별할 수 있는 속성 집합이지만 최소성은 만족하지 않는 키"),
        ("외래키", "다른 릴레이션의 기본키를 참조하는 속성 또는 속성들의 집합"),
        ("제1정규형", "테이블의 모든 속성 값이 원자값(더 이상 분해되지 않는 값)으로만 구성된 상태"),
        ("제3정규형", "제2정규형을 만족하면서, 이행적 함수 종속(A→B→C)을 제거한 상태"),
        ("ACID", "트랜잭션이 가져야 할 4가지 성질: 원자성(Atomicity), 일관성(Consistency), 고립성(Isolation), 지속성(Durability)"),
        ("RIP", "홉(hop) 수를 기준으로 최단 경로를 계산하는 거리 벡터 기반의 내부 라우팅 프로토콜"),
        ("OSPF", "링크 상태(다익스트라 알고리즘)를 기반으로 경로를 계산하는 대규모 네트워크용 내부 라우팅 프로토콜"),
        ("ARP", "IP 주소(논리 주소)를 MAC 주소(물리 주소)로 변환하는 프로토콜"),
        ("NAT", "사설 IP 주소를 공인 IP 주소로 변환해주는 기술로, IPv4 주소 부족 문제를 완화"),
    ]
    for term, definition in term_problems:
        add("term", term, definition, "")

    # OS / 네트워크 / 테스트기법 — 계산형·서술형 문제 (SQL과 같은 질문+답 형식, kind="etc")
    etc_problems = [
        ("FCFS 스케줄링에서 실행시간이 5, 3, 8인 프로세스 P1, P2, P3가 도착순서대로 처리될 때, 세 프로세스의 대기시간 합계를 구하세요.",
         "13", "P1 대기0, P2는 P1시간(5)만큼, P3는 P1+P2(8)만큼 대기: 0+5+8=13"),
        ("라운드로빈 스케줄링에서 타임퀀텀이 4이고 프로세스 P1(6), P2(3), P3(5)가 순서대로 도착했을 때, P2가 완료되는 시각을 구하세요.",
         "7", "P1이 먼저 4만큼 실행(남은2)하고 다음 P2가 남은 3을 모두 실행해 t=4+3=7에 종료"),
        ("페이지 참조열 1,2,3,1,2,4,1,2,3,4 에 대해 프레임이 3개일 때 FIFO 알고리즘의 페이지 부재(page fault) 횟수를 구하세요.",
         "8", "1,2,3 적재 후 4번째 참조부터 계속 교체가 발생. 히트는 4,5번째 참조 두 번뿐이라 10-2=8회 부재"),
        ("페이지 참조열 1,2,3,4,1,2,5,1,2,3 에 대해 프레임이 4개일 때 LRU 알고리즘의 페이지 부재 횟수를 구하세요.",
         "6", "가장 오래 사용 안 된 페이지부터 교체. 처음 4번 적재 후 5, 3에서만 추가 교체가 발생해 총 6회"),
        ("192.168.1.0/26 대역에서 사용 가능한 호스트 수를 구하세요.",
         "62", "/26은 호스트 비트 6개(2^6=64), 네트워크·브로드캐스트 주소 2개를 빼면 62개"),
        ("클래스 C 사설 IP 대역의 기본 서브넷마스크를 작성하세요.",
         "255.255.255.0", "클래스 C는 기본적으로 앞 24비트가 네트워크 주소"),
        ("TCP와 UDP의 가장 큰 차이점을 한 문장으로 설명하세요.",
         "TCP는 연결형이며 신뢰성 있는 전송을 보장하지만, UDP는 비연결형이며 속도가 빠른 대신 신뢰성을 보장하지 않는다.", ""),
        ("웹 서버의 기본 포트 번호(HTTP)와 보안 웹(HTTPS)의 포트 번호를 각각 작성하세요.",
         "80, 443", "HTTP는 80번, HTTPS는 443번 포트를 기본으로 사용"),
        ("화이트박스 테스트 기법 중, 프로그램 내 모든 분기를 한 번 이상 실행하도록 테스트 케이스를 만드는 커버리지 기준은?",
         "분기 커버리지(Branch Coverage)", "모든 문장을 한 번씩 실행하면 구문 커버리지, 모든 분기를 실행하면 분기 커버리지"),
        ("블랙박스 테스트 기법 중, 입력 값의 범위를 유효값과 무효값 그룹으로 나누어 대표값만 테스트하는 기법은?",
         "동등분할(Equivalence Partitioning)", "경계값 분석과 함께 대표적인 블랙박스 테스트 기법"),
        ("소스코드/문서의 버전을 관리하며 협업 시 변경 이력을 추적하는 활동과, 대표 도구 하나를 작성하세요.",
         "형상관리, Git", ""),
        ("쉘 스크립트에서 현재 디렉터리 내 모든 .txt 파일 목록을 출력하는 명령어를 작성하세요.",
         "ls *.txt", ""),
        ("리눅스에서 파일 소유자에게 읽기/쓰기/실행 권한을, 그룹과 다른 사용자에게는 읽기 권한만 부여하는 chmod 명령을 작성하세요.",
         "chmod 744 파일명", "rwx=7, r--=4이므로 744"),
        ("OSI 7계층 중 IP 주소를 이용한 경로설정(라우팅)을 담당하는 계층은?",
         "네트워크 계층", ""),
        ("Git에서 원격 저장소의 변경사항을 로컬로 가져오면서 자동으로 병합까지 수행하는 명령어는?",
         "git pull", "git fetch는 가져오기만, git pull은 fetch+merge"),
        ("구현된 UI가 사용하기 편한지 검증하기 위해 실제 사용자가 시스템을 사용하는 과정을 관찰하고 문제점을 도출하는 테스트를 무엇이라 하는가?",
         "사용성 테스트(Usability Test)", "계획-수행-분석-결과보고 순서로 진행"),
        ("정상적으로 작동하는 소프트웨어 빌드를 위해 형상관리 서버에 저장된 소스코드를 로컬 작업 공간으로 받아오는 작업을 무엇이라 하는가?",
         "체크아웃(Checkout)", "빌드 전에는 반드시 형상관리 서버에서 최신 소스코드를 체크아웃해야 함"),
        ("애플리케이션 배포 후 문제가 발생했을 때, 적용한 내용을 이전 상태로 되돌리는 작업을 무엇이라 하는가?",
         "롤백(Rollback)", "배포 결과에 문제가 있으면 이전 정상 상태로 복원"),
        ("테스트 케이스를 구성하는 요소 중, 테스트 수행 시 실제로 입력하는 값을 무엇이라 하는가?",
         "테스트 데이터", "테스트 케이스는 식별자ID, 테스트항목, 테스트조건, 테스트데이터, 예상결과로 구성됨"),
        ("여러 모듈을 하나의 시스템으로 결합할 때, 상위 모듈에서 하위 모듈 방향으로 통합하며 테스트하는 방식은?",
         "하향식 통합 테스트", "하향식은 미완성 하위 모듈 대신 테스트 스텁(Stub)을 사용"),
        ("상향식 통합 테스트에서, 아직 테스트되지 않은 상위 모듈 역할을 임시로 대신하여 하위 모듈을 호출하는 모듈을 무엇이라 하는가?",
         "테스트 드라이버(Test Driver)", "상향식은 드라이버, 하향식은 스텁을 사용"),
        ("리눅스에서 현재 실행 중인 프로세스 목록을 조회하는 명령어를 작성하세요.",
         "ps", "프로세스 종료는 kill, 목록 조회는 ps"),
        ("리눅스에서 파일 내용 중 특정 문자열 패턴을 검색하는 명령어를 작성하세요.",
         "grep", "grep [패턴] [파일명] 형태로 사용"),
    ]
    for q, a, e in etc_problems:
        add("etc", q, a, e)

    if added:
        db.session.commit()


# ---------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------
def _check_admin_key(candidate):
    """타이밍 공격 방지를 위해 상수 시간 비교 사용"""
    admin_key = os.environ.get("ADMIN_KEY", "changeme")
    return hmac.compare_digest(str(candidate or ""), admin_key)


@app.route("/api/admin/add_problems", methods=["POST"])
def api_admin_add_problems():
    """
    비밀키 + 문제 목록(JSON)을 받아 DB에 대량 추가.
    비밀키는 환경변수 ADMIN_KEY로 설정 (미설정시 기본값 'changeme').
    요청 형식은 프롬프트 템플릿 참고.
    """
    data = request.get_json(force=True)
    if not _check_admin_key(data.get("admin_key")):
        return jsonify({"error": "unauthorized"}), 401

    items = data.get("problems", [])
    added = 0
    skipped = 0
    for item in items:
        kind = item.get("kind")
        if kind not in ("code", "sql", "term", "etc"):
            skipped += 1
            continue
        prompt = (item.get("prompt") or "").strip()
        answer = (item.get("answer") or "").strip()
        if not prompt or not answer:
            skipped += 1
            continue
        # 중복 방지: 같은 kind + 같은 prompt면 건너뜀
        exists = Problem.query.filter_by(kind=kind, prompt=prompt).first()
        if exists:
            skipped += 1
            continue
        db.session.add(Problem(
            kind=kind,
            lang=item.get("lang"),
            prompt=prompt,
            answer=answer,
            explain=item.get("explain", ""),
        ))
        added += 1
    db.session.commit()
    return jsonify({"added": added, "skipped": skipped, "total_now": Problem.query.count()})


@app.route("/api/admin/problems")
def api_admin_list_problems():
    """관리 화면용: 등록된 문제 목록 조회 (템플릿 자동생성 정의는 제외)"""
    if not _check_admin_key(request.args.get("admin_key")):
        return jsonify({"error": "unauthorized"}), 401
    kind = request.args.get("kind")
    q = Problem.query.filter(Problem.template_key.is_(None))
    if kind in ("code", "sql", "term", "etc"):
        q = q.filter_by(kind=kind)
    problems = q.order_by(Problem.id.desc()).all()
    return jsonify([
        {"id": p.id, "kind": p.kind, "lang": p.lang, "prompt": p.prompt,
         "answer": p.answer, "explain": p.explain, "active": p.active}
        for p in problems
    ])


@app.route("/api/admin/problems/<int:problem_id>", methods=["DELETE"])
def api_admin_delete_problem(problem_id):
    """관리 화면용: 문제 1개 삭제"""
    if not _check_admin_key(request.args.get("admin_key")):
        return jsonify({"error": "unauthorized"}), 401
    p = Problem.query.get(problem_id)
    if not p:
        return jsonify({"error": "not found"}), 404
    db.session.delete(p)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/problems")
def api_problems():
    """kind=code|sql|term, wrong=1 이면 최근 오답(마지막 시도가 틀린) 문제들만"""
    kind = request.args.get("kind", "code")
    wrong_only = request.args.get("wrong") == "1"
    q = Problem.query.filter_by(kind=kind, active=True).filter(Problem.template_key.is_(None))
    problems = q.all()

    if wrong_only:
        # 문제별 가장 최근 시도가 오답인 것만 남긴다
        attempts = (Attempt.query.filter_by(kind=kind)
                    .order_by(Attempt.created_at.desc()).all())
        latest_correct = {}
        for a in attempts:
            latest_correct.setdefault(a.problem_id, a.correct)
        problems = [p for p in problems if latest_correct.get(str(p.id)) is False]

    result = []
    for p in problems:
        result.append({
            "id": p.id, "kind": p.kind, "lang": p.lang,
            "prompt": p.prompt, "answer": p.answer, "explain": p.explain,
        })
    # 템플릿 문제는 즉석 생성해서 몇 개 섞어준다 (code 한정, 오답 복습 모드에서는 제외)
    if kind == "code" and not wrong_only:
        templ_defs = Problem.query.filter_by(kind="code").filter(Problem.template_key.isnot(None)).all()
        for t in templ_defs:
            gen = generate_from_template(t.template_key)
            if gen:
                result.append({
                    "id": f"tpl-{t.template_key}-{random.randint(1000,9999)}",
                    "kind": "code", "lang": "자동생성",
                    "prompt": gen["code"], "answer": gen["answer"], "explain": gen["explain"],
                })
    random.shuffle(result)
    return jsonify(result)


@app.route("/api/regenerate/<template_key>")
def api_regenerate(template_key):
    """같은 유형, 다른 숫자로 새 문제 하나 즉석 생성"""
    gen = generate_from_template(template_key)
    if not gen:
        return jsonify({"error": "unknown template"}), 404
    return jsonify({
        "id": f"tpl-{template_key}-{random.randint(1000,9999)}",
        "kind": "code", "lang": "자동생성",
        "prompt": gen["code"], "answer": gen["answer"], "explain": gen["explain"],
    })


@app.route("/api/attempt", methods=["POST"])
def api_attempt():
    data = request.get_json(force=True)
    a = Attempt(
        problem_id=str(data.get("id")),
        kind=data.get("kind"),
        tag=data.get("tag"),
        correct=bool(data.get("correct")),
    )
    db.session.add(a)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/session", methods=["POST"])
def api_session():
    data = request.get_json(force=True)
    s = Session(mode=data.get("mode"), total=data.get("total"), correct=data.get("correct"))
    db.session.add(s)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/dashboard")
def api_dashboard():
    attempts = Attempt.query.order_by(Attempt.created_at.desc()).limit(500).all()
    sessions = Session.query.order_by(Session.created_at.desc()).limit(20).all()

    by_tag = {}
    for a in attempts:
        tag = a.tag or "기타"
        by_tag.setdefault(tag, {"c": 0, "t": 0})
        by_tag[tag]["t"] += 1
        if a.correct:
            by_tag[tag]["c"] += 1

    fail_count = {}
    for a in attempts:
        if not a.correct:
            fail_count[str(a.problem_id)] = fail_count.get(str(a.problem_id), 0) + 1
    top_fail_ids = sorted(fail_count.items(), key=lambda x: -x[1])[:5]

    def preview(pid):
        # 템플릿 자동생성 문제(tpl-...)는 저장돼있지 않아 미리보기를 만들 수 없음
        if not pid.isdigit():
            return "자동생성 문제"
        p = Problem.query.get(int(pid))
        if not p:
            return "(삭제된 문제)"
        text = p.prompt.strip().splitlines()[0]
        return text[:30] + ("…" if len(text) > 30 else "")

    top_fail = [{"id": pid, "count": cnt, "preview": preview(pid)} for pid, cnt in top_fail_ids]

    return jsonify({
        "total": len(attempts),
        "correct": sum(1 for a in attempts if a.correct),
        "by_tag": by_tag,
        "sessions": [
            {"mode": s.mode, "total": s.total, "correct": s.correct,
             "acc": round(s.correct / s.total * 100, 1) if s.total else 0,
             "time": s.created_at.isoformat()}
            for s in reversed(sessions)
        ],
        "top_fail": top_fail,
    })


def migrate():
    """create_all()은 새 테이블만 만들고 기존 컬럼 타입은 안 바꿔주므로,
    이미 Integer로 만들어져 있던 attempts.problem_id를 Postgres에서는 varchar로 넓혀준다.
    (SQLite는 타입 강제가 느슨해서 이미 문자열 저장이 가능하므로 별도 처리 불필요)"""
    if not _db_url.startswith("postgresql://"):
        return
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text(
                "ALTER TABLE attempts ALTER COLUMN problem_id TYPE VARCHAR(50) USING problem_id::VARCHAR(50)"
            ))
            conn.commit()
    except Exception as e:
        print(f"[migrate] problem_id 컬럼 마이그레이션 스킵: {e}")


with app.app_context():
    db.create_all()
    migrate()
    seed()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
