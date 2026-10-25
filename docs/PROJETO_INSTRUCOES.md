\# 🚀 Projeto: Duette (Companion Engine)



\## 📌 Visão Geral do Projeto

O \*\*Player 2 AI Hub\*\* é um ecossistema de software desktop projetado para transformar qualquer Inteligência Artificial (LLM) em um companheiro interativo de jogos em tempo real (um "Player 2" verdadeiro). 



Diferente de assistentes convencionais, este aplicativo integra diretamente a IA ao fluxo do jogo do usuário. Ele permite que a IA assuma o controle de avatares (em jogos com suporte a física/modding como \*Bonelab\* ou jogos de luta 2D), reaja ao estado do jogo, converse via chat e voz com o jogador e mantenha uma personalidade persistente, amigável e totalmente customizável.



\---



\## 🛠️ Arquitetura do Sistema \& Módulos Principais



O projeto é dividido em \*\*5 Módulos Fundamentais\*\* que devem ser integrados e respeitados:



\### 1. Sistema de Onboarding \& Aceite de Licença (EULA)

\* \*\*Trava Inicial:\*\* Ao iniciar o aplicativo pela primeira vez, o fluxo principal deve ser bloqueado até que o usuário leia e aceite os \*\*Termos de Licença e Uso (EULA)\*\* contidos no arquivo `LICENSE.txt`.

\* \*\*Persistência do Aceite:\*\* O aceite é registrado permanentemente no banco de dados/configuração local. Uma vez aceito, essa tela nunca mais é exibida nas inicializações subsequentes.



\### 2. Motor de Gerenciamento de Dados Persistentes (Data Storage \& Health-Check)

O sistema conta com um módulo de armazenamento local altamente resiliente (`config.json` / Data Storage System):

\* \*\*Armazenamento Seguro:\*\* Guarda preferências de interface, nome e avatar do bot, histórico de aceites e a chave de API da IA.

\* \*\*Validação de API em Tempo Real (Health-Check):\*\*

&#x20; \* Toda vez que o aplicativo é aberto, o sistema executa um \*ping\* assíncrono em background para testar a validade e a cota da chave de API cadastrada.

&#x20; \* \*\*Chave Válida:\*\* O aplicativo redireciona o usuário diretamente para o Dashboard Principal.

&#x20; \* \*\*Chave Inválida / Expirada / Nula:\*\* O sistema invalida o registro, interrompe a inicialização e redireciona automaticamente o usuário para a \*\*Tela de Configuração de API\*\*, exibindo um alerta explicativo e um mini tutorial de como obter uma nova chave.



\### 3. Módulo de Personalização Avançada do Player 2 (AI Profile System)

Permite ao usuário customizar completamente a identidade e a personalidade da IA:

\* \*\*Identidade:\*\* Alteração do Nome Customizado e Upload/Seleção de Foto de Perfil (Avatar).

\* \*\*Injeção de Contexto (System Prompt):\*\* As preferências do usuário (nome, traços de personalidade, tom de voz) são injetadas dinamicamente no comando inicial enviado à API.

\* \*\*Presets de Personalidade:\*\*

&#x20; \* \*\*Gamer Zueiro / Amigável:\*\* Comemora vitórias, brinca com falhas e conversa em tom descontraído.

&#x20; \* \*\*Tryhard / Estratégico:\*\* Focado em objetivos, chamadas táticas e respostas curtas/diretas.

&#x20; \* \*\*Personalizado:\*\* Campo de texto livre para o usuário definir a conduta do bot.



\### 4. Gerenciador Automático de Mods e Assets (Auto-Mod Installer)

\* O aplicativo lista os jogos compatíveis (ex: \*Bonelab\*).

\* Ao selecionar um jogo, o sistema verifica a presença das dependências de modding no diretório do jogo (ex: MelonLoader, DLLs de integração).

\* Se os arquivos não estiverem presentes, o aplicativo extrai os mods embutidos nos assets do software e os instala automaticamente nas pastas correspondentes do jogo, exibindo uma barra de progresso visual.



\### 5. Sandboxing \& Test-Game Integrado

\* O aplicativo possui um minijogo leve e interno pré-compilado/integrado para testes imediatos.

\* O usuário pode testar a conexão da IA, respostas de movimento, simulação de física, envio de áudio e comandos de voz dentro do minijogo de teste antes de rodar um jogo completo no PC.



\---



\## 📂 Estrutura de Arquivos e Diretórios do Projeto Base



O arquivo `.zip` fornecido contém a seguinte estrutura padronizada que deve ser utilizada pelo Claude:



```text

Duette/

│

├── PROJETO\_INSTRUCOES.md      <-- Este arquivo com a especificação técnica completa

├── LICENSE.txt                <-- Termos de uso obrigatórios para o EULA

│

├── assets/

│   ├── images/                <-- Interface gráfica, logos e avatares padrão

│   ├── sounds/                <-- Efeitos sonoros do app (ver sound\_manifest.json)

│   └── sound\_manifest.json    <-- Mapeamento de sons (nome, duração, função)

│

├── test\_game/                 <-- Jogo leve de teste para simulação do Player 2

│

├── mods\_bundle/               <-- Mods e dependências embutidas para os jogos

│

└── src/

&#x20;   ├── main.py                <-- Ponto de entrada do aplicativo

&#x20;   ├── storage.py             <-- Módulo de gerenciamento de dados e validação de API

&#x20;   ├── ai\_engine.py           <-- Módulo de integração com APIs de IA (Claude, OpenAI, etc.)

&#x20;   ├── mod\_installer.py       <-- Gerenciador e instalador de mods

&#x20;   └── ui/                    <-- Interfaces do usuário (EULA, API Config, Dashboard)

