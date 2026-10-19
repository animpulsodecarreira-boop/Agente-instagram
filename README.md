# Agente de Instagram — AN Impulso de Carreira

Todo dia útil às 08:00 (Brasília) o agente:
1. escolhe a etapa do funil (topo / meio / fundo) pela agenda da semana (`agent/config.py`);
2. pede ao **Gemini** o carrossel e a legenda (sem repetir temas já usados);
3. gera as imagens 1080x1350 com a sua marca (sem IA de imagem);
4. envia tudo para o seu **Telegram** com os botões **✅ Aprovar** e **❌ Rejeitar**;
5. ao aprovar, publica o carrossel no Instagram (verificação a cada ~10 min).

Tudo roda grátis no GitHub Actions. Nada fica ligado no seu computador.

---

## Configuração (uma vez só, ~40 min)

### 1) Repositório no GitHub (precisa ser PÚBLICO)
O Instagram só publica a partir de links públicos das imagens. Crie um repositório **público**,
suba esta pasta e ative **Settings → Actions → General → Workflow permissions → Read and write**.
> Atenção: as artes dos posts ficam visíveis no repositório. Não coloque nada confidencial aqui.

### 2) Chave do Gemini (grátis)
Entre em https://aistudio.google.com → **Get API key**. Guarde a chave.
Os nomes de modelos do Gemini mudam rápido; por isso o agente usa os aliases
`gemini-flash-latest` e `gemini-flash-lite-latest`. Se der erro de modelo, troque pelos nomes
atuais da sua conta na variável `GEMINI_MODELS`.
No plano gratuito o Google pode usar o que você envia para melhorar os produtos dele.
Como só enviamos instruções de marca e temas públicos, isso não é problema; **nunca coloque dados de clientes**.

### 3) Bot do Telegram (grátis)
1. No Telegram, fale com **@BotFather** → `/newbot` → guarde o **token**.
2. Abra uma conversa com o seu bot e mande qualquer mensagem (ex.: "oi").
3. Descubra o seu **chat id** abrindo `https://api.telegram.org/bot<TOKEN>/getUpdates`
   e copiando o número em `"chat":{"id": ...}`.

### 4) Instagram (a parte mais chata, mas é só uma vez)
- A conta precisa ser **Profissional** (Comercial ou Criador) e **ligada a uma Página do Facebook**.
- Crie um app em https://developers.facebook.com (tipo Business) e adicione **Instagram Graph API**.
- Gere um token com as permissões `instagram_basic`, `instagram_content_publish`,
  `pages_show_list` e `pages_read_engagement`.
- Troque por um token de longa duração e use o **token da Página** (esse não expira).
  O token de usuário comum dura ~60 dias; se usar esse, lembre de renovar.
- Pegue o **IG User ID** (id da conta do Instagram) pela Graph API Explorer.
- Enquanto o app estiver em modo de desenvolvimento, funciona para contas que você administra.

### 5) Segredos no GitHub
**Settings → Secrets and variables → Actions → New repository secret**:

| Nome | Valor |
|---|---|
| `GEMINI_API_KEY` | chave do passo 2 |
| `TELEGRAM_BOT_TOKEN` | token do passo 3 |
| `TELEGRAM_CHAT_ID` | seu chat id |
| `IG_ACCESS_TOKEN` | token do passo 4 |
| `IG_USER_ID` | id da conta do Instagram |

### 6) Teste
**Actions → Gerar post → Run workflow** (escolha "topo"). Em ~3 minutos chega no Telegram.
Toque em **Aprovar** e, em até ~10 min, o post sai no Instagram e você recebe o link.
Se o Instagram falhar, o bot avisa o motivo no Telegram.

---

## Personalizar
Tudo em `agent/config.py`: agenda da semana (`WEEK_PLAN`), oferta do post de fundo (`OFFER`),
texto do botão (`LINK_LABEL`), cores e modelos. O tom de voz e as regras ficam em `agent/generate.py` (`SYSTEM`).

## Testar o visual no seu computador
```bash
pip install -r requirements.txt && playwright install chromium
python -m agent.main preview --mock      # gera imagens de exemplo em queue/_preview
```

## Limites e cuidados
- O GitHub pode atrasar execuções agendadas em alguns minutos.
- Repositórios públicos sem atividade por 60 dias têm os agendamentos pausados (os próprios posts contam como atividade).
- Revise sempre antes de aprovar: o agente é um rascunhador, a decisão final é sua.
- Se o plano gratuito do Gemini estourar a cota, o agente tenta o modelo seguinte e avisa no Telegram se falhar.
