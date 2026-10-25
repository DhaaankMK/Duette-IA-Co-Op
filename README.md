# Duette

Aplicativo desktop que faz uma IA (Claude, GPT ou Gemini) jogar ao seu lado, como Player 2. A IA conversa
com você e tem nome, foto (robozinho por padrão) e personalidade próprios.

## Executar

```bash
pip install -r requirements.txt     # Pillow (fotos), pygame (jogo de teste e sons), keyring (opcional)
python Run.py
```

Requer Python 3.10+ com tkinter (Linux: `sudo apt install python3-tk`).

## Fluxo do aplicativo

1. **EULA**: na primeira execução, o app fica bloqueado até o usuário rolar os termos (`LICENSE.txt`)
   até o fim e aceitar. O aceite é gravado e a tela nunca mais aparece.
2. **Health-check da chave de API** a cada abertura (chamada leve de listagem de modelos, sem custo):
   * válida ➜ Dashboard;
   * ausente, recusada ou expirada ➜ a chave é descartada e abre a tela de API com mini tutorial;
   * sem internet / provedor fora do ar ➜ a chave **não** é apagada; o app abre em modo offline.
3. **Dashboard**: Jogos, Perfil do Player 2, Conversa e Configurações.

## Modelo de IA

Por padrão o Duette **detecta sozinho** o melhor modelo disponível para a sua chave (rápido, estável e na versão
mais nova) e o lembra. Se um modelo for aposentado ou não estiver liberado (erro 404), ele troca para o próximo
melhor automaticamente. O mais novo nem sempre é o melhor: o Duette prioriza modelos estáveis e conhecidos, e
testa se o modelo responde de verdade. Se um estiver sobrecarregado (503), lento ou indisponível, troca sozinho
para o próximo que responder e lembra da escolha. Em Configurações é possível redetectar, e na tela de API é possível fixar um modelo.

## Como a IA joga

Um LLM leva segundos para responder, o que é lento demais para controlar um personagem quadro a quadro.
O Duette divide o trabalho:

* **LLM** escolhe a *estratégia* (agressiva, equilibrada, defensiva, recuar, parado) a cada ~2,5 s e pode falar;
* **Reflexos locais** (`src/tactics.py`) executam a estratégia em tempo real, com atraso de reação humano.
  Sem rede, o Player 2 continua jogando com a última estratégia.

O jogo e o Duette conversam por uma **ponte local** (`src/bridge.py`): TCP em `127.0.0.1`, porta aleatória,
token por sessão, mensagens validadas e limitadas. O jogo de teste (`teste_game/`) já traz o cliente
(`ai/duette_client.py`, só biblioteca padrão) e o Jogador 2 passa a ser controlado pela IA quando iniciado pelo Duette.

## Estrutura

```
Run.py                  ponto de entrada
LICENSE.txt             EULA exibido ao usuário
assets/                 sons e manifesto (sound_manifest.json)
mods_bundle/            catálogo de jogos (games.json) e pacotes .zip de mods
teste_game/             jogo de teste (Mortal Stick Combat) com a integração da IA
src/
  main.py               inicia a interface
  storage.py            config.json atômico, EULA, chave de API, health-check
  ai_engine.py          provedores (Anthropic/OpenAI/Gemini), prompts, validação de chave
  tactics.py            reflexos locais do Player 2
  bridge.py             servidor local jogo <-> Duette
  agent.py              sessão do Player 2 (ponte + reflexos + IA)
  mod_installer.py      instalação segura/reversível de mods
  launcher.py           inicia o jogo de teste
  logger.py             log detalhado com mascaramento de segredos
  diagnostics.py        diagnóstico de rede e relatório de suporte
  avatar.py, sound.py   foto de perfil e efeitos sonoros (opcionais)
  ui/                   telas: EULA, API, Dashboard, Jogos, Perfil, Conversa, Configurações
tests/                  testes automatizados
tools/hash_bundle.py    gera o SHA-256 de um pacote de mods
```

### Consciência do jogo em tempo real (v0.2)

