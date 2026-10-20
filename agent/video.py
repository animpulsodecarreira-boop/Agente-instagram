"""Transforma a arte do story (PNG) em vídeo MP4 com trilha de áudio (ffmpeg)."""
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


def make_story_video(png: Path, out: Path, seed: str, seconds: int = STORY_SECONDS):
    """Cria story em vídeo (1080x1920, H.264 + AAC). Usa uma faixa de assets/music; sem faixas, áudio mudo."""
    ts = tracks()
    n = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-t", str(seconds), "-i", str(png)]
    if ts:
        track = ts[n % len(ts)]
        dur = _duration(track)
        start = (n // 7 % max(1, int(dur - seconds))) if dur > seconds + 1 else 0
        cmd += ["-ss", str(start), "-t", str(seconds), "-i", str(track)]
    else:
        cmd += ["-f", "lavfi", "-t", str(seconds), "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-vf", "scale=1080:1920,format=yuv420p,fade=t=in:st=0:d=0.4",
            "-af", f"afade=t=in:d=0.5,afade=t=out:st={seconds - 1}:d=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-r", "30",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-shortest", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out
