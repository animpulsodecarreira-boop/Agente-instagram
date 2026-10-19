"""Aprovação via Telegram (grátis): o bot envia as imagens + legenda com botões Aprovar/Rejeitar."""
import json
import os

import requests

BASE = "https://api.telegram.org/bot{token}/{method}"


def _call(method, **kw):
    r = requests.post(BASE.format(token=os.environ["TELEGRAM_BOT_TOKEN"], method=method), timeout=60, **kw)
    r.raise_for_status()
    return r.json()["result"]


def chat_id():
    return os.environ["TELEGRAM_CHAT_ID"]


def send_for_approval(post_id, paths, caption_full, funnel):
    # 1) álbum com as imagens (Telegram aceita até 10 por álbum)
    files, media = {}, []
    for i, p in enumerate(paths):
        files[f"f{i}"] = open(p, "rb")
        media.append({"type": "photo", "media": f"attach://f{i}"})
    _call("sendMediaGroup", data={"chat_id": chat_id(), "media": json.dumps(media)}, files=files)
    for f in files.values():
        f.close()
    # 2) legenda + botões
    text = f"📝 Post {post_id}  ({funnel.upper()})\n\n{caption_full}"[:4000]
    kb = {"inline_keyboard": [[
        {"text": "✅ Aprovar e postar", "callback_data": f"ap:{post_id}"},
        {"text": "❌ Rejeitar", "callback_data": f"rj:{post_id}"},
    ]]}
    return _call("sendMessage", json={"chat_id": chat_id(), "text": text, "reply_markup": kb})


def notify(text):
    return _call("sendMessage", json={"chat_id": chat_id(), "text": text[:4000]})


def get_updates(offset):
    return _call("getUpdates", json={"offset": offset, "timeout": 0, "allowed_updates": ["callback_query"]})


def answer(cb_id, text):
    try:
        _call("answerCallbackQuery", json={"callback_query_id": cb_id, "text": text})
    except Exception:
        pass  # o Telegram recusa respostas a toques antigos; isso não pode travar a publicação


def mark_message(chat, message_id, text):
    """Troca os botões por um texto de status, para não aprovar duas vezes."""
    _call("editMessageReplyMarkup", json={"chat_id": chat, "message_id": message_id,
                                          "reply_markup": {"inline_keyboard": []}})
    notify(text)
