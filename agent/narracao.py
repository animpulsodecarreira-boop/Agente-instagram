"""Narração dos Reels com a voz do Gemini (TTS), em português do Brasil.

O que faz
- gerar_narracao(roteiro, pasta): cria um clipe de voz para o gancho, para cada cena (nas cenas "antes e depois", um para o antes e outro
  para o depois) e para a chamada final. Cada clipe é limpo (sem silêncio nas pontas) e nivelado no mesmo volume. A duração de cada
  clipe manda no ritmo do vídeo (reel_palco.py).
- Se qualquer clipe falhar, devolve erro e o Reel sai sem narração (só com música), como antes. Nunca derruba o Reel.
- python -m agent.narracao --testar: gera uma frase de teste e manda o áudio ao Telegram (workflow "Testar voz").

Configuração (variáveis do repositório, em Settings > Secrets and variables > Actions > Variables; todas opcionais)
  TTS_VOZ     nome da voz do Gemini (padrão: Orus). Outras vozes firmes/graves: Alnilam, Algenib, Charon.
  TTS_GRAVE   1.0 = voz como vem; 0.94 deixa um pouco mais grave (muda o tom sem mudar a velocidade).
  TTS_DESSER  0 a 1: força do removedor de chiado dos "s" (sibilância). Padrão 0.6; 0 desliga; 0.8 é bem forte (pode "embolar" os s).
  TTS_MODELO  força um modelo de voz específico; sem isso, o robô descobre o melhor modelo disponível para a sua chave.
  TTS_ESTILO  instrução de estilo curta (ex.: "Diga com firmeza"). Por padrão fica VAZIO de propósito: o modelo de voz costuma LER a
              instrução em voz alta antes de cada frase. O tom vem da voz escolhida (Orus é firme) e do TTS_GRAVE.
  NARRACAO    0 desliga a narração.
Os modelos de voz do Gemini ainda estão em prévia e mudam de nome: por isso o robô lista os modelos da sua conta em vez de fixar um nome.
"""
import argparse
import base64
import os
import re
import subprocess
import time
import wave
from pathlib import Path

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
VOZ_PADRAO = "Orus"
PRAZO_TOTAL = 420        # segundos para gerar todos os clipes de um Reel
TETO_FALA = 38.0         # segundos de vídeo; acima disso a voz é acelerada (até 15%)

LEAD = {"MITO": "Mito.", "VERDADE": "Verdade.", "O ERRO": "O erro.", "POR QUE ATRAPALHA": "Por que atrapalha?",
        "CORRIJA ASSIM": "Corrija assim.", "FAÇA ASSIM": "Faça assim.", "FAÇA ISSO": "Faça isso.", "POR QUÊ": "Por quê?",
        "HOJE": "Hoje.", "NA PRÁTICA": "Na prática.", "EVITE": "Evite.", "A VIRADA": "A virada.", "DEPOIS": "Depois.",
        "RESPOSTA CURTA": "Resposta curta.", "COMO RESPONDER": "Como responder?", "O QUE ELE QUER SABER": "O que ele quer saber?"}
ORDINAIS = {"1": "Primeiro.", "2": "Segundo.", "3": "Terceiro.", "4": "Quarto.", "5": "Quinto."}


# ---------------- texto falado ----------------
def _limpo(t):
    t = re.sub(r"\bPOV:?", "Ponto de vista:", str(t or ""))
    t = t.replace("nº", "número").replace("Nº", "Número").replace("&", " e ")
    t = re.sub(r"[#*_`\[\]<>]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def falas(roteiro):
    """O que o narrador diz em cada parte: {'hook': str, 'beats': [{'antes': str|None, 'texto': str}], 'cta': str}."""
    beats = []
    for c in roteiro.get("cenas", []):
        texto, apoio, antes = _limpo(c.get("texto")), _limpo(c.get("apoio")), _limpo(c.get("antes"))
        if not texto:
            continue
        if antes:
            beats.append({"antes": f"Antes. {antes}.", "texto": f"Depois. {texto}." + (f" {apoio}" if apoio else "")})
            continue
        rot = _limpo(c.get("rotulo")).upper()
        lead = ORDINAIS.get(rot) or LEAD.get(rot) or ""
        beats.append({"antes": None, "texto": (lead + " " if lead else "") + texto + ("." if texto[-1] not in ".?!" else "") + (f" {apoio}" if apoio else "")})
    return {"hook": _limpo(roteiro.get("gancho")), "beats": beats, "cta": _limpo(roteiro.get("chamada"))}


# ---------------- Gemini TTS ----------------
def _erro_http(r):
    try:
        e = r.json().get("error", {})
        return f"HTTP {r.status_code}: {str(e.get('message', r.text))[:200]}"
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"


def _espera_429(r):
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text) or re.search(r"retry in (\d+(?:\.\d+)?)s", r.text)
    return min(70.0, float(m.group(1)) + 1.0) if m else 25.0


def modelos_tts(key):
    """Modelos de voz disponíveis para a chave, do mais indicado para o menos (versões finais antes das prévias, mais novos antes)."""
    forcado = os.getenv("TTS_MODELO", "").strip()
    if forcado:
        return [forcado]
    r = requests.get(f"{BASE}/models", params={"key": key, "pageSize": 200}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError("não consegui listar os modelos do Gemini: " + _erro_http(r))
    nomes = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "tts" in m["name"].lower() and "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if not nomes:
        raise RuntimeError("nenhum modelo de voz (TTS) disponível para esta chave do Gemini")

    def chave(n):
        versao = tuple(-float(x) for x in re.findall(r"\d+(?:\.\d+)?", n))
        return ("preview" in n, versao, "lite" in n, n)
    return sorted(nomes, key=chave)


def _pcm_para_wav(b64, mime, destino):
    pcm = base64.b64decode(b64)
    m = re.search(r"rate=(\d+)", mime or "")
    taxa = int(m.group(1)) if m else 24000
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)
    return taxa


def _estilo():
    return os.getenv("TTS_ESTILO", "").strip()


def _uma_chamada(key, modelo, voz, texto, destino, estilo=None):
    corpo = {"contents": [{"parts": [{"text": f"{estilo}: {texto}" if estilo else texto}]}],
             "generationConfig": {"responseModalities": ["AUDIO"],
                                  "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}}}
    for tentativa in range(4):
        try:
            r = requests.post(f"{BASE}/models/{modelo}:generateContent", params={"key": key}, json=corpo, timeout=(15, 90))
        except requests.exceptions.RequestException as e:
            if tentativa == 3:
                raise RuntimeError(f"falha de conexão com o Gemini ({type(e).__name__})")
            time.sleep(5 * (tentativa + 1))
            continue
        if r.status_code == 200:
            try:
                parte = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                return _pcm_para_wav(parte["data"], parte.get("mimeType", ""), destino)
            except (KeyError, IndexError, TypeError, ValueError):
                if tentativa >= 1:
                    raise RuntimeError("o Gemini respondeu sem áudio")
                time.sleep(3)
                continue
        if r.status_code == 429:
            espera = _espera_429(r)
            if tentativa == 3 or "limit: 0" in r.text:
                raise RuntimeError("limite de uso da voz do Gemini atingido: " + _erro_http(r))
            print(f"[voz] limite de pedidos; esperando {espera:.0f}s", flush=True)
            time.sleep(espera)
            continue
        if r.status_code in (500, 502, 503, 504) and tentativa < 3:
            time.sleep(6 * (tentativa + 1))
            continue
        raise RuntimeError(_erro_http(r))
    raise RuntimeError("não consegui gerar a voz")


def _ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-200:])


