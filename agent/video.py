"""Junta os quadros do story (e os slides do Reel) em vídeo MP4 com trilha de áudio (ffmpeg)."""
import hashlib
import re
import subprocess
from pathlib import Path

from .config import MUSIC_DIR, STORY_SECONDS

EXTS = {".mp3", ".m4a", ".wav", ".aac"}


def tracks():
    return sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in EXTS) if MUSIC_DIR.exists() else []


def _duration(path):
    """Duração da faixa em segundos. Usa o ffprobe; se ele não existir (ffmpeg do plano B), lê a duração pelo ffmpeg."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1",
                            str(path)], capture_output=True, text=True)
        return float(r.stdout.strip())
    except (FileNotFoundError, ValueError):
        pass
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def make_story_video(clip, out: Path, seed: str, seconds: int = STORY_SECONDS):
    """Cria o story em vídeo (1080x1920, H.264 + AAC).

    clip: {'png': Path, 'frames': [(arquivo, segundos), ...]} (animado) ou só um Path (imagem parada).
    Usa uma faixa de assets/music; sem faixas, o áudio fica mudo.
    """
    out = Path(out)
    if isinstance(clip, (str, Path)):
        frames = [(Path(clip), float(seconds))]
    else:
        frames = [(Path(p), float(d)) for p, d in clip["frames"]]
    lst = out.with_suffix(".txt")
    lines = ["ffconcat version 1.0"]
    for p, d in frames:
        lines += [f"file '{p.resolve()}'", f"duration {d:.3f}"]
    lines.append(f"file '{frames[-1][0].resolve()}'")  # o concat exige repetir o último quadro
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ts = tracks()
    n = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if ts:
        track = ts[n % len(ts)]
        dur = _duration(track)
        start = (n // 7 % max(1, int(dur - seconds))) if dur > seconds + 1 else 0
        cmd += ["-ss", str(start), "-t", str(seconds), "-i", str(track)]
    else:
        cmd += ["-f", "lavfi", "-t", str(seconds), "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-map", "0:v", "-map", "1:a",
            "-vf", f"fps=30,scale=1080:1920,format=yuv420p,tpad=stop_mode=clone:stop_duration={seconds},fade=t=in:st=0:d=0.3",
            "-af", f"afade=t=in:d=0.5,afade=t=out:st={seconds - 1}:d=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-r", "30",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-t", str(seconds), "-shortest",
            "-movflags", "+faststart", str(out)]
    try:
        subprocess.run(cmd, check=True)
    finally:
        lst.unlink(missing_ok=True)
    return out


# ---------------- Reel: os slides do carrossel viram um vídeo 9:16 ----------------
REEL_W, REEL_H = 1080, 1920
REEL_SLIDE_Y = 150       # topo do slide no quadro; a parte de baixo fica livre para os botões e a legenda do Reels
REEL_FADE = 0.4          # duração da troca entre slides (deslize lateral)
REEL_BAR_Y = 48          # barra de progresso: fica na margem de cima, sem tocar no slide


def _cor_do_canto(png):
    """Cor do fundo do slide (pixel do canto), para as margens do Reel combinarem com ele."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", "crop=1:1:4:4,format=rgb24",
                        "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True)
    b = r.stdout
    return "0x%02X%02X%02X" % tuple(b[:3]) if len(b) >= 3 else "0x0A0E1A"


def reel_durations(n, first=3.2, middle=3.8, last=4.4):
    """Tempo de cada slide (capa um pouco mais curta, CTA mais longo para dar tempo de ler)."""
    if n == 1:
        return [first + last]
    return [first] + [middle] * (n - 2) + [last]


