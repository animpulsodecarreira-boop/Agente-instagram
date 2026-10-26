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

# (agenda atual) 3 posts por dia, de segunda a sexta (os horários ficam em .github/workflows/generate.yml):
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
STORY_SECONDS = 8          # duração do story em vídeo
STORIES_PER_POST = 1       # 1 story por execução
MUSIC_DIR = ASSETS / "music"   # coloque aqui faixas livres de direitos (.mp3/.m4a/.wav)

# Modo do story (o código sorteia com rotação):
#   acompanha = mesmo tema do post, com ângulo diferente
#   paralela  = conversa solta, mais leve, sem relação direta com o post
STORY_MODES = ["acompanha", "paralela"]

# Formatos de story. Cada um é uma animação diferente (ver agent/render_v2.py).
#   funnels:      etapas do funil em que o formato pode aparecer
#   modes:        modos em que o formato faz sentido
#   post_formats: no modo "acompanha", só combina com estes formatos de post (None = qualquer um)
#   instrucao:    o que o Gemini deve preencher
STORY_FORMATS = {
    "digitar": dict(
        nome="Frase que se escreve", funnels=["topo", "meio", "fundo"], modes=["acompanha", "paralela"], post_formats=None,
        instrucao=("title = UMA frase de impacto, até 90 caracteres, uma ideia só (sem lista). "
                   "highlight = trecho do FINAL da própria frase (1 a 4 palavras, copiado EXATAMENTE como aparece em title) que ganha destaque. "
                   "body = vazio ou uma linha curta de apoio (até 80 caracteres).")),
    "riscar": dict(
        nome="Riscar e reescrever", funnels=["topo", "meio"], modes=["acompanha", "paralela"],
        post_formats=["erro_correcao", "antes_depois", "comparativo", "mito_verdade"],
        instrucao=("title = rótulo curto do que está sendo reescrito (ex.: 'Título do LinkedIn', 'Frase do currículo'), até 40 caracteres. "
                   "antes = versão fraca, curta, até 70 caracteres. depois = versão melhor, curta, até 85 caracteres. Exemplo FICTÍCIO.")),
    "chat": dict(
        nome="Conversa de chat", funnels=["topo", "meio", "fundo"], modes=["acompanha", "paralela"],
        post_formats=["pergunta", "caso_hipotetico", "bastidor", "mini_aula", "tres_sinais"],
        instrucao=("title = contexto curto (ex.: 'Entrevista', 'Mensagem no LinkedIn'), até 40 caracteres. "
                   "messages = de 2 a 4 mensagens alternando quem ('outro' = recrutador(a) ou colega; 'voce' = a pessoa), "
                   "cada texto com até 90 caracteres, tom natural de conversa. Conversa FICTÍCIA.")),
    "checklist": dict(
        nome="Checklist que se marca sozinho", funnels=["topo", "meio"], modes=["acompanha", "paralela"],
        post_formats=["checklist", "tres_sinais", "passo_a_passo", "mini_aula"],
        instrucao=("title = chamada curta (até 60 caracteres). items = 3 ou 4 itens, até 50 caracteres cada. "
                   "body = convite curto e opcional (até 60 caracteres), sem repetir fórmulas proibidas.")),
    "nota": dict(
        nome="Nota do celular", funnels=["topo", "meio", "fundo"], modes=["acompanha", "paralela"], post_formats=None,
        instrucao=("title = título da nota (até 40 caracteres, ex.: 'Lembrete'). "
                   "items = de 2 a 4 linhas curtas, até 60 caracteres cada; a ÚLTIMA linha é a mais importante (vai ganhar destaque).")),
    "pergunta": dict(
        nome="Pergunta aberta", funnels=["topo", "meio", "fundo"], modes=["acompanha", "paralela"], post_formats=None,
        instrucao=("title = pergunta aberta que a pessoa responde por DM, até 90 caracteres. "
                   "body = vazio ou uma linha curta (até 80 caracteres) dizendo que você responde.")),
    "teaser": dict(
        nome="Teaser do post", funnels=["topo", "meio", "fundo"], modes=["acompanha"], post_formats=None,
        instrucao=("title = gancho curto tirado do post (até 80 caracteres, diferente da capa palavra por palavra). "
                   "body = convite curto para ver o novo post no feed (até 70 caracteres), diferente a cada dia.")),
}
STORY_MODE_TEXT = {
    "acompanha": "Mesmo assunto do post de hoje, mas com ÂNGULO diferente (não copie a capa nem os títulos dos slides).",
    "paralela": ("CONVERSA PARALELA: tema solto e leve do mundo do trabalho e da carreira em geral (não precisa ser LinkedIn), "
                 "sem relação direta com o post, sem tom de venda e sem mencionar o post."),
}

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