def _duracao(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / float(w.getframerate())


def _niveis(arquivo):
    """(volume médio, volume máximo) em dB, como o ffmpeg mede."""
    r = subprocess.run(["ffmpeg", "-i", str(arquivo), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m, x = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr), re.search(r"max_volume: (-?[\d.]+) dB", r.stderr)
    return (float(m.group(1)), float(x.group(1))) if m and x else (-91.0, -91.0)


def _forca_desser():
    try:
        return min(1.0, max(0.0, float(os.getenv("TTS_DESSER", "") or 0.6)))
    except ValueError:
        return 0.6


def _limpa(entrada, saida, grave=1.0, tempo=1.0):
    """Limpa o clipe de voz: filtra o que não é voz, REMOVE O CHIADO DOS "S" (de-esser), corta o silêncio das pontas (limiar relativo
    ao pico da fala), faz fade nas pontas e nivela o volume pelo valor medido (sem loudnorm).
    O de-esser existe porque, nas vozes sintéticas, as sibilantes ("s", "x", "ch") saem tão altas quanto as vogais e soam como chiado."""
    saida = Path(saida)
    p1, p1d, p2 = saida.with_suffix(".p1.wav"), saida.with_suffix(".p1d.wav"), saida.with_suffix(".p2.wav")
    base = ["highpass=f=80", "lowpass=f=10500"]
    if abs(grave - 1.0) > 0.005:
        base += [f"asetrate=24000*{grave:.4f}", "aresample=24000", f"atempo={1 / grave:.4f}"]
    if abs(tempo - 1.0) > 0.005:
        base.append(f"atempo={tempo:.4f}")
    _ffmpeg(["-i", str(entrada), "-af", ",".join(base), "-ar", "24000", "-ac", "1", str(p1)])
    # 1) corta o silêncio das pontas ANTES do de-esser (com o "s" ainda forte, para não confundir um "s" no começo ou no fim com silêncio)
    _, pico = _niveis(p1)
    th = max(-48.0, min(-30.0, pico - 30.0))
    corte = f"silenceremove=start_periods=1:start_threshold={th:.0f}dB:start_silence=0.05"
    p1t = saida.with_suffix(".p1t.wav")
    _ffmpeg(["-i", str(p1), "-af", ",".join([corte, "areverse", corte, "areverse"]), "-ar", "24000", "-ac", "1", str(p1t)])
    # 2) tira o chiado dos "s"
    f = _forca_desser()
    fonte = p1t
    if f > 0:
        try:
            ds = f"aresample=44100,deesser=i={f:.2f}:m={min(0.9, f + 0.1):.2f}:f=0.5,equalizer=f=7000:t=q:w=0.8:g={-5 * f:.1f},aresample=24000"
            _ffmpeg(["-i", str(p1t), "-af", ds, "-ar", "24000", "-ac", "1", str(p1d)])
            fonte = p1d
        except RuntimeError as e:   # este ffmpeg não tem o filtro: segue sem o de-esser
            print(f"[voz] de-esser indisponível ({str(e)[:80]}); seguindo sem ele", flush=True)
    # 3) fades nas pontas
    _ffmpeg(["-i", str(fonte), "-af", "afade=t=in:d=0.012,areverse,afade=t=in:d=0.06,areverse", "-ar", "24000", "-ac", "1", str(p2)])
    media, pico2 = _niveis(p2)
    ganho = max(-12.0, min(12.0, min(-19.0 - media, -1.5 - pico2))) if media > -80 else 0.0
    _ffmpeg(["-i", str(p2), "-af", f"volume={ganho:.2f}dB,alimiter=limit=0.9", "-ar", "24000", "-ac", "1", str(saida)])
    for p in (p1, p1t, p1d, p2):
        p.unlink(missing_ok=True)


def _cfg():
    try:
        grave = float(os.getenv("TTS_GRAVE", "") or 1.0)
    except ValueError:
        grave = 1.0
    return (os.getenv("TTS_VOZ", "").strip() or VOZ_PADRAO), min(1.0, max(0.85, grave))


def sintetizar_clipe(key, modelos, voz, texto, destino, grave=1.0, tempo=1.0, estilo=None):
    """Gera um clipe. Devolve (modelo que funcionou, duração em segundos).
    Se houver instrução de estilo e o áudio vier longo demais para o texto (sinal de que o modelo leu a instrução em voz alta),
    gera de novo sem a instrução."""
    bruto = Path(destino).with_suffix(".bruto.wav")
    ultimo = None
    for modelo in modelos[:3]:
        try:
            _uma_chamada(key, modelo, voz, texto, bruto, estilo)
            _limpa(bruto, destino, grave, tempo)
            bruto.unlink(missing_ok=True)
            dur = _duracao(destino)
            if estilo and dur > 0.115 * len(texto) + 1.5:
                print("[voz] o áudio veio longo demais (o modelo provavelmente leu a instrução de estilo); gerando de novo sem ela", flush=True)
                _uma_chamada(key, modelo, voz, texto, bruto, None)
                _limpa(bruto, destino, grave, tempo)
                bruto.unlink(missing_ok=True)
                dur = _duracao(destino)
            return modelo, dur
        except RuntimeError as e:
            ultimo = e
            if not re.search(r"HTTP (400|403|404)", str(e)):
                raise
            print(f"[voz] modelo {modelo} não serviu ({str(e)[:120]}); tentando o próximo", flush=True)
    raise ultimo or RuntimeError("nenhum modelo de voz funcionou")


def gerar_narracao(roteiro, pasta):
    """Clipes de voz do Reel. Devolve {'hook':clipe,'beats':[{'antes':clipe|None,'texto':clipe}],'cta':clipe,'voz':..,'modelo':..}
    com clipe = {'path': Path, 'dur': segundos}. Levanta RuntimeError se algo falhar."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY ausente")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    voz, grave = _cfg()
    t_fala = falas(roteiro)
    if not t_fala["hook"] or not t_fala["beats"]:
        raise RuntimeError("roteiro sem texto para narrar")
    modelos = modelos_tts(key)
    inicio, usado = time.time(), {"modelo": modelos[0]}
    n = [0]

    def clipe(texto):
        if time.time() - inicio > PRAZO_TOTAL:
            raise RuntimeError("tempo esgotado para gerar a voz")
        n[0] += 1
        p = pasta / f"v{n[0]:02d}.wav"
        m, d = sintetizar_clipe(key, modelos, voz, texto, p, grave, estilo=_estilo())
        usado["modelo"] = m
        modelos[:] = [m] + [x for x in modelos if x != m]
        print(f"[voz] clipe {n[0]} ({d:.1f}s) com {m}/{voz}", flush=True)
        return {"path": p, "dur": d}
    out = {"hook": clipe(t_fala["hook"]), "beats": []}
    for b in t_fala["beats"]:
        out["beats"].append({"antes": clipe(b["antes"]) if b["antes"] else None, "texto": clipe(b["texto"])})
    out["cta"] = clipe(t_fala["cta"]) if t_fala["cta"] else None
    # se a fala não cabe no teto do vídeo, acelera todos os clipes (no máximo 15%)
    todos = [out["hook"], out["cta"]] + [c for b in out["beats"] for c in (b["antes"], b["texto"])]
    todos = [c for c in todos if c]
    estimado = sum(c["dur"] for c in todos) + 0.6 * len(todos) + 1.0
    if estimado > TETO_FALA:
        fator = min(1.15, estimado / TETO_FALA)
        for c in todos:
            acel = c["path"].with_suffix(".rapido.wav")
            _ffmpeg(["-i", str(c["path"]), "-af", f"atempo={fator:.4f}", "-ar", "24000", "-ac", "1", str(acel)])
            c["path"], c["dur"] = acel, _duracao(acel)
    out.update(voz=voz, modelo=usado["modelo"])
    return out


# ---------------- teste de voz ----------------
def _telegram_audio(caminho, legenda):
    tk, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not tk or not chat:
        print("[voz] sem Telegram configurado; áudio salvo em", caminho)
        return
    with open(caminho, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{tk}/sendAudio", data={"chat_id": chat, "caption": legenda[:900]},
                          files={"audio": (Path(caminho).name, f)}, timeout=120)
    print("[voz] Telegram:", "enviado" if r.status_code == 200 else f"falhou (HTTP {r.status_code})")


def testar(voz, texto, grave, estilo=""):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("GEMINI_API_KEY ausente")
    pasta = Path("_teste_voz")
    pasta.mkdir(exist_ok=True)
    modelos = modelos_tts(key)
    print("[voz] modelos de voz disponíveis:", ", ".join(modelos[:6]), flush=True)
    wav = pasta / "teste.wav"
    modelo, dur = sintetizar_clipe(key, modelos, voz, _limpo(texto), wav, grave, estilo=estilo or None)
    m4a = pasta / f"voz_{voz}.m4a"
    _ffmpeg(["-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(m4a)])
    _telegram_audio(m4a, f"🎙 Teste de voz\nVoz: {voz}\nModelo: {modelo}\nDuração: {dur:.1f}s\nTom mais grave (TTS_GRAVE): {grave}\nEstilo: {estilo or '(nenhum)'}")
    print(f"[voz] ok: {dur:.1f}s com {modelo}/{voz}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--voz", default="")
    ap.add_argument("--texto", default="Seu currículo não precisa de três páginas. Precisa de clareza. Pare de listar tarefas e mostre o que mudou.")
    ap.add_argument("--grave", type=float, default=0)
    ap.add_argument("--estilo", default="")
    a = ap.parse_args()
    v, g = _cfg()
    if a.testar:
        testar(a.voz or v, a.texto, a.grave or g, a.estilo)"""Narração dos Reels com a voz do Gemini (TTS), em português do Brasil.

O que faz
- gerar_narracao(roteiro, pasta): cria um clipe de voz para o gancho, para cada cena (nas cenas "antes e depois", um para o antes e outro
  para o depois) e para a chamada final. Cada clipe é limpo (sem silêncio nas pontas) e nivelado no mesmo volume. A duração de cada
  clipe manda no ritmo do vídeo (reel_palco.py).
- Se qualquer clipe falhar, devolve erro e o Reel sai sem narração (só com música), como antes. Nunca derruba o Reel.
- python -m agent.narracao --testar: gera uma frase de teste e manda o áudio ao Telegram (workflow "Testar voz").

Configuração (variáveis do repositório, em Settings > Secrets and variables > Actions > Variables; todas opcionais)
  TTS_VOZ     nome da voz do Gemini (padrão: Orus). Outras vozes firmes/graves: Alnilam, Algenib, Charon.
  TTS_GRAVE   1.0 = voz como vem; 0.94 deixa um pouco mais grave (muda o tom sem mudar a velocidade).
  TTS_DESSER  0 a 1: força do removedor de chiado dos "s" (sibilância). Padrão 0.6; 0 desliga; 0.8 é bem forte (pode "embolar" os s).
  TTS_MODELO  força um modelo de voz específico; sem isso, o robô descobre o melhor modelo disponível para a sua chave.
  TTS_ESTILO  instrução de estilo curta (ex.: "Diga com firmeza"). Por padrão fica VAZIO de propósito: o modelo de voz costuma LER a
              instrução em voz alta antes de cada frase. O tom vem da voz escolhida (Orus é firme) e do TTS_GRAVE.
  NARRACAO    0 desliga a narração.
Os modelos de voz do Gemini ainda estão em prévia e mudam de nome: por isso o robô lista os modelos da sua conta em vez de fixar um nome.
"""
import argparse
import base64
import os
import re
import subprocess
import time
import wave
from pathlib import Path

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
VOZ_PADRAO = "Orus"
PRAZO_TOTAL = 420        # segundos para gerar todos os clipes de um Reel
TETO_FALA = 38.0         # segundos de vídeo; acima disso a voz é acelerada (até 15%)

LEAD = {"MITO": "Mito.", "VERDADE": "Verdade.", "O ERRO": "O erro.", "POR QUE ATRAPALHA": "Por que atrapalha?",
        "CORRIJA ASSIM": "Corrija assim.", "FAÇA ASSIM": "Faça assim.", "FAÇA ISSO": "Faça isso.", "POR QUÊ": "Por quê?",
        "HOJE": "Hoje.", "NA PRÁTICA": "Na prática.", "EVITE": "Evite.", "A VIRADA": "A virada.", "DEPOIS": "Depois.",
        "RESPOSTA CURTA": "Resposta curta.", "COMO RESPONDER": "Como responder?", "O QUE ELE QUER SABER": "O que ele quer saber?"}
ORDINAIS = {"1": "Primeiro.", "2": "Segundo.", "3": "Terceiro.", "4": "Quarto.", "5": "Quinto."}


# ---------------- texto falado ----------------
def _limpo(t):
    t = re.sub(r"\bPOV:?", "Ponto de vista:", str(t or ""))
    t = t.replace("nº", "número").replace("Nº", "Número").replace("&", " e ")
    t = re.sub(r"[#*_`\[\]<>]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def falas(roteiro):
    """O que o narrador diz em cada parte: {'hook': str, 'beats': [{'antes': str|None, 'texto': str}], 'cta': str}."""
    beats = []
    for c in roteiro.get("cenas", []):
        texto, apoio, antes = _limpo(c.get("texto")), _limpo(c.get("apoio")), _limpo(c.get("antes"))
        if not texto:
            continue
        if antes:
            beats.append({"antes": f"Antes. {antes}.", "texto": f"Depois. {texto}." + (f" {apoio}" if apoio else "")})
            continue
        rot = _limpo(c.get("rotulo")).upper()
        lead = ORDINAIS.get(rot) or LEAD.get(rot) or ""
        beats.append({"antes": None, "texto": (lead + " " if lead else "") + texto + ("." if texto[-1] not in ".?!" else "") + (f" {apoio}" if apoio else "")})
    return {"hook": _limpo(roteiro.get("gancho")), "beats": beats, "cta": _limpo(roteiro.get("chamada"))}


# ---------------- Gemini TTS ----------------
def _erro_http(r):
    try:
        e = r.json().get("error", {})
        return f"HTTP {r.status_code}: {str(e.get('message', r.text))[:200]}"
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"


def _espera_429(r):
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text) or re.search(r"retry in (\d+(?:\.\d+)?)s", r.text)
    return min(70.0, float(m.group(1)) + 1.0) if m else 25.0


def modelos_tts(key):
    """Modelos de voz disponíveis para a chave, do mais indicado para o menos (versões finais antes das prévias, mais novos antes)."""
    forcado = os.getenv("TTS_MODELO", "").strip()
    if forcado:
        return [forcado]
    r = requests.get(f"{BASE}/models", params={"key": key, "pageSize": 200}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError("não consegui listar os modelos do Gemini: " + _erro_http(r))
    nomes = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "tts" in m["name"].lower() and "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if not nomes:
        raise RuntimeError("nenhum modelo de voz (TTS) disponível para esta chave do Gemini")

    def chave(n):
        versao = tuple(-float(x) for x in re.findall(r"\d+(?:\.\d+)?", n))
        return ("preview" in n, versao, "lite" in n, n)
    return sorted(nomes, key=chave)


def _pcm_para_wav(b64, mime, destino):
    pcm = base64.b64decode(b64)
    m = re.search(r"rate=(\d+)", mime or "")
    taxa = int(m.group(1)) if m else 24000
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)
    return taxa


def _estilo():
    return os.getenv("TTS_ESTILO", "").strip()


def _uma_chamada(key, modelo, voz, texto, destino, estilo=None):
    corpo = {"contents": [{"parts": [{"text": f"{estilo}: {texto}" if estilo else texto}]}],
             "generationConfig": {"responseModalities": ["AUDIO"],
                                  "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}}}
    for tentativa in range(4):
        try:
            r = requests.post(f"{BASE}/models/{modelo}:generateContent", params={"key": key}, json=corpo, timeout=(15, 90))
        except requests.exceptions.RequestException as e:
            if tentativa == 3:
                raise RuntimeError(f"falha de conexão com o Gemini ({type(e).__name__})")
            time.sleep(5 * (tentativa + 1))
            continue
        if r.status_code == 200:
            try:
                parte = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                return _pcm_para_wav(parte["data"], parte.get("mimeType", ""), destino)
            except (KeyError, IndexError, TypeError, ValueError):
                if tentativa >= 1:
                    raise RuntimeError("o Gemini respondeu sem áudio")
                time.sleep(3)
                continue
        if r.status_code == 429:
            espera = _espera_429(r)
            if tentativa == 3 or "limit: 0" in r.text:
                raise RuntimeError("limite de uso da voz do Gemini atingido: " + _erro_http(r))
            print(f"[voz] limite de pedidos; esperando {espera:.0f}s", flush=True)
            time.sleep(espera)
            continue
        if r.status_code in (500, 502, 503, 504) and tentativa < 3:
            time.sleep(6 * (tentativa + 1))
            continue
        raise RuntimeError(_erro_http(r))
    raise RuntimeError("não consegui gerar a voz")


def _ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-200:])


def _duracao(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / float(w.getframerate())


def _niveis(arquivo):
    """(volume médio, volume máximo) em dB, como o ffmpeg mede."""
    r = subprocess.run(["ffmpeg", "-i", str(arquivo), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m, x = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr), re.search(r"max_volume: (-?[\d.]+) dB", r.stderr)
    return (float(m.group(1)), float(x.group(1))) if m and x else (-91.0, -91.0)


def _forca_desser():
    try:
        return min(1.0, max(0.0, float(os.getenv("TTS_DESSER", "") or 0.6)))
    except ValueError:
        return 0.6


def _limpa(entrada, saida, grave=1.0, tempo=1.0):
    """Limpa o clipe de voz: filtra o que não é voz, REMOVE O CHIADO DOS "S" (de-esser), corta o silêncio das pontas (limiar relativo
    ao pico da fala), faz fade nas pontas e nivela o volume pelo valor medido (sem loudnorm).
    O de-esser existe porque, nas vozes sintéticas, as sibilantes ("s", "x", "ch") saem tão altas quanto as vogais e soam como chiado."""
    saida = Path(saida)
    p1, p1d, p2 = saida.with_suffix(".p1.wav"), saida.with_suffix(".p1d.wav"), saida.with_suffix(".p2.wav")
    base = ["highpass=f=80", "lowpass=f=10500"]
    if abs(grave - 1.0) > 0.005:
        base += [f"asetrate=24000*{grave:.4f}", "aresample=24000", f"atempo={1 / grave:.4f}"]
    if abs(tempo - 1.0) > 0.005:
        base.append(f"atempo={tempo:.4f}")
    _ffmpeg(["-i", str(entrada), "-af", ",".join(base), "-ar", "24000", "-ac", "1", str(p1)])
    # 1) corta o silêncio das pontas ANTES do de-esser (com o "s" ainda forte, para não confundir um "s" no começo ou no fim com silêncio)
    _, pico = _niveis(p1)
    th = max(-48.0, min(-30.0, pico - 30.0))
    corte = f"silenceremove=start_periods=1:start_threshold={th:.0f}dB:start_silence=0.05"
    p1t = saida.with_suffix(".p1t.wav")
    _ffmpeg(["-i", str(p1), "-af", ",".join([corte, "areverse", corte, "areverse"]), "-ar", "24000", "-ac", "1", str(p1t)])
    # 2) tira o chiado dos "s"
    f = _forca_desser()
    fonte = p1t
    if f > 0:
        try:
            ds = f"aresample=44100,deesser=i={f:.2f}:m={min(0.9, f + 0.1):.2f}:f=0.5,equalizer=f=7000:t=q:w=0.8:g={-5 * f:.1f},aresample=24000"
            _ffmpeg(["-i", str(p1t), "-af", ds, "-ar", "24000", "-ac", "1", str(p1d)])
            fonte = p1d
        except RuntimeError as e:   # este ffmpeg não tem o filtro: segue sem o de-esser
            print(f"[voz] de-esser indisponível ({str(e)[:80]}); seguindo sem ele", flush=True)
    # 3) fades nas pontas
    _ffmpeg(["-i", str(fonte), "-af", "afade=t=in:d=0.012,areverse,afade=t=in:d=0.06,areverse", "-ar", "24000", "-ac", "1", str(p2)])
    media, pico2 = _niveis(p2)
    ganho = max(-12.0, min(12.0, min(-19.0 - media, -1.5 - pico2))) if media > -80 else 0.0
    _ffmpeg(["-i", str(p2), "-af", f"volume={ganho:.2f}dB,alimiter=limit=0.9", "-ar", "24000", "-ac", "1", str(saida)])
    for p in (p1, p1t, p1d, p2):
        p.unlink(missing_ok=True)


def _cfg():
    try:
        grave = float(os.getenv("TTS_GRAVE", "") or 1.0)
    except ValueError:
        grave = 1.0
    return (os.getenv("TTS_VOZ", "").strip() or VOZ_PADRAO), min(1.0, max(0.85, grave))


def sintetizar_clipe(key, modelos, voz, texto, destino, grave=1.0, tempo=1.0, estilo=None):
    """Gera um clipe. Devolve (modelo que funcionou, duração em segundos).
    Se houver instrução de estilo e o áudio vier longo demais para o texto (sinal de que o modelo leu a instrução em voz alta),
    gera de novo sem a instrução."""
    bruto = Path(destino).with_suffix(".bruto.wav")
    ultimo = None
    for modelo in modelos[:3]:
        try:
            _uma_chamada(key, modelo, voz, texto, bruto, estilo)
            _limpa(bruto, destino, grave, tempo)
            bruto.unlink(missing_ok=True)
            dur = _duracao(destino)
            if estilo and dur > 0.115 * len(texto) + 1.5:
                print("[voz] o áudio veio longo demais (o modelo provavelmente leu a instrução de estilo); gerando de novo sem ela", flush=True)
                _uma_chamada(key, modelo, voz, texto, bruto, None)
                _limpa(bruto, destino, grave, tempo)
                bruto.unlink(missing_ok=True)
                dur = _duracao(destino)
            return modelo, dur
        except RuntimeError as e:
            ultimo = e
            if not re.search(r"HTTP (400|403|404)", str(e)):
                raise
            print(f"[voz] modelo {modelo} não serviu ({str(e)[:120]}); tentando o próximo", flush=True)
    raise ultimo or RuntimeError("nenhum modelo de voz funcionou")


def gerar_narracao(roteiro, pasta):
    """Clipes de voz do Reel. Devolve {'hook':clipe,'beats':[{'antes':clipe|None,'texto':clipe}],'cta':clipe,'voz':..,'modelo':..}
    com clipe = {'path': Path, 'dur': segundos}. Levanta RuntimeError se algo falhar."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY ausente")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    voz, grave = _cfg()
    t_fala = falas(roteiro)
    if not t_fala["hook"] or not t_fala["beats"]:
        raise RuntimeError("roteiro sem texto para narrar")
    modelos = modelos_tts(key)
    inicio, usado = time.time(), {"modelo": modelos[0]}
    n = [0]

    def clipe(texto):
        if time.time() - inicio > PRAZO_TOTAL:
            raise RuntimeError("tempo esgotado para gerar a voz")
        n[0] += 1
        p = pasta / f"v{n[0]:02d}.wav"
        m, d = sintetizar_clipe(key, modelos, voz, texto, p, grave, estilo=_estilo())
        usado["modelo"] = m
        modelos[:] = [m] + [x for x in modelos if x != m]
        print(f"[voz] clipe {n[0]} ({d:.1f}s) com {m}/{voz}", flush=True)
        return {"path": p, "dur": d}
    out = {"hook": clipe(t_fala["hook"]), "beats": []}
    for b in t_fala["beats"]:
        out["beats"].append({"antes": clipe(b["antes"]) if b["antes"] else None, "texto": clipe(b["texto"])})
    out["cta"] = clipe(t_fala["cta"]) if t_fala["cta"] else None
    # se a fala não cabe no teto do vídeo, acelera todos os clipes (no máximo 15%)
    todos = [out["hook"], out["cta"]] + [c for b in out["beats"] for c in (b["antes"], b["texto"])]
    todos = [c for c in todos if c]
    estimado = sum(c["dur"] for c in todos) + 0.6 * len(todos) + 1.0
    if estimado > TETO_FALA:
        fator = min(1.15, estimado / TETO_FALA)
        for c in todos:
            acel = c["path"].with_suffix(".rapido.wav")
            _ffmpeg(["-i", str(c["path"]), "-af", f"atempo={fator:.4f}", "-ar", "24000", "-ac", "1", str(acel)])
            c["path"], c["dur"] = acel, _duracao(acel)
    out.update(voz=voz, modelo=usado["modelo"])
    return out


# ---------------- teste de voz ----------------
def _telegram_audio(caminho, legenda):
    tk, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not tk or not chat:
        print("[voz] sem Telegram configurado; áudio salvo em", caminho)
        return
    with open(caminho, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{tk}/sendAudio", data={"chat_id": chat, "caption": legenda[:900]},
                          files={"audio": (Path(caminho).name, f)}, timeout=120)
    print("[voz] Telegram:", "enviado" if r.status_code == 200 else f"falhou (HTTP {r.status_code})")


def testar(voz, texto, grave, estilo=""):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("GEMINI_API_KEY ausente")
    pasta = Path("_teste_voz")
    pasta.mkdir(exist_ok=True)
    modelos = modelos_tts(key)
    print("[voz] modelos de voz disponíveis:", ", ".join(modelos[:6]), flush=True)
    wav = pasta / "teste.wav"
    modelo, dur = sintetizar_clipe(key, modelos, voz, _limpo(texto), wav, grave, estilo=estilo or None)
    m4a = pasta / f"voz_{voz}.m4a"
    _ffmpeg(["-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(m4a)])
    _telegram_audio(m4a, f"🎙 Teste de voz\nVoz: {voz}\nModelo: {modelo}\nDuração: {dur:.1f}s\nTom mais grave (TTS_GRAVE): {grave}\nEstilo: {estilo or '(nenhum)'}")
    print(f"[voz] ok: {dur:.1f}s com {modelo}/{voz}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--voz", default="")
    ap.add_argument("--texto", default="Seu currículo não precisa de três páginas. Precisa de clareza. Pare de listar tarefas e mostre o que mudou.")
    ap.add_argument("--grave", type=float, default=0)
    ap.add_argument("--estilo", default="")
    a = ap.parse_args()
    v, g = _cfg()
    if a.testar:
        testar(a.voz or v, a.texto, a.grave or g, a.estilo)"""Narração dos Reels com a voz do Gemini (TTS), em português do Brasil.

O que faz
- gerar_narracao(roteiro, pasta): cria um clipe de voz para o gancho, para cada cena (nas cenas "antes e depois", um para o antes e outro
  para o depois) e para a chamada final. Cada clipe é limpo (sem silêncio nas pontas) e nivelado no mesmo volume. A duração de cada
  clipe manda no ritmo do vídeo (reel_palco.py).
- Se qualquer clipe falhar, devolve erro e o Reel sai sem narração (só com música), como antes. Nunca derruba o Reel.
- python -m agent.narracao --testar: gera uma frase de teste e manda o áudio ao Telegram (workflow "Testar voz").

Configuração (variáveis do repositório, em Settings > Secrets and variables > Actions > Variables; todas opcionais)
  TTS_VOZ     nome da voz do Gemini (padrão: Orus). Outras vozes firmes/graves: Alnilam, Algenib, Charon.
  TTS_GRAVE   1.0 = voz como vem; 0.94 deixa um pouco mais grave (muda o tom sem mudar a velocidade).
  TTS_DESSER  0 a 1: força do removedor de chiado dos "s" (sibilância). Padrão 0.6; 0 desliga; 0.8 é bem forte (pode "embolar" os s).
  TTS_MODELO  força um modelo de voz específico; sem isso, o robô descobre o melhor modelo disponível para a sua chave.
  TTS_ESTILO  instrução de estilo curta (ex.: "Diga com firmeza"). Por padrão fica VAZIO de propósito: o modelo de voz costuma LER a
              instrução em voz alta antes de cada frase. O tom vem da voz escolhida (Orus é firme) e do TTS_GRAVE.
  NARRACAO    0 desliga a narração.
Os modelos de voz do Gemini ainda estão em prévia e mudam de nome: por isso o robô lista os modelos da sua conta em vez de fixar um nome.
"""
import argparse
import base64
import os
import re
import subprocess
import time
import wave
from pathlib import Path

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
VOZ_PADRAO = "Orus"
PRAZO_TOTAL = 420        # segundos para gerar todos os clipes de um Reel
TETO_FALA = 38.0         # segundos de vídeo; acima disso a voz é acelerada (até 15%)

LEAD = {"MITO": "Mito.", "VERDADE": "Verdade.", "O ERRO": "O erro.", "POR QUE ATRAPALHA": "Por que atrapalha?",
        "CORRIJA ASSIM": "Corrija assim.", "FAÇA ASSIM": "Faça assim.", "FAÇA ISSO": "Faça isso.", "POR QUÊ": "Por quê?",
        "HOJE": "Hoje.", "NA PRÁTICA": "Na prática.", "EVITE": "Evite.", "A VIRADA": "A virada.", "DEPOIS": "Depois.",
        "RESPOSTA CURTA": "Resposta curta.", "COMO RESPONDER": "Como responder?", "O QUE ELE QUER SABER": "O que ele quer saber?"}
ORDINAIS = {"1": "Primeiro.", "2": "Segundo.", "3": "Terceiro.", "4": "Quarto.", "5": "Quinto."}


# ---------------- texto falado ----------------
def _limpo(t):
    t = re.sub(r"\bPOV:?", "Ponto de vista:", str(t or ""))
    t = t.replace("nº", "número").replace("Nº", "Número").replace("&", " e ")
    t = re.sub(r"[#*_`\[\]<>]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def falas(roteiro):
    """O que o narrador diz em cada parte: {'hook': str, 'beats': [{'antes': str|None, 'texto': str}], 'cta': str}."""
    beats = []
    for c in roteiro.get("cenas", []):
        texto, apoio, antes = _limpo(c.get("texto")), _limpo(c.get("apoio")), _limpo(c.get("antes"))
        if not texto:
            continue
        if antes:
            beats.append({"antes": f"Antes. {antes}.", "texto": f"Depois. {texto}." + (f" {apoio}" if apoio else "")})
            continue
        rot = _limpo(c.get("rotulo")).upper()
        lead = ORDINAIS.get(rot) or LEAD.get(rot) or ""
        beats.append({"antes": None, "texto": (lead + " " if lead else "") + texto + ("." if texto[-1] not in ".?!" else "") + (f" {apoio}" if apoio else "")})
    return {"hook": _limpo(roteiro.get("gancho")), "beats": beats, "cta": _limpo(roteiro.get("chamada"))}


# ---------------- Gemini TTS ----------------
def _erro_http(r):
    try:
        e = r.json().get("error", {})
        return f"HTTP {r.status_code}: {str(e.get('message', r.text))[:200]}"
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"


def _espera_429(r):
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text) or re.search(r"retry in (\d+(?:\.\d+)?)s", r.text)
    return min(70.0, float(m.group(1)) + 1.0) if m else 25.0


def modelos_tts(key):
    """Modelos de voz disponíveis para a chave, do mais indicado para o menos (versões finais antes das prévias, mais novos antes)."""
    forcado = os.getenv("TTS_MODELO", "").strip()
    if forcado:
        return [forcado]
    r = requests.get(f"{BASE}/models", params={"key": key, "pageSize": 200}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError("não consegui listar os modelos do Gemini: " + _erro_http(r))
    nomes = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "tts" in m["name"].lower() and "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if not nomes:
        raise RuntimeError("nenhum modelo de voz (TTS) disponível para esta chave do Gemini")

    def chave(n):
        versao = tuple(-float(x) for x in re.findall(r"\d+(?:\.\d+)?", n))
        return ("preview" in n, versao, "lite" in n, n)
    return sorted(nomes, key=chave)


def _pcm_para_wav(b64, mime, destino):
    pcm = base64.b64decode(b64)
    m = re.search(r"rate=(\d+)", mime or "")
    taxa = int(m.group(1)) if m else 24000
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)
    return taxa


def _estilo():
    return os.getenv("TTS_ESTILO", "").strip()


def _uma_chamada(key, modelo, voz, texto, destino, estilo=None):
    corpo = {"contents": [{"parts": [{"text": f"{estilo}: {texto}" if estilo else texto}]}],
             "generationConfig": {"responseModalities": ["AUDIO"],
                                  "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}}}
    for tentativa in range(4):
        try:
            r = requests.post(f"{BASE}/models/{modelo}:generateContent", params={"key": key}, json=corpo, timeout=(15, 90))
        except requests.exceptions.RequestException as e:
            if tentativa == 3:
                raise RuntimeError(f"falha de conexão com o Gemini ({type(e).__name__})")
            time.sleep(5 * (tentativa + 1))
            continue
        if r.status_code == 200:
            try:
                parte = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                return _pcm_para_wav(parte["data"], parte.get("mimeType", ""), destino)
            except (KeyError, IndexError, TypeError, ValueError):
                if tentativa >= 1:
                    raise RuntimeError("o Gemini respondeu sem áudio")
                time.sleep(3)
                continue
        if r.status_code == 429:
            espera = _espera_429(r)
            if tentativa == 3 or "limit: 0" in r.text:
                raise RuntimeError("limite de uso da voz do Gemini atingido: " + _erro_http(r))
            print(f"[voz] limite de pedidos; esperando {espera:.0f}s", flush=True)
            time.sleep(espera)
            continue
        if r.status_code in (500, 502, 503, 504) and tentativa < 3:
            time.sleep(6 * (tentativa + 1))
            continue
        raise RuntimeError(_erro_http(r))
    raise RuntimeError("não consegui gerar a voz")


def _ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-200:])


def _duracao(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / float(w.getframerate())


def _niveis(arquivo):
    """(volume médio, volume máximo) em dB, como o ffmpeg mede."""
    r = subprocess.run(["ffmpeg", "-i", str(arquivo), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m, x = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr), re.search(r"max_volume: (-?[\d.]+) dB", r.stderr)
    return (float(m.group(1)), float(x.group(1))) if m and x else (-91.0, -91.0)


def _forca_desser():
    try:
        return min(1.0, max(0.0, float(os.getenv("TTS_DESSER", "") or 0.6)))
    except ValueError:
        return 0.6


def _limpa(entrada, saida, grave=1.0, tempo=1.0):
    """Limpa o clipe de voz: filtra o que não é voz, REMOVE O CHIADO DOS "S" (de-esser), corta o silêncio das pontas (limiar relativo
    ao pico da fala), faz fade nas pontas e nivela o volume pelo valor medido (sem loudnorm).
    O de-esser existe porque, nas vozes sintéticas, as sibilantes ("s", "x", "ch") saem tão altas quanto as vogais e soam como chiado."""
    saida = Path(saida)
    p1, p1d, p2 = saida.with_suffix(".p1.wav"), saida.with_suffix(".p1d.wav"), saida.with_suffix(".p2.wav")
    base = ["highpass=f=80", "lowpass=f=10500"]
    if abs(grave - 1.0) > 0.005:
        base += [f"asetrate=24000*{grave:.4f}", "aresample=24000", f"atempo={1 / grave:.4f}"]
    if abs(tempo - 1.0) > 0.005:
        base.append(f"atempo={tempo:.4f}")
    _ffmpeg(["-i", str(entrada), "-af", ",".join(base), "-ar", "24000", "-ac", "1", str(p1)])
    # 1) corta o silêncio das pontas ANTES do de-esser (com o "s" ainda forte, para não confundir um "s" no começo ou no fim com silêncio)
    _, pico = _niveis(p1)
    th = max(-48.0, min(-30.0, pico - 30.0))
    corte = f"silenceremove=start_periods=1:start_threshold={th:.0f}dB:start_silence=0.05"
    p1t = saida.with_suffix(".p1t.wav")
    _ffmpeg(["-i", str(p1), "-af", ",".join([corte, "areverse", corte, "areverse"]), "-ar", "24000", "-ac", "1", str(p1t)])
    # 2) tira o chiado dos "s"
    f = _forca_desser()
    fonte = p1t
    if f > 0:
        try:
            ds = f"aresample=44100,deesser=i={f:.2f}:m={min(0.9, f + 0.1):.2f}:f=0.5,equalizer=f=7000:t=q:w=0.8:g={-5 * f:.1f},aresample=24000"
            _ffmpeg(["-i", str(p1t), "-af", ds, "-ar", "24000", "-ac", "1", str(p1d)])
            fonte = p1d
        except RuntimeError as e:   # este ffmpeg não tem o filtro: segue sem o de-esser
            print(f"[voz] de-esser indisponível ({str(e)[:80]}); seguindo sem ele", flush=True)
    # 3) fades nas pontas
    _ffmpeg(["-i", str(fonte), "-af", "afade=t=in:d=0.012,areverse,afade=t=in:d=0.06,areverse", "-ar", "24000", "-ac", "1", str(p2)])
    media, pico2 = _niveis(p2)
    ganho = max(-12.0, min(12.0, min(-19.0 - media, -1.5 - pico2))) if media > -80 else 0.0
    _ffmpeg(["-i", str(p2), "-af", f"volume={ganho:.2f}dB,alimiter=limit=0.9", "-ar", "24000", "-ac", "1", str(saida)])
    for p in (p1, p1t, p1d, p2):
        p.unlink(missing_ok=True)


def _cfg():
    try:
        grave = float(os.getenv("TTS_GRAVE", "") or 1.0)
    except ValueError:
        grave = 1.0
    return (os.getenv("TTS_VOZ", "").strip() or VOZ_PADRAO), min(1.0, max(0.85, grave))


def sintetizar_clipe(key, modelos, voz, texto, destino, grave=1.0, tempo=1.0, estilo=None):
    """Gera um clipe. Devolve (modelo que funcionou, duração em segundos).
    Se houver instrução de estilo e o áudio vier longo demais para o texto (sinal de que o modelo leu a instrução em voz alta),
    gera de novo sem a instrução."""
    bruto = Path(destino).with_suffix(".bruto.wav")
    ultimo = None
    for modelo in modelos[:3]:
        try:
            _uma_chamada(key, modelo, voz, texto, bruto, estilo)
            _limpa(bruto, destino, grave, tempo)
            bruto.unlink(missing_ok=True)
            dur = _duracao(destino)
            if estilo and dur > 0.115 * len(texto) + 1.5:
                print("[voz] o áudio veio longo demais (o modelo provavelmente leu a instrução de estilo); gerando de novo sem ela", flush=True)
                _uma_chamada(key, modelo, voz, texto, bruto, None)
                _limpa(bruto, destino, grave, tempo)
                bruto.unlink(missing_ok=True)
                dur = _duracao(destino)
            return modelo, dur
        except RuntimeError as e:
            ultimo = e
            if not re.search(r"HTTP (400|403|404)", str(e)):
                raise
            print(f"[voz] modelo {modelo} não serviu ({str(e)[:120]}); tentando o próximo", flush=True)
    raise ultimo or RuntimeError("nenhum modelo de voz funcionou")


def gerar_narracao(roteiro, pasta):
    """Clipes de voz do Reel. Devolve {'hook':clipe,'beats':[{'antes':clipe|None,'texto':clipe}],'cta':clipe,'voz':..,'modelo':..}
    com clipe = {'path': Path, 'dur': segundos}. Levanta RuntimeError se algo falhar."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY ausente")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    voz, grave = _cfg()
    t_fala = falas(roteiro)
    if not t_fala["hook"] or not t_fala["beats"]:
        raise RuntimeError("roteiro sem texto para narrar")
    modelos = modelos_tts(key)
    inicio, usado = time.time(), {"modelo": modelos[0]}
    n = [0]

    def clipe(texto):
        if time.time() - inicio > PRAZO_TOTAL:
            raise RuntimeError("tempo esgotado para gerar a voz")
        n[0] += 1
        p = pasta / f"v{n[0]:02d}.wav"
        m, d = sintetizar_clipe(key, modelos, voz, texto, p, grave, estilo=_estilo())
        usado["modelo"] = m
        modelos[:] = [m] + [x for x in modelos if x != m]
        print(f"[voz] clipe {n[0]} ({d:.1f}s) com {m}/{voz}", flush=True)
        return {"path": p, "dur": d}
    out = {"hook": clipe(t_fala["hook"]), "beats": []}
    for b in t_fala["beats"]:
        out["beats"].append({"antes": clipe(b["antes"]) if b["antes"] else None, "texto": clipe(b["texto"])})
    out["cta"] = clipe(t_fala["cta"]) if t_fala["cta"] else None
    # se a fala não cabe no teto do vídeo, acelera todos os clipes (no máximo 15%)
    todos = [out["hook"], out["cta"]] + [c for b in out["beats"] for c in (b["antes"], b["texto"])]
    todos = [c for c in todos if c]
    estimado = sum(c["dur"] for c in todos) + 0.6 * len(todos) + 1.0
    if estimado > TETO_FALA:
        fator = min(1.15, estimado / TETO_FALA)
        for c in todos:
            acel = c["path"].with_suffix(".rapido.wav")
            _ffmpeg(["-i", str(c["path"]), "-af", f"atempo={fator:.4f}", "-ar", "24000", "-ac", "1", str(acel)])
            c["path"], c["dur"] = acel, _duracao(acel)
    out.update(voz=voz, modelo=usado["modelo"])
    return out


# ---------------- teste de voz ----------------
def _telegram_audio(caminho, legenda):
    tk, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not tk or not chat:
        print("[voz] sem Telegram configurado; áudio salvo em", caminho)
        return
    with open(caminho, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{tk}/sendAudio", data={"chat_id": chat, "caption": legenda[:900]},
                          files={"audio": (Path(caminho).name, f)}, timeout=120)
    print("[voz] Telegram:", "enviado" if r.status_code == 200 else f"falhou (HTTP {r.status_code})")


def testar(voz, texto, grave, estilo=""):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("GEMINI_API_KEY ausente")
    pasta = Path("_teste_voz")
    pasta.mkdir(exist_ok=True)
    modelos = modelos_tts(key)
    print("[voz] modelos de voz disponíveis:", ", ".join(modelos[:6]), flush=True)
    wav = pasta / "teste.wav"
    modelo, dur = sintetizar_clipe(key, modelos, voz, _limpo(texto), wav, grave, estilo=estilo or None)
    m4a = pasta / f"voz_{voz}.m4a"
    _ffmpeg(["-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(m4a)])
    _telegram_audio(m4a, f"🎙 Teste de voz\nVoz: {voz}\nModelo: {modelo}\nDuração: {dur:.1f}s\nTom mais grave (TTS_GRAVE): {grave}\nEstilo: {estilo or '(nenhum)'}")
    print(f"[voz] ok: {dur:.1f}s com {modelo}/{voz}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--voz", default="")
    ap.add_argument("--texto", default="Seu currículo não precisa de três páginas. Precisa de clareza. Pare de listar tarefas e mostre o que mudou.")
    ap.add_argument("--grave", type=float, default=0)
    ap.add_argument("--estilo", default="")
    a = ap.parse_args()
    v, g = _cfg()
    if a.testar:
        testar(a.voz or v, a.texto, a.grave or g, a.estilo)"""Narração dos Reels com a voz do Gemini (TTS), em português do Brasil.

O que faz
- gerar_narracao(roteiro, pasta): cria um clipe de voz para o gancho, para cada cena (nas cenas "antes e depois", um para o antes e outro
  para o depois) e para a chamada final. Cada clipe é limpo (sem silêncio nas pontas) e nivelado no mesmo volume. A duração de cada
  clipe manda no ritmo do vídeo (reel_palco.py).
- Se qualquer clipe falhar, devolve erro e o Reel sai sem narração (só com música), como antes. Nunca derruba o Reel.
- python -m agent.narracao --testar: gera uma frase de teste e manda o áudio ao Telegram (workflow "Testar voz").

Configuração (variáveis do repositório, em Settings > Secrets and variables > Actions > Variables; todas opcionais)
  TTS_VOZ     nome da voz do Gemini (padrão: Orus). Outras vozes firmes/graves: Alnilam, Algenib, Charon.
  TTS_GRAVE   1.0 = voz como vem; 0.94 deixa um pouco mais grave (muda o tom sem mudar a velocidade).
  TTS_MODELO  força um modelo de voz específico; sem isso, o robô descobre o melhor modelo disponível para a sua chave.
  TTS_ESTILO  instrução de estilo curta (ex.: "Diga com firmeza"). Por padrão fica VAZIO de propósito: o modelo de voz costuma LER a
              instrução em voz alta antes de cada frase. O tom vem da voz escolhida (Orus é firme) e do TTS_GRAVE.
  NARRACAO    0 desliga a narração.
Os modelos de voz do Gemini ainda estão em prévia e mudam de nome: por isso o robô lista os modelos da sua conta em vez de fixar um nome.
"""
import argparse
import base64
import os
import re
import subprocess
import time
import wave
from pathlib import Path

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
VOZ_PADRAO = "Orus"
PRAZO_TOTAL = 420        # segundos para gerar todos os clipes de um Reel
TETO_FALA = 38.0         # segundos de vídeo; acima disso a voz é acelerada (até 15%)

LEAD = {"MITO": "Mito.", "VERDADE": "Verdade.", "O ERRO": "O erro.", "POR QUE ATRAPALHA": "Por que atrapalha?",
        "CORRIJA ASSIM": "Corrija assim.", "FAÇA ASSIM": "Faça assim.", "FAÇA ISSO": "Faça isso.", "POR QUÊ": "Por quê?",
        "HOJE": "Hoje.", "NA PRÁTICA": "Na prática.", "EVITE": "Evite.", "A VIRADA": "A virada.", "DEPOIS": "Depois.",
        "RESPOSTA CURTA": "Resposta curta.", "COMO RESPONDER": "Como responder?", "O QUE ELE QUER SABER": "O que ele quer saber?"}
ORDINAIS = {"1": "Primeiro.", "2": "Segundo.", "3": "Terceiro.", "4": "Quarto.", "5": "Quinto."}


# ---------------- texto falado ----------------
def _limpo(t):
    t = re.sub(r"\bPOV:?", "Ponto de vista:", str(t or ""))
    t = t.replace("nº", "número").replace("Nº", "Número").replace("&", " e ")
    t = re.sub(r"[#*_`\[\]<>]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def falas(roteiro):
    """O que o narrador diz em cada parte: {'hook': str, 'beats': [{'antes': str|None, 'texto': str}], 'cta': str}."""
    beats = []
    for c in roteiro.get("cenas", []):
        texto, apoio, antes = _limpo(c.get("texto")), _limpo(c.get("apoio")), _limpo(c.get("antes"))
        if not texto:
            continue
        if antes:
            beats.append({"antes": f"Antes. {antes}.", "texto": f"Depois. {texto}." + (f" {apoio}" if apoio else "")})
            continue
        rot = _limpo(c.get("rotulo")).upper()
        lead = ORDINAIS.get(rot) or LEAD.get(rot) or ""
        beats.append({"antes": None, "texto": (lead + " " if lead else "") + texto + ("." if texto[-1] not in ".?!" else "") + (f" {apoio}" if apoio else "")})
    return {"hook": _limpo(roteiro.get("gancho")), "beats": beats, "cta": _limpo(roteiro.get("chamada"))}


# ---------------- Gemini TTS ----------------
def _erro_http(r):
    try:
        e = r.json().get("error", {})
        return f"HTTP {r.status_code}: {str(e.get('message', r.text))[:200]}"
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"


def _espera_429(r):
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text) or re.search(r"retry in (\d+(?:\.\d+)?)s", r.text)
    return min(70.0, float(m.group(1)) + 1.0) if m else 25.0


def modelos_tts(key):
    """Modelos de voz disponíveis para a chave, do mais indicado para o menos (versões finais antes das prévias, mais novos antes)."""
    forcado = os.getenv("TTS_MODELO", "").strip()
    if forcado:
        return [forcado]
    r = requests.get(f"{BASE}/models", params={"key": key, "pageSize": 200}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError("não consegui listar os modelos do Gemini: " + _erro_http(r))
    nomes = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "tts" in m["name"].lower() and "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if not nomes:
        raise RuntimeError("nenhum modelo de voz (TTS) disponível para esta chave do Gemini")

    def chave(n):
        versao = tuple(-float(x) for x in re.findall(r"\d+(?:\.\d+)?", n))
        return ("preview" in n, versao, "lite" in n, n)
    return sorted(nomes, key=chave)


def _pcm_para_wav(b64, mime, destino):
    pcm = base64.b64decode(b64)
    m = re.search(r"rate=(\d+)", mime or "")
    taxa = int(m.group(1)) if m else 24000
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)
    return taxa


def _estilo():
    return os.getenv("TTS_ESTILO", "").strip()


def _uma_chamada(key, modelo, voz, texto, destino, estilo=None):
    corpo = {"contents": [{"parts": [{"text": f"{estilo}: {texto}" if estilo else texto}]}],
             "generationConfig": {"responseModalities": ["AUDIO"],
                                  "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}}}
    for tentativa in range(4):
        try:
            r = requests.post(f"{BASE}/models/{modelo}:generateContent", params={"key": key}, json=corpo, timeout=(15, 90))
        except requests.exceptions.RequestException as e:
            if tentativa == 3:
                raise RuntimeError(f"falha de conexão com o Gemini ({type(e).__name__})")
            time.sleep(5 * (tentativa + 1))
            continue
        if r.status_code == 200:
            try:
                parte = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                return _pcm_para_wav(parte["data"], parte.get("mimeType", ""), destino)
            except (KeyError, IndexError, TypeError, ValueError):
                if tentativa >= 1:
                    raise RuntimeError("o Gemini respondeu sem áudio")
                time.sleep(3)
                continue
        if r.status_code == 429:
            espera = _espera_429(r)
            if tentativa == 3 or "limit: 0" in r.text:
                raise RuntimeError("limite de uso da voz do Gemini atingido: " + _erro_http(r))
            print(f"[voz] limite de pedidos; esperando {espera:.0f}s", flush=True)
            time.sleep(espera)
            continue
        if r.status_code in (500, 502, 503, 504) and tentativa < 3:
            time.sleep(6 * (tentativa + 1))
            continue
        raise RuntimeError(_erro_http(r))
    raise RuntimeError("não consegui gerar a voz")


def _ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-200:])


def _duracao(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / float(w.getframerate())


def _niveis(arquivo):
    """(volume médio, volume máximo) em dB, como o ffmpeg mede."""
    r = subprocess.run(["ffmpeg", "-i", str(arquivo), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m, x = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr), re.search(r"max_volume: (-?[\d.]+) dB", r.stderr)
    return (float(m.group(1)), float(x.group(1))) if m and x else (-91.0, -91.0)


def _limpa(entrada, saida, grave=1.0, tempo=1.0):
    """Limpa o clipe de voz para não deixar chiado: filtra o que não é voz, corta o silêncio e o ruído das pontas (com limiar
    relativo ao pico da própria fala), abafa o ruído entre as palavras, faz fade nas pontas e nivela o volume pelo valor medido
    (sem loudnorm, que pode puxar o chiado para cima)."""
    saida = Path(saida)
    p1, p2 = saida.with_suffix(".p1.wav"), saida.with_suffix(".p2.wav")
    base = ["highpass=f=80", "lowpass=f=9500"]
    if abs(grave - 1.0) > 0.005:
        base += [f"asetrate=24000*{grave:.4f}", "aresample=24000", f"atempo={1 / grave:.4f}"]
    if abs(tempo - 1.0) > 0.005:
        base.append(f"atempo={tempo:.4f}")
    _ffmpeg(["-i", str(entrada), "-af", ",".join(base), "-ar", "24000", "-ac", "1", str(p1)])
    _, pico = _niveis(p1)
    th = max(-48.0, min(-30.0, pico - 30.0))
    corte = f"silenceremove=start_periods=1:start_threshold={th:.0f}dB:start_silence=0.05"
    gate = 10 ** ((th - 6) / 20)
    _ffmpeg(["-i", str(p1), "-af", ",".join([corte, "areverse", corte, "areverse",
                                              f"agate=threshold={gate:.4f}:ratio=4:attack=4:release=70:range=0.08",
                                              "afade=t=in:d=0.012", "areverse", "afade=t=in:d=0.06", "areverse"]),
             "-ar", "24000", "-ac", "1", str(p2)])
    media, pico2 = _niveis(p2)
    ganho = max(-12.0, min(12.0, min(-19.0 - media, -1.5 - pico2))) if media > -80 else 0.0
    _ffmpeg(["-i", str(p2), "-af", f"volume={ganho:.2f}dB,alimiter=limit=0.9", "-ar", "24000", "-ac", "1", str(saida)])
    p1.unlink(missing_ok=True)
    p2.unlink(missing_ok=True)


def _cfg():
    try:
        grave = float(os.getenv("TTS_GRAVE", "") or 1.0)
    except ValueError:
        grave = 1.0
    return (os.getenv("TTS_VOZ", "").strip() or VOZ_PADRAO), min(1.0, max(0.85, grave))


def sintetizar_clipe(key, modelos, voz, texto, destino, grave=1.0, tempo=1.0, estilo=None):
    """Gera um clipe. Devolve (modelo que funcionou, duração em segundos).
    Se houver instrução de estilo e o áudio vier longo demais para o texto (sinal de que o modelo leu a instrução em voz alta),
    gera de novo sem a instrução."""
    bruto = Path(destino).with_suffix(".bruto.wav")
    ultimo = None
    for modelo in modelos[:3]:
        try:
            _uma_chamada(key, modelo, voz, texto, bruto, estilo)
            _limpa(bruto, destino, grave, tempo)
            bruto.unlink(missing_ok=True)
            dur = _duracao(destino)
            if estilo and dur > 0.115 * len(texto) + 1.5:
                print("[voz] o áudio veio longo demais (o modelo provavelmente leu a instrução de estilo); gerando de novo sem ela", flush=True)
                _uma_chamada(key, modelo, voz, texto, bruto, None)
                _limpa(bruto, destino, grave, tempo)
                bruto.unlink(missing_ok=True)
                dur = _duracao(destino)
            return modelo, dur
        except RuntimeError as e:
            ultimo = e
            if not re.search(r"HTTP (400|403|404)", str(e)):
                raise
            print(f"[voz] modelo {modelo} não serviu ({str(e)[:120]}); tentando o próximo", flush=True)
    raise ultimo or RuntimeError("nenhum modelo de voz funcionou")


def gerar_narracao(roteiro, pasta):
    """Clipes de voz do Reel. Devolve {'hook':clipe,'beats':[{'antes':clipe|None,'texto':clipe}],'cta':clipe,'voz':..,'modelo':..}
    com clipe = {'path': Path, 'dur': segundos}. Levanta RuntimeError se algo falhar."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY ausente")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    voz, grave = _cfg()
    t_fala = falas(roteiro)
    if not t_fala["hook"] or not t_fala["beats"]:
        raise RuntimeError("roteiro sem texto para narrar")
    modelos = modelos_tts(key)
    inicio, usado = time.time(), {"modelo": modelos[0]}
    n = [0]

    def clipe(texto):
        if time.time() - inicio > PRAZO_TOTAL:
            raise RuntimeError("tempo esgotado para gerar a voz")
        n[0] += 1
        p = pasta / f"v{n[0]:02d}.wav"
        m, d = sintetizar_clipe(key, modelos, voz, texto, p, grave, estilo=_estilo())
        usado["modelo"] = m
        modelos[:] = [m] + [x for x in modelos if x != m]
        print(f"[voz] clipe {n[0]} ({d:.1f}s) com {m}/{voz}", flush=True)
        return {"path": p, "dur": d}
    out = {"hook": clipe(t_fala["hook"]), "beats": []}
    for b in t_fala["beats"]:
        out["beats"].append({"antes": clipe(b["antes"]) if b["antes"] else None, "texto": clipe(b["texto"])})
    out["cta"] = clipe(t_fala["cta"]) if t_fala["cta"] else None
    # se a fala não cabe no teto do vídeo, acelera todos os clipes (no máximo 15%)
    todos = [out["hook"], out["cta"]] + [c for b in out["beats"] for c in (b["antes"], b["texto"])]
    todos = [c for c in todos if c]
    estimado = sum(c["dur"] for c in todos) + 0.6 * len(todos) + 1.0
    if estimado > TETO_FALA:
        fator = min(1.15, estimado / TETO_FALA)
        for c in todos:
            acel = c["path"].with_suffix(".rapido.wav")
            _ffmpeg(["-i", str(c["path"]), "-af", f"atempo={fator:.4f}", "-ar", "24000", "-ac", "1", str(acel)])
            c["path"], c["dur"] = acel, _duracao(acel)
    out.update(voz=voz, modelo=usado["modelo"])
    return out


# ---------------- teste de voz ----------------
def _telegram_audio(caminho, legenda):
    tk, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not tk or not chat:
        print("[voz] sem Telegram configurado; áudio salvo em", caminho)
        return
    with open(caminho, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{tk}/sendAudio", data={"chat_id": chat, "caption": legenda[:900]},
                          files={"audio": (Path(caminho).name, f)}, timeout=120)
    print("[voz] Telegram:", "enviado" if r.status_code == 200 else f"falhou (HTTP {r.status_code})")


def testar(voz, texto, grave, estilo=""):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("GEMINI_API_KEY ausente")
    pasta = Path("_teste_voz")
    pasta.mkdir(exist_ok=True)
    modelos = modelos_tts(key)
    print("[voz] modelos de voz disponíveis:", ", ".join(modelos[:6]), flush=True)
    wav = pasta / "teste.wav"
    modelo, dur = sintetizar_clipe(key, modelos, voz, _limpo(texto), wav, grave, estilo=estilo or None)
    m4a = pasta / f"voz_{voz}.m4a"
    _ffmpeg(["-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(m4a)])
    _telegram_audio(m4a, f"🎙 Teste de voz\nVoz: {voz}\nModelo: {modelo}\nDuração: {dur:.1f}s\nTom mais grave (TTS_GRAVE): {grave}\nEstilo: {estilo or '(nenhum)'}")
    print(f"[voz] ok: {dur:.1f}s com {modelo}/{voz}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--voz", default="")
    ap.add_argument("--texto", default="Seu currículo não precisa de três páginas. Precisa de clareza. Pare de listar tarefas e mostre o que mudou.")
    ap.add_argument("--grave", type=float, default=0)
    ap.add_argument("--estilo", default="")
    a = ap.parse_args()
    v, g = _cfg()
    if a.testar:
        testar(a.voz or v, a.texto, a.grave or g, a.estilo)
