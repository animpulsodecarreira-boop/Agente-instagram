"""Publica carrosséis na conta profissional do Instagram via Graph API.

Fluxo oficial: 1 container por imagem (is_carousel_item) -> 1 container CAROUSEL -> media_publish.
As imagens precisam estar em URLs públicas (aqui: raw.githubusercontent.com de um repositório público).
"""
import os
import time

import requests

from .config import IG_API_VERSION

GRAPH = f"https://graph.facebook.com/{IG_API_VERSION}"


def _post(path, **params):
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    r = requests.post(f"{GRAPH}/{path}", data=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Instagram API {path}: {r.status_code} {r.text[:400]}")
    return r.json()


def _wait_ready(container_id, tries=30):
    for _ in range(tries):
        r = requests.get(f"{GRAPH}/{container_id}", timeout=60,
                         params={"fields": "status_code,status", "access_token": os.environ["IG_ACCESS_TOKEN"]})
        data = r.json()
        code = data.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Container {container_id} falhou: {data}")
        time.sleep(4)
    raise RuntimeError(f"Container {container_id} não ficou pronto a tempo")


def publish_carousel(image_urls, caption):
    ig = os.environ["IG_USER_ID"]
    children = []
    for url in image_urls:
        c = _post(f"{ig}/media", image_url=url, is_carousel_item="true")["id"]
        children.append(c)
    for c in children:
        _wait_ready(c)
    parent = _post(f"{ig}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    _wait_ready(parent)
    return _post(f"{ig}/media_publish", creation_id=parent)["id"]


def permalink(media_id):
    r = requests.get(f"{GRAPH}/{media_id}", timeout=60,
                     params={"fields": "permalink", "access_token": os.environ["IG_ACCESS_TOKEN"]})
    return r.json().get("permalink", "")
