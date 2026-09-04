#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""نشر منشورات قناة Telegram العامة @ALYMENET إلى قناة أخرى عبر Bot API.

لا يستخدم Userbot: يقرأ صفحة المعاينة العامة t.me/s ثم ينشر نص الخبر والرابط.
"""

import hashlib
import html
import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_USERNAME = "ALYMENET"
SOURCE_URL = f"https://t.me/s/{SOURCE_USERNAME}"
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DESTINATION = os.environ["TELEGRAM_CHANNEL_ID"]
HISTORY_FILE = Path(os.environ.get("HISTORY_FILE", "alymenet_history.json"))
MAX_HISTORY = 1000
TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AlymenetPublisher/1.0; +https://t.me/ALYMENET)"
}


def load_history() -> set[str]:
    if not HISTORY_FILE.exists():
        return set()
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else [])
    except (OSError, ValueError):
        return set()


def save_history(history: set[str]) -> None:
    values = list(history)[-MAX_HISTORY:]
    HISTORY_FILE.write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def clean_text(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def fetch_posts() -> list[dict[str, str]]:
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    posts = []

    for wrap in soup.select(".tgme_widget_message_wrap"):
        message = wrap.select_one(".tgme_widget_message")
        text_node = wrap.select_one(".tgme_widget_message_text")
        post_link = wrap.select_one(".tgme_widget_message_date")
        if not message or not post_link:
            continue

        data_post = message.get("data-post", "")
        post_id = data_post.rsplit("/", 1)[-1] if data_post else ""
        if not post_id:
            continue

        text = clean_text(text_node.get_text("\n", strip=True) if text_node else "")
        url = post_link.get("href", f"https://t.me/{SOURCE_USERNAME}/{post_id}")
        # ننسخ المنشورات النصية. للمنشورات التي تحتوي وسائط فقط نرسل الرابط.
        if not text:
            text = "منشور جديد من قناة اليمن نت"

        posts.append({"id": post_id, "text": text, "url": url})

    return posts


def send_to_telegram(post: dict[str, str]) -> bool:
    message = (
        f"{html.escape(post['text'])}\n"
        "ــــــــــــــــــــــــــــ\n"
        "للاشتراك بالقناة عبر تيليجرام:\n"
        "https://t.me/hasadalyoum"
    )
    endpoint = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        endpoint,
        json={
            "chat_id": DESTINATION,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=TIMEOUT,
    )
    if not response.ok or not response.json().get("ok"):
        print(f"Telegram error: {response.status_code} {response.text}")
        return False
    return True


def main() -> None:
    history = load_history()
    posts = fetch_posts()
    fresh = [post for post in posts if post["id"] not in history]

    if not fresh:
        print("لا توجد منشورات جديدة.")
        return

    # الصفحة مرتبة من الأقدم إلى الأحدث عادةً؛ نرسل بالترتيب الظاهر.
    sent = 0
    for post in fresh:
        if send_to_telegram(post):
            history.add(post["id"])
            sent += 1

    save_history(history)
    print(f"تم نشر {sent} من {len(fresh)} منشور جديد.")


if __name__ == "__main__":
    main()
