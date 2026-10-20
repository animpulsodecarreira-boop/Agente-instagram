"""Gera trilhas ambientes originais (sem direitos autorais) para os stories.
Uso: python tools/make_music.py   -> cria assets/music/*.mp3 (precisa de numpy e ffmpeg)."""
import subprocess, wave
from pathlib import Path
import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "music"
OUT.mkdir(parents=True, exist_ok=True)

def midi(n): return 440.0 * 2 ** ((n - 69) / 12)

def pad(freq, dur, vol=0.12):
    t = np.arange(int(SR * dur)) / SR
    s = sum(np.sin(2*np.pi*freq*k*t) / k**1.6 for k in (1, 2, 3, 4))
    s *= 1 + 0.15*np.sin(2*np.pi*0.3*t)
    env = np.minimum(1, t/1.2) * np.minimum(1, (dur-t)/1.5)
    return vol * s * env

def pluck(freq, dur=1.4, vol=0.16):
    t = np.arange(int(SR * dur)) / SR
    s = np.sin(2*np.pi*freq*t) + 0.4*np.sin(2*np.pi*2*freq*t)
    return vol * s * np.exp(-3.2*t)

def track(name, chords, bpm, seconds=24, root_shift=0):
    n = int(SR * seconds); mix = np.zeros(n)
    beat = 60 / bpm; chord_len = beat * 8
    for ci in range(int(seconds / chord_len) + 1):
        notes = chords[ci % len(chords)]
        start = int(ci * chord_len * SR)
        for note in notes:
            seg = pad(midi(note + root_shift), chord_len + 1.0)
            end = min(n, start + len(seg)); mix[start:end] += seg[:end - start]
        arp = notes + [notes[1] + 12]
        for k in range(16):
            note = arp[k % len(arp)] + 12 + root_shift
            st = start + int(k * beat/2 * SR)
            if st >= n: break
            seg = pluck(midi(note)); end = min(n, st + len(seg)); mix[st:end] += seg[:end - st]
    mix /= max(1e-9, np.abs(mix).max()) / 0.85
    fade = int(SR * 1.0); mix[-fade:] *= np.linspace(1, 0, fade)
    wav = OUT / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", "aecho=0.8:0.6:380:0.3,stereotools=mlev=1",
                    "-b:a", "128k", str(OUT / f"{name}.mp3")], check=True)
    wav.unlink()

# Am-F-C-G, C-G-Am-F, Dm-Bb-F-C (acordes em notas MIDI)
track("ambiente_calmo", [[57,60,64],[53,57,60],[48,52,55],[55,59,62]], bpm=84)
track("ambiente_otimista", [[48,52,55],[55,59,62],[57,60,64],[53,57,60]], bpm=100)
track("ambiente_foco", [[50,53,57],[46,50,53],[53,57,60],[48,52,55]], bpm=92)
print("ok")
