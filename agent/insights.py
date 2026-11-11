"""Analista de conteúdo: lê as métricas do Instagram, guarda o histórico e escreve o relatório semanal.

Uso:
  python -m agent.insights coletar     # lê as métricas dos posts e Reels publicados e atualiza metricas.json
  python -m agent.insights relatorio   # monta o relatório e manda ao Telegram
  python -m agent.insights tudo        # coleta e depois relatório

Como funciona
- Cada post publicado gera até dois registros: o carrossel (media_id) e o Reel (reel_media_id).
- O registro copia os atributos do post (etapa, pilar, ângulo, formato, gancho, tema de cor) na hora da coleta,
  porque o robô apaga as pastas de posts antigos; sem essa cópia o cruzamento se perderia.
- As métricas são lidas uma vez por dia entre o 2º e o 9º dia de vida de cada post (e uma vez só, se o post já for mais
  velho quando o analista entra em ação). O relatório usa a leitura mais madura, com 3 a 14 dias de vida.
- A "nota" de cada post = (4 x salvamentos + 5 x compartilhamentos + 3 x comentários + 1 x curtidas) por 100 contas
  alcançadas. Salvamentos e compartilhamentos pesam mais que curtidas. Os pesos estão em PESOS, logo abaixo.
- Carrosséis e Reels são sempre comparados separadamente (têm públicos e ritmos diferentes).
- O alcance da CONTA (seguidores x não seguidores, e por tipo de conteúdo) é lido todo dia e guardado em metricas.json.
- Posts impulsionados (anúncio) devem entrar em ignorar_metricas.txt, para não misturar alcance pago com orgânico.
"""
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import telegram_io as tg
from .config import HISTORY_FILE, QUEUE
from .instagram import GRAPH, _token, check_token

TZ = ZoneInfo("America/Sao_Paulo")
METRICAS_FILE = HISTORY_FILE.parent / "metricas.json"
IGNORAR_FILE = HISTORY_FILE.parent / "ignorar_metricas.txt"   # um id por linha (ex.: 20261111-1654 ou 20261111-1654:reel)

PESOS = {"saved": 4, "shares": 5, "comments": 3, "likes": 1}
COMUNS = ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions"]
REELS_EXTRA = ["ig_reels_avg_watch_time", "reels_skip_rate"]

IDADE_MIN_LEITURA = 2      # dias: antes disso as métricas ainda mudam demais
IDADE_MAX_LEITURA = 9      # dias: depois disso o robô para de ler (menos chamadas à API)
IDADE_MAX_BACKFILL = 14    # post velho que o analista nunca leu: uma leitura única, se tiver até 14 dias
IDADE_MIN_RELATORIO = 3    # o relatório só avalia posts com pelo menos 3 dias de vida
AMOSTRA_MIN = 4            # grupos com menos posts que isso não geram recomendação
ALCANCE_CONFIAVEL = 50     # mediana de contas alcançadas abaixo disso: a nota oscila demais (1 curtida muda tudo); rankeia por alcance
TOTAL_MIN = 10             # com menos posts avaliados que isso, o relatório não recomenda nada

DIMENSOES = {
    "carrossel": [("funnel", "etapa"), ("pillar", "pilar"), ("format", "formato"), ("hook", "gancho"), ("theme", "cor")],
    "reel": [("funnel", "etapa"), ("pillar", "pilar"), ("theme", "cor")],
}


# ---------------- API ----------------
def _get(path, **params):
    params["access_token"] = _token()
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=60)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": {"message": r.text[:200]}}


def _msg(data):
    e = (data or {}).get("error") or {}
    return f"{e.get('message', '')[:160]} (code {e.get('code')})".strip()


def _sem_permissao(data):
    e = (data or {}).get("error") or {}
    txt = (e.get("message") or "").lower()
    return e.get("code") in (10, 200, 190) or "permission" in txt


def _valores(data):
    out = {}
    for item in (data or {}).get("data", []):
        v = item.get("values") or []
        val = v[0].get("value") if v else None
        if val is None:
            val = (item.get("total_value") or {}).get("value")
        out[item.get("name")] = val
    return out


def metricas_da_midia(mid, tipo):
    """Pede todas as métricas de uma vez; se a Meta recusar a lista, pede uma a uma. Devolve (métricas, falhas)."""
    lista = COMUNS + (REELS_EXTRA if tipo == "reel" else [])
    st, d = _get(f"{mid}/insights", metric=",".join(lista))
    if st == 200:
        return _valores(d), {}
    if _sem_permissao(d):
        return {}, {"_permissao": _msg(d)}
    ok, falhas = {}, {}
    for m in lista:
        st, d = _get(f"{mid}/insights", metric=m)
        if st == 200:
            ok.update(_valores(d))
        else:
            falhas[m] = _msg(d)
    return ok, falhas


