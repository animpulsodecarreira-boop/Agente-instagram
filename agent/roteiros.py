"""Roteiros de vídeo com o seu rosto, no modelo YAP: gancho + dois pontos + fecho, para falar com as próprias palavras.

Uso: python -m agent.roteiros [--qtd 1]
Todo dia de manhã o robô escolhe os temas (pilar e ângulo menos usados nos roteiros anteriores), pede ao Gemini os roteiros
e manda ao Telegram. Estes vídeos são separados dos Reels que o agente monta: você grava e publica pelo celular.
O histórico fica em roteiros.json, para os temas não se repetirem.
"""
import argparse
import json
import os
import random
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import telegram_io as tg
from .config import BANNED_PHRASES, BRAND_NAME, GEMINI_MODELS, HISTORY_FILE, KEYWORDS, PILLARS
from .generate import API, _extract

TZ = ZoneInfo("America/Sao_Paulo")
ROTEIROS_FILE = HISTORY_FILE.parent / "roteiros.json"
DEADLINE = 300          # segundos no total para falar com o Gemini
PALAVRAS_POR_SEGUNDO = 2.7   # ritmo de fala natural, para estimar a duração

GANCHOS = [
    "pergunta direta que gera identificação",
    "erro comum que muita gente comete (sem acusar)",
    "mito contra verdade",
    "pare de fazer isso (sem agressividade)",
    "uma observação do dia a dia de quem busca emprego",
    "algo que quase ninguém conta sobre o tema",
]

SYSTEM = f"""Você escreve ROTEIROS-GUIA de vídeo curto (Reels) para quem vai gravar com o próprio rosto, pela marca "{BRAND_NAME}",
consultoria de posicionamento profissional no LinkedIn para pessoas em transição ou recolocação.

MODELO YAP: o vídeo é uma conversa simples e orgânica com a câmera, não um texto decorado. A estrutura é só esta:
GANCHO (a frase de abertura, forte nos 3 primeiros segundos) + PONTO 1 + PONTO 2 + FECHO. Quem grava vai falar com as
próprias palavras, então escreva como a pessoa FALA, não como escreve.

Regras de fala: português do Brasil, informal e acolhedor, frases curtas (no máximo 15 palavras), sem jargão, sem "Olá
pessoal", sem enrolação. O gancho deve ter no máximo 14 palavras e entrar direto no assunto. Cada ponto tem 1 ou 2 frases.
O roteiro todo (gancho, pontos e fecho) deve ter entre 60 e 95 palavras, para caber em 25 a 40 segundos falados.

Regras da marca (obrigatórias): nada de estatística, pesquisa ou caso inventado apresentado como real; nenhum "cliente meu
conseguiu..."; nenhuma promessa de resultado (nada de "garanto", "você vai conseguir a vaga"); para leis, direitos, prazos,
valores e saúde, use só afirmações gerais e convide a confirmar em fonte oficial. Não fale mal de pessoas nem de empresas.
Sem markdown, sem asteriscos, sem hashtags dentro do texto falado. Revise a ortografia e a gramática antes de responder.
Evite estas fórmulas que ficaram repetitivas: {"; ".join(BANNED_PHRASES)}."""

ITEM = {"type": "OBJECT", "properties": {
    "tema": {"type": "STRING"}, "gancho": {"type": "STRING"}, "texto_na_tela": {"type": "STRING"},
    "ponto1": {"type": "STRING"}, "ponto2": {"type": "STRING"}, "fecho": {"type": "STRING"},
    "palavra_chave": {"type": "STRING"}, "chamada": {"type": "STRING"}, "seu_toque": {"type": "STRING"},
    "legenda": {"type": "STRING"}, "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
}, "required": ["tema", "gancho", "texto_na_tela", "ponto1", "ponto2", "fecho", "chamada", "legenda"]}
SCHEMA = {"type": "OBJECT", "properties": {"roteiros": {"type": "ARRAY", "items": ITEM}}, "required": ["roteiros"]}


