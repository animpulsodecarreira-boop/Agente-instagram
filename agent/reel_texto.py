"""Reel de texto: o conteúdo do post vira cenas animadas, com o visual dos stories, no ritmo da leitura.

Cada slide do carrossel vira uma cena (capa, frase, antes/depois, lista, CTA). Como nos stories, cada cena é uma
página HTML com tudo já posicionado; a animação é uma lista de passos (JavaScript + duração), uma captura por passo.
O ffmpeg (video.py) junta as capturas em vídeo com a trilha.
"""
import html
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import ASSETS, LINK_LABEL
from .render_v2 import STORY_FIT_JS, STORY_JS, THEMES, clean, css

MAX_TOTAL = 40.0        # segundos: acima disso o robô acelera a leitura, enxuga frases e tira cenas do miolo
MIN_SCENE = 2.6
LOGO_T = 1.2
# (palavras por segundo, máximo de frases por cena): do ritmo confortável ao mais enxuto
PARAMS = [dict(wps=3.4, max_sent=3), dict(wps=3.8, max_sent=2), dict(wps=4.2, max_sent=2), dict(wps=4.6, max_sent=1)]

REEL_CSS = """
.story .rsb{display:flex;flex-direction:column;gap:30px;width:100%}
.story .rs{font-size:50px;line-height:1.35;font-weight:500}
.story .rs.hl{font-weight:700;color:var(--hl)}
.story .nb{flex:none;width:68px;height:68px;border-radius:50%;background:var(--accent);color:var(--numfg);font-weight:700;font-size:36px;display:flex;align-items:center;justify-content:center;margin-top:2px}
.story .ckrow.h{opacity:0}
"""

REEL_JS = """
function sent(n){$$('.rs').forEach((c,i)=>c.classList.toggle('h',i>=n))}
function rows(n){$$('.ckrow').forEach((c,i)=>c.classList.toggle('h',i>=n))}
"""

CAPS = re.compile(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ]{4,})\b")


def _words(t):
    return len(str(t or "").split())


def _read(text, P):
    """Tempo para ler um texto no ritmo escolhido (+ uma pausa)."""
    return max(1.0, round(_words(text) / P["wps"] + 0.4, 2))


def esc(t):
    return html.escape(clean(t))


def rich(t):
    """Texto seguro para HTML, com as palavras-chave em MAIÚSCULAS (ex.: QUERO) em destaque."""
    return CAPS.sub(r"<span class='amb'>\1</span>", esc(t))


def wd_html(text):
    """Palavra por palavra (aparecem uma a uma); palavras-chave em MAIÚSCULAS ficam em destaque."""
    out = []
    for w in clean(text).split():
        hl = " hl" if CAPS.fullmatch(re.sub(r"[.,!?:;]+$", "", w)) else ""
        out.append(f"<span class='wd h{hl}'>{html.escape(w)}</span>")
    return " ".join(out)


def _sentences(text, max_n):
    parts = []
    for para in re.split(r"\n\s*\n", clean(text)):
        parts += [p.strip() for p in re.split(r"(?<=[.!?])\s+", para) if p.strip()]
    merged = []
    for p in parts:
        if merged and _words(merged[-1]) < 4:   # frase curtíssima junta com a seguinte
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged[:max_n]


def _type_steps(nw, speed=4.2, k_max=6):
    k = max(1, min(k_max, nw))
    return [(f"words({max(1, round(nw * i / k))})", max(0.18, round((nw / k) / speed, 3))) for i in range(1, k + 1)]


# ---------------- cenas ----------------
def sc_titulo(s, P):
    title, body = clean(s.get("title")), clean(s.get("body"))
    nw = _words(title)
    inner = f"<div class='st' data-fit>{wd_html(title)}</div>"
    if body:
        inner += f"<div class='ss h' data-fit>{rich(body)}</div>"
    steps = [("words(0)", 0.15)] + _type_steps(nw)
    base = f"words({nw});"
    steps.append((base + ("show('.ss')" if body else ""), _read(body, P) if body else 0.8))
    steps.append((base + ("show('.ss');" if body else "") + "show('.slogo')", 1.0))
    return inner, steps


