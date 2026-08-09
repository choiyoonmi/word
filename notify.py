# -*- coding: utf-8 -*-
"""텔레그램 알림 모듈 (원장님 수신용) — 외부 라이브러리 없이 stdlib만 사용.

환경변수(Render → Environment):
  TELEGRAM_BOT_TOKEN   BotFather 봇 토큰
  TELEGRAM_CHAT_ID     받는 사람 chat_id (여러 명이면 쉼표 구분: 123,456)

값이 없으면 조용히 건너뛰므로, 미설정 상태에서도 앱은 정상 동작합니다.
발송 실패해도 예외를 삼켜 앱 요청을 절대 막지 않습니다.
"""

import os
import json
import urllib.request
import urllib.error

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_IDS = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(text, chat_id=None, silent=False):
    if not BOT_TOKEN:
        return False
    targets = [chat_id] if chat_id else [c.strip() for c in CHAT_IDS.split(",") if c.strip()]
    if not targets:
        return False

    url = "https://api.telegram.org/bot%s/sendMessage" % BOT_TOKEN
    ok_all = True
    for cid in targets:
        payload = json.dumps({
            "chat_id": cid,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "disable_notification": silent,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:
            print("[telegram] 발송 실패:", e)
            ok_all = False
    return ok_all
