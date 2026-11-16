# 또풀어 (TTOPULO) Cloud v3 — 회원별 비공개 문제집

이 버전은 기존 **StudyMate Lite 로컬 앱과 별도 폴더**에서 사용하는 클라우드 버전입니다.
기존 로컬 SQLite 데이터베이스를 교체하거나 삭제하지 마세요.

## 제공하는 기능

- 이메일 회원가입/로그인, 로그아웃 (Supabase Auth)
- 사용자별 **비공개** 문제집·정답·학습 진행 기록 (Postgres Row Level Security)
- 텍스트형 PDF 문제 인식, 등록 전 문제·선지·정답·해설 미리보기
- 문제집별 학습 모드(정답/해설 처음부터 공개) → 실전 모드(선택 후 채점)
- 작은 번호 네모 5개씩, 아래쪽 이전/다음 문제 버튼
- 진행률: 현재 위치와 학습 완료 수 분리
- 문제집/문항 편집, 삭제, JSON 백업
- iPad Safari를 비롯한 브라우저에서 이용 가능 (웹 배포 완료 후)

**중요:** 지금 ZIP은 **배포 준비된 소스 코드**입니다. 웹주소나 실제 계정은 아직 생성되지 않았습니다. 아래 연결·배포 설정이 필요합니다.

## 1. Supabase 가입 및 데이터베이스 만들기

1. https://supabase.com 에 로그인하여 프로젝트를 생성합니다.
2. 프로젝트 **SQL Editor** → **New query**에서 `schema.sql` 파일 내용을 **전부 붙여넣고 Run**을 누릅니다.
3. **Project Settings → API Keys** 메뉴에서 `publishable` 키(또는 legacy `anon` 키)를 찾고, 프로젝트 URL도 확인합니다. 메뉴 이름은 업데이트에 따라 달라질 수 있습니다.
4. **Authentication → Providers → Email**에서 이메일 로그인이 활성화되어 있는지 확인합니다. 이메일 확인(confirmation)이 켜져 있으면 가입 후 수신 메일에서 인증을 해야 합니다.
5. **service_role / secret 키를 사용하지 마세요.** 이 앱은 공개 가능한 publishable/anon 키 + 사용자 로그인 토큰 + RLS로 접근을 제한하도록 설계되었습니다.

## 2. 로컬 컴퓨터에서 실행 테스트

1. `.streamlit/secrets.toml.example`을 복사해 `.streamlit/secrets.toml`이라는 새 파일을 만듭니다.
2. 안에 아래 값을 **실제 프로젝트 정보로 변경**합니다.

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_...또는_anon_key"
```

3. 이 폴더 주소창에 `cmd`를 입력해 명령 프롬프트를 엽니다.
4. 아래 명령어를 순서대로 실행합니다.

```bat
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

5. 브라우저에서 가입/로그인 → 퀴즈 PDF 업로드 → 학습 → 실전 순서로 확인합니다.

## 3. 노트북·아이패드에서 함께 이용할 수 있게 배포

1. https://github.com 에 로그인 후 새 저장소(repository)를 만듭니다.
2. **이 폴더의 코드 파일들**을 GitHub 저장소에 업로드합니다. 특히 `app.py`, `parser.py`, `cloud.py`, `schema.sql`, `requirements.txt`, `.streamlit/config.toml`이 필요합니다.
3. **절대 업로드하면 안 되는 것:** `.streamlit/secrets.toml`, 비밀번호, `studymate_lite.sqlite3`, 개인 PDF 파일. `.gitignore`에 제외 설정을 넣었습니다.
4. https://share.streamlit.io/ 에 GitHub로 로그인 → **Create app** → 방금 만든 저장소 선택 → 진입 파일 `app.py` 선택.
5. 배포 화면의 **Advanced settings / Secrets** 입력란에 아래와 같이 넣습니다.

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_...또는_anon_key"
```

6. **Deploy**를 누른 다음 표시된 `https://...streamlit.app` 주소를 노트북과 아이패드 Safari에서 엽니다.
7. 아이패드 Safari의 **공유 → 홈 화면에 추가**를 누르면 앱처럼 사용할 수 있습니다.
8. 친구들에게 같은 웹주소를 공유하면 각자가 **자기 계정**으로 가입해 자기 문제집을 따로 등록할 수 있습니다.

> 웹사이트 자체가 누구에게나 열려 있더라도, DB의 RLS 정책은 로그인한 사용자가 **자기 데이터만** 조회·수정하도록 제한합니다. 별도의 관리자가 모든 문제집을 열람하는 기능은 없습니다.

## 4. 기존 병리학 29문항 이전 방법

현재 로컬에 저장된 `studymate_lite.sqlite3`는 **자동으로 새 클라우드로 동기화되지 않습니다**.
가장 쉬운 방법은 **새 클라우드 앱에 기존 '병리학 기말고사 퀴즈.pdf'를 다시 업로드**하는 것입니다.
질문/선지/원문 정답/해설은 다시 추출됩니다. 다만 로컬 앱에서 저장했던 **학습 완료·채점 기록은 이전되지 않습니다.**

## 5. 제한·주의사항

- **텍스트형 PDF** 중심의 추출기입니다. 스캔 PDF, 복잡한 표/그림, 다른 편집 방식의 PDF는 일부 실패할 수 있습니다. 반드시 등록 전에 정답과 선지 확인이 필요합니다.
- 현재 자동 파서는 병리학 기말고사 퀴즈처럼 두 단 구성의 한국어 객관식 PDF를 기준으로 개발됐습니다. 모든 PDF를 완벽히 처리하진 못합니다.
- 실제 PDF 원본 파일은 저장하지 않고 추출한 문제 내용만 DB에 저장합니다.
- Streamlit 웹 세션의 새로고침 또는 브라우저 종료 후에는 다시 로그인해야 할 수 있습니다. 학습 기록은 클라우드에 유지됩니다.
- 이메일 주소 등 계정 정보는 Supabase Auth에서 관리하며, 문제 내용은 Supabase 데이터베이스에 저장됩니다. 민감한 개인 정보가 포함된 퀴즈 업로드는 피하세요.
- 앱 배포 후 부하·요금은 이용량과 각 서비스의 무료 정책에 따라 달라질 수 있습니다.
- 이 ZIP에 실제 Supabase 키, 로그인 계정, 공개 웹 주소는 포함되어 있지 않습니다.