def sc_frase(s, P):
    title = clean(s.get("title"))
    hl = clean(s.get("highlight"))
    blocks = _sentences(s.get("body"), P["max_sent"]) + ([hl] if hl else [])
    nw = _words(title)
    size = "" if s.get("kind") == "quote" else " sm"
    inner = f"<div class='st{size}' data-fit>{wd_html(title)}</div>" if title else ""
    if blocks:
        inner += "<div class='rsb'>" + "".join(
            f"<div class='rs{' hl' if hl and i == len(blocks) - 1 else ''} h' data-fit>{rich(b)}</div>"
            for i, b in enumerate(blocks)) + "</div>"
    steps = [("words(0);sent(0)", 0.15)]
    if title:
        steps += [(f"{js};sent(0)", d) for js, d in _type_steps(nw)]
    for i, b in enumerate(blocks, 1):
        steps.append((f"words({nw});sent({i})", _read(b, P)))
    if not blocks:
        steps.append((f"words({nw})", 1.0))
    return inner, steps


def sc_versus(s, P):
    title, left, right = clean(s.get("title")), clean(s.get("left")), clean(s.get("right"))
    custom = bool(s.get("left_label") or s.get("right_label"))   # contraste que não é erro x acerto: sem riscar
    l1 = esc(clean(s.get("left_label")) or "EM VEZ DE").upper()
    l2 = esc(clean(s.get("right_label")) or "FAÇA ASSIM").upper()
    nw = _words(title)
    inner = (f"<div class='st sm' data-fit>{wd_html(title)}</div>"
             f"<div class='rcard r1'><div class='tag'>{l1}</div><div class='tx' data-fit><span class='sk'>{esc(left)}</span></div></div>"
             f"<div class='rcard r2 h'><div class='tag'>{l2}</div><div class='tx' data-fit>{esc(right)}</div></div>")
    steps = [("words(0)", 0.15)] + [(f"{js}", d) for js, d in _type_steps(nw)]
    base = f"words({nw});"
    steps.append((base, _read(left, P) + 0.3))
    if not custom:
        steps += [(base + f"strike({p})", 0.12) for p in (25, 55, 80, 100)]
    steps.append((base + "strike(100);dim()" if not custom else base + "dim()", 0.5))
    steps.append((base + ("strike(100);" if not custom else "") + "dim();show('.r2')", _read(right, P) + 0.6))
    return inner, steps


def sc_lista(s, P):
    kind = s.get("kind")
    title, note = clean(s.get("title")), clean(s.get("note"))
    items = [clean(x) for x in (s.get("items") or [])[:5] if clean(x)]
    nw = _words(title)

    def mark(i):
        return "<div class='ck'></div>" if kind == "check" else f"<div class='nb'>{i}</div>"
    rows = "".join(f"<div class='ckrow h'>{mark(i)}<div class='ckt' data-fit>{rich(x)}</div></div>" for i, x in enumerate(items, 1))
    inner = f"<div class='st sm' data-fit>{wd_html(title)}</div><div class='cl'>{rows}</div>"
    if note:
        inner += f"<div class='ss h' data-fit>{rich(note)}</div>"
    steps = [("words(0);rows(0)", 0.15)] + [(f"{js};rows(0)", d) for js, d in _type_steps(nw)]
    base = f"words({nw});"
    for i, x in enumerate(items, 1):
        if kind == "check":
            steps.append((base + f"rows({i});tick({i - 1})", 0.55))
            steps.append((base + f"rows({i});tick({i})", max(0.6, _read(x, P) - 0.5)))
        else:
            steps.append((base + f"rows({i})", _read(x, P)))
    n = len(items)
    tail = base + f"rows({n});" + (f"tick({n});" if kind == "check" else "")
    if note:
        steps.append((tail + "show('.ss')", _read(note, P)))
    return inner, steps


def sc_cta(s, P):
    title = clean(s.get("title"))
    blocks = _sentences(s.get("body"), P["max_sent"] + 1)
    nw = _words(title)
    inner = f"<div class='st' data-fit>{wd_html(title)}</div>" if title else ""
    if blocks:
        inner += "<div class='rsb'>" + "".join(f"<div class='rs h' data-fit>{rich(b)}</div>" for b in blocks) + "</div>"
    link = s.get("show_link", True) and clean(LINK_LABEL)
    if link:
        inner += f"<div class='pill h'>{esc(link)}</div>"
    steps = [("words(0);sent(0)", 0.15)]
    if title:
        steps += [(f"{js};sent(0)", d) for js, d in _type_steps(nw)]
    for i, b in enumerate(blocks, 1):
        steps.append((f"words({nw});sent({i})", _read(b, P)))
    base = f"words({nw});sent({len(blocks)});"
    if link:
        steps.append((base + "show('.pill')", 1.0))
    steps.append((base + ("show('.pill');" if link else "") + "show('.slogo')", 1.6))
    return inner, steps


