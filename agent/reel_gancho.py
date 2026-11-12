"""Reel de gancho: um roteiro curto, em formatos conhecidos de vídeo curto, vira cenas rápidas de texto.

Diferente do Reel de texto (que lê o carrossel slide por slide), aqui o Gemini escreve um roteiro PRÓPRIO para o Reel, com base
no tema do post: um gancho de abertura que já aparece inteiro no primeiro quadro, 2 a 3 cenas com pouquíssimas palavras e
uma chamada final. Formatos: lista, mito x verdade, pare de..., antes e depois, erro nº 1 e POV.
Se o Gemini falhar ou a resposta não passar na validação, o chamador usa o Reel de texto de sempre.
"""
import html
import json
import os
import re
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from .config import ASSETS, BANNED_PHRASES, BRAND_NAME, GEMINI_MODELS, LINK_LABEL
from .generate import API, _extract
from .reel_texto import rich
from .render_v2 import STORY_FIT_JS, STORY_JS, THEMES, clean, css

MAX_TOTAL = 28.0          # segundos: acima disso o robô tira o texto de apoio e depois acelera
READ_WPS = 4.2            # palavras por segundo na leitura (mais rápido que o Reel de texto antigo)
DEADLINE = 200            # segundos no total para falar com o Gemini
EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200d]")

FORMATOS = {
    "lista": ("Lista curta com número no gancho. O gancho promete N coisas (N = número de cenas, 3). "
              "Cada cena: rotulo = o número (\"1\", \"2\", \"3\"), texto = o item em poucas palavras, apoio = por que importa. "
              "Estilo de exemplo: gancho \"3 sinais de que seu LinkedIn está invisível\"."),
    "mito": ("Mito contra verdade. O gancho afirma ou questiona o mito. Cenas (3): rotulo \"MITO\" com o mito; rotulo \"VERDADE\" "
             "com a correção; rotulo \"NA PRÁTICA\" com uma ação simples. Estilo: gancho \"Isso é o maior mito do currículo\"."),
    "pare": ("Pare de... O gancho começa com \"Pare de\" + um hábito ruim, sem agressividade. Cenas (3): rotulo \"FAÇA ASSIM\" "
             "(o que fazer no lugar), rotulo \"POR QUÊ\" (a razão em linguagem simples), rotulo \"HOJE\" (uma ação de 5 minutos)."),
    "antes_depois": ("Antes e depois. O gancho convida a ver a diferença. Cenas (2): cada uma tem antes (a versão fraca, que será "
                     "riscada) e texto (a versão melhor), rotulo \"ANTES / DEPOIS\", apoio opcional curto. Use exemplos genéricos, "
                     "nunca de uma pessoa real."),
    "erro": ("O erro número 1. O gancho diz \"O erro nº 1 em\" + o assunto. Cenas (3): rotulo \"O ERRO\", rotulo \"POR QUE ATRAPALHA\", "
             "rotulo \"CORRIJA ASSIM\"."),
    "pov": ("POV, para gerar identificação. O gancho começa com \"POV:\" e descreve a situação de quem está em transição ou "
            "buscando emprego. Cenas (3): rotulo \"A VIRADA\" (a percepção), rotulo \"FAÇA ISSO\" (o ajuste), rotulo \"DEPOIS\" "
            "(o que muda na forma como o perfil é lido, SEM prometer resultado)."),
}
ORDEM = list(FORMATOS)

SYSTEM = f"""Você escreve roteiros de Reels de TEXTO NA TELA, muito rápidos, para a marca "{BRAND_NAME}" (consultoria de posicionamento
profissional no LinkedIn para pessoas em transição ou recolocação). O texto precisa prender nos 2 primeiros segundos e ser entendido
de relance, com pouquíssimas palavras.

Regras de texto (obrigatórias): português do Brasil correto e natural, revisado; gancho com no máximo 9 palavras; texto de cada
cena com no máximo 8 palavras; apoio com no máximo 12 palavras; chamada final com no máximo 7 palavras. Frases curtas, palavras
simples, sem jargão. Sem emojis, sem hashtags, sem markdown.

Regras da marca (obrigatórias): use SOMENTE o conteúdo do post fornecido; não invente fatos, estatísticas, pesquisas, casos ou
nomes; nenhuma promessa de resultado (nada de "garanto", "você vai conseguir"); para leis, direitos, prazos, valores e saúde use
só afirmações gerais. Não ataque pessoas nem empresas.
Evite estas fórmulas repetitivas: {"; ".join(BANNED_PHRASES)}."""

