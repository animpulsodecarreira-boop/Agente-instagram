"""Armazenamento externo das mídias dos posts (Cloudflare Workers KV, plano grátis, sem cartão de crédito).

Por quê: o Instagram só publica imagens e vídeos de URLs públicas e diretas. Antes, tudo ficava no repositório do GitHub
(e o histórico do Git nunca encolhe). Agora os PNGs e MP4s vão para o KV; no repositório ficam só os JSONs pequenos.
O seu Worker entrega os arquivos em /m/posts/AAAAMMDD-HHMM/arquivo (endereço workers.dev, direto, sem redirecionar).

Segredos (GitHub > Settings > Secrets):
  CF_ACCOUNT_ID, CF_KV_NAMESPACE_ID, CF_API_TOKEN (permissão: Workers KV Storage: Edit), MIDIA_PUBLIC_URL
MIDIA_PUBLIC_URL é o endereço do Worker mais /m, por exemplo https://NOME.CONTA.workers.dev/m
Sem os segredos, tudo continua como antes (arquivos no GitHub).

Limites do plano grátis do KV: 1 GB no total, 1.000 gravações/dia, 100.000 leituras/dia, até 25 MiB por arquivo.
Cada arquivo é gravado com prazo de validade (MIDIA_TTL_DIAS, padrão 14): o próprio KV apaga o que ficou velho.
"""
import base64
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

ENV = ("CF_ACCOUNT_ID", "CF_KV_NAMESPACE_ID", "CF_API_TOKEN", "MIDIA_PUBLIC_URL")
PADROES = ("slide*.png", "story*.png", "story*.mp4", "reel.mp4")   # o que vai para fora do repositório
UA = {"User-Agent": "agente-instagram/1.0"}
MAX_BYTES = 25 * 1024 * 1024   # limite de um valor no KV (25 MiB)


def enabled():
    return all(os.getenv(k, "").strip() for k in ENV)


def faltando():
    return [k for k in ENV if not os.getenv(k, "").strip()]


def _ttl():
    try:
        return max(1, int(os.getenv("MIDIA_TTL_DIAS", "14"))) * 86400
    except ValueError:
        return 14 * 86400


def _api(path):
    base = os.getenv("CF_API_BASE", "https://api.cloudflare.com/client/v4").rstrip("/")
    return (f"{base}/accounts/{os.environ['CF_ACCOUNT_ID'].strip()}"
            f"/storage/kv/namespaces/{os.environ['CF_KV_NAMESPACE_ID'].strip()}{path}")


def _auth():
    return {"Authorization": f"Bearer {os.environ['CF_API_TOKEN'].strip()}", **UA}


def _erro(r):
    try:
        msgs = "; ".join(e.get("message", "") for e in r.json().get("errors", []))
    except ValueError:
        msgs = r.text[:200]
    return f"HTTP {r.status_code}" + (f" ({msgs})" if msgs else "")


def _req(method, url, **kw):
    """Chamada à API com 3 tentativas para falhas momentâneas (429 e 5xx)."""
    ultimo = None
    for i in range(3):
        try:
            r = requests.request(method, url, timeout=120, **kw)
        except requests.exceptions.RequestException as e:
            ultimo = f"falha de conexão ({type(e).__name__})"
        else:
            if r.status_code not in (429, 500, 502, 503, 504):
                return r
            ultimo = _erro(r)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"API da Cloudflare: {ultimo}")


def media_base(post_id):
    return f"{os.environ['MIDIA_PUBLIC_URL'].strip().rstrip('/')}/posts/{post_id}"


def upload_file(path, key):
    data = Path(path).read_bytes()
    if len(data) > MAX_BYTES:
        raise RuntimeError(f"{Path(path).name} tem {len(data) / 1e6:.1f} MB; o KV aceita até 25 MiB por arquivo")
    r = _req("PUT", _api("/values/" + quote(key, safe="")), params={"expiration_ttl": _ttl()}, data=data,
             headers={**_auth(), "Content-Type": "application/octet-stream"})
    if r.status_code != 200 or not r.json().get("success", False):
        raise RuntimeError(f"Não consegui gravar {key} no KV: {_erro(r)}")