BUILDERS = {"cover": sc_titulo, "content": sc_frase, "quote": sc_frase, "versus": sc_versus,
            "list": sc_lista, "check": sc_lista, "cta": sc_cta}


def _total(scenes):
    return sum(d for _, st in scenes for _, d in st)


def build_scenes(slides):
    """Monta as cenas no ritmo de leitura. Se passar de MAX_TOTAL: 1) acelera a leitura e enxuga as frases (4 níveis);
    2) se ainda passar, tira cenas do miolo (nunca a capa nem o CTA). Devolve (cenas, ritmo, quantas cenas saíram)."""
    if not slides:
        raise ValueError("Sem conteúdo para montar o Reel")
    for P in PARAMS:
        scenes = []
        for s in slides:
            inner, steps = BUILDERS.get(s.get("kind"), sc_frase)(s, P)
            total = sum(d for _, d in steps)
            if total < MIN_SCENE:
                js, d = steps[-1]
                steps[-1] = (js, round(d + MIN_SCENE - total, 3))
            steps[-1] = (steps[-1][0], round(steps[-1][1] + 0.3, 3))   # pausa antes da próxima cena
            scenes.append((inner, steps))
        if _total(scenes) <= MAX_TOTAL:
            break
    dropped = 0
    while _total(scenes) > MAX_TOTAL and len(scenes) > 3:
        del scenes[len(scenes) // 2]        # tira do meio, para manter a abertura e o fecho
        dropped += 1
    return scenes, P, dropped


def slides_from_caption(caption, topic=""):
    """Plano B para posts antigos (sem o conteúdo salvo): a legenda vira capa, frases e CTA."""
    text = re.sub(r"(?:\s*#\S+)+\s*$", "", str(caption or "").strip()).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()] or [topic or "Novo conteúdo"]
    slides = [{"kind": "cover", "title": paras[0]}]
    if len(paras) > 1:
        slides += [{"kind": "content", "title": "", "body": p} for p in paras[1:-1]]
        slides.append({"kind": "cta", "title": "", "body": paras[-1]})
    return slides


def render_reel_text(slides, theme, workdir: Path, capa: Path = None):
    """Renderiza as cenas e devolve a lista de quadros [(arquivo, segundos)] na ordem do vídeo.

    Se `capa` for dada, salva ali a capa do Reel (1080x1920): o título da primeira cena inteiro, com a marca,
    sem o subtítulo. Sem capa, o Instagram usa o primeiro quadro, que é quase vazio (só começa a escrever).
    """
    theme = theme if theme in THEMES else "escuro"
    scenes, P, dropped = build_scenes(slides)
    total = _total(scenes)
    print(f"[reel] {len(scenes)} cenas, {total:.0f}s de vídeo (ritmo {P['wps']} palavras/s, até {P['max_sent']} frases por cena)"
          + (f"; {dropped} cena(s) do miolo ficaram de fora para caber no limite" if dropped else ""), flush=True)
    workdir.mkdir(parents=True, exist_ok=True)
    t = THEMES[theme]
    frames = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--allow-file-access-from-files"])
        pg = browser.new_page()
        pg.set_viewport_size({"width": 1080, "height": 1920})
        for si, (inner, steps) in enumerate(scenes, 1):
            doc = (f"<html><head><meta charset='utf-8'><style>{css(theme)}{REEL_CSS}</style></head>"
                   f"<body class='story {theme}'><div class='sc'><div class='in'>{inner}</div></div>"
                   f"<img class='slogo h' src='file://{ASSETS}/{t['logo']}'><script>{STORY_JS}{REEL_JS}</script></body></html>")
            f = workdir / f"cena{si}.html"
            f.write_text(doc, encoding="utf-8")
            pg.goto(f"file://{f}")
            pg.wait_for_timeout(250)
            pg.evaluate(STORY_FIT_JS)
            for k, (js, dur) in enumerate(steps):
                pg.evaluate("() => {" + js + "}")
                fp = workdir / f"c{si}_{k:03d}.png"
                pg.screenshot(path=str(fp))
                frames.append((fp, round(dur, 3)))
            if capa and si == 1:   # estado final da primeira cena, já com o título completo e a marca
                try:
                    pg.evaluate("() => {document.querySelectorAll('.ss').forEach(e => e.classList.add('h'))}")
                    Path(capa).parent.mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(capa))
                except Exception as e:   # a capa é um extra: se falhar, o Reel segue sem ela
                    print(f"[reel] não consegui gerar a capa: {e}", flush=True)
            f.unlink()
        browser.close()
    return frames
