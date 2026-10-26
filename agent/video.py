"""Junta os quadros do story em vídeo MP4 com trilha de áudio (ffmpeg)."""
import hashlib
import subprocess
from pathlib import Path

from .config import MUSIC_DIR, STORY_SECONDS

EXTS = {".mp3", ".m4a", ".wav", ".aac"}


def tracks():
    return sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in EXTS) if MUSIC_DIR.exists() else []


def _duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


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
