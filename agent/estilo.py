"""Guia de voz da marca: o tom dos textos que o Gemini escreve, e a lista de expressões de manual que a revisão aponta.

Para ajustar o jeito de escrever do agente, edite os textos abaixo (é o que o Gemini lê antes de escrever cada post, Reel e roteiro).
Os exemplos "fraco / melhor" servem só de tom: o Gemini é instruído a não copiar as frases nem o assunto.
"""

GUIA_POSTS = """

GUIA DE VOZ (obrigatório; vale para legenda, slides e stories)
Escreva como uma pessoa inteligente e simpática fala com um colega: conversa, não redação. Se a frase soa como texto de manual,
de palestra ou de redação escolar, reescreva.
1. Comece pelo concreto. Abra com uma cena, um momento ou um detalhe específico (o e-mail das 17h50, a reunião que podia ser
   uma mensagem, o currículo de quatro páginas) e só depois tire a lição. Não abra com a ideia geral.
2. Uma ideia por post, dita logo. A primeira frase da legenda já tem que dar vontade de ler a segunda. Nada de preparar o terreno.
3. Frases curtas e variadas (até 18 palavras; uma ou outra bem curta). Parágrafos de no máximo 3 linhas. Nada de parágrafo
   único e denso.
4. Tenha um ponto de vista. Diga algo a que alguém possa responder "é isso mesmo" ou "discordo, porque...". Constatar o óbvio
   ("é universal", "faz parte da rotina") não é conteúdo.
5. Humor é específico e curto. Não explique a piada nem a anuncie ("fenômeno", "a famosa", "aquela..."). No máximo uma
   observação engraçada por post.
6. Corte enchimento e clichês: "faz parte da rotina profissional", "é universal", "primeiro passo para", "energia renovada",
   "exercício de paciência", "muita estrada pela frente", "evita mal-entendidos", "clareza e profissionalismo", "alinhar
   expectativas", "no mundo atual", "costuma ser", "existe um fenômeno".
7. O fechamento é uma pergunta específica e fácil de responder (ex.: "Que horas a sua quarta-feira vira sexta?") ou nenhum
   fechamento. Não use "marque nos comentários aquele amigo que..." nem "mande este post para alguém que..." (varie; essas
   fórmulas cansam).
8. Coerência: o gancho, o desenvolvimento e o fechamento falam do MESMO assunto e do mesmo tipo de situação (prazo de trabalho
   não vira proposta de emprego). Antes de responder, releia e confira.
9. Assuntos técnicos e afirmações científicas (leis, direitos, prazos legais, valores, saúde, psicologia, neurociência,
   estatísticas, "estudos mostram"): nada de afirmação de que você não tenha certeza ("o cérebro desliga", "a ciência prova").
   Fale da experiência comum ("muita gente sente que...") ou de ações práticas, sem inventar explicação. Na dúvida, tire a
   afirmação.
10. O conselho combina com a marca: ajudar a pessoa a se organizar, se comunicar e se posicionar. Não incentive a largar o
   trabalho nem a "não produzir".

Exemplos de TOM (só do jeito de escrever; não copie as frases nem o assunto):
Fraco: "Existe um fenômeno inexplicável chamado quarta-feira que faz a gente jurar que a semana praticamente acabou."
Melhor: "Quarta-feira, 14h. Você já se convenceu de que é quase sexta. A sua caixa de entrada discorda."
Fraco: "Conversar sobre prazos e limites faz parte da rotina profissional e evita mal-entendidos."
Melhor: "Recebeu um prazo apertado? Antes de dizer sim, pergunte: para quando exatamente, e o que pode ficar para depois?"
Fraco: "Tentar render algo produtivo nesse momento costuma ser um exercício de paciência com a própria atenção."
Melhor: "Sexta à tarde, deixe para o que pede pouco foco: organizar a caixa de entrada, planejar a semana, responder o que ficou pendente."
"""

GUIA_REEL = """

GUIA DE VOZ para texto na tela: conversa, não manual. Cada frase diz algo concreto que a pessoa pode fazer ou reconhecer em dois
segundos. Prefira verbos de ação e situações específicas (o e-mail das 17h50, o currículo de quatro páginas).
Proibido: palavras vazias e jargão ("alinhar expectativas", "clareza e profissionalismo", "faz parte da rotina", "é universal",
"primeiro passo para", "evita sobrecarga").
O gancho e todas as cenas tratam do MESMO assunto (não misture prazo de trabalho com proposta de emprego). Cada cena acrescenta
uma informação nova: não repita a mesma ideia com outras palavras nem explique o óbvio ("limites claros mostram clareza").
Nada de afirmação científica ou técnica de que você não tenha certeza (ex.: "o cérebro desliga"): diga o que fazer, não o
porquê biológico. Não incentive a pessoa a não trabalhar.
Exemplo de tom (não copie): fraco "Alinhar expectativas evita sobrecarga depois"; melhor "Diga o que dá para entregar e até quando".
"""

# expressões que a revisão aponta (só avisa; não troca nada). (padrão, rótulo)
EXPRESSOES_DE_MANUAL = [
    (r"\bfaz parte da rotina\b", "frase de manual"), (r"\bexiste um fen[oô]meno\b", "abertura de redação"),
    (r"\bfen[oô]meno inexplic[aá]vel\b", "abertura de redação"), (r"\b[eé] universal\b", "constata o óbvio"),
    (r"\benergia renovada\b", "clichê"), (r"\bprimeiro passo para\b", "clichê"), (r"\bexerc[ií]cio de paci[eê]ncia\b", "tom de redação"),
    (r"\bmuita estrada pela frente\b", "clichê"), (r"\bevita mal-entendidos\b", "frase de manual"),
    (r"\bclareza e profissionalismo\b", "palavras vazias"), (r"\balinhar expectativas\b", "jargão"),
    (r"\bevita sobrecarga\b", "frase de manual"), (r"\bno mundo (atual|corporativo)\b", "enchimento"),
    (r"\bnos dias de hoje\b", "enchimento"), (r"\b[eé] importante (ressaltar|lembrar|destacar)\b", "enchimento"),
    (r"\bcostuma ser\b", "enchimento"), (r"\ba famosa\b", "anuncia a piada"),
]
FORMULAS_DE_FECHAMENTO = [
    (r"marca nos coment[aá]rios aquele", "fechamento de fórmula"), (r"marque nos coment[aá]rios aquele", "fechamento de fórmula"),
    (r"mand[ae] (este|esse) post para algu[eé]m que", "fechamento de fórmula"),
]
AFIRMACOES_SEM_BASE = [
    (r"\bo c[eé]rebro (desliga|trava|p[aá]ra|entra em)", "afirmação científica sem base"),
    (r"\b(estudos|pesquisas) (mostram|indicam|provam|comprovam)\b", "afirmação sem fonte"),
    (r"\bcientificamente comprovad", "afirmação sem fonte"), (r"\ba ci[eê]ncia (prova|mostra|diz)\b", "afirmação sem fonte"),
]
FRASE_LONGA = 28   # palavras: acima disso a frase vira aviso
