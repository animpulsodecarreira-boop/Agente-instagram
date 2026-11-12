"""Reel direto: o Reel nasce sozinho, sem carrossel antes. Funciona com MODELOS PRONTOS.

Como funciona
1. O robô escolhe (sem usar o Gemini): etapa do funil, pilar, ângulo menos usado, modelo (formato) e a chamada final.
2. O Gemini só PREENCHE AS LACUNAS do modelo: gancho (a partir de moldes), 2 ou 3 cenas curtas, legenda e hashtags.
   Cada modelo traz a estrutura, os moldes de gancho e um exemplo completo; a chamada final vem pronta do código.
3. Se o Gemini falhar ou a resposta não passar na validação, o robô usa um roteiro pronto do BANCO DE RESERVA (escrito à mão).
   Assim o Reel sai do mesmo jeito, mesmo quando o Google está fora do ar.

Para mudar o tom, os moldes, as chamadas ou os roteiros de reserva, é só editar as listas aqui embaixo.
"""
import hashlib
import json
import random
import re

from .config import BANNED_PHRASES, FUNNEL, KEYWORDS, MISSIONS, PILLARS
from .generate import _lru, hist_for, load_history, pick_angle, pick_pillar, pick_theme, pick_variant
from .reel_gancho import FORMATOS as MODELOS_BASE
from .reel_gancho import SYSTEM as SYSTEM_BASE
from .reel_gancho import _gemini_json, _nw, _txt, validar

# ---------------------------------------------------------------- modelos
NOVOS = {
    "pergunta_recrutador": ("Pergunta que o recrutador faz. O gancho traz uma pergunta típica de processo seletivo. Cenas (3): rotulo "
                            "\"O QUE ELE QUER SABER\", rotulo \"COMO RESPONDER\", rotulo \"EVITE\"."),
    "antes_de": ("Antes de... O gancho começa com \"Antes de\" + uma ação de quem busca emprego, e promete conferir 3 coisas. Cenas (3): "
                 "rotulo \"1\", \"2\" e \"3\", cada uma com uma checagem simples (texto) e o porquê (apoio)."),
    "resposta_rapida": ("Resposta rápida a uma dúvida comum. O gancho é a dúvida, em forma de pergunta. Cenas (3): rotulo \"RESPOSTA CURTA\", "
                        "rotulo \"POR QUÊ\", rotulo \"DICA\"."),
}
MODELOS = {**MODELOS_BASE, **NOVOS}

# etapas em que cada modelo faz sentido (topo aceita todos)
POR_ETAPA = {"topo": list(MODELOS), "meio": ["mito", "erro", "resposta_rapida", "pergunta_recrutador"],
             "fundo": ["pare", "erro", "antes_depois"]}

MOLDES = {
    "lista": ["3 sinais de que {problema}", "3 erros no {assunto} que afastam recrutadores", "3 coisas que ninguém conta sobre {assunto}"],
    "mito": ["{mito} é o maior mito de {assunto}", "Disseram que {mito}. Será?", "Isso sobre {assunto} é mito"],
    "pare": ["Pare de {hábito} no seu {assunto}", "Pare de {hábito} se você busca emprego"],
    "antes_depois": ["Seu {item} diz o que você faz?", "{item}: veja a diferença"],
    "erro": ["O erro nº 1 em {assunto}", "O erro que muita gente comete em {assunto}"],
    "pov": ["POV: você {situação} e {problema}", "POV: {situação de quem busca emprego}"],
    "pergunta_recrutador": ["Recrutador pergunta: {pergunta}", "A pergunta que todo recrutador faz: {pergunta}"],
    "antes_de": ["Antes de {ação}, faça isto", "Antes de {ação}, confira 3 coisas"],
    "resposta_rapida": ["{dúvida frequente}?", "Pode {ação}? Resposta rápida"],
}

