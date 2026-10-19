"""Gera o conteúdo do carrossel (slides + legenda) com a API gratuita do Gemini."""
import json
import os
import time

import requests

from .config import (FUNNEL, GEMINI_MODELS, HISTORY_FILE, MAX_HASHTAGS, MAX_SLIDES,
                     MIN_SLIDES, MISSIONS, OFFER, BRAND_NAME)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM = f"""Você é o estrategista de conteúdo de Instagram da marca "{BRAND_NAME}", consultoria de posicionamento
profissional no LinkedIn para pessoas em transição/recolocação. Escreva em português do Brasil, tom humano,
direto e acolhedor, sem jargão e sem promessas de resultado garantido.

REGRAS DE CONTEÚDO
- Nunca invente estatísticas, depoimentos, nomes ou resultados. Use só afirmações que sejam generalizações seguras.
- Nada de promessas como "garanto emprego". Fale de clareza, posicionamento e percepção do perfil.
- Não repita temas já usados (lista abaixo).
- Títulos curtos (até 70 caracteres). Corpo de slide até 230 caracteres. Frases curtas.

ESTRUTURA DO CARROSSEL ({MIN_SLIDES} a {MAX_SLIDES} slides, nesta lógica)
1. cover: gancho forte e curioso (title) + subtítulo curto (body).
2. content (2 a 4 slides): um ponto por slide. Pode usar "highlight" para uma frase final de impacto.
3. Opcional: 1 slide check (checklist com 3 a 4 itens em "items" e "note" pedindo para salvar).
4. content de conexão: começa com "E aqui está o ponto:".
5. cta: pergunta final (title) + chamada (body). Para topo, peça para comentar "QUERO", salvar e compartilhar.
   Para meio, chame para a DM. Para fundo, mencione a oferta e o link na bio.

LEGENDA: 1ª linha é um gancho forte; corpo curto; pedido de salvar/compartilhar/comentar; até 1500 caracteres.
HASHTAGS: de 6 a {MAX_HASHTAGS}, sem espaços, em português e relevantes ao LinkedIn/carreira.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "topic": {"type": "STRING"},
        "slides": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "kind": {"type": "STRING", "enum": ["cover", "content", "check", "cta"]},
            "title": {"type": "STRING"}, "body": {"type": "STRING"},
            "highlight": {"type": "STRING"}, "note": {"type": "STRING"},
            "items": {"type": "ARRAY", "items": {"type": "STRING"}},
        }, "required": ["kind", "title"]}},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["topic", "slides", "caption", "hashtags"],
}


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(topic, funnel):
    h = load_history()
    h.append({"topic": topic, "funnel": funnel})
    HISTORY_FILE.write_text(json.dumps(h[-60:], ensure_ascii=False, indent=2), encoding="utf-8")


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
    tags = ["#" + t.lstrip("#").replace(" ", "") for t in post["hashtags"]][:MAX_HASHTAGS]
    post["hashtags"] = tags
    assert len(post["caption"]) <= 1800, "legenda longa demais"
    return post


def generate_post(funnel, extra_instruction=""):
    used = [h["topic"] for h in load_history()[-40:]]
    prompt = (
        f"Crie o carrossel de hoje.\nEtapa do funil: {funnel.upper()} -> {FUNNEL[funnel]}\n"
        f"Missão do post: {MISSIONS[funnel]}\nOferta (só use em post de FUNDO): {OFFER}\n"
        f"Temas já usados (NÃO repetir): {json.dumps(used, ensure_ascii=False)}\n{extra_instruction}"
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
