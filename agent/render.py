"""Transforma o conteúdo (JSON) em imagens PNG 1080x1350 usando HTML + Chromium."""
import html
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import ASSETS, BRAND_NAME, COLORS as C, LINK_LABEL

CSS = f"""
@font-face{{font-family:P;src:url(file://{ASSETS}/Poppins-Bold.ttf);font-weight:700}}
@font-face{{font-family:P;src:url(file://{ASSETS}/Poppins-Medium.ttf);font-weight:500}}
@font-face{{font-family:P;src:url(file://{ASSETS}/Poppins-Regular.ttf);font-weight:400}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1350px;font-family:P,sans-serif;color:{C['white']};background:{C['bg']};position:relative;overflow:hidden}}
h1{{font-weight:700;letter-spacing:-1.5px;line-height:1.08}}
.bgc{{position:absolute;inset:0;background:linear-gradient(180deg,{C['bg']} 0%,{C['deep']} 40%,{C['blue']} 100%)}}
.logo{{position:absolute;left:96px;top:90px;height:150px}}
.cover h1{{position:absolute;left:96px;right:96px;top:340px;font-size:104px}}
.cover p{{position:absolute;left:96px;right:140px;top:1010px;font-size:42px;font-weight:500;line-height:1.35}}
.trail{{position:absolute;right:70px;bottom:70px;width:300px;height:300px}}
.bar{{position:absolute;left:96px;top:150px;width:10px;height:150px;background:{C['amber']};border-radius:5px}}
.content h1,.check h1{{position:absolute;left:96px;right:96px;top:150px;font-size:84px;padding-left:44px}}
.sep{{position:absolute;left:140px;right:140px;top:480px;height:2px;background:{C['blue']};opacity:.6}}
.txt{{position:absolute;left:96px;right:110px;top:535px;font-size:46px;line-height:1.5;padding-left:44px}}
.txt b{{font-weight:700;color:{C['amber']}}}
.foot{{position:absolute;left:96px;right:96px;bottom:70px;display:flex;justify-content:space-between;font-size:26px;color:#7F93B8;font-weight:500}}
.check ul{{position:absolute;left:140px;right:96px;top:520px;list-style:none}}
.check li{{font-size:40px;line-height:1.3;margin-bottom:34px;padding-left:84px;position:relative}}
.check li:before{{content:'';position:absolute;left:0;top:2px;width:50px;height:50px;border:5px solid {C['blue']};border-radius:12px}}
.check .note{{position:absolute;left:140px;right:96px;top:1085px;font-size:34px;color:{C['amber']};font-weight:500}}
.cta h1{{position:absolute;left:96px;right:96px;top:300px;font-size:88px}}
.cta .txt{{top:680px;padding-left:0;font-size:44px;line-height:1.4}}
.amb{{color:{C['amber']};font-weight:700}}
.link{{position:absolute;left:96px;top:1060px;font-size:40px;font-weight:700;color:{C['bg']};background:{C['amber']};padding:22px 46px;border-radius:60px}}
"""

FIT_JS = """
(spec) => {
  for (const [sel, maxBottom, min] of spec) {
    const els = document.querySelectorAll(sel);
    if (!els.length) continue;
    const bottom = () => Math.max(...[...els].map(e => e.getBoundingClientRect().bottom));
    let fs = parseFloat(getComputedStyle(els[0]).fontSize);
    while (bottom() > maxBottom && fs > min) { fs -= 2; els.forEach(e => e.style.fontSize = fs + 'px'); }
  }
}
"""


def esc(t):
    return html.escape(str(t or "").strip())


def paragraphs(text):
    return "<br><br>".join(esc(p) for p in str(text or "").split("\n\n") if p.strip())


def body_html(slide):
    out = paragraphs(slide.get("body"))
    if slide.get("highlight"):
        out += f"<br><br><b>{esc(slide['highlight'])}</b>"
    return out


def page(slide, i, n):
    k = slide["kind"]
    foot = f"<div class='foot'><span>{esc(BRAND_NAME)}</span><span>{i}/{n}</span></div>"
    if k == "cover":
        trail = ("<svg class='trail' viewBox='0 0 300 300'><path d='M10 290 C90 270 170 190 270 40' fill='none' "
                 f"stroke='{C['amber']}' stroke-width='5' stroke-dasharray='2 14' stroke-linecap='round'/>"
                 f"<path d='M270 40 L236 58 M270 40 L274 78' stroke='{C['amber']}' stroke-width='6' stroke-linecap='round'/></svg>")
        return (f"<div class='bgc'></div><div class='cover'><img class='logo' src='file://{ASSETS}/logo.png'>"
                f"<h1>{esc(slide['title'])}</h1><p>{esc(slide.get('body'))}</p>{trail}</div>")
    if k == "check":
        items = "".join(f"<li>{esc(t)}</li>" for t in slide.get("items", [])[:5])
        return (f"<div class='check'><div class='bar'></div><h1>{esc(slide['title'])}</h1><div class='sep'></div>"
                f"<ul>{items}</ul><div class='note'>{esc(slide.get('note'))}</div>{foot}</div>")
    if k == "cta":
        body = esc(slide.get("body")).replace("QUERO", "<span class='amb'>QUERO</span>")
        body = body.replace("\n\n", "<br><br>")
        return (f"<div class='cta'><img class='logo' src='file://{ASSETS}/logo.png'><h1>{esc(slide['title'])}</h1>"
                f"<div class='txt'>{body}</div><div class='link'>{esc(LINK_LABEL)}</div>{foot}</div>")
    return (f"<div class='content'><div class='bar'></div><h1>{esc(slide['title'])}</h1><div class='sep'></div>"
            f"<div class='txt'>{body_html(slide)}</div>{foot}</div>")


def render_slides(slides, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    n = len(slides)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--allow-file-access-from-files"])
        pg = browser.new_page(viewport={"width": 1080, "height": 1350})
        for i, s in enumerate(slides, 1):
            doc = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{page(s, i, n)}</body></html>"
            f = outdir / f"slide{i}.html"
            f.write_text(doc, encoding="utf-8")
            pg.goto(f"file://{f}")
            pg.wait_for_timeout(250)
            pg.evaluate(FIT_JS, [
                [".cover h1", 990, 60], [".content h1,.check h1", 470, 52], [".cta h1", 660, 56],
                [".content .txt", 1230, 30], [".cta .txt", 1040, 30], [".check li", 1070, 28],
            ])
            png = outdir / f"slide{i}.png"
            pg.screenshot(path=str(png))
            f.unlink()
            paths.append(png)
        browser.close()
    return paths