EXEMPLOS = {   # um exemplo completo de cada modelo: serve de molde de tom e tamanho (o assunto muda sempre)
    "lista": {"gancho": "3 sinais de que seu LinkedIn está invisível", "destaque": "invisível", "cenas": [
        {"rotulo": "1", "texto": "Título só com o cargo", "apoio": "Quem lê não entende o valor que você entrega."},
        {"rotulo": "2", "texto": "Sobre sem palavras-chave", "apoio": "A busca não encontra perfis que não dizem o que fazem."},
        {"rotulo": "3", "texto": "Experiência sem conquistas", "apoio": "Conte o que mudou com o seu trabalho."}]},
    "mito": {"gancho": "Currículo grande impressiona mais? Mito", "destaque": "Mito", "cenas": [
        {"rotulo": "MITO", "texto": "Mais páginas mostram mais valor", "apoio": ""},
        {"rotulo": "VERDADE", "texto": "Clareza vale mais que tamanho", "apoio": "Quem lê procura rápido o que combina com a vaga."},
        {"rotulo": "NA PRÁTICA", "texto": "Priorize o que combina com a vaga", "apoio": ""}]},
    "pare": {"gancho": "Pare de usar só o cargo no título", "destaque": "cargo", "cenas": [
        {"rotulo": "FAÇA ASSIM", "texto": "Diga o que você entrega", "apoio": "Para quem você trabalha e que problema resolve."},
        {"rotulo": "POR QUÊ", "texto": "A busca lê o seu título", "apoio": "Palavras claras ajudam o perfil a ser encontrado."},
        {"rotulo": "HOJE", "texto": "Reescreva em cinco minutos", "apoio": ""}]},
    "antes_depois": {"gancho": "Seu título diz o que você faz?", "destaque": "título", "cenas": [
        {"rotulo": "ANTES / DEPOIS", "antes": "Analista de Marketing", "texto": "Ajudo pequenas empresas a atrair clientes", "apoio": ""},
        {"rotulo": "ANTES / DEPOIS", "antes": "Em busca de oportunidades", "texto": "Atendimento ao cliente com foco em vendas", "apoio": "Diga a área e o que você faz."}]},
    "erro": {"gancho": "O erro nº 1 no currículo", "destaque": "erro", "cenas": [
        {"rotulo": "O ERRO", "texto": "Listar tarefas em vez de conquistas", "apoio": ""},
        {"rotulo": "POR QUE ATRAPALHA", "texto": "Ninguém vê o que você mudou", "apoio": ""},
        {"rotulo": "CORRIJA ASSIM", "texto": "Mostre o resultado do seu trabalho", "apoio": "Sem inventar números: use fatos que você pode comprovar."}]},
    "pov": {"gancho": "POV: você quer mudar de área", "destaque": "mudar", "cenas": [
        {"rotulo": "A VIRADA", "texto": "Você já tem habilidades que servem", "apoio": ""},
        {"rotulo": "FAÇA ISSO", "texto": "Liste o que você sabe fazer", "apoio": "Pense nas tarefas, não só no cargo."},
        {"rotulo": "DEPOIS", "texto": "Seu perfil passa a contar essa ponte", "apoio": "Quem lê entende como sua experiência se conecta."}]},
    "pergunta_recrutador": {"gancho": "Recrutador pergunta: fale sobre você", "destaque": "você", "cenas": [
        {"rotulo": "O QUE ELE QUER SABER", "texto": "Quem é você para esta vaga", "apoio": "Não é a sua história de vida inteira."},
        {"rotulo": "COMO RESPONDER", "texto": "Presente, passado e foco", "apoio": "Quem você é hoje, o que já fez e o que busca."},
        {"rotulo": "EVITE", "texto": "Ler o currículo em voz alta", "apoio": ""}]},
    "antes_de": {"gancho": "Antes de uma entrevista, faça isto", "destaque": "entrevista", "cenas": [
        {"rotulo": "1", "texto": "Releia a descrição da vaga", "apoio": "Ela mostra o que a empresa procura."},
        {"rotulo": "2", "texto": "Prepare duas histórias reais", "apoio": "Situações em que você resolveu algo."},
        {"rotulo": "3", "texto": "Tenha uma pergunta para fazer", "apoio": "Mostra interesse de verdade."}]},
    "resposta_rapida": {"gancho": "Posso pedir tempo para pensar na proposta?", "destaque": "tempo", "cenas": [
        {"rotulo": "RESPOSTA CURTA", "texto": "Pode, e é normal", "apoio": "Avaliar com calma faz parte do processo."},
        {"rotulo": "POR QUÊ", "texto": "Decisão apressada custa caro", "apoio": "Compare rotina e crescimento, não só o valor."},
        {"rotulo": "DICA", "texto": "Combine um prazo e agradeça", "apoio": ""}]},
}