SCHEMA = {"type": "OBJECT", "properties": {
    "gancho": {"type": "STRING"}, "destaque": {"type": "STRING"},
    "cenas": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "rotulo": {"type": "STRING"}, "antes": {"type": "STRING"}, "texto": {"type": "STRING"}, "apoio": {"type": "STRING"}},
        "required": ["rotulo", "texto"]}},
    "chamada": {"type": "STRING"}, "palavra_chave": {"type": "STRING"},
}, "required": ["gancho", "cenas", "chamada"]}

CSS_G = """
.rg .in{gap:40px}
.rg .g0{opacity:0;transform-origin:left center}
.rg .chip{display:inline-block;font-size:34px;font-weight:700;letter-spacing:4px;background:var(--chipbg);color:var(--chipfg);padding:14px 32px;border-radius:44px}
.rg .bign{font-size:230px;font-weight:700;color:var(--accent);line-height:.95;letter-spacing:-6px}
.rg .tx{font-size:104px;line-height:1.1;font-weight:700;letter-spacing:-1.5px;overflow-wrap:anywhere}
.rg .tx.big{font-size:126px}
.rg .tx.old{font-size:70px;color:var(--muted);font-weight:500;text-decoration:line-through;text-decoration-color:rgba(229,100,92,0);text-decoration-thickness:8px}
.rg .tx.old.x{text-decoration-color:#E5645C;opacity:.55 !important}
.rg .ap{font-size:50px;line-height:1.3;color:var(--muted);font-weight:500}
.rg .hl,.rg .amb{color:var(--hl)}
.rg .pill{font-size:42px;font-weight:700;background:var(--chipbg);color:var(--chipfg);padding:24px 48px;border-radius:60px}
.rg .dots{position:absolute;left:0;right:0;top:1390px;text-align:center;font-size:0}
.rg .dots i{display:inline-block;width:20px;height:20px;border-radius:50%;margin:0 11px;background:var(--muted);opacity:.35}
.rg .dots i.on{background:var(--accent);opacity:1;width:46px;border-radius:12px}
"""
JS_G = """
function pose(s,o,y,sc){$$(s).forEach(e=>{e.style.opacity=o;e.style.transform='translateY('+y+'px) scale('+sc+')'})}
function swap(){$$('.l1').forEach(e=>e.style.opacity=0);}
"""


