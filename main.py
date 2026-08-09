import os
import re
import json
import random
import base64
import asyncio
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pdfplumber
from weasyprint import HTML
import anthropic
import io

from notify import send_telegram

app = FastAPI(title="단어시험지 생성기")
app.mount("/static", StaticFiles(directory="static"), name="static")

# 낭독 녹음 앱(happytree-speech)에서 과제 단어로 시험지를 만들 수 있게 CORS 허용.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://happytree-speech.onrender.com",
        "http://localhost:8000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


@app.exception_handler(Exception)
async def all_exceptions_handler(request, exc):
    # 예상치 못한 서버 오류가 나면 원장님께 텔레그램으로 알림 (실패해도 응답엔 영향 없음)
    try:
        await asyncio.to_thread(
            send_telegram,
            "⚠️ <b>단어시험지 생성기 오류</b>\n"
            f"경로: {request.url.path}\n"
            f"내용: {str(exc)[:300]}",
        )
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"detail": f"서버 오류: {str(exc)}"})


# ---------- Data models ----------

class WordItem(BaseModel):
    no: int
    word: str
    pos: Optional[str] = None
    kor: str


class UnitData(BaseModel):
    unit_title: str
    words: List[WordItem]


class GenerateRequest(BaseModel):
    academy_name: str = "학원명"
    book_title: str = ""
    unit_title: str = "Unit"
    words: List[WordItem]
    shuffle: bool = False
    direction: str = "kor_to_eng"  # or "eng_to_kor"


class GenerateAllRequest(BaseModel):
    academy_name: str = "학원명"
    book_title: str = ""
    units: List[UnitData]
    shuffle: bool = False
    direction: str = "kor_to_eng"  # or "eng_to_kor"


# ---------- PDF text extraction ----------

def extract_pdf_text(file_bytes: bytes) -> str:
    text_chunks = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_chunks.append(t)
    return "\n".join(text_chunks)


def extract_excel_text(file_bytes: bytes) -> str:
    import pandas as pd
    sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None, dtype=str)
    text_chunks = []
    for sheet_name, df in sheets.items():
        text_chunks.append(f"[Sheet: {sheet_name}]")
        for _, row in df.iterrows():
            cells = [str(c) for c in row.tolist() if c is not None and str(c) != "nan"]
            if cells:
                text_chunks.append(" ".join(cells))
    return "\n".join(text_chunks)


# ---------- Claude-based structuring ----------

PARSE_PROMPT = """다음은 영어 단어책 PDF/엑셀에서 추출한 텍스트입니다.
이 텍스트를 유닛(unit)별로 나누어 각 단어의 번호, 영어 단어, 한글 뜻을 추출하세요.

반드시 지킬 것:
- 응답은 오직 JSON 객체 하나여야 합니다. 코드블록(```), 설명, 인사말 등 그 어떤 텍스트도 앞뒤에 붙이지 마세요.
- 첫 글자는 반드시 { 여야 하고 마지막 글자는 반드시 } 여야 합니다.

형식:
{
  "units": [
    {
      "unit_title": "유닛 제목 (있으면 원문 그대로, 없으면 'Unit 1' 처럼 생성)",
      "words": [
        {"no": 1, "word": "영어단어", "kor": "한글 뜻"},
        ...
      ]
    }
  ]
}

텍스트:
---
{content}
---
"""


