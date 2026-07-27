import os
import re
import json
import random
import base64
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pdfplumber
from weasyprint import HTML
import anthropic
import io

app = FastAPI(title="단어시험지 생성기")
app.mount("/static", StaticFiles(directory="static"), name="static")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


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


# ---------- PDF text extraction ----------

def extract_pdf_text(file_bytes: bytes) -> str:
    text_chunks = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_chunks.append(t)
    return "\n".join(text_chunks)


# ---------- Claude-based structuring ----------

PARSE_PROMPT = """다음은 영어 단어책 PDF에서 추출한 텍스트입니다.
이 텍스트를 유닛(unit)별로 나누어 각 단어의 번호, 영어 단어, 한글 뜻을 추출해서
아래 JSON 형식으로만 응답하세요. 다른 설명이나 텍스트는 절대 포함하지 마세요.

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

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    text = text.strip()
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse Claude response as JSON")
    return data


# ---------- PDF test sheet rendering ----------

ROW_TEMPLATE = """
<div class="row">
  <div class="num">{no}</div>
  <div class="hint">{hint}</div>
  <div class="answer-line"></div>
</div>
"""

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4; margin: 14mm 12mm; }}
body {{ font-family: "Noto Sans CJK KR", sans-serif; color: #1a1a1a; margin: 0; }}
.header {{ display: flex; align-items: center; border: 1.5pt solid #1a1a1a; margin-bottom: 8mm; }}
.logo-box {{ width: 30mm; padding: 4mm; text-align: center; font-size: 9.5pt; font-weight: 600; color: #333; line-height: 1.3; border-right: 1.5pt solid #1a1a1a; }}
.title-box {{ flex: 1; padding: 4mm 5mm; }}
.title-box .book {{ font-size: 10pt; color: #555; }}
.title-box .unit {{ font-size: 15pt; font-weight: 700; margin-top: 1.5mm; }}
.name-box {{ width: 50mm; padding: 4mm 5mm; border-left: 1.5pt solid #1a1a1a; font-size: 11pt; }}
.columns {{ display: flex; gap: 12mm; }}
.col {{ flex: 1; }}
.row {{ display: flex; align-items: flex-end; min-height: 18.5mm; padding-bottom: 1.5mm; }}
.num {{ width: 8mm; font-size: 13pt; font-weight: 700; color: #333; padding-bottom: 1.5mm; }}
.hint {{ width: 34mm; font-size: 13pt; padding-bottom: 1.5mm; line-height: 1.3; }}
.answer-line {{ flex: 1; border-bottom: 1.3pt solid #333; margin-left: 4mm; height: 13mm; }}
.footer {{ margin-top: 3mm; font-size: 8pt; color: #999; text-align: right; }}
</style>
</head>
<body>
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
</body>
</html>
"""


def split_academy_name(name: str):
    parts = name.strip().split(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return name, ""


def render_test_pdf(req: GenerateRequest) -> bytes:
    words = [w.dict() for w in req.words]
    if req.shuffle:
        random.shuffle(words)
        for i, w in enumerate(words, start=1):
            w["no"] = i

    mid = (len(words) + 1) // 2
    left, right = words[:mid], words[mid:]

    def hint_of(w):
        return w["word"] if req.direction == "eng_to_kor" else w["kor"]

    left_html = "".join(ROW_TEMPLATE.format(no=w["no"], hint=hint_of(w)) for w in left)
    right_html = "".join(ROW_TEMPLATE.format(no=w["no"], hint=hint_of(w)) for w in right)

    line1, line2 = split_academy_name(req.academy_name)

    html = PAGE_TEMPLATE.format(
        academy_line1=line1,
        academy_line2=line2,
        book_title=req.book_title,
        unit_title=req.unit_title,
        left_rows=left_html,
        right_rows=right_html,
        academy_name=req.academy_name,
    )
    return HTML(string=html).write_pdf()


# ---------- Routes ----------

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html", encoding="utf-8") as f:
        return f.read()


@app.post("/api/parse")
async def api_parse(file: UploadFile = File(...)):
    file_bytes = await file.read()
    raw_text = extract_pdf_text(file_bytes)
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="PDF에서 텍스트를 추출하지 못했습니다.")
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


@app.get("/health")
async def health():
    return {"status": "ok"}
