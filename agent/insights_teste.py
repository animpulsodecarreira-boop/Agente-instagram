"""Teste de leitura dos insights do Instagram (Instagram Login). Só LÊ dados; não publica nem altera nada.

Uso: python -m agent.insights_teste
Mostra no log e manda ao Telegram: se o token tem a permissão de insights, quais métricas a Meta devolveu
para os últimos posts e Reels, e as métricas da conta nos últimos 7 dias.
"""
import json
import os
import time

import requests

from . import telegram_io as tg
from .instagram import GRAPH, _token, check_token

# métricas por tipo de mídia (impressions/plays/video_views foram aposentadas; hoje o número de exibições é "views")
COMUNS = ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions"]
REELS_EXTRA = ["ig_reels_avg_watch_time", "reels_skip_rate"]
CONTA = ["reach", "views", "accounts_engaged", "total_interactions"]


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
    return e.get("code") in (10, 200, 190) or "permission" in txt or "permiss" in txt


def _valores(data):
    out = {}
    for item in (data or {}).get("data", []):
        v = item.get("values") or []
        val = (v[0].get("value") if v else None)
        if val is None:
            val = (item.get("total_value") or {}).get("value")
        out[item.get("name")] = val
    return out


def metricas_da_midia(mid, product_type):
    """Pede todas as métricas de uma vez; se a Meta recusar a lista, pede uma a uma para saber qual falhou."""
    lista = COMUNS + (REELS_EXTRA if product_type == "REELS" else [])
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


def main():
    linhas, problemas = [], []
    conta = check_token()
    linhas.append(f"✅ Token ok: @{conta.get('username')}")

    st, d = _get("me/media", fields="id,media_product_type,media_type,timestamp,permalink", limit=10)
    if st != 200:
        raise RuntimeError(f"Não consegui listar os posts: {_msg(d)}")
    posts = d.get("data", [])
    linhas.append(f"Posts lidos: {len(posts)}")

    sem_perm, lidos = False, 0
    for p in posts:
        ok, falhas = metricas_da_midia(p["id"], p.get("media_product_type", "FEED"))
        if "_permissao" in falhas:
            sem_perm = True
            problemas.append(falhas["_permissao"])
            break
        tipo = p.get("media_product_type", "?")
        data = (p.get("timestamp") or "")[:10]
        if ok:
            lidos += 1
            resumo = ", ".join(f"{k}={v}" for k, v in ok.items())
            linhas.append(f"• {tipo} {data}: {resumo}")
        if falhas:
            problemas.append(f"{tipo} {data}: sem " + ", ".join(sorted(falhas)))
        time.sleep(0.3)

    if sem_perm:
        linhas.append("❌ O token NÃO tem permissão para ler insights.")
        linhas.append("Precisa de 'instagram_business_manage_insights'. Gere um token novo com essa permissão e atualize o segredo IG_ACCESS_TOKEN.")
    else:
        fim = int(time.time())
        st, d = _get("me/insights", metric=",".join(CONTA), period="day", metric_type="total_value",
                     since=fim - 7 * 86400, until=fim)
        if st == 200:
            linhas.append("Conta, últimos 7 dias: " + ", ".join(f"{k}={v}" for k, v in _valores(d).items()))
        else:
            problemas.append("conta: " + _msg(d))
        linhas.append(f"Posts com métricas: {lidos} de {len(posts)}")

    if problemas:
        linhas.append("⚠️ Avisos:")
        linhas += [f"- {x}" for x in problemas[:8]]
    texto = "📊 Teste de insights\n" + "\n".join(linhas)
    print(texto, flush=True)
    if os.getenv("SKIP_TELEGRAM") != "1":
        tg.notify(texto[:3800])
    if sem_perm:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
