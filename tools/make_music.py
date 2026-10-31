"""Gera trilhas LO-FI originais (sem direitos autorais) para os stories e reels.

Uso:  python tools/make_music.py [--out PASTA] [--only lofi_chuva]
Cria os .mp3 em assets/music (precisa de numpy e ffmpeg).

Cada faixa tem instrumentos e estilo próprios (tudo sintetizado por código, sem samples de terceiros):
  lofi_chuva    piano acústico macio + pad de cordas + chuva, sem bateria
  lofi_cafe     bossa nova: violão de nylon, contrabaixo, vassourinha e baqueta no aro
  lofi_noite    chillwave: pads de sintetizador, arpejo com eco, bumbo em 4/4 que "respira"
  lofi_estudo   boom-bap: bateria suja, sub grave, kalimba e estabs de piano elétrico
"""
import argparse
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "assets" / "music"


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def fft_filter(x, kind, fc, order=2):
    """Passa-baixa ('lp') ou passa-alta ('hp') suave, aplicado no espectro."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    lp = 1 / np.sqrt(1 + (f / fc) ** (2 * order))
    g = lp if kind == "lp" else np.sqrt(np.maximum(0.0, 1 - lp ** 2))
    return np.fft.irfft(X * g, len(x))


def nrm(x):
    return x / max(1e-9, np.abs(x).max())


def put(buf, seg, start):
    s = max(0, int(start * SR))
    if s >= len(buf):
        return
    e = min(len(buf), s + len(seg))
    buf[s:e] += seg[: e - s]


def tvec(dur):
    return np.arange(int(SR * dur)) / SR


# =============== instrumentos ===============
def piano(freq, dur, vel=1.0):
    """Piano acústico macio: parciais com leve inarmonicidade e martelo suave."""
    t = tvec(dur)
    s = np.zeros_like(t)
    for k in range(1, 10):
        f = freq * k * np.sqrt(1 + 0.0004 * k * k)
        if f > 6500:
            break
        s += (1 / k ** 1.15) * np.sin(2 * np.pi * f * t + k) * np.exp(-(0.9 + 0.5 * k) * t)
    env = (1 - np.exp(-t * 600)) * np.clip((dur - t) / 0.3, 0, 1)
    n_h = min(len(t), int(SR * 0.03))
    hammer = np.zeros_like(t)
    hammer[:n_h] = fft_filter(np.random.default_rng(int(freq * 7)).standard_normal(n_h), "lp", 2500, 1) \
        * np.exp(-np.arange(n_h) / SR * 180) * 0.12
    return vel * (s * env + hammer)


def nylon(freq, dur, vel=1.0):
    """Violão de nylon: parciais que decaem rápido, som seco e redondo."""
    t = tvec(dur)
    s = np.zeros_like(t)
    for k in range(1, 11):
        f = freq * k
        if f > 5500:
            break
        s += (np.exp(-0.3 * k) / k ** 0.7) * np.sin(2 * np.pi * f * t) * np.exp(-(2.0 + 0.9 * k) * t)
    env = (1 - np.exp(-t * 900)) * np.clip((dur - t) / 0.06, 0, 1)
    n_p = min(len(t), int(SR * 0.012))
    pick = np.zeros_like(t)
    pick[:n_p] = np.random.default_rng(int(freq * 3)).standard_normal(n_p) * np.exp(-np.arange(n_p) / SR * 400) * 0.05
    return vel * (s * env + pick)


def rhodes(freq, dur, vel=1.0, bright=1.0):
    """Piano elétrico (FM) com 'tine' curto."""
    t = tvec(dur)
    idx = bright * 1.8 * np.exp(-4.5 * t) + 0.25

    def voice(f):
        return np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t))

    body = (voice(freq) + 0.6 * voice(freq * 1.003)) / 1.6
    tine = 0.12 * np.sin(2 * np.pi * freq * 7 * t) * np.exp(-16 * t)
    env = (1 - np.exp(-t * 350)) * np.exp(-1.4 * t) * np.clip((dur - t) / 0.12, 0, 1)
    return vel * (body + tine) * env


def pad_saw(freq, dur, vel=1.0, detune=0.006, harm=8, attack=0.8, release=1.0):
    """Pad: duas ondas 'serra' desafinadas (limitadas em harmônicos, sem chiado digital)."""
    t = tvec(dur)
    s = np.zeros_like(t)
    for d in (-detune, detune):
        f0 = freq * (1 + d)
        for k in range(1, harm + 1):
            if f0 * k > 5000:
                break
            s += np.sin(2 * np.pi * f0 * k * t + k * 0.7) / k
    env = np.clip(t / attack, 0, 1) * np.clip((dur - t) / release, 0, 1)
    return vel * 0.5 * s * env


def pluck_syn(freq, dur, vel=1.0):
    """Pluck de sintetizador para arpejos."""
    t = tvec(dur)
    s = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-8 * t) \
        + 0.25 * np.sin(2 * np.pi * 3 * freq * t) * np.exp(-12 * t)
    env = (1 - np.exp(-t * 800)) * np.exp(-4 * t) * np.clip((dur - t) / 0.05, 0, 1)
    return vel * s * env


def bell(freq, dur, vel=1.0):
    """Kalimba: fundamental que dura + parciais metálicas que somem rápido."""
    t = tvec(dur)
    s = np.sin(2 * np.pi * freq * t) * np.exp(-3.0 * t) + 0.30 * np.sin(2 * np.pi * freq * 5.4 * t) * np.exp(-16 * t) \
        + 0.10 * np.sin(2 * np.pi * freq * 11.3 * t) * np.exp(-30 * t)
    env = (1 - np.exp(-t * 1500)) * np.clip((dur - t) / 0.05, 0, 1)
    return vel * s * env


def bass(freq, dur, vel=1.0):
    t = tvec(dur)
    s = np.sin(2 * np.pi * freq * t) + 0.28 * np.sin(2 * np.pi * 2 * freq * t)
    env = (1 - np.exp(-t * 120)) * np.exp(-1.8 * t) * np.clip((dur - t) / 0.08, 0, 1)
    return vel * s * env


def sub808(freq, dur, vel=1.0):
    """Sub grave com queda de afinação no início."""
    t = tvec(dur)
    f = freq * (1 + 1.2 * np.exp(-t * 25))
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) + 0.15 * np.sin(2 * ph)
    return vel * s * (1 - np.exp(-t * 300)) * np.exp(-1.3 * t) * np.clip((dur - t) / 0.05, 0, 1)


def kick(vel=1.0):
    t = tvec(0.4)
    f = 42 + 95 * np.exp(-t * 32)
    return vel * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) * (1 - np.exp(-t * 2000))


def kick_punch(rng, vel=1.0):
    t = tvec(0.35)
    f = 48 + 120 * np.exp(-t * 42)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 8)
    click = fft_filter(rng.standard_normal(len(t)), "lp", 3000, 1) * np.exp(-t * 400) * 0.25
    return vel * (body + click)


def snare(rng, vel=1.0, crisp=1.0):
    t = tvec(0.28)
    noise = fft_filter(rng.standard_normal(len(t)), "hp", 1400, 2)
    body = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30)
    return vel * (0.55 * crisp * noise * np.exp(-t * 20) + 0.45 * body)


def rim(rng, vel=1.0):
    """Baqueta no aro (bossa)."""
    t = tvec(0.05)
    tone = 0.6 * np.sin(2 * np.pi * 1700 * t) * np.exp(-t * 160) + 0.5 * np.sin(2 * np.pi * 900 * t) * np.exp(-t * 120)
    noise = 0.4 * fft_filter(rng.standard_normal(len(t)), "hp", 2500, 2) * np.exp(-t * 120)
    return vel * (tone + noise)


def shaker(rng, vel=1.0):
    t = tvec(0.07)
    return vel * fft_filter(rng.standard_normal(len(t)), "hp", 5000, 2) * np.clip(t / 0.008, 0, 1) * np.exp(-t * 50)


def hat(rng, vel=1.0, open_=False):
    t = tvec(0.22 if open_ else 0.09)
    return vel * fft_filter(rng.standard_normal(len(t)), "hp", 6500, 2) * np.exp(-t * (16 if open_ else 70))


def clap(rng, vel=1.0):
    t = tvec(0.22)
    noise = fft_filter(fft_filter(rng.standard_normal(len(t)), "hp", 900, 2), "lp", 6500, 2)
    env = sum(np.where(t >= o, np.exp(-(t - o) * 90), 0.0) for o in (0, 0.012, 0.024)) * 0.4 + np.exp(-t * 18) * 0.4
    return vel * noise * env


# =============== efeitos e mistura ===============
def reverb(x, rng, seconds=1.3):
    m = int(SR * seconds)
    t = np.arange(m) / SR
    ir = fft_filter(rng.standard_normal(m) * np.exp(-t * (6.5 / seconds)), "lp", 3500, 2)
    ir /= np.sqrt(np.sum(ir ** 2))
    size = 1 << int(np.ceil(np.log2(len(x) + m)))
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]


def stereo_wet(x, rng, seconds, wet, haas_ms=11):
    """Reverb diferente em cada lado + pequeno atraso no direito = largura estéreo."""
    d = int(haas_ms / 1000 * SR)
    dry_r = np.roll(x, d) * 0.95
    return (x * (1 - wet) + reverb(x, rng, seconds) * wet,
            dry_r * (1 - wet) + reverb(x, rng, seconds) * wet)


def ping_pong(x, beat):
    """Eco que vai e volta entre os lados (colcheia pontuada)."""
    d = int(0.75 * beat * SR)

    def sh(k):
        return np.concatenate([np.zeros(d * k), x[: len(x) - d * k]])

    return x + 0.30 * sh(2), 0.55 * sh(1) + 0.16 * sh(3) + 0.6 * x


def duck_curve(n, times, depth=0.55, rate=7.0):
    """Efeito 'respirar': o volume abaixa a cada bumbo e volta devagar."""
    d = np.ones(n)
    L = int(0.4 * SR)
    shape = 1 - depth * np.exp(-(np.arange(L) / SR) * rate)
    for tk in times:
        s = int(tk * SR)
        if s < n:
            e = min(n, s + L)
            d[s:e] = np.minimum(d[s:e], shape[: e - s])
    return d


def crush(x, factor=4, mix=0.4):
    """Redução de qualidade (granulado de sampler antigo)."""
    held = np.repeat(x[::factor], factor)[: len(x)]
    return x * (1 - mix) + held * mix


def wobble_stereo(left, right, rng, depth=1.0):
    """Oscilação de fita, igual nos dois lados."""
    t = np.arange(len(left)) / SR
    warp = (t + depth * (0.0007 * np.sin(2 * np.pi * 0.35 * t + rng.uniform(0, 6.28))
                         + 0.0003 * np.sin(2 * np.pi * 1.7 * t))) * SR
    idx = np.arange(len(left))
    return np.interp(warp, idx, left), np.interp(warp, idx, right)


def vinyl(n, rng, level=1.0):
    x = np.zeros(n)
    k = int(n / SR * 9)
    pos = rng.integers(0, n - 8, k)
    x[pos] = rng.uniform(-1, 1, k) * rng.uniform(0.1, 1, k) ** 3
    x = nrm(fft_filter(x, "hp", 1200, 1))
    hiss = nrm(fft_filter(rng.standard_normal(n), "hp", 3500, 1))
    return level * (0.035 * x + 0.012 * hiss)


def chuva(n, rng):
    """Chuva: ruído em faixa média/aguda com intensidade que varia + pingos."""
    base = fft_filter(fft_filter(rng.standard_normal(n), "hp", 900, 2), "lp", 9000, 2)
    t = np.arange(n) / SR
    base = nrm(base) * (0.8 + 0.2 * np.sin(2 * np.pi * 0.07 * t + rng.uniform(0, 6.28)))
    drops = np.zeros(n)
    k = int(n / SR * 55)
    drops[rng.integers(0, n - 8, k)] = rng.uniform(0.2, 1.0, k)
    drops = nrm(fft_filter(fft_filter(drops, "hp", 2500, 2), "lp", 7000, 2))
    return base * 0.8 + drops * 0.5


def finalizar(left, right, rng, fc=7000, vinil=1.0, fita=1.0, chuva_nivel=0.0, drive=1.4):
    n = len(left)
    left, right = wobble_stereo(left, right, rng, fita)
    left = left + vinyl(n, rng, vinil)
    right = right + vinyl(n, rng, vinil)
    if chuva_nivel:
        left = left + chuva(n, rng) * chuva_nivel
        right = right + chuva(n, rng) * chuva_nivel
    out = []
    for ch in (left, right):
        ch = fft_filter(ch, "lp", fc, 3)
        ch = fft_filter(ch, "hp", 35, 2)
        out.append(np.tanh(drive * ch))
    st = np.stack(out, axis=1)
    st *= 0.85 / max(1e-9, np.abs(st).max())
    # volume parecido entre todas as faixas (média em -15,5 dB), sem passar de -0,2 dB de pico
    rms_db = 20 * np.log10(max(1e-9, np.sqrt((st ** 2).mean())))
    st *= min(10 ** ((-15.5 - rms_db) / 20), 0.98 / max(1e-9, np.abs(st).max()))
    fi, fo = int(SR * 0.04), int(SR * 1.5)
    st[:fi] *= np.linspace(0, 1, fi)[:, None]
    st[-fo:] *= np.linspace(1, 0, fo)[:, None]
    return st


def tamanho(bars, bar):
    return int(SR * (bars * bar + 2.5))  # + cauda de 2,5 s


def ciclos(ciclo_s, minimo=48):
    return max(1, int(np.ceil(minimo / ciclo_s)))


# =============== as quatro faixas ===============
def compor_chuva(rng, bpm, chords):
    """Piano acústico em arpejo lento, pad de cordas e chuva. Sem bateria."""
    beat = 60.0 / bpm
    bar = 4 * beat
    bars = len(chords) * 2 * ciclos(len(chords) * 2 * bar)
    n = tamanho(bars, bar)
    pn, mel, pd = (np.zeros(n) for _ in range(3))
    arp_a, arp_b = [0, 1, 2, 3, 2, 1, 2, 1], [0, 2, 1, 3, 1, 2, 3, 2]
    for b in range(bars):
        t0 = b * bar
        bass_note, voicing = chords[(b // 2) % len(chords)]
        put(pn, piano(midi(bass_note), 4 * beat + 1.0, 0.9), t0 + rng.normal(0, 0.01))
        for j, i in enumerate(arp_a if b % 2 == 0 else arp_b):
            vel = 0.55 * (1.2 if j % 4 == 0 else 0.85) * rng.uniform(0.8, 1.0)
            put(pn, piano(midi(voicing[i]), 2.4 * beat + 0.8, vel), t0 + j * beat / 2 + rng.normal(0, 0.012))
        if rng.random() < 0.5:
            put(mel, piano(midi(int(rng.choice(voicing)) + 12), 3.0, 0.45),
                t0 + int(rng.integers(0, 4)) * beat + rng.normal(0, 0.02))
        if b % 2 == 0:
            for note in voicing:
                put(pd, pad_saw(midi(note), 2 * bar + 1.5, 0.25, detune=0.004, harm=3, attack=1.5, release=1.5), t0 - 0.3)
    pn, mel, pd = fft_filter(pn, "lp", 4500, 2), fft_filter(mel, "lp", 3800, 2), fft_filter(pd, "lp", 1700, 2)
    pl, pr = stereo_wet(nrm(pn) + 0.6 * nrm(mel), rng, 2.2, 0.32)
    dl, dr = stereo_wet(nrm(pd), rng, 3.0, 0.4, haas_ms=19)
    return 0.80 * pl + 0.40 * dl, 0.80 * pr + 0.40 * dr, dict(fc=6200, vinil=0.45, fita=1.0, chuva_nivel=0.16, drive=1.3)


def compor_cafe(rng, bpm, chords):
    """Bossa nova: violão de nylon, contrabaixo, baqueta no aro, vassourinha e bumbo suave."""
    beat = 60.0 / bpm
    bar = 4 * beat
    bars = len(chords) * ciclos(len(chords) * bar)
    n = tamanho(bars, bar)
    gt, gm, bs, dr, sh = (np.zeros(n) for _ in range(5))

    def st(s):
        return s * beat / 4  # semicolcheias

    comp = {0: 0.95, 3: 0.65, 6: 0.85, 10: 0.7, 12: 0.8}  # a "clave" da bossa
    shk = [0.9, 0.35, 0.55, 0.35]
    for b in range(bars):
        t0 = b * bar
        bass_note, voicing = chords[b % len(chords)]
        for s, hv in comp.items():
            if s != 0 and rng.random() < 0.12:
                continue
            for k, note in enumerate(voicing):
                put(gt, nylon(midi(note), (1.5 if s == 0 else 0.8) * beat, hv * rng.uniform(0.85, 1.0)),
                    t0 + st(s) + k * 0.009 + rng.normal(0, 0.004))
            put(dr, rim(rng, 0.45 * rng.uniform(0.8, 1.0)), t0 + st(s) + rng.normal(0, 0.003))
        if rng.random() < 0.45:
            put(gm, nylon(midi(int(rng.choice(voicing)) + 12), 1.2 * beat, 0.5),
                t0 + st(int(rng.choice([2, 5, 8, 9, 11, 13, 14]))) + rng.normal(0, 0.005))
        put(bs, bass(midi(bass_note), 1.6 * beat, 0.95), t0 + rng.normal(0, 0.004))
        put(bs, bass(midi(bass_note + 7), 1.2 * beat, 0.7), t0 + st(6))
        if rng.random() < 0.6:
            put(bs, bass(midi(bass_note), 1.0 * beat, 0.6), t0 + st(12))
        put(dr, kick(0.5), t0)
        put(dr, kick(0.38), t0 + st(8))
        for s in range(16):
            put(sh, shaker(rng, 0.5 * shk[s % 4] * rng.uniform(0.8, 1.0)), t0 + st(s) + rng.normal(0, 0.003))
    gl, gr = stereo_wet(nrm(fft_filter(gt, "lp", 6500, 2)) + 0.6 * nrm(fft_filter(gm, "lp", 5500, 2)), rng, 0.7, 0.14, haas_ms=6)
    b_, d_, s_ = nrm(fft_filter(bs, "lp", 1200, 2)), nrm(fft_filter(dr, "lp", 7000, 2)), nrm(sh)
    left = 0.65 * gl + 0.55 * b_ + 0.45 * d_ + 0.18 * s_
    right = 0.65 * gr + 0.55 * b_ + 0.45 * d_ + 0.30 * s_
    return left, right, dict(fc=8500, vinil=0.4, fita=0.6, drive=1.2)


def compor_noite(rng, bpm, chords):
    """Chillwave: pads que abrem e fecham, arpejo com eco, bumbo em 4/4 que faz o som 'respirar', palmas."""
    beat = 60.0 / bpm
    bar = 4 * beat
    bars = len(chords) * 2 * ciclos(len(chords) * 2 * bar)
    n = tamanho(bars, bar)
    pad, arp, bs, kk, cl, oh = (np.zeros(n) for _ in range(6))
    kicks = []
    pat = [0, 1, 2, 3, 2, 1, 3, 2]
    for b in range(bars):
        t0 = b * bar
        bass_note, voicing = chords[(b // 2) % len(chords)]
        if b % 2 == 0:
            for note in voicing:
                put(pad, pad_saw(midi(note), 2 * bar + 1.4, 0.22), t0 - 0.2)
        for j, i in enumerate(pat):
            if rng.random() < 0.15:
                continue
            put(arp, pluck_syn(midi(voicing[i] + 12), 1.2, 0.5 * rng.uniform(0.8, 1.0) * (1.0 if j % 2 == 0 else 0.7)),
                t0 + j * beat / 2 + rng.normal(0, 0.004))
        put(bs, bass(midi(bass_note), 3.3 * beat, 0.85), t0)
        if rng.random() < 0.6:
            put(bs, bass(midi(bass_note), 1.0 * beat, 0.6), t0 + 1.5 * beat)
        for q in range(4):
            put(kk, kick(0.75), t0 + q * beat)
            kicks.append(t0 + q * beat)
            put(oh, hat(rng, 0.4 * rng.uniform(0.8, 1.0), open_=True), t0 + q * beat + beat / 2)
        for q in (1, 3):
            put(cl, clap(rng, 0.6), t0 + q * beat + rng.normal(0, 0.004))
    duck = duck_curve(n, kicks, 0.55, 7.0)
    t = np.arange(n) / SR
    m = 0.5 + 0.5 * np.sin(2 * np.pi * 0.09 * t)  # o filtro do pad abre e fecha devagar
    pad = (fft_filter(pad, "lp", 650, 2) * (1 - m) + fft_filter(pad, "lp", 2600, 2) * m) * duck
    arp = fft_filter(arp, "lp", 5200, 2) * duck
    a1, a2 = ping_pong(nrm(arp), beat)
    arv = reverb(nrm(arp), rng, 1.6) * 0.25
    pl, pr = stereo_wet(nrm(pad), rng, 3.2, 0.38, haas_ms=21)
    cw = reverb(nrm(cl), rng, 1.4) * 0.5
    sub, k_, c_, o_ = nrm(fft_filter(bs, "lp", 500, 2)), nrm(kk), nrm(cl) + cw, nrm(oh)
    left = 0.55 * pl + 0.35 * (a1 + arv) + 0.55 * sub + 0.55 * k_ + 0.35 * c_ + 0.12 * o_
    right = 0.55 * pr + 0.35 * (a2 + arv) + 0.55 * sub + 0.55 * k_ + 0.35 * c_ + 0.18 * o_
    return left, right, dict(fc=9500, vinil=0.3, fita=1.6, drive=1.3)


def compor_estudo(rng, bpm, chords):
    """Boom-bap: bateria suja com swing, sub grave, motivo de kalimba repetido e estabs de piano elétrico."""
    beat = 60.0 / bpm
    bar = 4 * beat
    bars = len(chords) * 2 * ciclos(len(chords) * 2 * bar)
    n = tamanho(bars, bar)
    dr, sb, ks, kal = (np.zeros(n) for _ in range(4))
    sw = 0.30 * beat / 4

    def st(s):
        return s * beat / 4 + (sw if s % 2 else 0.0)  # semicolcheias com swing

    hook_a = [(0, 72), (3, 68), (6, 70), (10, 65), (12, 68)]          # escala pentatônica de Fá menor
    hook_b = [(0, 72), (2, 75), (6, 72), (8, 70), (11, 68), (14, 65)]
    hat_v = [0.8, 0.55, 0.7, 0.55]
    for b in range(bars):
        t0 = b * bar
        bass_note, voicing = chords[(b // 2) % len(chords)]
        for s, v in ((0, 1.0), (7, 0.7), (10, 0.8)):
            put(dr, kick_punch(rng, v * rng.uniform(0.92, 1.0)), t0 + st(s))
        if rng.random() < 0.3:
            put(dr, kick_punch(rng, 0.45), t0 + st(15))
        for s in (4, 12):
            put(dr, snare(rng, 0.95, crisp=1.3), t0 + st(s) + rng.normal(0, 0.003))
        if rng.random() < 0.35:
            put(dr, snare(rng, 0.3), t0 + st(15))
        for s in range(0, 16, 2):
            put(dr, hat(rng, hat_v[(s // 2) % 4] * rng.uniform(0.8, 1.0)), t0 + st(s))
            if rng.random() < 0.25:
                put(dr, hat(rng, 0.3), t0 + st(s + 1))
        put(sb, sub808(midi(bass_note), 3.3 * beat, 0.85), t0)
        if rng.random() < 0.6:
            put(sb, sub808(midi(bass_note), 1.2 * beat, 0.6), t0 + st(10))
        for s in (0, 7):
            for k, note in enumerate(voicing):
                put(ks, rhodes(midi(note), 1.1 * beat, 0.6 * rng.uniform(0.85, 1.0), bright=0.7), t0 + st(s) + k * 0.01)
        for s, note in (hook_a if b % 2 == 0 else hook_b):
            put(kal, bell(midi(note), 1.4, 0.55 * rng.uniform(0.85, 1.0)), t0 + st(s) + rng.normal(0, 0.004))
    dr = np.tanh(1.8 * crush(fft_filter(nrm(dr), "lp", 6000, 2), 4, 0.35))   # bateria granulada e saturada
    ks = fft_filter(crush(nrm(ks), 3, 0.25), "lp", 2200, 2)                    # estabs "empoeirados"
    kl, kr = stereo_wet(nrm(kal), rng, 0.8, 0.12, haas_ms=9)
    sub = nrm(fft_filter(sb, "lp", 400, 2))
    kv = nrm(ks)
    left = 0.55 * dr + 0.60 * sub + 0.40 * kv + 0.45 * kl
    right = 0.55 * dr + 0.60 * sub + 0.45 * kv + 0.45 * kr
    return left, right, dict(fc=5600, vinil=1.8, fita=1.4, drive=1.8)


FAIXAS = {
    # Dm9 - Bbmaj7 - Gm9 - A7: sombrio e contemplativo
    "lofi_chuva": dict(fn=compor_chuva, bpm=66, seed=11, chords=[
        (38, [53, 57, 60, 64]), (46, [53, 57, 62, 65]), (43, [58, 62, 65, 69]), (45, [55, 61, 64, 69])]),
    # Ebmaj7 - C7 - Fm7 - Bb7: bossa em Mi bemol
    "lofi_cafe": dict(fn=compor_cafe, bpm=96, seed=23, chords=[
        (39, [55, 58, 62, 67]), (36, [52, 58, 60, 64]), (41, [56, 60, 63, 65]), (46, [56, 62, 65, 70])]),
    # Em9 - Cmaj9 - Gmaj7 - D6/9: sonhador, em Mi menor
    "lofi_noite": dict(fn=compor_noite, bpm=88, seed=37, chords=[
        (40, [55, 59, 62, 66]), (36, [59, 62, 64, 67]), (43, [59, 62, 66, 67]), (38, [57, 62, 64, 66])]),
    # Fm9 - Dbmaj7 - Abmaj7 - Eb9: boom-bap em Fá menor
    "lofi_estudo": dict(fn=compor_estudo, bpm=84, seed=41, chords=[
        (41, [56, 60, 63, 67]), (37, [53, 56, 60, 65]), (44, [55, 60, 63, 67]), (39, [58, 61, 65, 67])]),
}


def salvar(nome, stereo, pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    wav = pasta / f"{nome}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "128k",
                    str(pasta / f"{nome}.mp3")], check=True)
    wav.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="pasta de saída (padrão: assets/music)")
    ap.add_argument("--only", choices=list(FAIXAS), help="gera só uma faixa")
    args = ap.parse_args()
    for nome, f in FAIXAS.items():
        if args.only and nome != args.only:
            continue
        rng = np.random.default_rng(f["seed"])
        left, right, fx = f["fn"](rng, f["bpm"], f["chords"])
        salvar(nome, finalizar(left, right, rng, **fx), Path(args.out))
        print(f"{nome}.mp3 ok")
    print("ok")


if __name__ == "__main__":
    main()
