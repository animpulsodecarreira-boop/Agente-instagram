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

# ---------- Variedade de conteúdo (o código sorteia; o Gemini só executa) ----------
# Cada formato é uma "receita" diferente de post. O agente alterna, evitando repetir os últimos.
FORMATS = {
    "mito_verdade": dict(funnels=["topo"], nome="Mito vs. verdade",
                         plano="cover; 3 slides 'versus' ou 'content' desmentindo um mito de LinkedIn por slide; 1 slide 'quote' com a conclusão; cta"),
    "erro_correcao": dict(funnels=["topo"], nome="Erros e como corrigir",
                          plano="cover; 2 a 3 slides 'versus' (erro -> melhor versão); 1 slide 'list' com o resumo; cta"),
    "antes_depois": dict(funnels=["topo", "meio"], nome="Antes e depois de um trecho do perfil",
                         plano="cover; 1 slide 'versus' com um EXEMPLO FICTÍCIO de antes/depois; 2 slides 'content' explicando o que mudou; cta"),
    "tres_sinais": dict(funnels=["topo"], nome="Sinais de que algo está errado",
                        plano="cover; 3 a 4 slides 'content' (um sinal por slide, com exemplo curto); 1 slide 'check'; cta"),
    "pergunta": dict(funnels=["topo"], nome="Pergunta provocativa respondida",
                     plano="cover em forma de pergunta; 3 slides 'content' ou 'quote' respondendo; cta (sem slide de conexão)"),
    "mini_aula": dict(funnels=["topo", "meio"], nome="Mini-aula com analogia",
                      plano="cover; 1 slide 'quote' com a ideia central; 2 a 3 slides 'content' usando uma analogia do dia a dia; 1 slide 'list'; cta"),
    "comparativo": dict(funnels=["topo", "fundo"], nome="Perfil A vs. perfil B",
                        plano="cover; 2 slides 'versus' comparando dois perfis FICTÍCIOS ou dois jeitos de se apresentar; 1 slide 'content' com a lição; cta"),
    "checklist": dict(funnels=["topo"], nome="Checklist de autoavaliação",
                      plano="cover; 1 slide 'check'; 2 a 3 slides 'content' explicando os itens mais negligenciados; cta"),
    "passo_a_passo": dict(funnels=["meio"], nome="Passo a passo prático",
                          plano="cover; 1 slide 'list' com os passos; 3 slides 'content' detalhando os passos mais importantes; cta"),
    "bastidor": dict(funnels=["meio"], nome="Como funciona o trabalho (bastidores do método)",
                     plano="cover; 3 a 4 slides 'content' mostrando as etapas de uma consultoria de LinkedIn (SEM casos reais, SEM resultados prometidos); cta para DM"),
    "caso_hipotetico": dict(funnels=["meio", "fundo"], nome="Mini-caso hipotético",
                            plano="cover com 'Imagine...'; 3 slides 'content' contando um caso FICTÍCIO (deixe claro que é um exemplo); 1 slide 'quote' com a lição; cta"),
    "oferta": dict(funnels=["fundo"], nome="Apresentação da oferta",
                   plano="cover; 1 slide 'content' sobre para quem é; 1 slide 'list' com o que a pessoa recebe; 1 slide 'content' de como funciona; cta com link na bio"),
}

HOOKS = [
    "pergunta direta que gera identificação",
    "afirmação contraintuitiva que quebra uma crença comum",
    "número concreto + promessa moderada (sem garantir resultado)",
    "alerta curto no imperativo (ex.: 'Pare de...', 'Antes de...')",
    "observação do dia a dia de quem procura emprego",
    "comparação inesperada entre duas coisas",
    "curiosidade que deixa a pessoa querendo saber o motivo",
]

CTAS = {
    "topo": [
        "convidar a comentar a palavra-chave {kw}",
        "convidar a salvar para consultar antes de mexer no perfil",
        "convidar a mandar o post para alguém que está buscando recolocação",
        "fazer uma pergunta que a pessoa responde nos comentários (ex.: qual é o seu título hoje?)",
        "convidar a seguir o perfil para a próxima dica",
    ],
    "meio": [
        "convidar a mandar uma DM com a palavra {kw}",
        "convidar a responder o story do dia",
        "convidar a comentar a dúvida para virar tema de um próximo post",
    ],
    "fundo": [
        "apontar o link na bio para o diagnóstico",
        "convidar a comentar {kw} para receber o diagnóstico",
        "convidar a mandar DM com a palavra {kw}",
    ],
}
KEYWORDS = ["QUERO", "PERFIL", "TITULO", "CHECK", "AJUDA"]

# Fórmulas que ficaram repetitivas: o Gemini é instruído a não usá-las.
BANNED_PHRASES = [
    "e aqui está o ponto", "quantos você marcaria", "salva para conferir depois", "desliza e confere",
    "pequenos ajustes", "muda a percepção", "mudam a percepção", "mudar completamente",
    "salva este post e manda", "recrutador escaneia", "seu perfil pode estar correto",
]
