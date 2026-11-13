"""Revisão rápida do texto, sem IA e sem rede: corrige o que é seguro e avisa o resto.

O que faz
- Corrige sozinha (só casos seguros): palavras terminadas em "ji" que são "gi" (ex.: "Finji" -> "Fingi", "elegi", "dirigi")
  e espaços duplicados.
- Avisa, sem mexer no texto: palavras que o dicionário não conhece (possível erro de digitação, com sugestões) e palavras
  repetidas em seguida ("de de", "que que"). Os avisos chegam ao Telegram junto com o post.
- Se uma palavra certa for apontada como erro, escreva-a numa linha de palavras_ok.txt (na raiz do repositório) e ela
  deixa de ser apontada.
Funciona com o pacote pyspellchecker (os workflows já o instalam). Sem ele, só corrige os casos "ji" de uma
lista curta e não dá avisos de ortografia. Nunca interrompe a geração: qualquer falha aqui só desliga a revisão.
"""
import re
from pathlib import Path

from .config import HISTORY_FILE

try:
    from spellchecker import SpellChecker
except Exception:   # pacote não instalado: a revisão fica reduzida, mas o agente segue funcionando
    SpellChecker = None

OK_FILE = HISTORY_FILE.parent / "palavras_ok.txt"

# palavras certas que o dicionário não conhece (termos de carreira, marcas, estrangeirismos comuns)
PALAVRAS_OK = set("""
linkedin instagram reels reel stories story feed hashtag hashtags telegram whatsapp google gemini canva pdf app apps site link
bio banner chat checklist checagem contatos gerenciar gerenciamento boletos embaixo fenômeno hobby mail registrar releia
networking feedback soft skills mindset headhunter onboarding brainstorming freelancer freela freelas coaching coach coaches
mentoria workshop dashboard deadline briefing inbox startup startups kpi kpis ats clt pov dm cv online offline home office
recolocação reposicionar reposicionamento posicionamento diagnóstico currículo recrutadores recrutador time times fuji
""".split())

# plano B do "ji" sem dicionário: verbos em -gir mais comuns, no passado (1ª pessoa)
FINJI_LISTA = {"fingi", "elegi", "dirigi", "corrigi", "exigi", "protegi", "surgi", "fugi", "atingi", "reagi", "afligi", "tingi",
               "erigi", "mugi", "cingi", "infringi", "restringi", "transigi", "emergi", "submergi", "imergi", "convergi", "divergi"}

TOKEN = re.compile(r"[A-Za-zÀ-ÿ]+(?:-[A-Za-zÀ-ÿ]+)*")
_sp = None
_carregado = False


def _speller():
    global _sp, _carregado
    if not _carregado:
        _carregado = True
        if SpellChecker is not None:
            try:
                _sp = SpellChecker(language="pt")
            except Exception:
                _sp = None
    return _sp


