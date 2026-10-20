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

# 3 posts por dia, de segunda a sexta (os horários ficam em .github/workflows/generate.yml):
#   08:00 topo | 12:30 meio | 18:00 fundo   (horário de Brasília)
# Se rodar manualmente sem escolher a etapa, ela é definida pela hora atual (ver main.funnel_by_hour).

# ---------- IA ----------
# Nomes de modelo do Gemini mudam rápido; usamos aliases e permitimos trocar por variável de ambiente.
GEMINI_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-flash-latest,gemini-flash-lite-latest").split(",") if m.strip()]

# ---------- Instagram ----------
IG_API_VERSION = os.getenv("IG_API_VERSION", "v25.0")
MAX_SLIDES, MIN_SLIDES = 8, 5
MAX_HASHTAGS = 10

# ---------- Visual ----------
THEMES = ["escuro", "claro", "azul", "geometrico"]  # o agente alterna, evitando repetir o último

# ---------- Stories ----------
STORY_SECONDS = 8          # duração de cada story em vídeo
STORIES_PER_POST = 2       # 1 frase/pergunta + 1 teaser "novo post no feed"
MUSIC_DIR = ASSETS / "music"   # coloque aqui faixas livres de direitos (.mp3/.m4a/.wav)
