"""Gera o conteúdo (carrossel + stories + legenda) com a API gratuita do Gemini."""
import json
import os
import time

import requests

from .config import (BRAND_NAME, FUNNEL, GEMINI_MODELS, HISTORY_FILE, MAX_HASHTAGS, MAX_SLIDES,
                     MIN_SLIDES, MISSIONS, OFFER, THEMES)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM = f"""Você é o estrategista de conteúdo de Instagram da marca "{BRAND_NAME}", consultoria de posicionamento
profissional no LinkedIn para pessoas em transição/recolocação. Escreva em português do Brasil, tom humano,
direto e acolhedor, sem jargão e sem promessas de resultado garantido. NÃO use markdown (nada de ** ou #) nos textos dos slides.

REGRAS DE CONTEÚDO
- Nunca invente estatísticas, depoimentos, nomes ou resultados. Use só generalizações seguras.
- Nada de promessas como "garanto emprego". Fale de clareza, posicionamento e percepção do perfil.
- Não repita temas já usados (lista abaixo).
- Títulos curtos (até 70 caracteres). Corpo de slide até 230 caracteres. Frases curtas.

TIPOS DE SLIDE (campo "kind")
- cover: gancho forte e curioso (title) + subtítulo curto (body). Sempre o PRIMEIRO.
- content: um ponto por slide (title + body; "highlight" opcional = frase final de impacto).
- quote: frase de impacto grande (title) + apoio curto (body). Ótimo para uma verdade incômoda.
- versus: contraste "em vez de / faça assim": title + left (o erro, curto) + right (a melhor versão, curta).
- list: título + items (3 a 4 passos curtos, até 70 caracteres cada).
- check: checklist (title + items com 3 a 4 itens + note pedindo para salvar).
- cta: pergunta final (title) + chamada (body). Sempre o ÚLTIMO.
Monte {MIN_SLIDES} a {MAX_SLIDES} slides, de cover a cta. USE VARIEDADE: inclua pelo menos 2 tipos diferentes entre
content, quote, versus, list e check. Se houver um slide de conexão, comece com "E aqui está o ponto:".
CTA por etapa: TOPO pede comentar "QUERO", salvar e compartilhar; MEIO chama para a DM; FUNDO apresenta a oferta e o link na bio.

STORIES (campo "stories", exatamente 2, para acompanhar o post):
1. kind "frase" (uma frase de impacto, title até 80 caracteres) ou "pergunta" (pergunta que gera resposta por DM). body opcional curto.
2. kind "teaser": convida a ver o novo post no feed (title = gancho curto; body = "Veja o novo post no feed agora.").

LEGENDA: 1ª linha é um gancho forte; corpo curto; pedido de salvar/compartilhar/comentar; até 1500 caracteres.
HASHTAGS: de 6 a {MAX_HASHTAGS}, sem espaços, em português e relevantes ao LinkedIn/carreira.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "topic": {"type": "STRING"},
        "slides": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "kind": {"type": "STRING", "enum": ["cover", "content", "quote", "versus", "list", "check", "cta"]},
            "title": {"type": "STRING"}, "body": {"type": "STRING"},
            "highlight": {"type": "STRING"}, "note": {"type": "STRING"},
            "left": {"type": "STRING"}, "right": {"type": "STRING"},
            "items": {"type": "ARRAY", "items": {"type": "STRING"}},
        }, "required": ["kind", "title"]}},
        "stories": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "kind": {"type": "STRING", "enum": ["frase", "pergunta", "teaser"]},
            "title": {"type": "STRING"}, "body": {"type": "STRING"},
        }, "required": ["kind", "title"]}},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["topic", "slides", "stories", "caption", "hashtags"],
}


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(topic, funnel, theme=""):
    h = load_history()
    h.append({"topic": topic, "funnel": funnel, "theme": theme})
    HISTORY_FILE.write_text(json.dumps(h[-90:], ensure_ascii=False, indent=2), encoding="utf-8")


def pick_theme():
    """Escolhe o estilo visual menos usado recentemente (nunca repete o último)."""
    recent = [h.get("theme") for h in load_history() if h.get("theme")]
    last = recent[-1] if recent else None
    candidates = [t for t in THEMES if t != last]
    return min(candidates, key=lambda t: (recent[-8:].count(t), THEMES.index(t)))


def call_gemini(prompt):
    key = os.environ["GEMINI_API_KEY"]
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                             "temperature": 0.9},
    }
    last = None
    for model in GEMINI_MODELS:
        for attempt in range(3):
            try:
                r = requests.post(API.format(model=model), params={"key": key}, json=body, timeout=(15, 240))
            except requests.exceptions.RequestException as e:  # timeout, conexão caiu etc.
                last = f"{model}: {type(e).__name__}"
                time.sleep(2 ** attempt * 5)
                continue
            if r.status_code == 200:
                data = r.json()
                try:
                    return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
                except (KeyError, IndexError, json.JSONDecodeError) as e:
                    last = f"{model}: resposta inválida ({e})"
                    break
            last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
            if r.status_code in (429, 500, 503):
                time.sleep(2 ** attempt * 5)
                continue
            break  # erro não recuperável neste modelo -> tenta o próximo
    raise RuntimeError(f"Gemini falhou: {last}")


def validate(post):
    s = post["slides"]
    assert MIN_SLIDES <= len(s) <= MAX_SLIDES, f"{len(s)} slides"
    assert s[0]["kind"] == "cover" and s[-1]["kind"] == "cta", "primeiro deve ser cover e último cta"
    for x in s:
        assert len(x["title"]) <= 110, "título longo demais"
        assert len(x.get("body", "")) <= 400, "corpo longo demais"
        if x["kind"] == "versus":
            assert x.get("left") and x.get("right"), "versus precisa de left e right"
        if x["kind"] in ("list", "check"):
            assert 3 <= len(x.get("items", [])) <= 5, f"{x['kind']} precisa de 3 a 5 itens"
    tags = ["#" + t.lstrip("#").replace(" ", "") for t in post["hashtags"]][:MAX_HASHTAGS]
    post["hashtags"] = tags
    assert len(post["caption"]) <= 1800, "legenda longa demais"
    st = post.get("stories") or []
    assert len(st) >= 1, "faltam stories"
    st = st[:2]
    if st[-1]["kind"] != "teaser":  # garante o teaser "novo post no feed" por último
        teaser = {"kind": "teaser", "title": post["slides"][0]["title"][:80], "body": "Veja o novo post no feed agora."}
        if len(st) >= 2:
            st[-1] = teaser
        else:
            st.append(teaser)
    for x in st:
        assert len(x["title"]) <= 120, "título de story longo demais"
    post["stories"] = st
    return post


def generate_post(funnel, extra_instruction=""):
    used = [h["topic"] for h in load_history()[-40:]]
    today = [h["topic"] for h in load_history()[-3:]]
    prompt = (
        f"Crie o conteúdo de hoje.\nEtapa do funil: {funnel.upper()} -> {FUNNEL[funnel]}\n"
        f"Missão do post: {MISSIONS[funnel]}\nOferta (só use em post de FUNDO): {OFFER}\n"
        f"Temas já usados (NÃO repetir): {json.dumps(used, ensure_ascii=False)}\n"
        f"Os posts mais recentes foram: {json.dumps(today, ensure_ascii=False)} — escolha um ângulo diferente.\n"
        f"{extra_instruction}"
    )
    last_err = None
    for _ in range(3):  # se a validação falhar, pede de novo
        post = call_gemini(prompt)
        try:
            post = validate(post)
            post["funnel"] = funnel
            return post
        except (AssertionError, KeyError) as e:
            last_err = e
            prompt += f"\nA tentativa anterior falhou na validação ({e}). Corrija."
    raise RuntimeError(f"Conteúdo inválido após 3 tentativas: {last_err}")
