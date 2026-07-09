# 정처산기 실기 학습 서버

Flask + SQLite 기반. 로컬 실행도, 무료 배포도 가능합니다.

## 1. 로컬에서 먼저 테스트

```bash
pip install -r requirements.txt
python app.py
```

브라우저에서 http://localhost:5000 접속하면 바로 확인 가능합니다.
(같은 Wi-Fi의 폰에서 쓰려면 컴퓨터 IP로 접속: http://192.168.x.x:5000)

## 2. 셀룰러(어디서나)에서 쓰려면 → Render 웹서버 + Neon(무료 Postgres, 만료 없음)

### 준비물
- GitHub 계정 (무료)
- Render 계정 (https://render.com, 무료 가입)
- Neon 계정 (https://neon.tech, 무료 가입) — Render 무료 Postgres는 **30일 후 만료**되지만, Neon은 무료 인스턴스가 만료 없이 유지됩니다.

### 단계

1. **Neon에서 무료 데이터베이스 만들기**
   - https://neon.tech 가입 → New Project 생성
   - 프로젝트 생성하면 `Connection string`이 보임 (예: `postgres://user:pass@ep-xxx.neon.tech/dbname`)
   - 이 문자열을 복사해두기 (나중에 Render 환경변수로 씀)

2. **GitHub에 이 폴더 올리기**
   - GitHub에서 새 저장소(Repository) 생성 (예: `jeongcheogi-app`)
   - 이 폴더(`jeongcheogi_app`) 안의 파일들을 그 저장소에 업로드

3. **Render에서 New Web Service 생성**
   - Render 대시보드 → "New +" → "Web Service"
   - 방금 만든 GitHub 저장소 연결
   - 설정값:
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn app:app`
     - **Instance Type**: Free
   - **Environment 탭에서 환경변수 추가**:
     - Key: `DATABASE_URL`
     - Value: (1단계에서 복사한 Neon 연결 문자열 붙여넣기)
   - "Create Web Service" 클릭

4. **배포 완료 대기 (2~5분)**
   - 배포가 끝나면 `https://jeongcheogi-app.onrender.com` 같은 고정 URL 생성됨
   - 이 상태에서는 SQLite가 아니라 Neon의 Postgres에 데이터가 저장되므로,
     Render 서버가 재시작/재배포되어도 데이터가 안전하게 유지됩니다.

5. **폰에서 그 URL 접속**
   - 셀룰러 데이터로도 어디서든 접속 가능
   - 사파리/크롬에서 "홈 화면에 추가" 하면 앱처럼 아이콘 생성

### ⚠️ 남아있는 주의사항
- Render 무료 웹서비스 자체는 15분간 요청이 없으면 잠들어요(sleep).
  다시 접속하면 첫 로딩만 30초~1분 정도 걸릴 수 있어요(이후엔 빠름). → **이건 서버(연산)만 잠드는 것이고, Neon의 DB 데이터는 영향 없어요.**
- Neon 무료 플랜도 용량 제한(보통 0.5GB 안팎)이 있지만, 이 정도 학습 앱 데이터로는 충분합니다.


## 3. 문제 추가하는 방법 (세 가지)

### 방법 A: 코드로 직접
`app.py`의 `seed()` 함수 안 리스트(`code_problems`/`sql_problems`/`etc_problems`/`term_problems`)에
문제를 추가하고 재배포하면 됩니다. `seed()`는 서버가 켜질 때마다 실행되지만 이미 있는 (종류, 문제) 조합은
건너뛰므로, 계속 추가해도 기존 DB의 풀이 기록이 지워지지 않고 새로 추가한 문제만 반영됩니다.

### 방법 B: 복사-붙여넣기 프롬프트 + `/admin` 페이지로 실시간 추가 (추천 ⭐)
1. `문제추가_프롬프트.md` 파일을 열어보세요. 이 프롬프트를 새 Claude 대화에 복사해서
   PDF/텍스트 자료와 함께 보내면, Claude가 서버 API에 맞는 JSON을 만들어줍니다.
2. 배포된 주소 뒤에 `/admin`을 붙여 접속하세요 (예: `https://내서버주소.onrender.com/admin`).
   상단 홈 화면(`/`)의 ⚙️ 아이콘으로도 들어갈 수 있어요.
3. 관리자 키를 한 번 저장해두면(브라우저에만 저장됨) 이후엔 Claude가 만들어준 JSON을
   그대로 붙여넣고 "서버에 추가" 버튼만 누르면 됩니다. **curl이나 터미널이 필요 없어요.**
4. 같은 페이지에서 등록된 문제 목록 조회/삭제도 가능합니다.

**꼭 하세요**: Render 환경변수에 `ADMIN_KEY`를 임의의 비밀값으로 설정하세요
(기본값 `changeme`를 그대로 두면 누구나 문제를 추가/조작할 수 있어요).

### 방법 C: curl (터미널에 익숙하다면)
`문제추가_프롬프트.md` 끝부분에 안내된 대로 curl 명령어를 직접 실행해도 동일하게 동작합니다.

## 4. API 목록

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/problems?kind=code\|sql\|etc\|term&wrong=1` | 문제 목록 (템플릿은 즉석 생성 포함). `etc`는 OS/네트워크/테스트기법. `wrong=1`이면 마지막 시도가 오답이었던 문제만 |
| GET | `/api/regenerate/<template_key>` | 같은 유형, 다른 숫자로 재생성 |
| POST | `/api/attempt` | 문제 풀이 기록 저장 |
| POST | `/api/session` | 세션(퀴즈 1회) 결과 저장 |
| GET | `/api/dashboard` | 전체 통계 조회 (자주 틀리는 문제는 내용 미리보기 포함) |
| POST | `/api/admin/add_problems` | 문제 대량 추가 (admin_key 필요) |
| GET | `/api/admin/problems?admin_key=...&kind=...` | 등록된 문제 목록 조회 (admin_key 필요) |
| DELETE | `/api/admin/problems/<id>?admin_key=...` | 문제 1개 삭제 (admin_key 필요) |
| GET | `/admin` | 브라우저에서 문제 추가/조회/삭제하는 관리 페이지 |