# chamadas finais prontas (o Gemini não escreve a chamada). {kw} = palavra-chave rotativa de config.KEYWORDS
CHAMADAS = {
    "topo": ["Salva para consultar depois", "Segue para mais dicas de carreira", "Comenta {kw} e eu te mando", "Manda para quem precisa ver"],
    "meio": ["Chama na DM com {kw}", "Quer ver como funciona? Chama na DM"],
    "fundo": ["Diagnóstico gratuito no link da bio"],
}
MOSTRAR_LINK = {"topo": False, "meio": False, "fundo": True}   # botão "Link na bio" no fim do vídeo

SYSTEM_DIRETO = SYSTEM_BASE + """

Neste pedido você PREENCHE LACUNAS de um modelo pronto: siga a estrutura, escolha UM molde de gancho e complete as lacunas com o
assunto do dia. Não invente formato novo. A chamada final NÃO é sua tarefa (o sistema coloca). Escreva também o campo "tema"
(uma frase curta que descreve o assunto do vídeo), a "legenda" (2 ou 3 linhas curtas; a última convida a salvar ou comentar,
sem promessa de resultado) e de 5 a 8 hashtags em português, sem espaços."""

SCHEMA_DIRETO = {"type": "OBJECT", "properties": {
    "tema": {"type": "STRING"}, "gancho": {"type": "STRING"}, "destaque": {"type": "STRING"},
    "cenas": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "rotulo": {"type": "STRING"}, "antes": {"type": "STRING"}, "texto": {"type": "STRING"}, "apoio": {"type": "STRING"}},
        "required": ["rotulo", "texto"]}},
    "legenda": {"type": "STRING"}, "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
}, "required": ["tema", "gancho", "cenas", "legenda", "hashtags"]}

# ---------------------------------------------------------------- banco de reserva (escrito à mão, só topo)
def _r(pilar, formato, tema, gancho, destaque, cenas, legenda, tags):
    return {"pillar": pilar, "formato": formato, "tema": tema, "gancho": gancho, "destaque": destaque, "cenas": cenas,
            "legenda": legenda, "hashtags": tags}