# ---------------- roteiro (Gemini) ----------------
def _gemini_json(prompt, system=None, schema=None, deadline=None, max_tokens=4096):
    key = os.environ["GEMINI_API_KEY"]
    inicio, erros = time.time(), []
    limite = deadline or DEADLINE
    for volta in range(2):
        for model in GEMINI_MODELS:
            sobra = limite - (time.time() - inicio)
            if sobra < 25:
                raise RuntimeError("Gemini (roteiro do Reel) sem tempo: " + " | ".join(erros[-3:])[-400:])
            body = {"systemInstruction": {"parts": [{"text": system or SYSTEM}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema or SCHEMA,
                                         "temperature": 0.8, "maxOutputTokens": max_tokens}}
            try:
                r = requests.post(API.format(model=model), params={"key": key}, json=body,
                                  timeout=(15, max(20, min(75, sobra - 5))))
            except requests.exceptions.RequestException as e:
                erros.append(f"{model}: {type(e).__name__}")
                print(f"[reel-gancho] {erros[-1]}", flush=True)
                continue
            if r.status_code == 200:
                texto, why = _extract(r.json())
                if texto:
                    try:
                        return json.loads(texto)
                    except ValueError:
                        why = "JSON inválido"
                erros.append(f"{model}: {why}")
            else:
                erros.append(f"{model}: HTTP {r.status_code}")
            print(f"[reel-gancho] {erros[-1]}", flush=True)
        if volta == 0:
            time.sleep(15)
    raise RuntimeError("Gemini (roteiro do Reel) falhou: " + " | ".join(erros[-3:])[-400:])


def _txt(t):
    return re.sub(r"\s+", " ", EMOJI.sub("", clean(t))).strip()


def _nw(t):
    return len(_txt(t).split())


def validar(r, formato):
    if not isinstance(r, dict):
        return "resposta inválida"
    cenas = r.get("cenas") or []
    esperado = 2 if formato == "antes_depois" else 3
    if not _txt(r.get("gancho")) or _nw(r["gancho"]) > 12:
        return "gancho vazio ou longo demais"
    if not (esperado - 1 <= len(cenas) <= esperado + 1):
        return f"número de cenas inesperado ({len(cenas)})"
    for c in cenas:
        if not _txt(c.get("texto")) or _nw(c["texto"]) > 11:
            return "texto de cena vazio ou longo demais"
        if _nw(c.get("apoio")) > 16:
            return "apoio longo demais"
        if formato == "antes_depois" and not _txt(c.get("antes")):
            return "cena de antes e depois sem o 'antes'"
    if not _txt(r.get("chamada")) or _nw(r["chamada"]) > 10:
        return "chamada vazia ou longa demais"
    return None


def criar_roteiro(slides, meta, seed):
    """Escolhe o formato (girando entre os 6) e pede o roteiro ao Gemini. Devolve (formato, roteiro)."""
    n = int.from_bytes(__import__("hashlib").sha1(str(seed).encode()).digest()[:4], "big")
    ordem = ORDEM[n % len(ORDEM):] + ORDEM[:n % len(ORDEM)]
    partes = []
    for s in slides or []:
        t = " ".join(_txt(s.get(k)) for k in ("title", "body", "left", "right", "highlight", "note") if _txt(s.get(k)))
        itens = " ".join(_txt(x) for x in (s.get("items") or []))
        if t or itens:
            partes.append((t + " " + itens).strip())
    base = " | ".join(partes)[:1800] or _txt(meta.get("caption"))[:1200]
    ultimo = ""
    for formato in ordem[:2]:   # se o primeiro formato não passar na validação, tenta o seguinte
        prompt = (f"Formato: {formato}. {FORMATOS[formato]}\n\nTema do post: {_txt(meta.get('topic'))}\n"
                  f"Conteúdo do post (use só isto): {base}\n\n"
                  "Campos: gancho; destaque (UMA palavra do gancho para realçar em cor); cenas; chamada (convite final curto, "
                  "ex.: \"Comenta QUERO e eu te mando\" com a palavra-chave em MAIÚSCULAS); palavra_chave (a mesma da chamada).")
        r = _gemini_json(prompt)
        ultimo = validar(r, formato)
        if not ultimo:
            return formato, r
        print(f"[reel-gancho] formato {formato} reprovado na validação: {ultimo}", flush=True)
    raise RuntimeError(f"roteiro do Reel reprovado: {ultimo}")


# ---------------- cenas ----------------
def _hl(texto, destaque):
    t = _txt(texto)
    d = _txt(destaque).strip(".,!?:;")
    esc = html.escape(t)
    if d:
        esc = re.sub(re.escape(html.escape(d)), lambda m: f"<span class='hl'>{m.group(0)}</span>", esc, count=1, flags=re.I)
    return esc


def _tempos(roteiro, wps, com_apoio):
    """Duração de cada parte, no ritmo de leitura escolhido."""
    gancho = max(1.9, round(_nw(roteiro["gancho"]) / wps + 0.8, 2))
    cenas = []
    for c in roteiro["cenas"]:
        principal = max(1.6, round(_nw(c["texto"]) / wps + 0.6, 2))
        antes = max(1.0, round(_nw(c.get("antes")) / wps + 0.5, 2)) if _txt(c.get("antes")) else 0.0
        apoio = max(1.0, round(_nw(c.get("apoio")) / wps + 0.5, 2)) if (com_apoio and _txt(c.get("apoio"))) else 0.0
        cenas.append((antes, principal, apoio))
    cta = 2.8
    total = gancho + sum(a + p + b + 0.2 for a, p, b in cenas) + cta
    return gancho, cenas, cta, total


def montar(roteiro):
    """Define o ritmo para caber em MAX_TOTAL: 1) acelera a leitura; 2) tira o texto de apoio; 3) corta cenas do fim."""
    r = dict(roteiro)
    r["cenas"] = list(roteiro["cenas"])
    for wps, apoio in ((READ_WPS, True), (5.0, True), (5.0, False)):
        t = _tempos(r, wps, apoio)
        if t[3] <= MAX_TOTAL:
            return r, t, wps, apoio
    while len(r["cenas"]) > 2:
        r["cenas"].pop()
        t = _tempos(r, 5.0, False)
        if t[3] <= MAX_TOTAL:
            break
    return r, t, 5.0, False


def _dots(i, n):
    return "<div class='dots'>" + "".join(f"<i class='{'on' if k == i else ''}'></i>" for k in range(n)) + "</div>"


def _pagina(theme, corpo, logo_t):
    return (f"<html><head><meta charset='utf-8'><style>{css(theme)}{CSS_G}</style></head>"
            f"<body class='story rg {theme}'>{corpo}<img class='slogo h' src='file://{ASSETS}/{logo_t}'>"
            f"<script>{STORY_JS}{JS_G}</script></body></html>")


def render_reel_gancho(roteiro, theme, workdir: Path, capa: Path = None, mostrar_link: bool = True):
    """Renderiza as cenas e devolve ([(quadro, segundos)], segundos totais, roteiro usado)."""
    theme = theme if theme in THEMES else "escuro"
    r, (t_gancho, t_cenas, t_cta, total), wps, com_apoio = montar(roteiro)
    t = THEMES[theme]
    destaque = r.get("destaque", "")
    n = len(r["cenas"])
    cenas = []   # (html interno, extras fora do .sc, passos)

    # gancho: já aparece inteiro no primeiro quadro (só um "pulo" de 0,1 s), sem fade nem escrita palavra por palavra
    cenas.append((f"<div class='tx big g0' data-fit>{_hl(r['gancho'], destaque)}</div>", "",
                  [("pose('.tx',.9,12,.94)", 0.04), ("pose('.tx',1,0,1.035)", 0.06), ("pose('.tx',1,0,1)", t_gancho - 0.1)]))

    for i, c in enumerate(r["cenas"]):
        antes_t, prin_t, apo_t = t_cenas[i]
        rotulo = _txt(c.get("rotulo")).upper()
        eh_num = bool(re.fullmatch(r"\d", rotulo))
        topo = f"<div class='bign g0 l0'>{rotulo}</div>" if eh_num else (f"<div class='chip g0 l0'>{html.escape(rotulo)}</div>" if rotulo else "")
        antes = _txt(c.get("antes"))
        corpo = topo
        if antes:
            corpo += f"<div class='tx old g0 l1' data-fit>{html.escape(antes)}</div>"
        corpo += f"<div class='tx g0 mn' data-fit>{html.escape(_txt(c['texto']))}</div>"
        apoio = _txt(c.get("apoio")) if apo_t else ""
        if apoio:
            corpo += f"<div class='ap g0 apo' data-fit>{html.escape(apoio)}</div>"
        p = [("pose('.l0',.6,14,.96)", 0.05)]
        if antes:   # versão fraca aparece, é riscada, e só então entra a versão melhor
            p += [("pose('.l0',1,0,1);pose('.l1',.8,16,.97)", 0.05), ("pose('.l1',1,0,1)", antes_t),
                  ("document.querySelector('.l1').classList.add('x')", 0.45),
                  ("pose('.mn',.7,24,.97)", 0.05), ("pose('.mn',1,-6,1.02)", 0.05), ("pose('.mn',1,0,1)", prin_t)]
        else:
            p += [("pose('.l0',1,0,1);pose('.mn',.7,24,.97)", 0.05), ("pose('.mn',1,-6,1.02)", 0.05), ("pose('.mn',1,0,1)", prin_t)]
        if apoio:
            p += [("pose('.apo',.7,10,1)", 0.05), ("pose('.apo',1,0,1)", apo_t)]
        p[-1] = (p[-1][0], round(p[-1][1] + 0.2, 3))   # respiro antes do corte para a próxima cena
        cenas.append((corpo, _dots(i, n) if n > 1 else "", p))

    cta = f"<div class='tx g0 mn' data-fit>{rich(r['chamada'])}</div>"
    link = clean(LINK_LABEL) if mostrar_link else ""   # posts de topo não pedem nada: sem botão de link
    if link:
        cta += f"<div class='pill g0 pl'>{html.escape(link)}</div>"
    pc = [("pose('.mn',.8,18,.95)", 0.05), ("pose('.mn',1,0,1)", 0.9 if link else t_cta - 0.1)]
    if link:
        pc += [("pose('.pl',.8,14,.96)", 0.05), ("pose('.pl',1,0,1);show('.slogo')", t_cta - 1.0)]
    else:
        pc[-1] = (pc[-1][0] + ";show('.slogo')", t_cta - 0.1)
    cenas.append((cta, "", pc))

    frames = []
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--allow-file-access-from-files"])
        pg = browser.new_page()
        pg.set_viewport_size({"width": 1080, "height": 1920})
        for si, (inner, extra, passos) in enumerate(cenas, 1):
            f = workdir / f"g{si}.html"
            f.write_text(_pagina(theme, f"<div class='sc'><div class='in'>{inner}</div></div>{extra}", t["logo"]), encoding="utf-8")
            pg.goto(f"file://{f}")
            pg.wait_for_timeout(200)
            pg.evaluate(STORY_FIT_JS)
            for k, (js, dur) in enumerate(passos):
                pg.evaluate("() => {" + js + "}")
                fp = workdir / f"g{si}_{k:03d}.png"
                pg.screenshot(path=str(fp))
                frames.append((fp, round(max(0.04, dur), 3)))
            if capa and si == 1:   # capa = o gancho completo, com a marca
                try:
                    pg.evaluate("() => {show('.slogo')}")
                    Path(capa).parent.mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(capa))
                except Exception as e:
                    print(f"[reel-gancho] não consegui gerar a capa: {e}", flush=True)
            f.unlink()
        browser.close()
    soma = sum(d for _, d in frames)
    print(f"[reel-gancho] {len(cenas)} cenas, {soma:.0f}s de vídeo (ritmo {wps} palavras/s"
          + ("" if com_apoio else ", sem texto de apoio") + ")", flush=True)
    return frames, soma, r