# ---------------- arquivo de histórico ----------------
def _carregar():
    try:
        d = json.loads(METRICAS_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("midias"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"versao": 1, "midias": {}}


def _salvar(dados):
    METRICAS_FILE.write_text(json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def _historico():
    """history.json indexado pelo assunto (topic): é de lá que vêm formato, gancho etc. A última entrada de cada assunto vale."""
    try:
        h = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {e.get("topic"): e for e in h if isinstance(e, dict) and e.get("topic")}


def _atributos(meta, hist):
    h = hist.get(meta.get("topic", ""), {})
    a = {k: meta.get(k) if meta.get(k) is not None else h.get(k) for k in ("funnel", "pillar", "angle", "theme", "variant")}
    for k in ("format", "hook"):
        a[k] = h.get(k)
    a["topic"] = meta.get("topic")
    return a


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


# ---------------- alcance da conta (seguidores x não seguidores) ----------------
SUPERFICIES = {"REEL": "Reels", "REELS": "Reels", "POST": "Posts", "FEED": "Posts", "STORY": "Stories",
               "AD": "Anúncios", "CAROUSEL_CONTAINER": "Carrosséis", "CAROUSEL": "Carrosséis"}


def _breakdown(metric, breakdown, since, until):
    """Alcance da conta aberto por um critério. Devolve ({'total': n, 'partes': {...}}, None) ou (None, erro)."""
    st, d = _get("me/insights", metric=metric, period="day", metric_type="total_value",
                 breakdown=breakdown, since=since, until=until)
    if st != 200:
        return None, _msg(d)
    try:
        tv = d["data"][0]["total_value"]
        partes = {}
        for b in tv.get("breakdowns", []):
            for r in b.get("results", []):
                partes[str(r["dimension_values"][0])] = r.get("value", 0)
        return {"total": tv.get("value"), "partes": partes}, None
    except (KeyError, IndexError, TypeError):
        return None, "resposta inesperada da Meta"


def alcance_conta(agora):
    """Contas únicas alcançadas nos últimos 7 e 28 dias, abertas por seguidor/não seguidor e por tipo de conteúdo."""
    fim = int(agora.timestamp())
    out, erros = {}, []
    for dias in (7, 28):
        item = {}
        for chave, brk in (("follow_type", "follow_type"), ("superficie", "media_product_type")):
            r, e = _breakdown("reach", brk, fim - dias * 86400, fim)
            if r:
                item[chave] = r
            else:
                erros.append(f"{dias} dias/{brk}: {e}")
        if item:
            out[str(dias)] = item
    return out, erros


def _linhas_conta(dados):
    if not dados.get("conta"):
        return []
    dia = max(dados["conta"])
    c = dados["conta"][dia]
    linhas = ["🌐 Alcance da conta (contas únicas, lido em " + datetime.strptime(dia, "%Y-%m-%d").strftime("%d/%m") + ")"]
    for dias in ("7", "28"):
        it = c.get(dias) or {}
        ft = it.get("follow_type")
        if ft:
            p = ft["partes"]
            seg, nao, unk = p.get("FOLLOWER", 0), p.get("NON_FOLLOWER", 0), p.get("UNKNOWN", 0)
            tot = seg + nao + unk
            if tot:
                linhas.append(f"{dias} dias: {tot} contas — seguidores {seg} ({_f1(seg / tot * 100)}%), "
                              f"não seguidores {nao} ({_f1(nao / tot * 100)}%)" + (f", desconhecido {unk}" if unk else ""))
        sf = it.get("superficie")
        if sf and sf["partes"]:
            ordem = sorted(sf["partes"].items(), key=lambda kv: -kv[1])
            linhas.append("   por tipo: " + " · ".join(f"{SUPERFICIES.get(k, k.title())} {v}" for k, v in ordem if v))
    return linhas if len(linhas) > 1 else []


def _ignorados():
    try:
        return {l.split("#")[0].strip() for l in IGNORAR_FILE.read_text(encoding="utf-8").splitlines() if l.split("#")[0].strip()}
    except OSError:
        return set()


# ---------------- coleta ----------------
def coletar(agora=None):
    """Lê as métricas dos posts publicados. Devolve um resumo (dict)."""
    agora = agora or datetime.now(timezone.utc)
    dados, hist = _carregar(), _historico()
    midias = dados["midias"]
    alvos = []
    pastas = sorted(QUEUE.iterdir()) if QUEUE.exists() else []
    for pasta in pastas:
        mf = pasta / "post.json"
        if not pasta.is_dir() or pasta.name.startswith("_") or not mf.exists():
            continue
        try:
            meta = json.loads(mf.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if meta.get("status") == "published" and meta.get("media_id"):
            alvos.append((pasta.name, "carrossel", str(meta["media_id"]), meta))
        if meta.get("reel_status") == "published" and meta.get("reel_media_id"):
            alvos.append((pasta.name, "reel", str(meta["reel_media_id"]), meta))

    res = {"alvos": len(alvos), "lidos": 0, "novos": 0, "ignorados": 0, "erros": []}
    for post_id, tipo, mid, meta in alvos:
        chave = f"{post_id}:{tipo}"
        reg = midias.get(chave)
        if reg is None:
            reg = midias[chave] = {"post_id": post_id, "tipo": tipo, "media_id": mid,
                                   "atributos": _atributos(meta, hist), "coletas": []}
            res["novos"] += 1
        if not reg.get("publicado_em"):
            st, d = _get(mid, fields="timestamp,permalink")
            if st == 200 and d.get("timestamp"):
                reg["publicado_em"], reg["permalink"] = d["timestamp"], d.get("permalink", "")
            else:
                res["erros"].append(f"{chave}: não consegui a data de publicação ({_msg(d)})")
                continue
        idade = (agora - _parse(reg["publicado_em"])).total_seconds() / 86400
        ja = reg["coletas"]
        if idade < IDADE_MIN_LEITURA or (idade > IDADE_MAX_LEITURA and (ja or idade > IDADE_MAX_BACKFILL)):
            res["ignorados"] += 1
            continue
        if ja and (agora - _parse(ja[-1]["em"])).total_seconds() < 20 * 3600:   # no máximo uma leitura por dia
            res["ignorados"] += 1
            continue
        ok, falhas = metricas_da_midia(mid, tipo)
        if "_permissao" in falhas:
            raise RuntimeError("O token não tem permissão para ler insights (instagram_business_manage_insights): "
                               + falhas["_permissao"])
        if not ok:
            res["erros"].append(f"{chave}: sem métricas ({'; '.join(f'{k}: {v}' for k, v in list(falhas.items())[:2])})")
            continue
        ja.append({"em": agora.strftime("%Y-%m-%dT%H:%M:%S%z"), "idade": round(idade, 2), "metricas": ok})
        reg["coletas"] = ja[-8:]
        res["lidos"] += 1
        time.sleep(0.3)
    try:   # alcance da conta: um registro por dia, guardado para ver a tendência
        conta, erros_conta = alcance_conta(agora)
        if conta:
            dados.setdefault("conta", {})[agora.astimezone(TZ).strftime("%Y-%m-%d")] = conta
            for k in sorted(dados["conta"])[:-60]:
                del dados["conta"][k]
        for e in erros_conta[:4]:
            res["erros"].append("conta: " + e)
    except Exception as e:   # a conta é um extra: se falhar, a coleta dos posts continua valendo
        res["erros"].append(f"conta: {str(e)[:150]}")
    _salvar(dados)
    print(f"[insights] {res['alvos']} mídias publicadas: {res['lidos']} lidas, {res['novos']} novas no histórico, "
          f"{res['ignorados']} sem leitura hoje, {len(res['erros'])} erro(s)", flush=True)
    for e in res["erros"][:10]:
        print(f"[insights] aviso: {e}", flush=True)
    return res


# ---------------- análise ----------------
def _nota(m):
    reach = m.get("reach") or 0
    if reach <= 0:
        return None
    return sum(p * (m.get(k) or 0) for k, p in PESOS.items()) / reach * 100


def _referencia(reg):
    """A leitura mais madura entre 3 e 14 dias de vida."""
    cand = [c for c in reg.get("coletas", []) if IDADE_MIN_RELATORIO <= c.get("idade", 0) <= IDADE_MAX_BACKFILL]
    return max(cand, key=lambda c: c["idade"]) if cand else None


def _avaliaveis(dados):
    out = []
    ign = _ignorados()
    for chave, reg in dados["midias"].items():
        if reg.get("post_id") in ign or chave in ign:
            continue
        ref = _referencia(reg)
        if not ref or not reg.get("publicado_em"):
            continue
        nota = _nota(ref["metricas"])
        if nota is None:
            continue
        out.append({"reg": reg, "m": ref["metricas"], "idade": ref["idade"], "nota": nota,
                    "pub": _parse(reg["publicado_em"]), "tipo": reg["tipo"]})
    return out


def _f1(x):
    return f"{x:.1f}".replace(".", ",")


def _rotulo(x):
    a = x["reg"]["atributos"]
    topo = (a.get("topic") or "(sem assunto)").strip()
    topo = topo if len(topo) <= 42 else topo[:41].rstrip() + "…"
    return f"{x['pub'].astimezone(TZ).strftime('%d/%m')} {a.get('funnel') or '?'} · {topo}"


def _linha_post(i, x):
    m = x["m"]
    s = f"{i}. {_rotulo(x)}\n   id {x['reg']['post_id']}\n   nota {_f1(x['nota'])} · alcance {m.get('reach', 0)} · 🔖{m.get('saved', 0)} ↗{m.get('shares', 0)} 💬{m.get('comments', 0)} ♥{m.get('likes', 0)}"
    if x["tipo"] == "reel":
        extra = []
        t = m.get("ig_reels_avg_watch_time")
        if t is not None:
            extra.append(f"assistiu em média {_f1(t / 1000)} s")
        sk = m.get("reels_skip_rate")
        if sk is not None:
            extra.append(f"abandono {_f1(sk * 100 if sk <= 1 else sk)}%")
        if extra:
            s += "\n   " + " · ".join(extra)
    if x["idade"] < 7:
        s += "\n   (ainda pode crescer: tem " + _f1(x["idade"]) + " dias)"
    return s


def _grupos(itens, dim):
    g = defaultdict(list)
    for x in itens:
        v = x["reg"]["atributos"].get(dim)
        if v not in (None, ""):
            g[str(v)].append(x)
    return g


def _curto(t, n=34):
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def _modo_alcance(itens):
    """Com alcance muito baixo, a nota é ruído: ranqueia por alcance até a conta crescer."""
    r = [x["m"].get("reach", 0) for x in itens]
    return bool(r) and statistics.median(r) < ALCANCE_CONFIAVEL


def bloco_tipo(tipo, semana, base):
    nome = "Carrosséis" if tipo == "carrossel" else "Reels"
    out = [f"— {nome} —"]
    todos = [x for x in base if x["tipo"] == tipo] + [x for x in semana if x["tipo"] == tipo]
    por_alcance = _modo_alcance(todos)
    chave = (lambda x: x["m"].get("reach", 0)) if por_alcance else (lambda x: x["nota"])
    nome_chave = "alcance" if por_alcance else "nota"
    if por_alcance:
        out.append(f"⚠️ Alcance baixo (mediana de {int(statistics.median(x['m'].get('reach', 0) for x in todos))} contas): "
                   "a nota oscila demais com tão poucas pessoas, então o ranking abaixo é por alcance.")
    sm = sorted([x for x in semana if x["tipo"] == tipo], key=lambda x: -chave(x))
    if sm:
        out.append("Posts desta janela (de 3 a 10 dias atrás):")
        mostrar = sm if len(sm) <= 6 else sm[:3] + sm[-3:]
        for i, x in enumerate(mostrar, 1):
            out.append(_linha_post(i if len(sm) <= 6 or i <= 3 else len(sm) - (len(mostrar) - i), x))
    else:
        out.append("Nenhum post dessa janela tinha métricas.")
    bt = [x for x in base if x["tipo"] == tipo]
    if len(bt) >= 2:
        media = statistics.mean(x["nota"] for x in bt)
        out.append(f"Últimos 28 dias: {len(bt)} posts, nota média {_f1(media)}, alcance médio "
                   f"{int(statistics.mean(x['m'].get('reach', 0) for x in bt))}")
        if por_alcance:
            out.append("(médias por categoria abaixo em contas alcançadas)")
        for dim, nome_dim in DIMENSOES[tipo]:
            g = {k: v for k, v in _grupos(bt, dim).items() if len(v) >= 2}
            if not g:
                continue
            ordem = sorted(g.items(), key=lambda kv: -statistics.mean(chave(x) for x in kv[1]))[:4]
            out.append(f"{nome_dim}: " + " · ".join(
                f"{_curto(k)} {_f1(statistics.mean(chave(x) for x in v))} (n={len(v)})" for k, v in ordem))
    return out, bt


def sugestoes(tipo, bt):
    nome = "carrosséis" if tipo == "carrossel" else "Reels"
    if bt and _modo_alcance(bt):
        return [f"{nome}: o alcance ainda é baixo demais para recomendar categorias; o foco agora é ampliar quantas pessoas veem os posts."]
    if len(bt) < TOTAL_MIN:
        return [f"{nome}: só {len(bt)} post(s) avaliados (o relatório só recomenda a partir de {TOTAL_MIN}). Trate os números como pista, não como regra."]
    media = statistics.mean(x["nota"] for x in bt)
    achados = []
    for dim, nome_dim in DIMENSOES[tipo]:
        for k, v in _grupos(bt, dim).items():
            if len(v) >= AMOSTRA_MIN and media > 0:
                r = statistics.mean(x["nota"] for x in v) / media
                achados.append((r, nome_dim, k, len(v)))
    out = []
    melhores = sorted([a for a in achados if a[0] >= 1.3], reverse=True)[:2]
    piores = sorted([a for a in achados if a[0] <= 0.7])[:2]
    for r, d, k, n in melhores:
        out.append(f"{nome}: vale repetir {d} “{_curto(k, 40)}” (nota {_f1(r * media)} contra média {_f1(media)}, n={n}).")
    for r, d, k, n in piores:
        out.append(f"{nome}: rever {d} “{_curto(k, 40)}” (nota {_f1(r * media)} contra média {_f1(media)}, n={n}).")
    return out or [f"{nome}: ainda sem diferença clara entre as categorias. Siga variando."]


def montar_relatorio(agora=None):
    agora = agora or datetime.now(timezone.utc)
    dados = _carregar()
    av = _avaliaveis(dados)
    if not av:
        return "📊 Relatório semanal\nAinda não há posts com 3 dias de vida e métricas lidas. Rode a coleta e volte em alguns dias."
    ini, fim = agora - timedelta(days=10), agora - timedelta(days=3)
    semana = [x for x in av if ini <= x["pub"] <= fim]
    base = [x for x in av if x["pub"] >= agora - timedelta(days=28)]
    d = lambda t: t.astimezone(TZ).strftime("%d/%m")
    texto = [f"📊 Relatório semanal — posts de {d(ini)} a {d(fim)}",
             "Nota = (4×salvamentos + 5×compartilhamentos + 3×comentários + 1×curtidas) por 100 contas alcançadas."]
    conta = _linhas_conta(dados)
    if conta:
        texto += [""] + conta
    ign = _ignorados()
    if ign:
        texto.append(f"({len(ign)} post(s) na lista ignorar_metricas.txt ficaram fora das comparações, por exemplo os impulsionados.)")
    sug = []
    for tipo in ("carrossel", "reel"):
        linhas, bt = bloco_tipo(tipo, semana, base)
        if bt or any(x["tipo"] == tipo for x in semana):
            texto += [""] + linhas
            sug += sugestoes(tipo, bt)
    texto += ["", "💡 Sugestões"] + sug
    texto.append("Isto são indícios, não regras: uma categoria só merece mudar a estratégia se continuar se destacando por 3 semanas seguidas.")
    return "\n".join(texto)


def _enviar(texto):
    print(texto, flush=True)
    if os.getenv("SKIP_TELEGRAM") == "1":
        return
    resto = texto
    while resto:   # o Telegram aceita até 4096 caracteres por mensagem
        if len(resto) <= 3800:
            tg.notify(resto)
            break
        corte = resto.rfind("\n", 0, 3800)
        corte = corte if corte > 0 else 3800
        tg.notify(resto[:corte])
        resto = resto[corte:].lstrip("\n")


def main(argv=None):
    acao = (argv or sys.argv[1:] or ["tudo"])[0]
    if acao not in ("coletar", "relatorio", "tudo"):
        print("Uso: python -m agent.insights [coletar|relatorio|tudo]")
        sys.exit(2)
    try:
        if acao in ("coletar", "tudo"):
            check_token()
            res = coletar()
            if res["alvos"] and not res["lidos"] and res["erros"] and acao == "coletar":
                _enviar("⚠️ Coleta de insights: nenhuma mídia lida.\n" + "\n".join(res["erros"][:5]))
        if acao in ("relatorio", "tudo"):
            _enviar(montar_relatorio())
    except Exception as e:
        _enviar(f"⚠️ O analista de conteúdo falhou: {tg.redact(str(e))[:600]}")
        raise


if __name__ == "__main__":
    main()
