# -*- coding: utf-8 -*-
"""نشر منشورات قناتي Telegram العامتين إلى قناة النشر عبر Bot API.

يقرأ النصوص والوسائط الظاهرة في صفحات المعاينة العامة. الصور والفيديوهات
تُنقل عبر روابط CDN، أما الملفات والوثائق فتُنقل من Telegram مباشرة باستخدام
copyMessage حتى لا نحتاج إلى تنزيلها محليًا أو استخدام Userbot.
"""

import html
import json
import os
import re
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

SOURCE_USERNAMES = ("AbdmomenShjaaAldeen", "qada_a")
DESTINATION = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
HISTORY_FILE = Path(os.environ.get("HISTORY_FILE", "telegram_sources_history.json"))
MAX_HISTORY = 1000
TIMEOUT = 45
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TelegramPublisher/1.0; +https://t.me/muen2025)"
}


def validate_configuration() -> None:
    missing = []
    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not DESTINATION:
        missing.append("TELEGRAM_CHANNEL_ID")
    if missing:
        raise RuntimeError(
            "إعدادات Telegram غير مكتملة. أضف المتغيرات التالية في GitHub Actions: "
            + ", ".join(missing)
        )


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
    """يحذف روابط وأسماء القنوات والتذييلات من النص قبل إعادة نشره."""
    value = re.sub(
        r"(?:\n+ـ{5,})?\n*للاشتراك(?: بالقناة)? عبر تيليجرام:?\s*\n*"
        r"(?:https?://)?t\.me/\S*.*$",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )

    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        # إيقاف النسخة الإنجليزية كما في منطق المستودع الأصلي.
        if re.match(r"^[^\u0600-\u06FF\n]*[A-Za-z]", stripped):
            break
        if re.search(r"(?:https?://|www\.)\S+|t\.me/\S+", stripped, re.IGNORECASE):
            continue
        if re.search(
            r"@?(?:AbdmomenShjaaAldeen|qada_a|muen2025)\b|"
            r"منصة\s+الناصر\s+القانونية|رويترز|Reuters",
            stripped,
            re.IGNORECASE,
        ):
            continue
        lines.append(line)

    cleaned = "\n".join(lines)
    cleaned = re.sub(
        r"(?:https?://|www\.)\S+|t\.me/\S+", "", cleaned, flags=re.IGNORECASE
    )
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def extract_message_text(text_node: Any) -> str:
    """يحافظ على الرموز ويحوّل عناصر br إلى فواصل أسطر فعلية."""
    for br in text_node.find_all("br"):
        br.replace_with("\n")
    return clean_text(text_node.get_text("", strip=False))


def extract_media(wrap: Any) -> tuple[str, str, str]:
    """يعيد نوع الوسيط والرابط واسم الملف إن ظهر في المعاينة العامة."""
    photo_wrap = wrap.select_one(".tgme_widget_message_photo_wrap")
    if photo_wrap:
        style = photo_wrap.get("style", "")
        match = re.search(r"url\(['\"]?(.*?)['\"]?\)", style)
        if match:
            return "photo", html.unescape(match.group(1)), ""

    video = wrap.select_one("video")
    if video:
        source = video.select_one("source")
        candidate = video.get("src") or (source.get("src") if source else "")
        if candidate:
            return "video", html.unescape(candidate), ""

    document_wrap = wrap.select_one(".tgme_widget_message_document_wrap")
    if document_wrap:
        title_node = document_wrap.select_one(".tgme_widget_message_document_title")
        filename = title_node.get_text(" ", strip=True) if title_node else "document"
        # لا يظهر رابط تنزيل مباشر للوثيقة في t.me/s؛ سيُستخدم copyMessage.
        return "document", "", filename

    return "", "", ""


