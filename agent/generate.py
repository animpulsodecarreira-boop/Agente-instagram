"""Gera o conteúdo (carrossel + stories + legenda) com a API gratuita do Gemini."""
import json
import os
import random
import time

import requests

from .config import (BANNED_PHRASES, BRAND_NAME, CTAS, FORMATS, FUNNEL, GEMINI_MODELS, HISTORY_FILE, HOOKS,
                     KEYWORDS, MAX_HASHTAGS, MAX_SLIDES, MIN_SLIDES, MISSIONS, OFFER, STORY_FORMATS, STORY_MODES,
                     STORY_MODE_TEXT, THEMES, PILLARS, LEVE_BANNED, LEVE_HOOKS, LEVE_THEMES)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM = f"""Você é o estrategista de conteúdo de Instagram da marca "{BRAND_NAME}", consultoria de posicionamento
profissional no LinkedIn para pessoas em transição/recolocação. Escreva em português do Brasil, tom humano,
direto e acolhedor, sem jargão e sem promessas de resultado garantido. NÃO use markdown (nada de ** ou #) nos textos dos slides.
Parte dos posts trata de temas profissionais em geral (currículo, entrevista, rotina, comunicação, negociação, aprendizado),
sempre com o olhar de quem ajuda pessoas a se posicionarem melhor no mercado. O PILAR do dia vem na mensagem do usuário: SIGA-O.

MODO LEVE (quando a etapa do funil for LEVE, aos fins de semana): tom de conversa de amigo, humor suave e acolhedor, frases curtas,
sem jargão de carreira. NÃO venda nada: nada de diagnóstico, consultoria, link na bio, palavra-chave de oferta nem LinkedIn.
Nunca faça piada com quem está desempregado ou buscando recolocação, com grupos de pessoas, com cargos ou com empresas reais;
sem estereótipos. Sem estatísticas, estudos, livros, filmes ou autores citados. O objetivo é identificação, um sorriso e conversa.
No modo leve o CTA é só interação (comentar, marcar alguém, salvar para a segunda).

REGRAS DE CONTEÚDO
- Nunca invente estatísticas, depoimentos, nomes ou resultados. Use só generalizações seguras.
- Nada de promessas como "garanto emprego". Fale de clareza, posicionamento e percepção do perfil.
- Não repita temas já usados (lista abaixo).
- Títulos curtos (até 70 caracteres). Corpo de slide até 230 caracteres. Frases curtas.

TIPOS DE SLIDE (campo "kind")
- cover: gancho (title) + subtítulo curto (body). Sempre o PRIMEIRO.
- content: um ponto por slide (title + body; "highlight" opcional = frase final de impacto).
- quote: frase de impacto grande (title) + apoio curto (body).
- versus: contraste "em vez de / faça assim": title + left (o erro, curto) + right (a melhor versão, curta). Opcional: left_label e right_label (até 18 caracteres, em maiúsculas) para trocar os rótulos, quando o contraste não for erro x acerto (ex.: 'DOMINGO À NOITE' / 'SEGUNDA CEDO').
- list: título + items (3 a 4 passos curtos, até 70 caracteres cada).
- check: checklist (title + items com 3 a 4 itens + note curta).
- cta: chamada final (title + body). Sempre o ÚLTIMO.
Monte de 5 a 8 slides. A receita do dia (formato, gancho e CTA) vem na mensagem do usuário: SIGA-A. Cada post deve
parecer diferente dos anteriores: varie o jeito de abrir, de transicionar e de fechar. O slide de conexão é OPCIONAL
e, se usar, nunca repita a mesma frase de transição dos posts anteriores.
Não escreva "Salva este post" ou pedidos de salvar em todo post: peça só quando fizer sentido para a receita do dia.
Exemplos e casos devem ser FICTÍCIOS e identificados como exemplo ("Imagine...", "Por exemplo:"). Nunca apresente um caso inventado como real.

STORY (campo "stories": EXATAMENTE 1 item). Não é um slide do carrossel: é uma conversa rápida de 8 segundos, com UMA ideia só,
tom de amigo que entende do assunto, frases curtas, sem tom de anúncio e sem listas longas. O tipo (kind), o modo e os limites de
cada campo vêm na receita do dia: SIGA-OS. Conversas e exemplos são FICTÍCIOS e nunca prometem resultado.

LEGENDA: 1ª linha é um gancho forte e diferente das anteriores; corpo curto; termine com a chamada do CTA da receita (não repita o mesmo pedido todo dia); até 1500 caracteres.
HASHTAGS: de 6 a {MAX_HASHTAGS}, sem espaços, em português, relevantes ao tema do dia e à carreira (#LinkedIn só se o tema ou o post citar a plataforma).
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
            "left_label": {"type": "STRING"}, "right_label": {"type": "STRING"},
            "items": {"type": "ARRAY", "items": {"type": "STRING"}},
        }, "required": ["kind", "title"]}},
        "stories": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "kind": {"type": "STRING", "enum": list(STORY_FORMATS)},
            "title": {"type": "STRING"}, "body": {"type": "STRING"}, "highlight": {"type": "STRING"},
            "antes": {"type": "STRING"}, "depois": {"type": "STRING"}, "outro_label": {"type": "STRING"},
            "items": {"type": "ARRAY", "items": {"type": "STRING"}},
            "messages": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "quem": {"type": "STRING", "enum": ["outro", "voce"]}, "texto": {"type": "STRING"},
            }, "required": ["quem", "texto"]}},
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


def hist_for(funnel, hist=None):
    """O modo leve (fim de semana) tem rotação própria: não se mistura com o histórico dos posts de semana."""
    hist = load_history() if hist is None else hist
    leve = funnel == "leve"
    return [h for h in hist if (h.get("funnel") == "leve") == leve]


def pick_theme(funnel=None):
    return _lru(LEVE_THEMES if funnel == "leve" else THEMES, "theme", hist_for(funnel))


def pick_variant(funnel=None):
    return _lru([0, 1, 2], "variant", hist_for(funnel))


def pick_pillar(funnel, hist=None, rng=random):
    """Sorteia o pilar do post por peso, respeitando as etapas do funil.
    Não repete pilares dos 2 últimos posts (o LinkedIn só fica de fora se saiu nos 2 últimos)."""
    hist = load_history() if hist is None else hist
    cands = {k: v for k, v in PILLARS.items() if funnel in v["funnels"]}
    recent = [h.get("pillar") for h in hist[-2:] if h.get("pillar")]
    pool = {k: v for k, v in cands.items() if k not in recent or (k == "linkedin" and recent.count("linkedin") < 2)}
    pool = pool or cands
    keys = list(pool)
    return rng.choices(keys, weights=[pool[k]["weight"] for k in keys])[0]


def pick_recipe(funnel, pillar="linkedin", hist=None):
    """Sorteia a 'receita' do post: formato, gancho, estilo de CTA e palavra-chave."""
    hist = load_history() if hist is None else hist
    fmts = [k for k, v in FORMATS.items() if funnel in v["funnels"] and (not v.get("pillars") or pillar in v["pillars"])]
    fmt = _lru(fmts, "format", hist)
    hook = _lru(LEVE_HOOKS if funnel == "leve" else HOOKS, "hook", hist)
    cta_opts = CTAS[funnel]
    cta = _lru(cta_opts, "cta", hist)
    kw = _lru(KEYWORDS, "keyword", hist)
    return {"format": fmt, "hook": hook, "cta": cta, "keyword": kw}


def pick_story_recipe(funnel, post_format, hist=None):
    """Sorteia o modo (acompanha/paralela) e o formato do story, respeitando a tabela de compatibilidade."""
    hist = load_history() if hist is None else hist
    mode = _lru(STORY_MODES, "story_mode", hist)
    cands = [k for k, v in STORY_FORMATS.items()
             if funnel in v["funnels"] and mode in v["modes"]
             and (mode == "paralela" or not v["post_formats"] or post_format in v["post_formats"])]
    fmt = _lru(cands or ["digitar"], "story_format", hist)
    return {"mode": mode, "format": fmt}


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


def validate_story(st, kind):
    """Confere o story do tipo sorteado. Levanta AssertionError se estiver fora do combinado."""
    st = dict(st)
    assert st.get("kind") == kind, f"o story deveria ser do tipo '{kind}'"
    st["title"] = st["title"].strip()
    assert st["title"] and len(st["title"]) <= 110, "título de story vazio ou longo demais"
    if kind == "digitar":
        if st.get("highlight", "").strip() not in st["title"]:
            st["highlight"] = ""  # destaque que não está na frase: ignora
    elif kind == "riscar":
        assert st.get("antes", "").strip() and st.get("depois", "").strip(), "riscar precisa de antes e depois"
        assert len(st["antes"]) <= 110 and len(st["depois"]) <= 120, "antes/depois longos demais"
    elif kind == "chat":
        if len(st.get("outro_label", "")) > 20:
            st["outro_label"] = ""
        m = st.get("messages") or []
        assert 2 <= len(m) <= 4, "chat precisa de 2 a 4 mensagens"
        for x in m:
            assert x.get("quem") in ("outro", "voce") and x.get("texto", "").strip(), "mensagem inválida"
            assert len(x["texto"]) <= 130, "mensagem longa demais"
    elif kind == "checklist":
        assert 3 <= len(st.get("items") or []) <= 4, "checklist precisa de 3 ou 4 itens"
        assert all(len(i) <= 70 for i in st["items"]), "item longo demais"
    elif kind == "nota":
        assert 2 <= len(st.get("items") or []) <= 4, "nota precisa de 2 a 4 linhas"
        assert all(len(i) <= 80 for i in st["items"]), "linha da nota longa demais"
    return st


def fallback_story(post):
    """Story de segurança (teaser do post) se o Gemini errar o formato na última tentativa."""
    return {"kind": "teaser", "title": post["slides"][0]["title"][:80], "body": "Veja o novo post no feed agora."}


def validate(post, strict=True, story_kind=None, pillar=None, funnel=None):
    s = post["slides"]
    assert MIN_SLIDES <= len(s) <= MAX_SLIDES, f"{len(s)} slides"
    assert s[0]["kind"] == "cover" and s[-1]["kind"] == "cta", "primeiro deve ser cover e último cta"
    for x in s:
        assert len(x["title"]) <= 110, "título longo demais"
        assert len(x.get("body", "")) <= 400, "corpo longo demais"
        if x["kind"] == "versus":
            assert x.get("left") and x.get("right"), "versus precisa de left e right"
            for lab in ("left_label", "right_label"):
                if len(x.get(lab, "")) > 20:
                    x[lab] = ""  # rótulo longo demais: volta ao padrão
        if x["kind"] in ("list", "check"):
            assert 3 <= len(x.get("items", [])) <= 5, f"{x['kind']} precisa de 3 a 5 itens"
    tags = ["#" + t.lstrip("#").replace(" ", "") for t in post["hashtags"]][:MAX_HASHTAGS]
    post["hashtags"] = tags
    assert len(post["caption"]) <= 1800, "legenda longa demais"
    st = post.get("stories") or []
    assert len(st) >= 1, "faltam stories"
    try:
        story = validate_story(st[0], story_kind or st[0]["kind"])
    except (AssertionError, KeyError):
        if strict:
            raise
        story = fallback_story(post)  # última tentativa: não fica sem story
    post["stories"] = [story]
    if strict:
        if pillar and PILLARS[pillar]["capa_sem_linkedin"]:
            assert "linkedin" not in s[0]["title"].lower(), "a capa de um tema fora do LinkedIn não deve citar o LinkedIn"
        sblob = " ".join(str(v) for v in story.values() if isinstance(v, (str, list)))
        blob = " ".join([post["caption"], sblob] + [x["title"] + " " + x.get("body", "") + " " + x.get("highlight", "") for x in s]).lower()
        hit = [p for p in BANNED_PHRASES if p in blob]
        assert not hit, f"usou fórmulas repetidas: {hit}"
        if funnel == "leve":
            sales = [w for w in LEVE_BANNED if w in blob]
            assert not sales, f"o modo leve não pode citar: {sales}"
    return post


def generate_post(funnel, extra_instruction=""):
    hist_all = load_history()
    used = [h["topic"] for h in hist_all[-40:]]
    hist = hist_for(funnel, hist_all)  # semana e fim de semana giram separados
    recent_hooks = [h.get("cover") for h in hist[-14:] if h.get("cover")]
    recent_openers = [h.get("opener") for h in hist[-14:] if h.get("opener")]
    recent_stories = [h.get("story_title") for h in hist[-14:] if h.get("story_title")]
    pillar = pick_pillar(funnel, hist)
    pl = PILLARS[pillar]
    recipe = pick_recipe(funnel, pillar, hist)
    story_rc = pick_story_recipe(funnel, recipe["format"], hist)
    sf = STORY_FORMATS[story_rc["format"]]
    fmt = FORMATS[recipe["format"]]
    cta = recipe["cta"].replace("{kw}", f"“{recipe['keyword']}”")
    leve = funnel == "leve"
    offer_line = ("Oferta: NÃO mencione oferta, diagnóstico, consultoria, link na bio nem palavra-chave.\n\n" if leve
                  else f"Oferta (só use em post de FUNDO): {OFFER}\n\n")
    pillar_rule = "- Modo LEVE: não cite LinkedIn nem a consultoria; humor suave e acolhedor.\n" if leve else "" if pillar == "linkedin" else (
        "- Este pilar NÃO é sobre LinkedIn: o post fala do tema profissional em geral. Cite o LinkedIn só na ponte, "
        "de forma natural e curta (no máximo em um slide) ou não cite. A missão do funil vale, aplicada a este tema.\n"
        + ("- NÃO use a palavra LinkedIn na capa.\n" if pl["capa_sem_linkedin"] else ""))
    prompt = (
        f"Crie o conteúdo de hoje.\nEtapa do funil: {funnel.upper()} -> {FUNNEL[funnel]}\n"
        f"Missão do post: {MISSIONS[funnel]}\n{offer_line}"
        f"PILAR DO DIA: {pl['nome']}. {pl['descricao']}\n"
        f"- Ângulos possíveis (escolha UM que ainda não foi usado): {'; '.join(pl['angulos'])}\n"
        f"- Ponte com a marca: {pl['ponte']}\n"
        f"{pillar_rule}"
        f"\nRECEITA DO DIA (siga):\n- Formato: {fmt['nome']}. Plano dos slides: {fmt['plano']}\n"
        f"- Estilo do gancho da capa: {recipe['hook']}\n- CTA do último slide: {cta}\n\n"
        f"RECEITA DO STORY (exatamente 1 story de 8 segundos):\n"
        f"- Tipo: {sf['nome']} (kind \"{story_rc['format']}\"). {sf['instrucao']}\n"
        f"- Modo: {STORY_MODE_TEXT[story_rc['mode']]}\n"
        f"- Stories recentes (NÃO repetir ideia nem estrutura): {json.dumps(recent_stories, ensure_ascii=False)}\n\n"
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
            post = validate(post, strict=attempt < 2, story_kind=story_rc["format"], pillar=pillar, funnel=funnel)  # na última tentativa aceita, para não ficar sem post
            post["funnel"] = funnel
            last = post["slides"][-1]
            last["show_link"] = funnel != "leve" and (funnel == "fundo" or "link" in (last.get("body", "") + last["title"]).lower())
            post["recipe"] = recipe
            post["pillar"] = pillar
            post["story_recipe"] = {**story_rc, "format": post["stories"][0]["kind"]}  # reflete o fallback, se houve
            post["cover"] = post["slides"][0]["title"]
            post["opener"] = post["caption"].strip().split("\n")[0][:120]
            return post
        except (AssertionError, KeyError) as e:
            last_err = e
            prompt += f"\nA tentativa anterior falhou na validação ({e}). Corrija."
    raise RuntimeError(f"Conteúdo inválido após 3 tentativas: {last_err}")