BANCO = [
    _r("linkedin", "lista", "Sinais de que o LinkedIn está invisível", "3 sinais de que seu LinkedIn está invisível", "invisível", [
        {"rotulo": "1", "texto": "Título só com o cargo", "apoio": "Quem lê não entende o valor que você entrega."},
        {"rotulo": "2", "texto": "Sobre sem palavras-chave", "apoio": "A busca não encontra perfis que não dizem o que fazem."},
        {"rotulo": "3", "texto": "Experiência sem conquistas", "apoio": "Conte o que mudou com o seu trabalho."}],
       "Seu perfil conta o que você entrega?\nConfira esses três pontos hoje. Salva para revisar depois.", ["linkedin", "carreira", "recolocacao", "perfilprofissional", "dicasdecarreira"]),
    _r("linkedin", "pare", "Título do LinkedIn com mais do que o cargo", "Pare de usar só o cargo no título", "cargo", [
        {"rotulo": "FAÇA ASSIM", "texto": "Diga o que você entrega", "apoio": "Para quem você trabalha e que problema resolve."},
        {"rotulo": "POR QUÊ", "texto": "A busca lê o seu título", "apoio": "Palavras claras ajudam o perfil a ser encontrado."},
        {"rotulo": "HOJE", "texto": "Reescreva em cinco minutos", "apoio": "Uma frase simples já melhora a leitura."}],
       "O título é a primeira coisa que o recrutador lê.\nReescreva o seu hoje e salva este vídeo.", ["linkedin", "carreira", "titulo", "recolocacao", "dicasdecarreira"]),
    _r("curriculo", "erro", "Conquistas em vez de tarefas no currículo", "O erro nº 1 no currículo", "erro", [
        {"rotulo": "O ERRO", "texto": "Listar tarefas em vez de conquistas", "apoio": ""},
        {"rotulo": "POR QUE ATRAPALHA", "texto": "Ninguém vê o que você mudou", "apoio": ""},
        {"rotulo": "CORRIJA ASSIM", "texto": "Mostre o resultado do seu trabalho", "apoio": "Sem inventar números: use fatos que você pode comprovar."}],
       "Tarefa diz o que você fazia. Conquista diz o que mudou.\nRevise seu currículo hoje.", ["curriculo", "carreira", "recolocacao", "entrevista", "dicasdecarreira"]),
    _r("curriculo", "mito", "Tamanho do currículo", "Currículo grande impressiona mais? Mito", "Mito", [
        {"rotulo": "MITO", "texto": "Mais páginas mostram mais valor", "apoio": ""},
        {"rotulo": "VERDADE", "texto": "Clareza vale mais que tamanho", "apoio": "Quem lê procura rápido o que combina com a vaga."},
        {"rotulo": "NA PRÁTICA", "texto": "Priorize o que combina com a vaga", "apoio": ""}],
       "Currículo bom é o que se lê rápido.\nSalva para revisar o seu.", ["curriculo", "carreira", "vagas", "recolocacao", "dicasdecarreira"]),
    _r("entrevista", "pergunta_recrutador", "Como responder fale sobre você", "Recrutador pergunta: fale sobre você", "você", [
        {"rotulo": "O QUE ELE QUER SABER", "texto": "Quem é você para esta vaga", "apoio": "Não é a sua história de vida inteira."},
        {"rotulo": "COMO RESPONDER", "texto": "Presente, passado e foco", "apoio": "Quem você é hoje, o que já fez e o que busca."},
        {"rotulo": "EVITE", "texto": "Ler o currículo em voz alta", "apoio": ""}],
       "Prepare essa resposta antes da entrevista.\nSalva e treina em voz alta.", ["entrevista", "carreira", "recrutamento", "vagas", "dicasdecarreira"]),
    _r("entrevista", "antes_de", "Preparação para entrevista", "Antes de uma entrevista, faça isto", "entrevista", [
        {"rotulo": "1", "texto": "Releia a descrição da vaga", "apoio": "Ela mostra o que a empresa procura."},
        {"rotulo": "2", "texto": "Prepare duas histórias reais", "apoio": "Situações em que você resolveu algo."},
        {"rotulo": "3", "texto": "Tenha uma pergunta para fazer", "apoio": "Mostra interesse de verdade."}],
       "Três passos simples para chegar mais seguro.\nSalva para a próxima entrevista.", ["entrevista", "carreira", "vagas", "recolocacao", "dicasdecarreira"]),
    _r("transicao", "pov", "Mudar de área aproveitando habilidades", "POV: você quer mudar de área", "mudar", [
        {"rotulo": "A VIRADA", "texto": "Você já tem habilidades que servem", "apoio": ""},
        {"rotulo": "FAÇA ISSO", "texto": "Liste o que você sabe fazer", "apoio": "Pense nas tarefas, não só no cargo."},
        {"rotulo": "DEPOIS", "texto": "Seu perfil passa a contar essa ponte", "apoio": "Quem lê entende como sua experiência se conecta."}],
       "Mudar de área começa por enxergar o que você já sabe fazer.\nManda para quem está nessa fase.", ["transicaodecarreira", "carreira", "recolocacao", "mudancadecarreira", "dicasdecarreira"]),
    _r("transicao", "lista", "Habilidades que servem em várias áreas", "3 habilidades que servem em qualquer área", "qualquer", [
        {"rotulo": "1", "texto": "Comunicação clara", "apoio": "Explicar bem uma ideia ajuda em qualquer função."},
        {"rotulo": "2", "texto": "Organização do próprio trabalho", "apoio": "Prazos e prioridades são universais."},
        {"rotulo": "3", "texto": "Aprender rápido", "apoio": "Mostre exemplos reais de quando você aprendeu algo novo."}],
       "Suas habilidades vão além do cargo.\nSalva e revisa o seu perfil.", ["transicaodecarreira", "habilidades", "carreira", "recolocacao", "dicasdecarreira"]),
    _r("comunicacao", "pare", "Mensagens objetivas no trabalho", "Pare de escrever mensagens longas no trabalho", "longas", [
        {"rotulo": "FAÇA ASSIM", "texto": "Comece pelo ponto principal", "apoio": "Depois dê o contexto, se precisar."},
        {"rotulo": "POR QUÊ", "texto": "Texto enorme perde a atenção", "apoio": "Quem lê quer saber o que fazer."},
        {"rotulo": "HOJE", "texto": "Reescreva a última em duas linhas", "apoio": ""}],
       "Mensagem clara economiza tempo de todo mundo.\nSalva e testa hoje.", ["comunicacao", "trabalho", "carreira", "produtividade", "dicasdecarreira"]),
    _r("produtividade", "lista", "Hábitos para fechar o dia com clareza", "3 hábitos para fechar o dia com clareza", "clareza", [
        {"rotulo": "1", "texto": "Liste o que você concluiu", "apoio": "Ver o que andou ajuda a descansar."},
        {"rotulo": "2", "texto": "Escolha a prioridade de amanhã", "apoio": "Comece o dia sabendo por onde ir."},
        {"rotulo": "3", "texto": "Feche as abas e respire", "apoio": "O dia terminou. Deixe o trabalho aí."}],
       "Terminar o dia com clareza muda o seguinte.\nSalva para testar.", ["produtividade", "rotina", "trabalho", "carreira", "dicasdecarreira"]),
    _r("negociacao", "resposta_rapida", "Pedir tempo para avaliar uma proposta", "Posso pedir tempo para pensar na proposta?", "tempo", [
        {"rotulo": "RESPOSTA CURTA", "texto": "Pode, e é normal", "apoio": "Avaliar com calma faz parte do processo."},
        {"rotulo": "POR QUÊ", "texto": "Decisão apressada custa caro", "apoio": "Compare rotina e crescimento, não só o valor."},
        {"rotulo": "DICA", "texto": "Combine um prazo e agradeça", "apoio": "Diga quando vai responder."}],
       "Pedir tempo é parte da negociação.\nSalva para quando chegar a proposta.", ["negociacao", "carreira", "proposta", "vagas", "dicasdecarreira"]),
    _r("aprendizado", "mito", "Aprender é só fazer cursos?", "Aprender é só fazer cursos? Mito", "Mito", [
        {"rotulo": "MITO", "texto": "Mais cursos, mais preparo", "apoio": ""},
        {"rotulo": "VERDADE", "texto": "Prática fixa o que o curso ensina", "apoio": "Sem aplicar, o conteúdo se perde."},
        {"rotulo": "NA PRÁTICA", "texto": "Aplique algo pequeno nesta semana", "apoio": ""}],
       "Estudar e praticar andam juntos.\nSalva e escolha o que aplicar.", ["aprendizado", "carreira", "desenvolvimento", "estudos", "dicasdecarreira"]),
]