# ---------------- histórico ----------------
def _carregar():
    try:
        d = json.loads(ROTEIROS_FILE.read_text(encoding="utf-8"))
        if isinstance(d.get("itens"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"itens": []}


def _salvar(d):
    d["itens"] = d["itens"][-150:]
    ROTEIROS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def escolher(qtd, hist, hoje):
    """Pilares e ângulos: evita os pilares dos 2 últimos dias e pega o ângulo menos usado nos roteiros anteriores."""
    pilares = [k for k in PILLARS if not k.startswith("leve")]
    recentes = {i["pillar"] for i in hist["itens"][-2 * qtd:]}
    livres = [k for k in pilares if k not in recentes] or pilares
    escolhidos = []
    for _ in range(qtd):
        base = [k for k in livres if k not in escolhidos] or [k for k in pilares if k not in escolhidos] or pilares
        pesos = [PILLARS[k].get("weight", 10) for k in base]
        k = random.choices(base, weights=pesos)[0]
        usados = {}
        for i in hist["itens"]:
            if i["pillar"] == k:
                usados[i["angulo"]] = usados.get(i["angulo"], 0) + 1
        angulos = PILLARS[k].get("angulos") or [PILLARS[k]["nome"]]
        menor = min(usados.get(a, 0) for a in angulos)
        angulo = random.choice([a for a in angulos if usados.get(a, 0) == menor])
        escolhidos.append(k)
        yield k, angulo
    return


def _estilos(qtd, hist):
    ult = [i.get("gancho_estilo") for i in hist["itens"][-qtd:]]
    livres = [g for g in GANCHOS if g not in ult] or GANCHOS
    return random.sample(livres, min(qtd, len(livres))) + [random.choice(GANCHOS) for _ in range(max(0, qtd - len(livres)))]


# ---------------- Gemini ----------------
def _gemini(prompt):
    """Chama o Gemini com paciência: sobrecarga e lentidão passam para o próximo modelo, e há até 3 voltas."""
    key = os.environ["GEMINI_API_KEY"]
    inicio, erros = time.time(), []
    for volta in range(3):
        for model in GEMINI_MODELS:
            sobra = DEADLINE - (time.time() - inicio)
            if sobra < 25:
                raise RuntimeError("Gemini falhou (tempo esgotado): " + " | ".join(erros[-4:])[-600:])
            body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                                         "temperature": 0.9, "maxOutputTokens": 8192}}
            try:
                r = requests.post(API.format(model=model), params={"key": key}, json=body,
                                  timeout=(15, max(20, min(90, sobra - 5))))
            except requests.exceptions.RequestException as e:
                erros.append(f"{model}/volta{volta + 1}: {type(e).__name__}")
                print(f"[roteiros] {erros[-1]}", flush=True)
                continue
            if r.status_code == 200:
                texto, why = _extract(r.json())
                if texto:
                    try:
                        return json.loads(texto)
                    except ValueError:
                        why = "JSON inválido"
                erros.append(f"{model}/volta{volta + 1}: {why}")
            else:
                erros.append(f"{model}/volta{volta + 1}: HTTP {r.status_code}")
            print(f"[roteiros] {erros[-1]}", flush=True)
        if volta < 2:
            time.sleep(20 * (volta + 1))
    raise RuntimeError("Gemini falhou: " + " | ".join(erros[-4:])[-600:])


# ---------------- texto ----------------
def _limpo(t):
    return re.sub(r"[*_`\[\]]", "", str(t or "")).strip()


def _palavras(r):
    return len(" ".join(_limpo(r.get(k)) for k in ("gancho", "ponto1", "ponto2", "fecho")).split())


def validar(r):
    faltam = [k for k in ("gancho", "ponto1", "ponto2", "fecho", "legenda") if not _limpo(r.get(k))]
    if faltam:
        return "faltam campos: " + ", ".join(faltam)
    if len(_limpo(r["gancho"]).split()) > 22:
        return "gancho longo demais"
    if not 35 <= _palavras(r) <= 140:
        return f"tamanho fora do esperado ({_palavras(r)} palavras)"
    return None


