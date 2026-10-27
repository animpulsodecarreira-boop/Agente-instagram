"""Aprovação via Telegram (grátis): o bot envia as imagens + legenda com botões Aprovar/Rejeitar."""
import json
import os
import re

import requests

BASE = "https://api.telegram.org/bot{token}/{method}"
SECRET_ENVS = ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "IG_ACCESS_TOKEN")


def redact(text):
    """Remove tokens e chaves de qualquer texto antes de mostrar/enviar."""
    text = str(text)
    for name in SECRET_ENVS:
        v = os.environ.get(name, "").strip()
        if v:
            text = text.replace(v, "***")
    return re.sub(r"bot\d{5,}:[A-Za-z0-9_-]{20,}", "bot***", text)


def _call(method, **kw):
    url = BASE.format(token=os.environ["TELEGRAM_BOT_TOKEN"].strip(), method=method)
    try:
        r = requests.post(url, timeout=180, **kw)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(redact(f"Telegram {method}: falha de conexão ({type(e).__name__})")) from None
    if r.status_code != 200:
        try:
            desc = r.json().get("description", r.text[:200])
        except ValueError:
            desc = r.text[:200]
        raise RuntimeError(redact(f"Telegram {method}: HTTP {r.status_code} - {desc}")) from None
    return r.json()["result"]


def chat_id():
    return os.environ["TELEGRAM_CHAT_ID"].strip()


def _album(kind, paths):
    """Envia um álbum; se o Telegram recusar, envia item por item; se recusar de novo, como documento.
    kind: 'photo' ou 'video'. Nunca derruba o fluxo: devolve uma nota com o que não deu certo."""
    if not paths:
        return ""
    media_type = "photo" if kind == "photo" else "video"
    if len(paths) >= 2:  # álbum só faz sentido com 2 ou mais itens; com 1, envia direto
        files, media = {}, []
        try:
            for i, p in enumerate(paths):
                files[f"f{i}"] = open(p, "rb")
                item = {"type": media_type, "media": f"attach://f{i}"}
                if kind == "video":
                    item["supports_streaming"] = True
                media.append(item)
            _call("sendMediaGroup", data={"chat_id": chat_id(), "media": json.dumps(media)}, files=files)
            return ""
        except Exception as e:
            print(f"[telegram] álbum de {kind} falhou ({redact(e)}); enviando um a um")
        finally:
            for f in files.values():
                f.close()
    notes = []
    for p in paths:
        sent = False
        for method, field in (("sendPhoto" if kind == "photo" else "sendVideo", kind), ("sendDocument", "document")):
            try:
                with open(p, "rb") as fh:
                    _call(method, data={"chat_id": chat_id()}, files={field: fh})
                sent = True
                break
            except Exception as e:
                print(f"[telegram] {method} falhou para {p.name if hasattr(p, 'name') else p}: {redact(e)}")
        if not sent:
            notes.append(str(p))
    return f"⚠️ Não consegui enviar a prévia de {len(notes)} arquivo(s)." if notes else ""


def send_for_approval(post_id, paths, caption_full, funnel, theme="", story_videos=None):
    notes = [_album("photo", paths), _album("video", story_videos or [])]
    notes = "\n".join(n for n in notes if n)
    extra = f" · estilo {theme}" if theme else ""
    stories_note = (f"\n\n🎬 + {len(story_videos)} {'story' if len(story_videos) == 1 else 'stories'} em vídeo (acima)"
                    if story_videos else "")
    warn = f"\n\n{notes}\nO post foi salvo mesmo assim; você pode aprovar normalmente." if notes else ""
    text = redact(f"📝 Post {post_id}  ({funnel.upper()}{extra}){stories_note}{warn}\n\n{caption_full}")[:4000]
    kb = {"inline_keyboard": [
        [{"text": "✅ Aprovar post + story", "callback_data": f"ap:{post_id}"}],
        [{"text": "📷 Só o post", "callback_data": f"po:{post_id}"},
         {"text": "❌ Rejeitar", "callback_data": f"rj:{post_id}"}],
    ]}
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo:  # plano B que não depende do Telegram: abre o fluxo "Aprovar post" no GitHub
        kb["inline_keyboard"].append([{"text": "🛠 Plano B: aprovar pelo GitHub",
                                       "url": f"https://github.com/{repo}/actions/workflows/aprovar.yml"}])
        text += f"\n\nSe o botão não funcionar: abra o plano B e informe o número {post_id}."
    return _call("sendMessage", json={"chat_id": chat_id(), "text": text, "reply_markup": kb})


def notify(text):
    return _call("sendMessage", json={"chat_id": chat_id(), "text": redact(text)[:4000]})


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


def webhook_info():
    return _call("getWebhookInfo", json={})


def get_me():
    return _call("getMe", json={})
