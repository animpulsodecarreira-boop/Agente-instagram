"""Gera o conteúdo (carrossel + stories + legenda) com a API gratuita do Gemini."""
import json
import os
import time

import requests

from .config import (BANNED_PHRASES, BRAND_NAME, CTAS, FORMATS, FUNNEL, GEMINI_MODELS, HISTORY_FILE, HOOKS,
                     KEYWORDS, MAX_HASHTAGS, MAX_SLIDES, MIN_SLIDES, MISSIONS, OFFER, THEMES)

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
- cover: gancho (title) + subtítulo curto (body). Sempre o PRIMEIRO.
- content: um ponto por slide (title + body; "highlight" opcional = frase final de impacto).
- quote: frase de impacto grande (title) + apoio curto (body).
- versus: contraste "em vez de / faça assim": title + left (o erro, curto) + right (a melhor versão, curta).
- list: título + items (3 a 4 passos curtos, até 70 caracteres cada).
- check: checklist (title + items com 3 a 4 itens + note curta).
- cta: chamada final (title + body). Sempre o ÚLTIMO.
Monte de 5 a 8 slides. A receita do dia (formato, gancho e CTA) vem na mensagem do usuário: SIGA-A. Cada post deve
parecer diferente dos anteriores: varie o jeito de abrir, de transicionar e de fechar. O slide de conexão é OPCIONAL
e, se usar, nunca repita a mesma frase de transição dos posts anteriores.
Não escreva "Salva este post" ou pedidos de salvar em todo post: peça só quando fizer sentido para a receita do dia.
Exemplos e casos devem ser FICTÍCIOS e identificados como exemplo ("Imagine...", "Por exemplo:"). Nunca apresente um caso inventado como real.

STORIES (campo "stories", exatamente 2, para acompanhar o post):
1. kind "frase" (uma frase de impacto, title até 80 caracteres) ou "pergunta" (pergunta que gera resposta por DM). body opcional curto.
2. kind "teaser": convida a ver o novo post no feed (title = gancho curto; body = convite curto, diferente a cada dia).

LEGENDA: 1ª linha é um gancho forte e diferente das anteriores; corpo curto; termine com a chamada do CTA da receita (não repita o mesmo pedido todo dia); até 1500 caracteres.
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


def save_history(topic, funnel, theme="", extra=None):
    h = load_history()
    entry = {"topic": topic, "funnel": funnel, "theme": theme}
    entry.update(extra or {})
    h.append(entry)
    HISTORY_FILE.write_text(json.dumps(h[-120:], ensure_ascii=False, indent=2), encoding="utf-8")


def _lru(options, key, history=None):
    """Escolhe a opção usada há mais tempo (nunca usadas primeiro; nunca repete a última)."""
    hist = [h[key] for h in (history if history is not None else load_history()) if h.get(key) is not None]
    last = hist[-1] if hist else None
    pool = [o for o in options if o != last] or list(options)

    def age(o):  # índice da última vez usada (-1 = nunca usada)
        return max((i for i, v in enumerate(hist) if v == o), default=-1)
    return min(pool, key=lambda o: (age(o), options.index(o)))


def pick_theme():
    return _lru(THEMES, "theme")


def pick_variant():
    return _lru([0, 1, 2], "variant")


def pick_recipe(funnel):
    """Sorteia a 'receita' do post: formato, gancho, estilo de CTA e palavra-chave."""
    hist = load_history()
    fmt = _lru([k for k, v in FORMATS.items() if funnel in v["funnels"]], "format", hist)
    hook = _lru(HOOKS, "hook", hist)
    cta_opts = CTAS[funnel]
    cta = _lru(cta_opts, "cta", hist)
    kw = _lru(KEYWORDS, "keyword", hist)
    return {"format": fmt, "hook": hook, "cta": cta, "keyword": kw}


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


def validate(post, strict=True):
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
    if strict:
        blob = " ".join([post["caption"]] + [x["title"] + " " + x.get("body", "") + " " + x.get("highlight", "") for x in s]).lower()
        hit = [p for p in BANNED_PHRASES if p in blob]
        assert not hit, f"usou fórmulas repetidas: {hit}"
    return post


def generate_post(funnel, extra_instruction=""):
    hist = load_history()
    used = [h["topic"] for h in hist[-40:]]
    recent_hooks = [h.get("cover") for h in hist[-14:] if h.get("cover")]
    recent_openers = [h.get("opener") for h in hist[-14:] if h.get("opener")]
    recipe = pick_recipe(funnel)
    fmt = FORMATS[recipe["format"]]
    cta = recipe["cta"].replace("{kw}", f"“{recipe['keyword']}”")
    prompt = (
        f"Crie o conteúdo de hoje.\nEtapa do funil: {funnel.upper()} -> {FUNNEL[funnel]}\n"
        f"Missão do post: {MISSIONS[funnel]}\nOferta (só use em post de FUNDO): {OFFER}\n\n"
        f"RECEITA DO DIA (siga):\n- Formato: {fmt['nome']}. Plano dos slides: {fmt['plano']}\n"
        f"- Estilo do gancho da capa: {recipe['hook']}\n- CTA do último slide: {cta}\n\n"
        f"Temas já usados (NÃO repetir): {json.dumps(used, ensure_ascii=False)}\n"
        f"Capas recentes (NÃO usar estrutura parecida): {json.dumps(recent_hooks, ensure_ascii=False)}\n"
        f"Aberturas de legenda recentes (NÃO repetir o jeito de começar): {json.dumps(recent_openers, ensure_ascii=False)}\n"
        f"Frases PROIBIDAS (já ficaram repetitivas): {json.dumps(BANNED_PHRASES, ensure_ascii=False)}\n"
        f"{extra_instruction}"
    )
    last_err = None
    for attempt in range(3):  # se a validação falhar, pede de novo
        post = call_gemini(prompt)
        try:
            post = validate(post, strict=attempt < 2)  # na última tentativa aceita, para não ficar sem post
            post["funnel"] = funnel
            last = post["slides"][-1]
            last["show_link"] = funnel == "fundo" or "link" in (last.get("body", "") + last["title"]).lower()
            post["recipe"] = recipe
            post["cover"] = post["slides"][0]["title"]
            post["opener"] = post["caption"].strip().split("\n")[0][:120]
            return post
        except (AssertionError, KeyError) as e:
            last_err = e
            prompt += f"\nA tentativa anterior falhou na validação ({e}). Corrija."
    raise RuntimeError(f"Conteúdo inválido após 3 tentativas: {last_err}")
