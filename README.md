# 단어시험지 생성기 (Vocab Test Generator)

단어책 PDF를 업로드하면 유닛별로 단어시험지 PDF를 만들어주는 웹앱입니다.

## 로컬 실행

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn main:app --reload
```

`http://localhost:8000` 접속.

## GitHub에 올리기

이 폴더 전체를 새 GitHub 레포로 push하면 됩니다.

```bash
cd vocab-test-app
git init
git add .
git commit -m "Initial commit: 단어시험지 생성기"
git branch -M main
git remote add origin https://github.com/<본인계정>/<레포이름>.git
git push -u origin main
```

## Render에 배포하기

1. Render 대시보드 → **New +** → **Web Service**
2. 방금 push한 GitHub 레포 선택
3. Environment: **Docker** 선택 (Dockerfile을 자동으로 인식합니다)
4. Instance Type: Free (또는 원하는 플랜)
5. **Environment Variables**에 다음 추가:
   - Key: `ANTHROPIC_API_KEY`
   - Value: 본인의 Anthropic API 키 (https://console.anthropic.com 에서 발급)
6. **Create Web Service** 클릭

빌드가 끝나면 `https://<서비스이름>.onrender.com` 주소로 다른 선생님들도 접속해서 바로 사용할 수 있습니다.

## 왜 Dockerfile을 쓰나요?

이 앱은 PDF 생성에 WeasyPrint를 쓰는데, 한글(Noto Sans CJK KR) 폰트와 몇 가지 시스템 라이브러리가 서버에 설치되어 있어야 합니다. Render의 기본 Python 환경에는 이게 없어서, Dockerfile로 필요한 패키지(`fonts-noto-cjk` 등)를 직접 설치하도록 구성했습니다.

## 폴더 구조

```
vocab-test-app/
├── main.py              # FastAPI 백엔드 (PDF 파싱 + 시험지 생성)
├── requirements.txt
├── Dockerfile
├── render.yaml
├── templates/
│   └── index.html       # 업로드 화면
└── static/
    ├── style.css
    └── app.js
```

## 사용 흐름

1. 선생님이 단어책 PDF 업로드
2. 서버가 PDF 텍스트를 추출해 Claude API로 전달 → 유닛/번호/단어/한글뜻 구조화
3. 학원명, 유닛, 랜덤 여부, 방향(한글→영어 / 영어→한글) 선택
4. "시험지 PDF 만들기" 클릭 → 즉시 다운로드

## 다음에 추가하면 좋을 기능

- 정답지 별도 다운로드
- 여러 유닛 합쳐서 시험 범위 지정
- 로고 이미지 업로드 지원
- 사용량이 늘면 학원별 프리셋 저장 (로그인 도입 시)
