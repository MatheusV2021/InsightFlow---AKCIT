# Assistente documental com agente e Qdrant local

## Funcionamento

O Assistente responde a perguntas sobre os textos extraídos dos PDFs. O SQLite continua armazenando documentos, páginas e análises. O Qdrant local funciona como índice vetorial reconstruível. Não há Docker, serviço remoto de banco vetorial ou framework de agentes.

1. O usuário seleciona documentos e envia uma pergunta explicitamente.
2. O serviço valida a pergunta e todos os IDs e avisa sobre páginas não extraídas ou PDFs sem texto.
3. No modo normal com `CHAT_RETRIEVAL=qdrant` e `CHAT_AGENT_ENABLED=true`, o agente escolhe sequencialmente buscas vetoriais e leituras de páginas dos documentos selecionados. Pode reformular consultas e encerrar antes dos limites.
4. Cada busca sincroniza o índice dos documentos consultados e gera o embedding da consulta escolhida pelo agente; os resultados são filtrados pelos IDs permitidos e pelo limiar de similaridade.
5. Leituras de páginas usam uma consulta SQL parametrizada por ID e número de página. Os recortes vetoriais também são reconstruídos a partir do SQLite atual; o texto armazenado no payload não é usado como fonte da resposta.
6. Havendo contexto, uma chamada ao provedor ativo solicita afirmações estruturadas com evidências. Sem fontes recuperadas, retorna uma mensagem local sem chamar o modelo de geração; as decisões anteriores do agente podem ter consumido chamadas.
7. Valida todas as citações antes de exibir a resposta. Perguntas, respostas e fontes ficam somente no histórico da sessão.

Uploads, seleção de documentos, abertura de páginas e reruns não geram embeddings. A indexação acontece somente ao enviar uma pergunta. Cada pergunta é independente; o histórico de perguntas anteriores não é enviado à API. As chamadas de ferramentas e seus resultados da pergunta atual são enviados nas decisões seguintes.

## Agente e limites por pergunta