# ---------------------------------------------------------------- escolha e validação
def _seed(post_id):
    return int(hashlib.sha1(str(post_id).encode()).hexdigest()[:8], 16)


def chamada_final(etapa, post_id):
    kws = KEYWORDS or ["QUERO"]
    rnd = random.Random(_seed(post_id))
    texto = rnd.choice(CHAMADAS.get(etapa) or CHAMADAS["topo"]).replace("{kw}", rnd.choice(kws))
    return texto


def _valida_extra(r):
    if not 2 <= len(r.get("hashtags") or []) <= 10:
        return "hashtags fora do esperado"
    if not _txt(r.get("legenda")) or len(_txt(r["legenda"])) > 420:
        return "legenda vazia ou longa demais"
    if not _txt(r.get("tema")):
        return "sem tema"
    tudo = " ".join(_txt(r.get(k)) for k in ("gancho", "legenda")) + " " + " ".join(
        _txt(c.get(k)) for c in r["cenas"] for k in ("texto", "apoio", "antes"))
    for frase in BANNED_PHRASES:
        if frase and frase.lower() in tudo.lower():
            return f"frase proibida: {frase}"
    return None


def escolher_modelo(etapa, modelo=None):
    if modelo in MODELOS:
        return modelo
    opcoes = POR_ETAPA.get(etapa) or POR_ETAPA["topo"]
    return _lru(opcoes, "reel_formato", load_history())


