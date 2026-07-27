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


@app.exception_handler(Exception)
async def all_exceptions_handler(request, exc):
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


def parse_vocab_with_claude(raw_text: str)
