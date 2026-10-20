"""Uso:
  python -m agent.main generate [--funnel topo|meio|fundo]   # gera post + stories, renderiza e manda pro Telegram
  python -m agent.main poll                                  # lê aprovações e publica
  python -m agent.main preview [--mock] [--theme escuro]     # só gera/renderiza localmente (teste)
"""
import argparse
import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import telegram_io as tg
from .config import QUEUE, STATE_FILE, THEMES
from .generate import generate_post, pick_theme, save_history
from .render_v2 import render_all
from .video import make_story_video

TZ = ZoneInfo("America/Sao_Paulo")

MOCK = {
    "topic": "Teste de layout", "funnel": "topo",
    "slides": [
        {"kind": "cover", "title": "Seu LinkedIn diz o que você faz ou só o seu cargo?", "body": "Pequenos ajustes mudam a percepção do recrutador."},
        {"kind": "content", "title": "Cargo não é posicionamento.", "body": "“Analista Administrativo” descreve uma função, mas não mostra a área em que você atua.", "highlight": "Clareza vence quantidade."},
        {"kind": "versus", "title": "Como escrever o seu título", "left": "Analista Administrativo", "right": "Analista Administrativo | Rotinas financeiras e processos"},
        {"kind": "list", "title": "3 ajustes rápidos no Sobre", "items": ["Diga quem você é em uma frase", "Mostre no que você é bom", "Feche com o tipo de oportunidade que busca"]},
        {"kind": "quote", "title": "Recrutador não lê o perfil. Ele escaneia.", "body": "Nos primeiros segundos, o título decide se ele continua."},
        {"kind": "cta", "title": "Quer saber o que está enfraquecendo o seu LinkedIn?", "body": "Comenta QUERO que eu te mostro o que observar.\n\nSalva e manda para quem precisa."},
    ],
    "stories": [
        {"kind": "pergunta", "title": "Seu título diz o que você faz?", "body": "Me conta seu cargo e eu dou uma ideia de ajuste."},
        {"kind": "teaser", "title": "Cargo não é posicionamento.", "body": "Veja o novo post no feed agora."},
    ],
    "caption": "Seu LinkedIn diz o que você faz? 👀\n\nDesliza e confere.\n\nComenta QUERO e salva este post.",
    "hashtags": ["#LinkedIn", "#Carreira", "#PosicionamentoProfissional"],
}


def full_caption(post):
    return post["caption"].strip() + "\n\n" + " ".join(post["hashtags"])