def fetch_posts(source_username: str) -> list[dict[str, str]]:
    source_url = f"https://t.me/s/{source_username}"
    response = requests.get(source_url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    posts = []

    for wrap in soup.select(".tgme_widget_message_wrap"):
        message = wrap.select_one(".tgme_widget_message")
        post_link = wrap.select_one(".tgme_widget_message_date")
        if not message or not post_link:
            continue

        data_post = message.get("data-post", "")
        message_id = data_post.rsplit("/", 1)[-1] if data_post else ""
        if not message_id:
            continue

        text_node = wrap.select_one(".tgme_widget_message_text")
        text = extract_message_text(text_node) if text_node else ""
        post_url = post_link.get("href", f"https://t.me/{source_username}/{message_id}")
        media_type, media_url, filename = extract_media(wrap)

        if not text:
            text = "منشور جديد"

        posts.append(
            {
                "id": f"{source_username}:{message_id}",
                "source_username": source_username,
                "message_id": message_id,
                "text": text,
                "url": post_url,
                "media_url": media_url,
                "media_type": media_type,
                "filename": filename,
            }
        )

    return posts


def fetch_all_posts() -> list[dict[str, str]]:
    posts = []
    for source_username in SOURCE_USERNAMES:
        try:
            posts.extend(fetch_posts(source_username))
        except requests.RequestException as error:
            print(f"تعذر جلب منشورات المصدر {source_username}: {error}")
    return posts


def format_message(post: dict[str, str]) -> str:
    paragraphs = [
        part.strip() for part in re.split(r"\n\s*\n", post["text"]) if part.strip()
    ]
    title = paragraphs[0] if paragraphs else post["text"]
    summary = "\n\n".join(paragraphs[1:])

    parts = [f"<b>{html.escape(title)}</b>"]
    if summary:
        parts.append(f"<blockquote expandable>\n{html.escape(summary)}\n</blockquote>")
    parts.append(
        "ــــــــــــــــــــــــــــ\n\n"
        "للاشتراك بالقناة عبر تيليجرام\n"
        "https://t.me/muen2025"
    )
    return "\n\n".join(parts)


def telegram_request(method: str, **payload: Any) -> dict[str, Any]:
    response = requests.post(
        f"{TELEGRAM_API}/{method}", json=payload, timeout=TIMEOUT
    )
    try:
        data = response.json()
    except ValueError:
        data = {"ok": False, "description": response.text}
    if not response.ok or not data.get("ok"):
        raise RuntimeError(
            f"Telegram {method} failed ({response.status_code}): "
            f"{data.get('description', response.text)}"
        )
    return data


def send_text_message(message: str) -> bool:
    telegram_request(
        "sendMessage",
        chat_id=DESTINATION,
        text=message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return True


def send_downloaded_media(post: dict[str, str], message: str) -> bool:
    media_type = post["media_type"]
    media_url = post["media_url"]
    media_response = requests.get(
        media_url, headers=HEADERS, timeout=TIMEOUT, stream=True
    )
    media_response.raise_for_status()

    endpoint = f"{TELEGRAM_API}/send{media_type.title()}"
    payload: dict[str, str] = {
        "chat_id": DESTINATION,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if len(message) <= 1024:
        payload["caption"] = message

    response = requests.post(
        endpoint,
        data=payload,
        files={media_type: (f"post_{post['message_id']}", media_response.raw)},
        timeout=TIMEOUT,
    )
    data = response.json()
    if not response.ok or not data.get("ok"):
        raise RuntimeError(
            f"Telegram send{media_type.title()} failed ({response.status_code}): "
            f"{data.get('description', response.text)}"
        )
    if len(message) > 1024:
        send_text_message(message)
    return True


def send_document(post: dict[str, str], message: str) -> bool:
    """ينقل الوثيقة من المصدر مباشرة دون تنزيلها، مع وضع النص كتعليق."""
    payload: dict[str, Any] = {
        "chat_id": DESTINATION,
        "from_chat_id": f"@{post['source_username']}",
        "message_id": int(post["message_id"]),
    }
    if len(message) <= 1024:
        payload.update({"caption": message, "parse_mode": "HTML"})

    try:
        telegram_request("copyMessage", **payload)
    except RuntimeError as error:
        raise RuntimeError(
            f"تعذر نسخ الملف {post.get('filename', '')} من @{post['source_username']}. "
            "يجب أن يكون البوت قادرًا على الوصول إلى القناة المصدر، أو أن تُرسل الوثيقة "
            "من حساب/بوت لديه صلاحية قراءة منشوراتها. التفاصيل: " + str(error)
        ) from error

    if len(message) > 1024:
        send_text_message(message)
    return True


def send_to_telegram(post: dict[str, str]) -> bool:
    message = format_message(post)
    media_type = post.get("media_type", "")

    try:
        if media_type == "document":
            return send_document(post, message)
        if media_type in {"photo", "video"} and post.get("media_url"):
            return send_downloaded_media(post, message)
        return send_text_message(message)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        print(f"فشل إرسال المنشور {post['id']}: {error}")
        return False


def main() -> None:
    validate_configuration()
    history = load_history()
    posts = fetch_all_posts()
    fresh = [post for post in posts if post["id"] not in history]

    if not fresh:
        print("لا توجد منشورات جديدة.")
        return

    sent = 0
    failed = 0
    for post in fresh:
        if send_to_telegram(post):
            history.add(post["id"])
            sent += 1
            save_history(history)
        else:
            failed += 1

    save_history(history)
    print(f"تم نشر {sent} من {len(fresh)} منشور جديد. الفاشل: {failed}.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
