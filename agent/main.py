"""Uso:
  python -m agent.main generate [--funnel topo|meio|fundo] [--force]   # gera, renderiza e manda pro Telegram
  python -m agent.main poll                                            # lê aprovações e publica
  python -m agent.main preview [--mock]                                # só gera/renderiza localmente (teste)
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from . import telegram_io as tg
from .config import QUEUE, STATE_FILE, WEEK_PLAN
from .generate import generate_post, save_history
from .render import render_slides

TZ = ZoneInfo("America/Sao_Paulo")

MOCK = {
    "topic": "Teste de layout", "funnel": "topo",
    "slides": [
        {"kind": "cover", "title": "Seu LinkedIn diz o que você faz ou só o seu cargo?", "body": "Pequenos ajustes mudam a percepção do recrutador."},
        {"kind": "content", "title": "Cargo não é posicionamento.", "body": "“Analista Administrativo” descreve uma função, mas não mostra a área em que você atua nem o valor que entrega.", "highlight": "Clareza vence quantidade de informação."},
        {"kind": "check", "title": "Seu título está pronto para ser encontrado?", "items": ["Cargo ou especialidade clara", "Área de atuação", "Valor que você entrega", "Palavras que recrutadores buscam"], "note": "Salva para conferir depois."},
        {"kind": "content", "title": "E aqui está o ponto:", "body": "Seu perfil pode estar correto...\n\n...e ainda assim não estar bem posicionado.", "highlight": "Detalhes pequenos mudam tudo."},
        {"kind": "cta", "title": "Quer saber o que está enfraquecendo o seu LinkedIn?", "body": "Comenta QUERO que eu te mostro o que observar.\n\nSalva e manda para quem precisa."},
    ],
    "caption": "Seu LinkedIn diz o que você faz? 👀\n\nDesliza e confere.\n\nComenta QUERO e salva este post.",
    "hashtags": ["#LinkedIn", "#Carreira", "#PosicionamentoProfissional"],
}


def full_caption(post):
    return post["caption"].strip() + "\n\n" + " ".join(post["hashtags"])


def raw_url(post_id, i):
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.getenv("REPO_BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/queue/{post_id}/slide{i}.png"


def cmd_generate(args):
    now = datetime.now(TZ)
    funnel = args.funnel or WEEK_PLAN.get(now.weekday())
    if not funnel:
        print("Sem post planejado para hoje.")
        return
    post_id = now.strftime("%Y%m%d-%H%M")
    try:
        post = generate_post(funnel)
        out = QUEUE / post_id
        paths = render_slides(post["slides"], out)
        cap = full_caption(post)
        meta = {"id": post_id, "status": "pending", "funnel": funnel, "topic": post["topic"],
                "caption": cap, "slides": len(paths)}
        (out / "post.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        save_history(post["topic"], funnel)
        if os.getenv("SKIP_TELEGRAM") != "1":
            # as imagens só ficam públicas após o commit/push do workflow; o Telegram recebe os arquivos direto
            tg.send_for_approval(post_id, paths, cap, funnel)
        print(f"Post {post_id} gerado: {post['topic']}")
    except Exception:
        err = traceback.format_exc()
        print(err, file=sys.stderr)
        if os.getenv("SKIP_TELEGRAM") != "1":
            tg.notify(f"⚠️ O agente falhou ao gerar o post de hoje:\n{err[-800:]}")
        sys.exit(1)


def cmd_poll(_args):
    from .instagram import permalink, publish_carousel
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"offset": 0}
    print(f"[poll] offset atual: {state['offset']}")
    pend = [p.parent.name for p in sorted(QUEUE.glob("*/post.json"))
            if json.loads(p.read_text(encoding="utf-8")).get("status") == "pending"]
    print(f"[poll] posts aguardando aprovação: {pend or 'nenhum'}")
    updates = tg.get_updates(state["offset"])
    print(f"[poll] atualizações recebidas do Telegram: {len(updates)}")
    for u in updates:
        state["offset"] = u["update_id"] + 1
        cb = u.get("callback_query")
        if not cb:
            print(f"[poll] update {u['update_id']} ignorado (não é toque em botão)")
            continue
        if str(cb["message"]["chat"]["id"]) != str(tg.chat_id()):
            print(f"[poll] toque ignorado: chat {cb['message']['chat']['id']} não é o seu")
            continue
        action, _, post_id = cb["data"].partition(":")
        print(f"[poll] toque encontrado: ação={action} post={post_id}")
        meta_file = QUEUE / post_id / "post.json"
        if not meta_file.exists():
            print(f"[poll] post {post_id} não encontrado em queue/")
            tg.answer(cb["id"], "Post não encontrado.")
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta["status"] != "pending":
            print(f"[poll] post {post_id} já está '{meta['status']}', ignorando")
            tg.answer(cb["id"], f"Já processado ({meta['status']}).")
            continue
        chat, msg = cb["message"]["chat"]["id"], cb["message"]["message_id"]
        if action == "rj":
            meta["status"] = "rejected"
            print(f"[poll] post {post_id} rejeitado")
            tg.answer(cb["id"], "Rejeitado.")
            tg.mark_message(chat, msg, f"❌ Post {post_id} rejeitado. Nada foi publicado.")
        elif action == "ap":
            tg.answer(cb["id"], "Aprovado! Publicando...")
            try:
                urls = [raw_url(post_id, i) for i in range(1, meta["slides"] + 1)]
                print(f"[poll] publicando {len(urls)} imagens, primeira: {urls[0]}")
                media_id = publish_carousel(urls, meta["caption"])
                meta["status"], meta["media_id"] = "published", media_id
                print(f"[poll] publicado! media_id={media_id}")
                tg.mark_message(chat, msg, f"✅ Post {post_id} publicado!\n{permalink(media_id)}")
            except Exception as e:
                meta["status"] = "failed"
                print(f"[poll] FALHA ao publicar: {e}")
                tg.mark_message(chat, msg, f"⚠️ Falha ao publicar {post_id}:\n{str(e)[:700]}")
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    STATE_FILE.write_text(json.dumps(state))
    print("[poll] fim")


def cmd_preview(args):
    post = MOCK if args.mock else generate_post(args.funnel or "topo")
    paths = render_slides(post["slides"], QUEUE / "_preview")
    print("\n".join(map(str, paths)))
    print("\n" + full_caption(post))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate"); g.add_argument("--funnel", choices=["topo", "meio", "fundo"]); g.add_argument("--force", action="store_true")
    sub.add_parser("poll")
    p = sub.add_parser("preview"); p.add_argument("--mock", action="store_true"); p.add_argument("--funnel", choices=["topo", "meio", "fundo"])
    args = ap.parse_args()
    {"generate": cmd_generate, "poll": cmd_poll, "preview": cmd_preview}[args.cmd](args)


if __name__ == "__main__":
    main()