def make_reel_video(slides, out: Path, seed: str):
    """Cria o Reel (1080x1920, H.264 + AAC, 30 fps) a partir dos PNGs do carrossel, na ordem.

    Cada slide (1080x1350) fica no alto de um quadro 9:16, com margens da cor do próprio slide;
    a troca é um deslize lateral e uma barra âmbar de progresso corre na margem de cima.
    Usa uma faixa de assets/music; sem faixas, o áudio fica mudo.
    """
    out = Path(out)
    slides = [Path(p) for p in slides]
    if not slides:
        raise ValueError("Nenhum slide para montar o Reel")
    n = len(slides)
    durs = reel_durations(n)
    total = sum(durs) - (n - 1) * REEL_FADE

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p, d in zip(slides, durs):
        cmd += ["-loop", "1", "-framerate", "30", "-t", f"{d:.3f}", "-i", str(p)]
    cmd += ["-f", "lavfi", "-i", f"color=c=0xE8A33D:s={REEL_W}x10:r=30:d={total:.3f}"]  # barra de progresso
    ts = tracks()
    h = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    if ts:
        track = ts[h % len(ts)]
        dur = _duration(track)
        start = (h // 7 % max(1, int(dur - total))) if dur > total + 1 else 0
        cmd += ["-ss", str(start), "-t", f"{total:.3f}", "-i", str(track)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]

    parts = []
    for i, p in enumerate(slides):
        parts.append(f"[{i}:v]scale={REEL_W}:1350,setsar=1,pad={REEL_W}:{REEL_H}:0:{REEL_SLIDE_Y}:color={_cor_do_canto(p)},"
                     f"format=yuv420p,fps=30[v{i}]")
    last = "v0"
    acc = durs[0]
    for i in range(1, n):
        offset = acc - REEL_FADE
        parts.append(f"[{last}][v{i}]xfade=transition=slideleft:duration={REEL_FADE}:offset={offset:.3f}[x{i}]")
        last = f"x{i}"
        acc += durs[i] - REEL_FADE
    parts.append(f"[{last}][{n}:v]overlay=x='-w+w*t/{total:.3f}':y={REEL_BAR_Y}:shortest=1,format=yuv420p[v]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", f"{n + 1}:a",
            "-af", f"afade=t=in:d=0.5,afade=t=out:st={total - 1.5:.3f}:d=1.5",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high", "-r", "30",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-t", f"{total:.3f}", "-shortest",
            "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out


def make_reel_from_frames(frames, out: Path, seed: str):
    """Junta os quadros do Reel de texto [(arquivo, segundos)] em vídeo 1080x1920 (H.264 + AAC) com a trilha.

    Se o Reel for mais longo que a faixa, a trilha se repete (lo-fi emenda bem).
    """
    out = Path(out)
    frames = [(Path(p), float(d)) for p, d in frames]
    if not frames:
        raise ValueError("Sem quadros para o Reel")
    total = sum(d for _, d in frames)
    lst = out.with_suffix(".txt")
    lines = ["ffconcat version 1.0"]
    for p, d in frames:
        lines += [f"file '{p.resolve()}'", f"duration {d:.3f}"]
    lines.append(f"file '{frames[-1][0].resolve()}'")  # o concat exige repetir o último quadro
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ts = tracks()
    h = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if ts:
        track = ts[h % len(ts)]
        dur = _duration(track)
        if dur > total + 1:
            start = h // 7 % max(1, int(dur - total))
            cmd += ["-ss", str(start), "-t", f"{total:.3f}", "-i", str(track)]
        else:
            cmd += ["-stream_loop", "-1", "-t", f"{total:.3f}", "-i", str(track)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-map", "0:v", "-map", "1:a",
            # 24 fps (a Meta aceita de 23 a 60) e ajustes para imagem quase parada: montagem bem mais rápida
            "-vf", f"fps=24,scale={REEL_W}:{REEL_H},format=yuv420p,fade=t=in:st=0:d=0.3",
            "-af", f"afade=t=in:d=0.5,afade=t=out:st={total - 1.5:.3f}:d=1.5",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-crf", "21", "-profile:v", "high", "-r", "24",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-t", f"{total:.3f}", "-shortest",
            "-movflags", "+faststart", str(out)]
    try:
        subprocess.run(cmd, check=True)
    finally:
        lst.unlink(missing_ok=True)
    return out