def parse_vocab_with_claude(raw_text: str) -> dict:
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured on server")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    # Truncate very large inputs defensively
    content = raw_text[:60000]
    prompt = PARSE_PROMPT.replace("{content}", content)

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"Claude API 오류: {e.status_code} {e.message}")
    except anthropic.APIConnectionError as e:
        raise HTTPException(status_code=502, detail=f"Claude API 연결 실패: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"알 수 없는 오류: {str(e)}")

    text = "".join(b.text for b in resp.content if b.type == "text")
    text = text.strip()

    # Robustly extract the JSON object even if Claude adds stray text/fences around it
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise HTTPException(
            status_code=500,
            detail=f"Claude 응답에서 JSON을 찾지 못했습니다. (응답 앞부분: {text[:200]})",
        )
    json_str = text[start:end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        finish_reason = getattr(resp, "stop_reason", None)
        hint = " (응답이 중간에 잘렸을 수 있어요 — 유닛 수가 많은 파일이면 파일을 나눠서 올려보세요)" if finish_reason == "max_tokens" else ""
        raise HTTPException(
            status_code=500,
            detail=f"Claude 응답이 올바른 JSON이 아닙니다: {str(e)}{hint}",
        )
    return data


# ---------- PDF test sheet rendering ----------

ROW_TEMPLATE = """
<div class="row">
  <div class="num">{no}</div>
  <div class="hint">{hint}</div>
  <div class="answer-line"></div>
</div>
"""

DOC_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4; margin: 14mm 12mm; }}
body {{ font-family: "Noto Sans CJK KR", sans-serif; color: #1a1a1a; margin: 0; }}
.sheet + .sheet {{ page-break-before: always; }}
.header {{ display: flex; align-items: center; border: 1.5pt solid #1a1a1a; margin-bottom: var(--hmb, 8mm); }}
.logo-box {{ width: 30mm; padding: var(--hpad, 4mm); text-align: center; font-size: var(--hlogo, 9.5pt); font-weight: 600; color: #333; line-height: 1.3; border-right: 1.5pt solid #1a1a1a; }}
.title-box {{ flex: 1; padding: var(--hpad, 4mm) 5mm; }}
.title-box .book {{ font-size: var(--hbook, 10pt); color: #555; }}
.title-box .unit {{ font-size: var(--hunit, 15pt); font-weight: 700; margin-top: 1.5mm; }}
.name-box {{ width: 50mm; padding: var(--hpad, 4mm) 5mm; border-left: 1.5pt solid #1a1a1a; font-size: var(--hname, 11pt); }}
.columns {{ display: flex; gap: 12mm; }}
.col {{ flex: 1; }}
.row {{ display: flex; align-items: flex-end; min-height: var(--rowh, 18.5mm); padding-bottom: 1.5mm; }}
.num {{ width: 8mm; font-size: var(--fs, 13pt); font-weight: 700; color: #333; padding-bottom: 1.5mm; }}
.hint {{ width: 34mm; font-size: var(--fs, 13pt); padding-bottom: 1.5mm; line-height: 1.25; }}
.answer-line {{ flex: 1; border-bottom: 1.3pt solid #333; margin-left: 4mm; height: var(--ansh, 13mm); }}
.footer {{ margin-top: 3mm; font-size: 8pt; color: #999; text-align: right; }}
</style>
</head>
<body>{sections}</body>
</html>
"""

SECTION_TEMPLATE = """
<div class="sheet" style="--rowh: {rowh}mm; --fs: {fs}pt; --ansh: {ansh}mm; --hpad: {hpad}mm; --hlogo: {hlogo}pt; --hbook: {hbook}pt; --hunit: {hunit}pt; --hname: {hname}pt; --hmb: {hmb}mm;">
  <div class="header">
    <div class="logo-box">{academy_line1}<br>{academy_line2}</div>
    <div class="title-box">
      <div class="book">{book_title}</div>
      <div class="unit">{unit_title}</div>
    </div>
    <div class="name-box">Name : ____________________</div>
  </div>
  <div class="columns">
    <div class="col">{left_rows}</div>
    <div class="col">{right_rows}</div>
  </div>
  <div class="footer">{academy_name}</div>
</div>
"""


def split_academy_name(name: str):
    parts = name.strip().split(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return name, ""


def fit_metrics(n_words: int):
    """단어 수에 맞춰 한 유닛이 A4 한 장에 들어가도록 헤더/줄높이/글자를 계산.
    단어가 많은 유닛은 헤더도 3단계로 축소해 본문에 세로 공간을 더 준다.
    2단 배치라 한 단(칼럼)의 줄 수 = ceil(n/2). 각 줄 실제높이 = rowh + padding(1.5).
    반환: dict (본문 + 헤더 치수). 값은 mm/pt.
    """
    rows_per_col = max(1, (n_words + 1) // 2)
    ROW_PAD = 1.5
    TOTAL = 269.0     # A4 297 - @page 위아래 여백 28
    FOOTER = 6.0
    SLACK = 14.0      # 안전 여유 (렌더링 오차/줄바꿈 대비)

    # 헤더 티어: 단어가 많을수록 헤더를 작게. hfoot = 헤더 대략 높이(여백 포함) 추정.
    if n_words <= 28:
        hdr = dict(hpad=4.0, hlogo=9.5, hbook=10.0, hunit=15.0, hname=11.0, hmb=8.0)
        hfoot = 34.0
    elif n_words <= 44:
        hdr = dict(hpad=2.5, hlogo=8.0, hbook=8.5, hunit=12.0, hname=9.5, hmb=5.0)
        hfoot = 22.0
    else:
        hdr = dict(hpad=2.0, hlogo=7.0, hbook=7.5, hunit=10.5, hname=8.5, hmb=4.0)
        hfoot = 17.0

    budget = TOTAL - hfoot - FOOTER - SLACK   # 본문(한 칼럼) 세로 예산
    rowh = min(18.5, budget / rows_per_col - ROW_PAD)
    rowh = max(6.0, rowh)
    fs = 8.0 + (rowh - 6.0) / (18.5 - 6.0) * (13.0 - 8.0)
    fs = max(8.0, min(13.0, fs))
    ansh = max(3.5, rowh - 5.0)

    m = dict(rowh=round(rowh, 1), fs=round(fs, 1), ansh=round(ansh, 1))
    m.update({k: round(v, 1) for k, v in hdr.items()})
    return m


def build_section(academy_name, book_title, unit_title, words, shuffle, direction) -> str:
    """유닛 하나의 시험지 HTML 섹션(A4 한 장)을 만든다."""
    words = [dict(w) for w in words]
    if shuffle:
        random.shuffle(words)
        for i, w in enumerate(words, start=1):
            w["no"] = i

    mid = (len(words) + 1) // 2
    left, right = words[:mid], words[mid:]

    def hint_of(w):
        return w["word"] if direction == "eng_to_kor" else w["kor"]

    left_html = "".join(ROW_TEMPLATE.format(no=w["no"], hint=hint_of(w)) for w in left)
    right_html = "".join(ROW_TEMPLATE.format(no=w["no"], hint=hint_of(w)) for w in right)

    line1, line2 = split_academy_name(academy_name)
    m = fit_metrics(len(words))

    return SECTION_TEMPLATE.format(
        academy_line1=line1,
        academy_line2=line2,
        book_title=book_title,
        unit_title=unit_title,
        left_rows=left_html,
        right_rows=right_html,
        academy_name=academy_name,
        **m,
    )


def render_test_pdf(req: GenerateRequest) -> bytes:
    section = build_section(
        req.academy_name, req.book_title, req.unit_title,
        [w.dict() for w in req.words], req.shuffle, req.direction,
    )
    html = DOC_TEMPLATE.format(sections=section)
    return HTML(string=html).write_pdf()


def render_all_pdf(req: "GenerateAllRequest") -> bytes:
    """책 전체: 유닛마다 새 페이지로 시험지를 이어붙여 하나의 PDF로."""
    sections = "".join(
        build_section(
            req.academy_name, req.book_title, u.unit_title,
            [w.dict() for w in u.words], req.shuffle, req.direction,
        )
        for u in req.units
    )
    html = DOC_TEMPLATE.format(sections=sections)
    return HTML(string=html).write_pdf()


# ---------- Routes ----------

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html", encoding="utf-8") as f:
        return f.read()


@app.post("/api/parse")
async def api_parse(file: UploadFile = File(...)):
    file_bytes = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith((".xlsx", ".xls")):
        raw_text = extract_excel_text(file_bytes)
    elif filename.endswith(".pdf"):
        raw_text = extract_pdf_text(file_bytes)
    else:
        raise HTTPException(status_code=400, detail="PDF 또는 엑셀(.xlsx, .xls) 파일만 업로드할 수 있습니다.")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="파일에서 텍스트를 추출하지 못했습니다.")
    data = parse_vocab_with_claude(raw_text)
    return JSONResponse(data)


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    pdf_bytes = render_test_pdf(req)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=vocab_test.pdf"},
    )


@app.post("/api/generate-all")
async def api_generate_all(req: GenerateAllRequest):
    if not req.units:
        raise HTTPException(status_code=400, detail="유닛이 없습니다.")
    pdf_bytes = render_all_pdf(req)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=vocab_test_all.pdf"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