def formatar(i, total, pilar, angulo, r, data):
    n = _palavras(r)
    seg = max(10, round(n / PALAVRAS_POR_SEGUNDO))
    tags = " ".join(("#" + _limpo(h).lstrip("#").replace(" ", "")) for h in (r.get("hashtags") or [])[:5])
    linhas = [f"🎥 VÍDEO {i} DE {total} · {PILLARS[pilar]['nome']} · {angulo}",
              f"Tema: {_limpo(r['tema'])}", "",
              f"🎬 Gancho (os 3 primeiros segundos): {_limpo(r['gancho'])}",
              f"🖥 Texto na tela: {_limpo(r.get('texto_na_tela'))}", "",
              f"1️⃣ Ponto 1: {_limpo(r['ponto1'])}", f"2️⃣ Ponto 2: {_limpo(r['ponto2'])}",
              f"🔚 Fecho: {_limpo(r['fecho'])}"]
    if _limpo(r.get("chamada")):
        linhas.append(f"💬 Chamada: {_limpo(r['chamada'])}")
    if _limpo(r.get("seu_toque")):
        linhas.append(f"✍️ Seu toque (opcional, só se for verdade): {_limpo(r['seu_toque'])}")
    linhas += ["", f"⏱ Cerca de {seg} segundos ({n} palavras)", f"📝 Legenda: {_limpo(r['legenda'])}"]
    if tags:
        linhas.append(tags)
    return "\n".join(linhas)


def gerar(qtd=2, hoje=None):
    hoje = hoje or datetime.now(TZ)
    hist = _carregar()
    alvos = list(escolher(qtd, hist, hoje))
    estilos = _estilos(qtd, hist)
    recentes = [i["tema"] for i in hist["itens"][-20:] if i.get("tema")]
    chaves = random.sample(KEYWORDS, min(qtd, len(KEYWORDS)))
    pedidos = "\n".join(
        f"{n}. Pilar: {PILLARS[p]['nome']} ({PILLARS[p].get('descricao', '')}). Ângulo obrigatório: {a}. "
        f"Estilo do gancho: {estilos[n - 1]}. Palavra-chave da chamada final: {chaves[n - 1]}."
        for n, (p, a) in enumerate(alvos, 1))
    prompt = (f"Escreva {qtd} roteiros diferentes entre si, um para cada pedido abaixo, na mesma ordem.\n{pedidos}\n\n"
              "A chamada (campo chamada) é uma frase curta de fala que convida a comentar a palavra-chave, sem promessa de resultado. "
              "O campo seu_toque é uma pergunta curta que ajuda quem grava a encaixar uma experiência REAL sua (não invente nada). "
              "A legenda tem 2 ou 3 linhas curtas, e hashtags são de 3 a 5, em português, sem espaços.\n"
              + ("Assuntos já usados nos últimos roteiros (não repita): " + "; ".join(recentes) if recentes else ""))
    dados = None
    for tentativa in range(2):
        dados = _gemini(prompt)
        itens = dados.get("roteiros") or []
        problemas = [validar(r) for r in itens[:qtd]]
        if len(itens) >= qtd and not any(problemas):
            break
        print(f"[roteiros] resposta fora do padrão ({[p for p in problemas if p] or 'poucos roteiros'}); tentando de novo", flush=True)
        if tentativa == 1:
            itens = [r for r, p in zip(itens, problemas) if not p]
            dados = {"roteiros": itens}
    itens = (dados.get("roteiros") or [])[:qtd]
    if not itens:
        raise RuntimeError("O Gemini não devolveu nenhum roteiro utilizável.")
    msgs = [f"🎥 Roteiros de hoje ({hoje.strftime('%d/%m')}) no modelo YAP: gancho + dois pontos + fecho.\n"
            "Não é para decorar: fale com as suas palavras. Se travar, repita o gancho e siga em frente."]
    for n, (r, (p, a)) in enumerate(zip(itens, alvos), 1):
        msgs.append(formatar(n, len(itens), p, a, r, hoje))
        hist["itens"].append({"data": hoje.strftime("%Y-%m-%d"), "pillar": p, "angulo": a,
                              "tema": _limpo(r["tema"]), "gancho_estilo": estilos[n - 1]})
    _salvar(hist)
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qtd", type=int, default=1)
    qtd = max(1, min(3, ap.parse_args().qtd))
    try:
        msgs = gerar(qtd)
    except Exception as e:
        tg.notify(f"⚠️ Não consegui gerar os roteiros de hoje: {tg.redact(str(e))[:500]}")
        raise
    for m in msgs:
        print(m + "\n", flush=True)
        if os.getenv("SKIP_TELEGRAM") != "1":
            tg.notify(m[:3900])


if __name__ == "__main__":
    main()
