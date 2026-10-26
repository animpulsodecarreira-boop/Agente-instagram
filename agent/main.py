"""Uso:
  python -m agent.main generate [--funnel topo|meio|fundo]   # gera post + story, renderiza e manda pro Telegram
  python -m agent.main poll                                  # lê aprovações e publica
  python -m agent.main approve --post-id ID [--action ap|po|rj]   # aprova/reprocessa um post pelo GitHub
  python -m agent.main preview [--mock] [--theme escuro] [--variant 0|1|2] [--story digitar|riscar|chat|checklist|nota|pergunta|teaser|all]   # teste local
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
from .config import QUEUE, STATE_FILE, STORY_FORMATS, THEMES
from .generate import generate_post, pick_theme, pick_variant, save_history
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
        {"kind": "riscar", "title": "Título do LinkedIn", "antes": "Analista Administrativo",
         "depois": "Analista Administrativo | Rotinas financeiras e processos"},
    ],
    "caption": "Seu LinkedIn diz o que você faz? 👀\n\nDesliza e confere.\n\nComenta QUERO e salva este post.",
    "hashtags": ["#LinkedIn", "#Carreira", "#PosicionamentoProfissional"],
}

# Um exemplo de cada formato de story (para `preview --story ...`)
STORY_SAMPLES = {
    "digitar": {"kind": "digitar", "title": "Seu perfil fala por você quando você não está na sala.", "highlight": "não está na sala"},
    "riscar": {"kind": "riscar", "title": "Título do LinkedIn", "antes": "Analista Administrativo",
               "depois": "Analista Administrativo | Rotinas financeiras e processos"},
    "chat": {"kind": "chat", "title": "Entrevista", "messages": [
        {"quem": "outro", "texto": "Me conta um pouco sobre você."},
        {"quem": "voce", "texto": "Trabalho há 6 anos com rotinas financeiras e quero migrar para análise de dados."},
        {"quem": "outro", "texto": "E o que você já fez nessa direção?"}]},
    "checklist": {"kind": "checklist", "title": "Antes de mandar o currículo:",
                  "items": ["Revisei o título do perfil", "Conferi datas e cargos", "Salvei em PDF"], "body": "Marca aí o que você já faz."},
    "nota": {"kind": "nota", "title": "Lembrete", "items": ["Você não é o seu cargo.", "Seu perfil é um resumo, não um currículo.", "Clareza vale mais que volume."]},
    "pergunta": {"kind": "pergunta", "title": "Qual foi o último ajuste que você fez no seu perfil?", "body": "Me conta por DM, eu respondo."},
    "teaser": {"kind": "teaser", "title": "Cargo não é posicionamento.", "body": "Veja o novo post no feed agora."},
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
        theme, variant = pick_theme(), pick_variant()
        out = QUEUE / post_id
        paths, clips = render_all(post["slides"], post["stories"], out, theme, variant)
        videos = [make_story_video(c, out / f"story{i}.mp4", f"{post_id}-{i}") for i, c in enumerate(clips, 1)]
        shutil.rmtree(out / "_frames", ignore_errors=True)  # quadros intermediários não vão para o repositório
        cap = full_caption(post)
        src = post["story_recipe"]
        meta = {"id": post_id, "status": "pending", "funnel": funnel, "theme": theme, "variant": variant, "topic": post["topic"],
                "caption": cap, "slides": len(paths), "stories": len(videos),
                "story_format": src["format"], "story_mode": src["mode"]}
        (out / "post.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        rc = post["recipe"]
        save_history(post["topic"], funnel, theme, {
            "variant": variant, "format": rc["format"], "hook": rc["hook"], "cta": rc["cta"], "keyword": rc["keyword"],
            "cover": post["cover"], "opener": post["opener"],
            "story_format": src["format"], "story_mode": src["mode"], "story_title": post["stories"][0]["title"][:90]})
        if os.getenv("SKIP_TELEGRAM") != "1":
            tg.send_for_approval(post_id, paths, cap, funnel, theme, videos)
        print(f"Post {post_id} gerado ({funnel}, formato {post['recipe']['format']}, estilo {theme}/v{variant}, "
              f"story {src['format']}/{src['mode']}): {post['topic']}")
    except Exception:
        err = tg.redact(traceback.format_exc())
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


def _report(chat, msg, text):
    if chat is not None and msg is not None:
        try:
            tg.mark_message(chat, msg, text)
            return
        except Exception as e:  # mensagem antiga/apagada não pode derrubar o robô
            print(f"[poll] não consegui editar a mensagem do Telegram ({e}); enviando aviso novo")
    tg.notify(text)


def process_action(action, post_id, chat=None, msg=None, retry=False, cb_id=None):
    """Aplica aprovar/só post/rejeitar a um post. retry=True permite reprocessar um post que falhou."""
    from .instagram import permalink, publish_carousel
    meta_file = QUEUE / post_id / "post.json"
    if not meta_file.exists():
        existing = sorted(d.name for d in QUEUE.iterdir() if d.is_dir() and not d.name.startswith("_")) if QUEUE.exists() else []
        print(f"[poll] post {post_id} NÃO existe em queue/. Existentes: {existing}")
        if cb_id:
            tg.answer(cb_id, "Post não encontrado.")
        _report(chat, msg, f"⚠️ Não encontrei o post {post_id} no repositório (pode ter sido removido ou não foi salvo).")
        return
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    ok_states = ("pending", "failed") if retry else ("pending",)
    if meta["status"] not in ok_states:
        print(f"[poll] post {post_id} está '{meta['status']}', nada a fazer")
        if cb_id:
            tg.answer(cb_id, f"Já processado ({meta['status']}).")
        return
    if action == "rj":
        meta["status"] = "rejected"
        print(f"[poll] post {post_id} rejeitado")
        if cb_id:
            tg.answer(cb_id, "Rejeitado.")
        _report(chat, msg, f"❌ Post {post_id} rejeitado. Nada foi publicado.")
    elif action in ("ap", "po"):
        if cb_id:
            tg.answer(cb_id, "Aprovado! Publicando...")
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
            _report(chat, msg, report)
        except Exception as e:
            meta["status"] = "failed"
            print(f"[poll] FALHA ao publicar: {e}")
            _report(chat, msg, f"⚠️ Falha ao publicar {post_id}:\n{str(e)[:700]}\n\nPara tentar de novo: Actions → Aprovar post → informe {post_id}.")
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_poll(_args):
    me = tg.get_me()
    print(f"[poll] bot: @{me.get('username')}")
    posts = {p.parent.name: json.loads(p.read_text(encoding="utf-8")).get("status") for p in sorted(QUEUE.glob("*/post.json"))}
    print(f"[poll] posts no repositório: {posts or 'nenhum'}")
    # Sem offset salvo: pede tudo o que o Telegram ainda não confirmou. Seguro porque cada post só é
    # processado uma vez (o status muda de 'pending'). Só confirma os toques no FINAL da execução.
    updates = tg.get_updates(0)
    print(f"[poll] atualizações recebidas do Telegram: {len(updates)} (ids: {[u['update_id'] for u in updates]})")
    max_id = None
    for u in updates:
        max_id = u["update_id"]
        cb = u.get("callback_query")
        if not cb:
            print(f"[poll] update {u['update_id']} ignorado (não é toque em botão)")
            continue
        if str(cb["message"]["chat"]["id"]) != str(tg.chat_id()):
            print(f"[poll] toque ignorado: chat {cb['message']['chat']['id']} não é o seu")
            continue
        action, _, post_id = cb["data"].partition(":")
        print(f"[poll] toque encontrado: ação={action} post={post_id}")
        process_action(action, post_id, cb["message"]["chat"]["id"], cb["message"]["message_id"], cb_id=cb["id"])
    if max_id is not None:
        tg.get_updates(max_id + 1)  # confirma os toques já tratados
    print("[poll] fim")


def cmd_approve(args):
    """Aprovação manual pelo GitHub (Actions → Aprovar post). Também reprocessa posts que falharam."""
    print(f"[approve] post={args.post_id} ação={args.action}")
    process_action(args.action, args.post_id.strip(), retry=True)
    print("[approve] fim")


def cmd_preview(args):
    post = dict(MOCK if args.mock else generate_post(args.funnel or "topo"))
    if args.story:
        post["stories"] = list(STORY_SAMPLES.values()) if args.story == "all" else [STORY_SAMPLES[args.story]]
    theme = args.theme or pick_theme()
    variant = args.variant if args.variant is not None else pick_variant()
    out = QUEUE / "_preview"
    paths, clips = render_all(post["slides"], post["stories"], out, theme, variant)
    vids = [make_story_video(c, out / f"story{i}.mp4", f"prev-{i}") for i, c in enumerate(clips, 1)]
    shutil.rmtree(out / "_frames", ignore_errors=True)
    print("\n".join(map(str, paths + [c["png"] for c in clips] + vids)))
    print(f"\nEstilo: {theme}/v{variant}\n\n" + full_caption(post))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate"); g.add_argument("--funnel", choices=["topo", "meio", "fundo"])
    sub.add_parser("poll")
    ap_ = sub.add_parser("approve"); ap_.add_argument("--post-id", required=True); ap_.add_argument("--action", choices=["ap", "po", "rj"], default="ap")
    p = sub.add_parser("preview"); p.add_argument("--mock", action="store_true"); p.add_argument("--funnel", choices=["topo", "meio", "fundo"]); p.add_argument("--theme", choices=THEMES); p.add_argument("--variant", type=int, choices=[0, 1, 2]); p.add_argument("--story", choices=list(STORY_FORMATS) + ["all"])
    args = ap.parse_args()
    {"generate": cmd_generate, "poll": cmd_poll, "approve": cmd_approve, "preview": cmd_preview}[args.cmd](args)


if __name__ == "__main__":
    main()
