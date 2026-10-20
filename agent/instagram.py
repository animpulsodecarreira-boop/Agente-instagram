"""Publica carrosséis na conta profissional do Instagram via Graph API (Instagram Login, sem Página).

Fluxo oficial: 1 container por imagem (is_carousel_item) -> 1 container CAROUSEL -> media_publish.
As imagens precisam estar em URLs públicas (aqui: raw.githubusercontent.com de um repositório público).
"""
import os
import re
import time

import requests

from .config import IG_API_VERSION

GRAPH = f"{os.getenv('IG_API_HOST', 'https://graph.instagram.com')}/{IG_API_VERSION}"


def _token():
    """Token limpo: remove espaços, quebras de linha e aspas coladas por engano."""
    raw = os.environ.get("IG_ACCESS_TOKEN", "")
    return re.sub(r"[\s\"'“”‘’]", "", raw)


def _describe_token():
    t = _token()
    return f"tamanho={len(t)}, começa com '{t[:4]}'" if t else "VAZIO (segredo IG_ACCESS_TOKEN não chegou)"


def check_token():
    """Testa o token antes de publicar e explica o problema, se houver."""
    r = requests.get(f"{GRAPH}/me", timeout=60,
                     params={"fields": "user_id,username", "access_token": _token()})
    data = r.json()
    if r.status_code != 200:
        hint = ""
        if not _token().startswith("IG"):
            hint = " Dica: tokens do login do Instagram começam com 'IG'. Este não começa; talvez seja outro tipo de token."
        raise RuntimeError(f"Token recusado pelo Instagram ({_describe_token()}). Resposta: {str(data)[:300]}.{hint}")
    print(f"[ig] token ok, conta: {data.get('username')} (user_id={data.get('user_id')}, id={data.get('id')})")
    return data


def _post(path, **params):
    params["access_token"] = _token()
    r = requests.post(f"{GRAPH}/{path}", data=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Instagram API {path}: {r.status_code} {r.text[:400]}")
    return r.json()


def _wait_ready(container_id, tries=30):
    for _ in range(tries):
        r = requests.get(f"{GRAPH}/{container_id}", timeout=60,
                         params={"fields": "status_code,status", "access_token": _token()})
        data = r.json()
        code = data.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Container {container_id} falhou: {data}")
        time.sleep(4)
    raise RuntimeError(f"Container {container_id} não ficou pronto a tempo")


def publish_carousel(image_urls, caption):
    check_token()
    ig = os.environ.get("IG_USER_ID", "").strip() or "me"
    children = []
    for url in image_urls:
        children.append(_post(f"{ig}/media", image_url=url, is_carousel_item="true")["id"])
    for c in children:
        _wait_ready(c)
    parent = _post(f"{ig}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    _wait_ready(parent)
    return _post(f"{ig}/media_publish", creation_id=parent)["id"]


def permalink(media_id):
    r = requests.get(f"{GRAPH}/{media_id}", timeout=60,
                     params={"fields": "permalink", "access_token": _token()})
    return r.json().get("permalink", "")


def publish_story(video_url=None, image_url=None):
    """Publica um story (vídeo ou imagem). Retorna o id da mídia."""
    ig = os.environ.get("IG_USER_ID", "").strip() or "me"
    if video_url:
        container = _post(f"{ig}/media", media_type="STORIES", video_url=video_url)["id"]
    else:
        container = _post(f"{ig}/media", media_type="STORIES", image_url=image_url)["id"]
    _wait_ready(container, tries=45)
    return _post(f"{ig}/media_publish", creation_id=container)["id"]