def raw_url(post_id, filename):
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.getenv("REPO_BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/queue/{post_id}/{filename}"


def funnel_by_hour(hour):
    """08h topo, 12h30 meio, 18h fundo (usado quando você roda manualmente sem escolher)."""
    return "topo" if hour < 11 else "meio" if hour < 16 else "fundo"


def prune(days=10):
    """Remove pastas antigas já resolvidas (mantém o repositório leve)."""
    if not QUEUE.exists():
        return
    limit = datetime.now(TZ) - timedelta(days=days)
    for d in QUEUE.iterdir():
        meta = d / "post.json"
        if not d.is_dir() or d.name.startswith("_") or not meta.exists():
            continue
        try:
            when = datetime.strptime(d.name[:13], "%Y%m%d-%H%M").replace(tzinfo=TZ)
        except ValueError:
            continue
        if when < limit and json.loads(meta.read_text(encoding="utf-8")).get("status") != "pending":
            shutil.rmtree(d, ignore_errors=True)


def cmd_generate(args):
    now = datetime.now(TZ)
    funnel = args.funnel or funnel_by_hour(now.hour)
    post_id = now.strftime("%Y%m%d-%H%M")
    try:
        prune()
        post = generate_post(funnel)
        theme = pick_theme()
        out = QUEUE / post_id
        paths, story_pngs = render_all(post["slides"], post["stories"], out, theme)
        videos = [make_story_video(png, out / f"story{i}.mp4", f"{post_id}-{i}") for i, png in enumerate(story_pngs, 1)]
        cap = full_caption(post)
        meta = {"id": post_id, "status": "pending", "funnel": funnel, "theme": theme, "topic": post["topic"],
                "caption": cap, "slides": len(paths), "stories": len(videos)}
        (out / "post.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        save_history(post["topic"], funnel, theme)
        if os.getenv("SKIP_TELEGRAM") != "1":
            tg.send_for_approval(post_id, paths, cap, funnel, theme, videos)
        print(f"Post {post_id} gerado ({funnel}, estilo {theme}): {post['topic']}")
    except Exception:
        err = traceback.format_exc()
        print(err, file=sys.stderr)
        if os.getenv("SKIP_TELEGRAM") != "1":
            tg.notify(f"⚠️ O agente falhou ao gerar o post ({funnel}):\n{err[-800:]}")
        sys.exit(1)


def publish_stories(post_id, n):
    """Publica os stories em sequência. Tenta vídeo; se falhar, tenta a imagem. Retorna (ok, relatório)."""
    from .instagram import publish_story
    done, notes = 0, []
    for i in range(1, n + 1):
        try:
            publish_story(video_url=raw_url(post_id, f"story{i}.mp4"))
            print(f"[poll] story {i} publicado em vídeo")
            done += 1
            continue
        except Exception as e:
            print(f"[poll] story {i}: vídeo falhou ({e}); tentando imagem")
            video_err = str(e)[:200]
        try:
            publish_story(image_url=raw_url(post_id, f"story{i}.png"))
            print(f"[poll] story {i} publicado como imagem (sem música)")
            done += 1
            notes.append(f"story {i}: saiu como imagem (vídeo falhou: {video_err})")
        except Exception as e:
            print(f"[poll] story {i} FALHOU: {e}")
            notes.append(f"story {i}: falhou ({str(e)[:200]})")
    return done, notes


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
        elif action in ("ap", "po"):
            tg.answer(cb["id"], "Aprovado! Publicando...")
            try:
                urls = [raw_url(post_id, f"slide{i}.png") for i in range(1, meta["slides"] + 1)]
                print(f"[poll] publicando {len(urls)} imagens, primeira: {urls[0]}")
                media_id = publish_carousel(urls, meta["caption"])
                meta["status"], meta["media_id"] = "published", media_id
                report = f"✅ Post {post_id} publicado!\n{permalink(media_id)}"
                if action == "ap" and meta.get("stories"):
                    done, notes = publish_stories(post_id, meta["stories"])
                    meta["stories_published"] = done
                    report += f"\n🎬 Stories: {done}/{meta['stories']} publicados"
                    if notes:
                        report += "\n" + "\n".join(notes)
                tg.mark_message(chat, msg, report)
            except Exception as e:
                meta["status"] = "failed"
                print(f"[poll] FALHA ao publicar: {e}")
                tg.mark_message(chat, msg, f"⚠️ Falha ao publicar {post_id}:\n{str(e)[:700]}")
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    STATE_FILE.write_text(json.dumps(state))
    print("[poll] fim")


def cmd_preview(args):
    post = MOCK if args.mock else generate_post(args.funnel or "topo")
    theme = args.theme or pick_theme()
    out = QUEUE / "_preview"
    paths, story_pngs = render_all(post["slides"], post["stories"], out, theme)
    vids = [make_story_video(p, out / f"story{i}.mp4", f"prev-{i}") for i, p in enumerate(story_pngs, 1)]
    print("\n".join(map(str, paths + story_pngs + vids)))
    print(f"\nEstilo: {theme}\n\n" + full_caption(post))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate"); g.add_argument("--funnel", choices=["topo", "meio", "fundo"])
    sub.add_parser("poll")
    p = sub.add_parser("preview"); p.add_argument("--mock", action="store_true"); p.add_argument("--funnel", choices=["topo", "meio", "fundo"]); p.add_argument("--theme", choices=THEMES)
    args = ap.parse_args()
    {"generate": cmd_generate, "poll": cmd_poll, "preview": cmd_preview}[args.cmd](args)


if __name__ == "__main__":
    main()