O `agent_service.py` usa function calling por um adaptador de provedor, sem framework adicional. No Gemini, o SDK Google recebe declarações de funções e a execução automática é desativada; múltiplas chamadas numa mesma decisão são recusadas antes de executar ferramentas. Na OpenAI, as definições têm `strict=true` e `parallel_tool_calls=false`. As funções e seus argumentos são validados novamente em Python, independentemente da saída do modelo. Referência: [documentação oficial de function calling](https://developers.openai.com/api/docs/guides/function-calling).

```dotenv
CHAT_AGENT_ENABLED=true
AGENT_MAX_TOOL_CALLS=4
AGENT_MAX_SEARCHES=3
```

O limite padrão é de quatro decisões que podem executar ferramentas, incluindo no máximo três buscas no Qdrant. Leituras de páginas, tentativas inválidas e repetições também consomem o limite total. O contador é recriado a cada pergunta. O servidor remove a ferramenta de busca quando o limite específico acaba e recusa qualquer chamada adicional mesmo que o modelo tente usá-la. O modelo pode encerrar sem ferramenta; o texto livre dessa etapa nunca é apresentado como resposta.

As únicas ferramentas são:

- `search_documents(query, document_ids)`: busca semântica restrita a um subconjunto dos documentos selecionados; até 3.000 caracteres de fontes são retidos por chamada.
- `read_page(document_id, page_number, offset)`: lê texto do SQLite a partir da posição pedida, até 4.000 caracteres. `offset=0` começa no início da página; páginas ou posições ausentes retornam uma mensagem sem inventar texto.

O orçamento total compartilhado entre todas as ferramentas continua sendo de seis fontes e 10.000 caracteres. Recortes são preservados literalmente e avisos indicam cortes. Ao atingir um limite, o agente encerra a investigação e a geração recebe apenas as fontes já obtidas. Não há autorização para documentos fora da seleção, SQL livre, rede de pesquisa, escrita ou execução de comandos.

Os resultados das ferramentas são devolvidos ao modelo com o `call_id` correspondente. O histórico transitório da investigação existe somente durante a pergunta e não persiste no SQLite nem cria sessão remota. A OpenAI usa `store=False`; no Gemini, `generate_content` recebe explicitamente os conteúdos a cada decisão. As partes nativas e assinaturas de raciocínio do Gemini são preservadas para o retorno das ferramentas, sem exibir seu conteúdo ao usuário. Cada decisão tem até 1.000 tokens de saída, entrada serializada de até 24.000 caracteres, timeout de 60 segundos e nenhuma retentativa automática. Falhas de API interrompem a consulta com mensagem sanitizada; reruns não repetem a investigação.

Com os padrões, há até quatro chamadas de decisão e uma chamada final de geração, além dos embeddings de até três buscas e dos lotes de indexação necessários. Esses limites são de chamadas lógicas: a indexação de documentos pode envolver vários lotes e não equivale a uma única requisição de embeddings. A primeira indexação pode aumentar a espera. O modelo ativo (`GEMINI_MODEL` ou `OPENAI_MODEL`) deve suportar function calling; o mesmo modelo continua sendo usado na geração estruturada final.

`CHAT_AGENT_ENABLED=false` restaura a consulta vetorial única anterior. `CHAT_RETRIEVAL=lexical` e o modo demonstração também preservam seus fluxos anteriores, sem o agente. A resposta validada mostra contagens de buscas e leituras e avisos de limite; não expõe raciocínio interno do modelo.

## Índice e embeddings

A configuração padrão é:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.8-flash
DEMO_MODE=false
CHAT_RETRIEVAL=qdrant
QDRANT_PATH=database/qdrant
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_EMBEDDING_DIMENSIONS=1536
VECTOR_SCORE_THRESHOLD=0.3
```

`GEMINI_API_KEY` é usada tanto para embeddings quanto para geração quando `AI_PROVIDER=gemini`. `GEMINI_MODEL` configura as decisões e a geração final; `GEMINI_EMBEDDING_MODEL` e `GEMINI_EMBEDDING_DIMENSIONS` configuram os vetores. Na alternativa `AI_PROVIDER=openai`, valem as variáveis `OPENAI_*` anteriores. As chaves não são intercambiáveis e não há fallback automático. A integração Google usa o SDK oficial [Google Gen AI](https://googleapis.github.io/python-genai/). Caminhos relativos do índice são resolvidos a partir da raiz do projeto.

Cada página é dividida em trechos de até 1.800 caracteres, com sobreposição de 200. Texto, documento, nome e página são preservados. IDs determinísticos incluem texto, referências e posição; trechos inalterados reutilizam os vetores persistidos. Cada coleção identifica o caminho do SQLite, provedor, modelo de embeddings, dimensões e configuração dos recortes.

Embeddings são criados em lotes de até 16 trechos, com timeout de 60 segundos e sem retentativas automáticas. Uma falha interrompe a consulta e é exibida com mensagem sanitizada. Lotes já gravados são reaproveitados quando o usuário reenviar a pergunta. Vetores antigos da seleção só são removidos após concluir os novos lotes. Documentos excluídos do SQLite têm seus vetores removidos da coleção ativa na próxima consulta vetorial.

A busca usa similaridade de cosseno, até seis trechos e no máximo 10.000 caracteres por recuperação. No agente, cada resultado é novamente limitado pelo orçamento por ferramenta e pelo orçamento compartilhado da pergunta. Recortes omitidos pelos limites geram aviso. `VECTOR_SCORE_THRESHOLD` é um limiar ajustável, não uma probabilidade de correção; deve ser avaliado com perguntas reais em português. Trocar provedor, modelo ou dimensões cria outra coleção e gera novos custos de indexação. Coleções anteriores não são excluídas automaticamente.

A pasta `database/qdrant/` fica fora do Git. Ela pode ser reconstruída: pare a aplicação, renomeie a pasta configurada e faça novas consultas. Preserve o SQLite e os PDFs. Não há transação única entre SQLite e Qdrant; o índice é sincronizado sob demanda.

O modo local aceita um único processo por pasta. Sessões Streamlit do mesmo processo são serializadas durante as operações do índice. O cliente fecha a pasta após cada consulta, inclusive em caso de erro. Para múltiplos processos ou réplicas, será necessário adaptar a conexão para Qdrant em servidor.

## Busca lexical e demonstração

`CHAT_RETRIEVAL=lexical` mantém explicitamente a recuperação anterior, sem embeddings. A pergunta é normalizada em caixa baixa, sem acentos e com redução simples de plurais. Palavras frequentes são ignoradas. Trechos são ordenados pela quantidade de termos distintos correspondentes, frequência limitada a três por termo e desempate determinístico por ID, página e posição. Não há tratamento de sinônimos nessa opção.

Com `DEMO_MODE=true`, a busca sempre é lexical, independentemente de `CHAT_RETRIEVAL`. Não abre Qdrant nem chama provedores externos. Mostra até três recortes literais identificados como demonstração sem geração por IA. As fontes continuam sendo validadas. Análises predefinidas permanecem restritas aos PDFs fictícios originais; veja [demo.md](demo.md).

## Validação de fontes

A API retorna `ChatModelOutput`, validado por Pydantic: até seis afirmações, cada uma com evidências que incluem ID, nome, página e citação literal contínua de até 600 caracteres.

Para cada afirmação, a aplicação exige evidência que corresponda ao documento selecionado, nome e página, e cuja citação exista em um dos recortes efetivamente enviados à geração. Se qualquer afirmação tiver fonte ausente ou inválida, toda a resposta proposta é ocultada. Não há chamada automática para reparar citações.

As referências são numeradas e deduplicadas. Antes da primeira exibição e em reruns do histórico, são reconferidas contra as páginas salvas no SQLite. Se o texto mudar, fontes incompatíveis são ocultadas. Essa conferência comprova a existência da citação, não a correção da interpretação.

## Histórico, segurança e custos

O histórico fica em `st.session_state`, separado por modo, sem tabela de mensagens. Reiniciar o servidor ou abrir outra sessão perde as mensagens, preservando PDFs, páginas, análises e vetores. Mensagens antigas não alteram a busca; faça perguntas completas.

Perguntas e conteúdo dos PDFs são dados não confiáveis no JSON enviado à geração. Instruções fixas são enviadas separadamente e mandam ignorar comandos documentais. O planejador dispõe somente das duas ferramentas de leitura validadas; a geração final não recebe ferramentas. Não há execução de conteúdo documental. Textos e citações são exibidos sem interpretar HTML ou comandos. Chaves e textos não são registrados em logs.

O banco vetorial é local, mas os trechos ainda não indexados e cada pergunta são enviados ao provedor ativo para gerar embeddings. A primeira busca pode exigir vários lotes; buscas seguintes reutilizam os vetores existentes, mas geram um embedding novo por consulta vetorial. O agente também faz chamadas de decisão e, havendo fontes, uma geração final. Páginas consultadas são enviadas como contexto às decisões seguintes e à geração. Indexação e perguntas podem gerar custos. A disponibilidade depende de conexão, conta e cota. Falhas não são repetidas em reruns.

As perguntas têm até 1.000 caracteres. A geração mantém os limites de 24.000 caracteres no JSON completo, 4.000 tokens de saída, timeout de 60 segundos, sem retentativas automáticas. A OpenAI usa `max_retries=0` e `store=False`; o Gemini usa `HttpRetryOptions(attempts=1)` (uma tentativa total) e sem sessão remota. Caracteres não equivalem a tokens.

## Limitações e testes

A busca semântica pode selecionar recortes inadequados ou omitir evidências. Não garante cobertura de todos os documentos ou respostas exaustivas. Recortes podem separar ressalvas e a extração pode perder tabelas e diagramação. Apenas as primeiras dez páginas extraídas de cada PDF estão disponíveis; não há OCR. Ausência de evidência não comprova ausência de informação no PDF completo. Revisão humana continua necessária.

```bash
python -m pytest tests/test_gemini_service.py tests/test_agent_service.py tests/test_vector_service.py tests/test_chat_service.py tests/test_llm_service.py -q
python -m pytest -q
```

Os testes usam SQLite temporário, Qdrant real em pastas temporárias e embeddings simulados. Chamadas reais à OpenAI e ao Gemini são bloqueadas. São verificados persistência, filtros, atualização e remoção de vetores, ausência de contexto, limites, falhas recuperáveis, bloqueio da pasta, demonstração e validação de fontes. O agente também é testado quanto a reformulação, limites de buscas e ferramentas, consulta de páginas, isolamento da seleção, protocolo de `call_id` e ausência de repetição em reruns. Os vetores simulados verificam a integração; não medem a qualidade semântica de um modelo real.

Para avaliar a qualidade real, configure uma chave e envie perguntas sobre PDFs conhecidos, incluindo sinônimos, números e perguntas sem resposta. Confira as fontes e ajuste o limiar. Essa avaliação manual pode consumir tokens.
