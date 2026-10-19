"""Configuração do agente. Edite aqui sem mexer no resto do código."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
QUEUE = ROOT / "queue"
HISTORY_FILE = ROOT / "history.json"
STATE_FILE = ROOT / "state.json"  # guarda o offset do Telegram

# ---------- Marca ----------
BRAND_NAME = "AN Impulso de Carreira"
LINK_LABEL = "Link na bio."
OFFER = "Diagnóstico gratuito do LinkedIn (link na bio)"  # usado nos posts de FUNDO
COLORS = {
    "bg": "#0A0E1A", "blue": "#2F6FED", "deep": "#0B1E3D",
    "amber": "#E8A33D", "white": "#F5F6FA",
}

# ---------- Funil (inspirado no 4-4-4) ----------
FUNNEL = {
    "topo": "Atrai gente nova, sem pedir nada. CTA: comentar QUERO / salvar / compartilhar.",
    "meio": "Mostra bastidores, método e dia a dia da consultoria. CTA: chamar na DM.",
    "fundo": "Mostra o que a consultoria vende e a oferta. CTA: acessar o link na bio.",
}
# Missão de cada tipo de post (o que a pessoa precisa saber depois de ver)
MISSIONS = {
    "topo": "Que eu existo: dor/erro comum de LinkedIn que gera identificação.",
    "meio": "Quem eu sou e o que eu faço: como o diagnóstico funciona, antes/depois, bastidores.",
    "fundo": "O que eu vendo: a oferta, para quem é, o que a pessoa recebe.",
}

# Agenda semanal: dia da semana (0=segunda) -> etapa do funil.
# Dias ausentes = sem post. Horário de geração é definido no workflow (cron).
WEEK_PLAN = {0: "topo", 1: "topo", 2: "meio", 3: "topo", 4: "fundo"}

# ---------- IA ----------
# Nomes de modelo do Gemini mudam rápido; usamos aliases e permitimos trocar por variável de ambiente.
GEMINI_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-flash-latest,gemini-flash-lite-latest").split(",") if m.strip()]

# ---------- Instagram ----------
IG_API_VERSION = os.getenv("IG_API_VERSION", "v25.0")
MAX_SLIDES, MIN_SLIDES = 8, 5
MAX_HASHTAGS = 10
