"""Monitor do agente: avisa quando um horário não gerou post e manda um resumo do dia no Telegram.

Uso:
  python -m agent.monitor checar   # 1 hora depois de cada horário: se o post/Reel daquele horário não saiu, avisa (só avisa se houver problema)
  python -m agent.monitor resumo   # resumo do dia (roda às 20:00)

Como sabe o que aconteceu: consulta as execuções do GitHub Actions de hoje (usa o GITHUB_TOKEN do próprio workflow) e lê as
pastas queue/ do repositório (o que foi gerado, aprovado, publicado). Se o GitHub não responder, usa só a pasta queue/.
Os horários esperados estão em SLOTS, logo abaixo: se mudar a agenda dos workflows, mude aqui também.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from . import telegram_io as tg
from .config import QUEUE

TZ = ZoneInfo("America/Sao_Paulo")
GITHUB = os.getenv("GITHUB_API_URL", "https://api.github.com")

# (hora, workflow, rótulo). Seg a sex e fim de semana. O "workflow" é o NOME que aparece em Actions.
SLOTS = {
    "semana": [("08:00", "Reel direto", "Reel"), ("12:30", "Gerar post", "Carrossel"), ("18:00", "Reel direto", "Reel")],
    "fim": [("10:30", "Gerar post", "Carrossel leve"), ("17:00", "Gerar post", "Carrossel leve")],
}
ATRASO_ACEITO = 55    # minutos depois do horário para avisar (o GitHub costuma atrasar agendamentos em alguns minutos)
ATRASO_JANELA = 150   # a execução tem que ter começado até 150 min depois do horário para contar
CHECAR_ATE = 115      # a conferência só olha o horário que passou há menos de 115 min (evita avisar duas vezes)
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


# ---------------- dados ----------------
def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ)


def execucoes(dia):
    """Execuções do GitHub Actions do dia (horário de Brasília). Devolve lista ou None se não deu para consultar."""
    token, repo = os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return None
    ini = datetime(dia.year, dia.month, dia.day, tzinfo=TZ) - timedelta(hours=1)
    out = []
    try:
        for pagina in (1, 2, 3):
            r = requests.get(f"{GITHUB}/repos/{repo}/actions/runs", timeout=30,
                             params={"per_page": 100, "page": pagina},
                             headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
            if r.status_code != 200:
                return None if not out else out
            runs = r.json().get("workflow_runs", [])
            for x in runs:
                inicio = _dt(x["created_at"])
                if inicio >= ini:
                    out.append({"nome": x.get("name", ""), "evento": x.get("event", ""), "status": x.get("status", ""),
                                "conclusao": x.get("conclusion"), "inicio": inicio, "fim": _dt(x.get("updated_at", x["created_at"])),
                                "url": x.get("html_url", "")})
            if len(runs) < 100 or min(_dt(x["created_at"]) for x in runs) < ini:
                break
    except requests.exceptions.RequestException:
        return None if not out else out
    return out


def pastas_do_dia(dia):
    """Posts/Reels gerados no dia, lidos de queue/: lista de dicts com horário, tipo, estado e assunto."""
    out = []
    prefixo = dia.strftime("%Y%m%d-")
    if not QUEUE.exists():
        return out
    for p in sorted(QUEUE.iterdir()):
        mf = p / "post.json"
        if not p.name.startswith(prefixo) or not mf.exists():
            continue
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except ValueError:
            continue
        hh, mm = int(p.name[9:11]), int(p.name[11:13])
        out.append({"id": p.name, "hora": datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=TZ), "meta": m})
    return out


def pendentes_antigos(dia):
    """Posts/Reels de dias anteriores que ainda esperam aprovação."""
    antigos = []
    if not QUEUE.exists():
        return antigos
    hoje = dia.strftime("%Y%m%d")
    for p in sorted(QUEUE.iterdir()):
        mf = p / "post.json"
        if not mf.exists() or p.name[:8] >= hoje or p.name.startswith("_"):
            continue
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if m.get("status") == "pending" or m.get("reel_status") == "pending":
            antigos.append(p.name)
    return antigos


# ---------------- análise ----------------
def _tipo_dia(dia):
    return "fim" if dia.weekday() >= 5 else "semana"


def _hora(dia, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(dia.year, dia.month, dia.day, h, m, tzinfo=TZ)


def avaliar(dia, hhmm, workflow, runs, pastas, agora):
    """Estado de um horário: ok | falhou | andamento | nao_rodou | sem_registro | futuro, mais a execução e a pasta achadas."""
    t0 = _hora(dia, hhmm)
    if agora < t0:
        return {"estado": "futuro"}
    pasta = None
    if runs is not None:
        cand = [r for r in runs if r["nome"] == workflow and t0 - timedelta(minutes=10) <= r["inicio"] <= t0 + timedelta(minutes=ATRASO_JANELA)]
        if not cand:
            return {"estado": "nao_rodou"}
        cand.sort(key=lambda r: r["inicio"])
        falhas = sum(1 for r in cand if r["status"] == "completed" and r["conclusao"] not in ("success", None))
        melhor = next((r for r in cand if r["conclusao"] == "success"), None) or cand[-1]
        pasta = next((p for p in pastas if melhor["inicio"] - timedelta(minutes=1) <= p["hora"] <= melhor["fim"] + timedelta(minutes=1)), None)
        if melhor["conclusao"] == "success":
            return {"estado": "ok", "run": melhor, "pasta": pasta, "falhas": falhas}
        if melhor["status"] != "completed":
            return {"estado": "andamento", "run": melhor}
        return {"estado": "falhou", "run": melhor}
    # sem acesso ao GitHub: só a pasta queue/
    pasta = next((p for p in pastas if t0 - timedelta(minutes=10) <= p["hora"] <= t0 + timedelta(minutes=ATRASO_JANELA)), None)
    return {"estado": "ok" if pasta else "sem_registro", "pasta": pasta}


def _estado_pasta(m):
    """Resumo curto do estado de um post/Reel."""
    partes = []
    if m.get("saida") == "reel_direto":
        partes.append({"pending": "Reel aguardando sua aprovação", "published": "Reel publicado",
                       "rejected": "Reel descartado"}.get(m.get("reel_status"), "Reel gerado"))
    else:
        partes.append({"pending": "aguardando sua aprovação", "published": "publicado", "rejected": "rejeitado"}.get(m.get("status"), "gerado"))
        if m.get("reel_status") in ("published", "pending"):
            partes.append("Reel " + ("publicado" if m["reel_status"] == "published" else "aguardando"))
    return " · ".join(partes)


def _descr(pasta):
    if not pasta:
        return ""
    m = pasta["meta"]
    return f"{pasta['hora'].strftime('%H:%M')} · {m.get('funnel', '?')} · “{(m.get('topic') or '')[:48]}” · {_estado_pasta(m)}"


# ---------------- ações ----------------
def checar(agora=None):
    """Avisa se o horário que acabou de passar não gerou nada. Silencioso quando está tudo certo."""
    agora = agora or datetime.now(TZ)
    dia = agora.date()
    slots = SLOTS[_tipo_dia(dia)]
    alvo = next(((h, w, r) for h, w, r in slots
                 if timedelta(minutes=ATRASO_ACEITO) <= agora - _hora(dia, h) < timedelta(minutes=CHECAR_ATE)), None)
    if not alvo:
        print("[monitor] nenhum horário para conferir agora", flush=True)
        return None
    hhmm, workflow, rotulo = alvo
    res = avaliar(dia, hhmm, workflow, execucoes(dia), pastas_do_dia(dia), agora)
    est = res["estado"]
    print(f"[monitor] {hhmm} {workflow}: {est}", flush=True)
    msg = None
    if est == "falhou":
        msg = (f"⚠️ O {rotulo} das {hhmm} falhou ({workflow}).\nVeja o motivo: {res['run']['url']}\n"
               f"Para tentar de novo: Actions → {workflow} → Run workflow.")
    elif est == "nao_rodou":
        msg = (f"⚠️ O {rotulo} das {hhmm} não rodou: o GitHub não iniciou o {workflow} nesse horário "
               "(acontece de ele atrasar ou pular agendamentos).\nPara gerar agora: Actions → " + workflow + " → Run workflow.")
    elif est == "sem_registro":
        msg = (f"⚠️ Não encontrei o {rotulo} das {hhmm} e não consegui consultar o GitHub para saber por quê.\n"
               f"Confira em Actions → {workflow}.")
    if msg:
        _enviar(msg)
    return est


def montar_resumo(agora=None):
    agora = agora or datetime.now(TZ)
    dia = agora.date()
    runs, pastas = execucoes(dia), pastas_do_dia(dia)
    linhas = [f"📋 Resumo do dia — {DIAS[dia.weekday()]}, {dia.strftime('%d/%m')}"]
    usadas = set()
    problemas = 0
    refeitos = 0
    for hhmm, workflow, rotulo in SLOTS[_tipo_dia(dia)]:
        res = avaliar(dia, hhmm, workflow, runs, pastas, agora)
        est = res["estado"]
        if res.get("pasta"):
            usadas.add(res["pasta"]["id"])
        if est == "ok":
            extra = ""
            if res.get("falhas"):
                refeitos += 1
                extra = f" (depois de {res['falhas']} falha{'s' if res['falhas'] > 1 else ''})"
            linhas.append(f"✅ {hhmm} {rotulo}{extra}: {_descr(res.get('pasta')) or 'rodou e terminou'}")
        elif est == "falhou":
            problemas += 1
            linhas.append(f"❌ {hhmm} {rotulo}: falhou ({res['run']['url']})")
        elif est == "andamento":
            linhas.append(f"⏳ {hhmm} {rotulo}: ainda rodando")
        elif est == "nao_rodou":
            problemas += 1
            linhas.append(f"⚠️ {hhmm} {rotulo}: não rodou")
        elif est == "sem_registro":
            problemas += 1
            linhas.append(f"⚠️ {hhmm} {rotulo}: não achei o post")
        else:
            linhas.append(f"🕓 {hhmm} {rotulo}: ainda não chegou a hora")
    extras = [p for p in pastas if p["id"] not in usadas]
    if extras:
        linhas.append("Fora dos horários (manuais ou atrasados):")
        linhas += [f"• {_descr(p)}" for p in extras]
    pend = [p for p in pastas if p["meta"].get("status") == "pending" or p["meta"].get("reel_status") == "pending"]
    pub_c = sum(1 for p in pastas if p["meta"].get("status") == "published")
    pub_r = sum(1 for p in pastas if p["meta"].get("reel_status") == "published")
    linhas.append("")
    linhas.append(f"Publicados hoje: {pub_c} carrossel(éis) e {pub_r} Reel(s).")
    if pend:
        linhas.append(f"Aguardando a sua aprovação hoje: {len(pend)} ({', '.join(p['id'] for p in pend)}).")
    antigos = pendentes_antigos(dia)
    if antigos:
        linhas.append(f"Esquecidos de dias anteriores, ainda sem resposta: {len(antigos)} ({', '.join(antigos[-5:])}).")
    if runs is None:
        linhas.append("(Não consegui consultar as execuções do GitHub; o resumo usa só as pastas do repositório.)")
    if problemas == 0 and runs is not None:
        linhas.append("Tudo rodou como esperado." if not refeitos else "Tudo saiu, mas algum horário precisou de nova tentativa.")
    return "\n".join(linhas)


def _enviar(texto):
    print(texto, flush=True)
    if os.getenv("SKIP_TELEGRAM") != "1":
        tg.notify(texto[:3900])


def main():
    acao = (sys.argv[1:] or ["resumo"])[0]
    if acao == "checar":
        checar()
    elif acao == "resumo":
        _enviar(montar_resumo())
    else:
        print("Uso: python -m agent.monitor [checar|resumo]")
        sys.exit(2)


if __name__ == "__main__":
    main()