def _ok_extra():
    try:
        return {l.strip().lower() for l in OK_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    except OSError:
        return set()


def _conhece(palavra):
    sp = _speller()
    p = palavra.lower()
    if p in PALAVRAS_OK:
        return True
    return bool(sp is not None and p in sp)


def _mesma_caixa(modelo, texto):
    if modelo.isupper() and len(modelo) > 1:
        return texto.upper()
    if modelo[:1].isupper():
        return texto[:1].upper() + texto[1:]
    return texto


def _inicio_de_frase(texto, pos):
    return pos == 0 or bool(re.search(r"(^|[.!?:]\s+|\n\s*|[\"“(-]\s*)$", texto[:pos]))


def _corrige_ji(m):
    w = m.group(0)
    low = w.lower()
    if w[:1].isupper() and not w.isupper() and not _inicio_de_frase(m.string, m.start()):
        return w                                                          # nome próprio no meio da frase (ex.: Fuji)
    if not low.endswith("ji") or len(low) < 4 or low in PALAVRAS_OK:
        return w
    cand = low[:-2] + "gi"
    sp = _speller()
    if (sp is not None and cand in sp) or cand in FINJI_LISTA:
        return _mesma_caixa(w, cand)
    return w


def _sugestoes(low):
    sp = _speller()
    if sp is None:
        return []
    cands = sp.candidates(low) or set()
    cands = [c for c in cands if c != low]
    cands.sort(key=lambda c: -sp[c])   # as mais comuns primeiro
    return cands[:3]


def revisar_texto(texto, extra_ok=None):
    """Devolve (texto corrigido, lista de avisos)."""
    if not isinstance(texto, str) or not texto.strip():
        return texto, []
    ok = extra_ok if extra_ok is not None else _ok_extra()
    avisos, novo = [], texto
    novo = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", novo)             # espaços duplicados
    novo = TOKEN.sub(_corrige_ji, novo)                                 # Finji -> Fingi
    if novo != texto:
        antes = {w for w in TOKEN.findall(texto)}
        for w in TOKEN.findall(novo):
            if w not in antes and w.lower().endswith("gi"):
                avisos.append(f"corrigi “{_original(texto, w)}” para “{w}”")
    # palavras repetidas em seguida
    for m in re.finditer(r"\b([A-Za-zÀ-ÿ]{2,})\s+\1\b", novo, flags=re.I):
        avisos.append(f"palavra repetida: “{m.group(0)}”")
    # palavras desconhecidas
    if _speller() is not None:
        vistos = set()
        for m in TOKEN.finditer(novo):
            w = m.group(0)
            ini = m.start()
            if ini > 0 and novo[ini - 1] in "#@/.":
                continue                                                  # hashtag, menção, endereço
            if any(c.isdigit() for c in w) or w.isupper() or re.search(r"[a-zà-ÿ][A-ZÀ-Þ]", w):
                continue                                                  # siglas e nomes como LinkedIn
            if w[:1].isupper() and not re.search(r"(^|[.!?:]\s+|\n)$", novo[:ini]):
                continue                                                  # nome próprio no meio da frase
            partes = [p for p in w.split("-") if len(p) > 2]
            for p in partes:
                low = p.lower()
                if low in ok or low in vistos or _conhece(low):
                    continue
                vistos.add(low)
                sug = _sugestoes(low)
                avisos.append(f"“{p}” não está no dicionário" + (f" (sugestões: {', '.join(sug)})" if sug else ""))
    return novo, avisos


def _original(texto, corrigida):
    """Acha no texto original a palavra que virou 'corrigida' (só para o aviso)."""
    base = corrigida[:-2] + "ji"
    m = re.search(re.escape(base), texto, flags=re.I)
    return m.group(0) if m else base


def _walk(obj, fn, avisos, onde):
    if isinstance(obj, str):
        novo, av = fn(obj)
        avisos.extend(f"{onde}: {a}" for a in av)
        return novo
    if isinstance(obj, list):
        return [_walk(x, fn, avisos, f"{onde} {i + 1}") for i, x in enumerate(obj)]
    if isinstance(obj, dict):
        return {k: (v if k in PULAR else _walk(v, fn, avisos, onde)) for k, v in obj.items()}
    return obj


PULAR = {"kind", "format", "mode", "theme", "variant", "icon", "emoji", "show_link", "style"}


def _unicos(avisos, limite=10):
    vistos, out = set(), []
    for a in avisos:
        chave = a.split(": ", 1)[-1]
        if chave not in vistos:
            vistos.add(chave)
            out.append(a)
    return out[:limite]


def revisar_post(post):
    """Revisa legenda, slides e stories do post (corrige no próprio dicionário) e devolve os avisos."""
    try:
        ok, avisos = _ok_extra(), []
        fn = lambda t: revisar_texto(t, ok)
        if isinstance(post.get("caption"), str):
            post["caption"] = _walk(post["caption"], fn, avisos, "legenda")
        for chave, nome in (("slides", "slide"), ("stories", "story")):
            if post.get(chave):
                post[chave] = _walk(post[chave], fn, avisos, nome)
        return _unicos(avisos)
    except Exception as e:
        print(f"[revisao] falhou e foi ignorada: {e}", flush=True)
        return []


def revisar_roteiro(roteiro, caption=None):
    """Revisa o roteiro do Reel (gancho, cenas, chamada). Devolve (legenda, avisos); o roteiro é corrigido no próprio dicionário."""
    try:
        ok, avisos = _ok_extra(), []
        fn = lambda t: revisar_texto(t, ok)
        for k in ("gancho", "chamada"):
            if roteiro.get(k):
                roteiro[k] = _walk(roteiro[k], fn, avisos, k)
        roteiro["cenas"] = _walk(roteiro.get("cenas", []), fn, avisos, "cena")
        if caption:
            caption = _walk(caption, fn, avisos, "legenda")
        return caption, _unicos(avisos)
    except Exception as e:
        print(f"[revisao] falhou e foi ignorada: {e}", flush=True)
        return caption, []


def formatar_avisos(avisos):
    if not avisos:
        return ""
    return ("🔎 Revisão do texto:\n" + "\n".join(f"• {a}" for a in avisos)
            + "\nSe for uma palavra certa, adicione em palavras_ok.txt.")