def upload_post(post_id, folder, patterns=PADROES):
    """Sobe slides, stories e Reel da pasta do post. Devolve os nomes enviados."""
    folder = Path(folder)
    nomes = []
    for pat in patterns:
        for p in sorted(folder.glob(pat)):
            upload_file(p, f"posts/{post_id}/{p.name}")
            nomes.append(p.name)
    return nomes


def _chaves(prefixo):
    cursor = None
    while True:
        params = {"prefix": prefixo, "limit": 1000, **({"cursor": cursor} if cursor else {})}
        r = _req("GET", _api("/keys"), params=params, headers=_auth())
        if r.status_code != 200:
            raise RuntimeError(f"Não consegui listar o KV: {_erro(r)}")
        corpo = r.json()
        for item in corpo.get("result", []):
            yield item["name"]
        cursor = (corpo.get("result_info") or {}).get("cursor")
        if not cursor:
            return


def delete_post(post_id):
    """Apaga tudo do post no KV. Devolve quantos arquivos saíram."""
    total = 0
    for nome in list(_chaves(f"posts/{post_id}/")):
        r = _req("DELETE", _api("/values/" + quote(nome, safe="")), headers=_auth())
        if r.status_code == 200:
            total += 1
    return total


def verify_public(post_id, filename, expected_size=None, espera=None):
    """Confere o que a Meta vai encontrar: status 200 direto (sem redirecionar), tipo de mídia certo e tamanho certo.

    O KV demora até ~60 s para mostrar um arquivo novo em todos os lugares do mundo: enquanto responder 404,
    tenta de novo (até `espera` segundos). Outros erros falham na hora.
    """
    url = f"{media_base(post_id)}/{filename}"
    limite = time.time() + (espera if espera is not None else float(os.getenv("MIDIA_VERIFY_ESPERA", "90")))
    while True:
        try:
            r = requests.get(url, timeout=60, allow_redirects=False, stream=True, headers=UA)
        except requests.exceptions.RequestException as e:
            return False, f"não consegui abrir {url} ({type(e).__name__})"
        try:
            if not (r.status_code == 404 and time.time() < limite):   # 404 dentro do prazo = ainda propagando
                ctype = r.headers.get("Content-Type", "")
                size = int(r.headers.get("Content-Length", "0") or 0)
                if r.status_code != 200:
                    return False, f"{url} respondeu HTTP {r.status_code}" + (
                        " (redirecionamento: a Meta não aceita)" if 300 <= r.status_code < 400 else "")
                if not (ctype.startswith("image/") or ctype.startswith("video/")):
                    return False, f"{url} respondeu com tipo '{ctype}', esperado image/* ou video/*"
                if expected_size is not None and size and size != expected_size:
                    return False, f"{url} veio com {size} bytes, esperado {expected_size}"
                return True, f"HTTP 200, {ctype}, {size} bytes"
        finally:
            r.close()
        time.sleep(float(os.getenv("MIDIA_VERIFY_INTERVALO", "6")))


def download_url(url, dest):
    """Baixa um arquivo público (por exemplo, os slides de um post que já saiu do repositório)."""
    r = requests.get(url, timeout=120, headers=UA)
    if r.status_code != 200:
        raise RuntimeError(f"Não consegui baixar {url}: HTTP {r.status_code}")
    Path(dest).write_bytes(r.content)
    return dest


# PNG 1x1 transparente, para o teste
_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def self_test(tmp_dir="."):
    """Sobe um arquivinho de teste, confere a URL pública e apaga. Devolve (ok, relatório)."""
    pid, nome = "00000000-0000", "ping.png"
    f = Path(tmp_dir) / nome
    f.write_bytes(_PNG)
    try:
        try:
            upload_file(f, f"posts/{pid}/{nome}")
        except Exception as e:
            return False, (f"o envio ao KV falhou ({str(e)[:220]}). Confira CF_ACCOUNT_ID, CF_KV_NAMESPACE_ID e se o token "
                           "tem a permissão 'Workers KV Storage: Edit'.")
        ok, info = verify_public(pid, nome, expected_size=len(_PNG))
        try:
            delete_post(pid)
        except Exception:
            pass
        if not ok:
            return False, (f"o arquivo subiu, mas a URL pública não serve direito: {info}. Confira o Worker "
                           "(rota /m e o vínculo MIDIA com o namespace) e o MIDIA_PUBLIC_URL.")
        return True, f"envio ao KV e URL pública funcionando ({info})"
    finally:
        f.unlink(missing_ok=True)