def _do_banco(etapa, formato=None):
    """Roteiro pronto de reserva: o menos usado recentemente, de preferência no formato escolhido."""
    usados = [h.get("topic") for h in load_history()]

    def idade(item):
        return max((i for i, t in enumerate(usados) if t == item["tema"]), default=-1)
    pool = [b for b in BANCO if b["formato"] == formato] or BANCO
    return min(pool, key=lambda b: (idade(b), BANCO.index(b)))


def criar_reel_direto(etapa, post_id, tema=None, modelo=None):
    """Devolve o necessário para montar e registrar o Reel: roteiro, legenda, tema, pilar, ângulo, tema de cor etc."""
    hist = hist_for(etapa)
    pillar = pick_pillar(etapa, hist)
    pl = PILLARS[pillar]
    ang = None if tema else pick_angle(pillar)
    formato = escolher_modelo(etapa, modelo)
    chamada = chamada_final(etapa, post_id)
    origem, r = "gemini", None
    try:
        recentes = [h.get("topic") for h in load_history()[-30:] if h.get("topic")]
        assunto = (f"Assunto sugerido (obrigatório): {tema}" if tema else
                   f"Ângulo do dia (obrigatório): {ang['angulo']}"
                   + (f". Já saíram sobre ele, faça um recorte DIFERENTE: {json.dumps(ang['topicos'], ensure_ascii=False)}" if ang["topicos"] else ""))
        prompt = (f"MODELO: {formato}. {MODELOS[formato]}\n"
                  f"Moldes de gancho (escolha um e preencha as lacunas): {json.dumps(MOLDES[formato], ensure_ascii=False)}\n"
                  f"Exemplo COMPLETO do modelo (só de estilo e tamanho; o assunto de hoje é outro): "
                  f"{json.dumps(EXEMPLOS[formato], ensure_ascii=False)}\n\n"
                  f"Etapa do funil: {etapa.upper()} -> {FUNNEL[etapa]}\nMissão: {MISSIONS[etapa]}\n"
                  f"Pilar: {pl['nome']}. {pl['descricao']}\n{assunto}\n"
                  + ("" if pillar == "linkedin" else "Este pilar não é sobre LinkedIn: fale do tema profissional em geral, sem forçar o LinkedIn.\n")
                  + ("Etapa de topo: não venda nada e não mencione oferta, diagnóstico nem link na bio.\n" if etapa == "topo" else "")
                  + (f"Assuntos recentes (não repita): {json.dumps(recentes[-12:], ensure_ascii=False)}\n" if recentes else ""))
        for tentativa in range(2):
            r = _gemini_json(prompt, system=SYSTEM_DIRETO, schema=SCHEMA_DIRETO, deadline=150, max_tokens=2048)
            r["chamada"] = chamada
            erro = validar(r, formato) or _valida_extra(r)
            if not erro:
                break
            print(f"[reel-direto] roteiro reprovado ({erro})" + ("; tentando de novo" if tentativa == 0 else ""), flush=True)
            r = None
    except Exception as e:
        print(f"[reel-direto] Gemini indisponível ({str(e)[:160]}); usando o banco de reserva", flush=True)
        r = None
    if r is None:
        b = _do_banco(etapa, formato)
        origem, formato, pillar, ang = "banco", b["formato"], b["pillar"], None
        r = {k: b[k] for k in ("gancho", "destaque", "cenas", "legenda", "hashtags")}
        r["tema"], r["chamada"] = b["tema"], chamada
    tags = " ".join("#" + _txt(h).lstrip("#").replace(" ", "") for h in r["hashtags"][:8])
    return {"roteiro": {k: r[k] for k in ("gancho", "destaque", "cenas", "chamada")},
            "formato": formato, "origem": origem, "topic": _txt(r["tema"]), "pillar": pillar,
            "angle": ang["angulo"] if ang else None, "caption": r["legenda"].strip() + "\n\n" + tags,
            "theme": pick_theme(etapa), "variant": pick_variant(etapa),
            "mostrar_link": MOSTRAR_LINK.get(etapa, False)}