O jogo envia ~20 estados por segundo com campos extras opcionais (recarga do golpe, arma, estilo,
invulnerabilidade, fase da luta, placar) e **eventos discretos** (golpe, golpe errado, combo, vida crítica,
KO, nova luta). Tudo é validado e limitado em `parse_state`. A sessão guarda os últimos eventos,
calcula a tendência da vida e entrega ao modelo um resumo em português (`_brief`). Eventos importantes
(sofrer golpe, KO, vida crítica, combos) antecipam a próxima decisão da IA, respeitando um intervalo
mínimo de 3 s para não estourar os limites do provedor. Os reflexos locais também usam os dados novos:
punem quem está se recuperando de um golpe, não atacam quem está invulnerável e esquivam em pânico.

### Fala da IA no jogo

As falas aparecem em um **painel fixo no chão da arena** (nunca sobre os personagens): ícone de robô que
"fala", nome da IA, etiqueta com a estratégia atual e texto com efeito de digitação. O jogo também recebe
o nome e a estratégia por mensagens `status`.

### Jogo de teste renovado

Três cenários animados (Dojo, Cidade neon, Vulcão), HUD com barra de dano fantasma, cronômetro, recarga e
combos, contagem regressiva, golpes críticos e contra-ataques, hit-stop, tremor de tela, câmera lenta e
zoom no KO, tela de resultado com estatísticas, animações com articulações (antecipação do golpe, rastro da
arma, queda no KO, olhos e expressões), partículas por estilo, **efeitos sonoros e música sintetizados**
(nenhum arquivo de áudio é necessário; tecla M liga/desliga a música).

### Interface animada (v0.2)

Tela de carregamento com estrelas, robô flutuante com órbitas, título que brilha e barra de progresso
com etapas; logo animado; avatar da IA que pisca, fala e pula quando clicado; faixa de boas-vindas com
dicas digitadas (clique para a próxima); transição deslizante entre páginas; bordas que brilham ao passar
o mouse; botão "Jogar" que pulsa; indicador de status que pulsa quando conectado.
Os efeitos sonoros (hover, clique, navegação, sucesso, erro, aviso, abertura) e a **música ambiente** são
sintetizados por `src/synth.py` em segundo plano; a música tem botão na barra lateral e opção em Configurações.

## Testes

```bash
python -m unittest tests.test_core tests.test_logging tests.test_awareness tests.test_audio tests.test_game_integration
xvfb-run python -m unittest tests.test_ui_smoke      # interface (precisa de display)
```

## Logs e diagnóstico

* Log detalhado em `<dados do usuário>/logs/duette.log` (Windows: `%APPDATA%\Duette\logs`), rotativo (1 MB x 5).
  O jogo grava também em `logs/game.log`. Cada requisição de rede tem um id, método, destino, status HTTP e tempo.
* No app: **Configurações > Logs e diagnóstico** mostra o log, **testa a rede etapa por etapa** (DNS, TCP, TLS e API,
  apontando onde falha: firewall, antivírus, proxy, certificado) e copia um relatório pronto para suporte.
* `python Run.py --debug` (ou `DUETTE_DEBUG=1`) também imprime o log no console.
* Chaves de API são sempre mascaradas. Conteúdo das conversas não é gravado (só tamanhos);
  para depurar o conteúdo, use `DUETTE_LOG_CONTENT=1`.

## Segurança (resumo)

* Chave de API: guardada no cofre do sistema (`keyring`) quando disponível; senão em `config.json` com
  permissão 0600. **Nesse caso ela não é criptografada.** Nunca aparece em logs, erros, `repr` ou na interface (só mascarada).
* Rede: somente HTTPS para hosts fixos dos provedores; redirecionamentos recusados; respostas com tamanho máximo.
* Saída do modelo é dado não confiável: decisões passam por lista de permissão estrita.
* Mods: SHA-256 obrigatório, extração anti zip-slip/zip-bomb/symlink, backup e rollback, desinstalação por recibo.
* `config.json`: escrita atômica, backup `.bak`, recuperação automática de arquivo corrompido.

## Estado atual e próximos passos

* Funcionando: tudo acima, com o jogo de teste.
* **BONELAB**: o catálogo e o instalador estão prontos, mas o pacote de mods (MelonLoader + `DuetteBridge.dll`,
  um mod em C# que fala o mesmo protocolo da ponte) ainda precisa ser criado.
* **Voz** (Whisper para ouvir, TTS para falar) e **overlay no jogo**: ainda não implementados.
* Empacotamento (PyInstaller): o launcher do jogo de teste ainda não suporta a versão empacotada.
