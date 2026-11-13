# Assistente documental — etapa 5

## Funcionamento

O Assistente IA responde a perguntas sobre os textos já extraídos dos PDFs. Não depende de análises prévias, embeddings, banco vetorial, frameworks de agentes ou novos serviços externos. Usa o SQLite e o mesmo cliente OpenAI das análises.

1. O usuário seleciona os documentos e envia uma pergunta por `st.chat_input`.
2. `chat_service.py` valida a pergunta e os IDs selecionados.
3. O repositório recupera somente as páginas desses documentos, com ID, nome original e número da página.
4. Uma busca lexical local escolhe trechos relevantes dentro do orçamento de contexto.
5. Havendo contexto, uma chamada à API Responses solicita afirmações estruturadas com suas evidências. Sem contexto, o serviço responde sobre a insuficiência de evidências sem chamar a API.
6. A aplicação valida todas as fontes antes de exibir a resposta com `st.chat_message`.
7. Perguntas, respostas e fontes ficam no histórico da sessão. Reruns apenas renderizam o histórico; não refazem a consulta à IA.

As perguntas sugeridas são exemplos estáticos para copiar. Selecionar documentos, abrir a página ou expandir fontes não envia uma pergunta.

## Recuperação lexical

São usadas as páginas persistidas em `document_pages`; o PDF não é aberto novamente. As restrições anteriores continuam: no máximo dez páginas extraídas de cada PDF e ausência de OCR. Documentos parciais ou sem texto geram avisos de cobertura.

Para a busca, o texto é normalizado em caixa baixa, sem acentos e com redução simples de plurais (`contratos` → `contrato`, `obrigações` → `obrigacao`). Palavras frequentes como “quais”, “de” e “para” são ignoradas. Não há dicionário de sinônimos, modelo linguístico ou lematização completa.

Cada página é dividida em trechos de até **1.800 caracteres**, com **200 caracteres de sobreposição**. A ordem de relevância é:

1. Maior quantidade de termos distintos da pergunta presentes no trecho.
2. Maior soma das frequências desses termos, limitada a três ocorrências por termo para reduzir repetição artificial.
3. ID do documento em ordem crescente, número da página e posição inicial no texto.

O desempate é determinístico para os mesmos dados, independentemente da ordem da seleção ou dos termos da pergunta. São enviados até **seis trechos**, com um total máximo de **10.000 caracteres de origem**. O último trecho pode ser cortado; se perder os termos relevantes, é omitido. Recortes adicionais geram aviso.

As citações usam o texto original, nunca a versão normalizada da busca. Um trecho pode ser escolhido por um termo relacionado, mas a escolha não garante relevância semântica.

## Resposta e validação de fontes

O SDK oficial usa `responses.parse` com `ChatModelOutput`, validado por Pydantic. O modelo indica se há evidência suficiente e retorna até seis afirmações. Cada uma pode ter até quatro evidências, contendo `document_id`, `filename`, `page_number` e `quote` literal de até 600 caracteres.

Não há um parágrafo livre adicional sem referências. Para cada afirmação, a aplicação exige ao menos uma evidência e confere:

- Documento selecionado e realmente enviado no contexto.
- Nome original correspondente.
- Página correspondente.
- Trecho literal contínuo existente em um dos recortes enviados daquela página.

Se qualquer afirmação tiver fonte ausente, inválida ou não enviada, **a resposta proposta inteira é ocultada**, inclusive suas fontes, e aparece uma mensagem determinística de evidência insuficiente. O mesmo ocorre se o modelo declarar insuficiência ou retornar uma lista vazia. Não há nova chamada automática para reparar citações.

A aplicação numera as fontes como `[1]`, `[2]` etc., associando-as às afirmações. Referências idênticas são deduplicadas. No expansor **Fontes verificadas**, o usuário consulta nome, página, ID e trecho literal. Antes da primeira exibição e em reruns do histórico, as fontes são reconferidas contra o SQLite; se a origem não corresponder mais, a resposta é ocultada sem chamar o modelo.

Correspondência literal confirma a existência do trecho, **não comprova que a interpretação ou a conclusão seja correta**. O assistente deve preservar condições e não inferir descumprimento apenas pela ausência de um comprovante. A revisão humana continua necessária.

## Histórico da conversa

O histórico vive somente em `st.session_state`. Não há tabela de mensagens e nenhuma mudança no esquema do banco. Navegar entre páginas mantém o histórico na mesma sessão. Reiniciar o servidor ou abrir uma nova sessão perde as mensagens, preservando PDFs, páginas e análises.

Cada pergunta é independente: mensagens anteriores não são enviadas à API e não alteram a busca. Use perguntas completas; “e aquele contrato?” pode não recuperar o contexto desejado. Mudar os documentos selecionados afeta as próximas perguntas, sem reaproveitar fontes da seleção anterior. Respostas antigas permanecem com suas referências originais e são reconferidas ao renderizar.

Erros de conexão, cota, chave, estrutura ou armazenamento aparecem como mensagens no histórico; não são repetidos em reruns. Para tentar novamente, o usuário deve reenviar a pergunta explicitamente.

## Segurança e custos

A pergunta e os trechos são dados não confiáveis dentro de uma carga JSON. As instruções fixas são enviadas separadamente e mandam ignorar comandos contidos nos PDFs. Não há ferramentas disponibilizadas ao modelo ou execução de conteúdo. Perguntas, respostas e citações são exibidas como texto, sem interpretar HTML, links ou comandos do documento. A aplicação não registra chaves nem conteúdo em logs.

São permitidos até **1.000 caracteres por pergunta**, até **10.000 caracteres de trechos** e **uma chamada por pergunta com contexto relevante**. O cliente compartilhado também limita a carga JSON completa a **24.000 caracteres**, a saída a **4.000 tokens**, o timeout a **60 segundos** e usa `max_retries=0` e `store=False`. Instruções e schema fixos também compõem a entrada da API. Caracteres não equivalem a tokens; o custo depende do modelo e do uso real.

`OPENAI_API_KEY` e `OPENAI_MODEL` vêm da configuração existente. No modo normal (`DEMO_MODE=false`), uma resposta gerada exige chave; reenviar a pergunta com contexto relevante pode consumir tokens novamente, sem cache. Nenhuma consulta é automática.

Na demonstração (`DEMO_MODE=true`), a API é bloqueada. O chat retorna até três trechos literais recuperados localmente, identificados como demonstração sem geração por IA. Não tenta produzir uma interpretação do documento. As fontes passam pela validação e o histórico é separado do modo normal. A consulta extrativa pode usar qualquer texto armazenado; a análise predefinida da página Análises aceita somente os PDFs fictícios originais. Veja [o roteiro](demo.md).

O histórico não é enviado à OpenAI, mas a pergunta atual e seus trechos são enviados quando o usuário a submete. A disponibilidade da API, a cota e a compatibilidade do modelo dependem da conta. Falhas são apresentadas sem stack traces ou corpos brutos da API.

## Limitações

- Sinônimos, pronomes e grafias diferentes podem não produzir correspondências.
- Plurais são tratados por regras simples, sem compreensão linguística completa.
- Termos frequentes podem selecionar trechos pouco úteis, e vários trechos de um documento podem ocupar o contexto.
- A busca não garante cobertura de todos os documentos nem respostas exaustivas para perguntas como “quais contratos”.
- Recortes podem separar condições importantes; tabelas e diagramação podem perder estrutura na extração.
- PDFs digitalizados sem texto, páginas além do limite inicial e trechos não recuperados não fazem parte da resposta.
- Não encontrar evidência não comprova ausência de informação ou de obrigação no PDF completo.
- Não há pesquisa externa, execução de instruções documentais ou verificação automática da correção semântica das afirmações.

## Exemplos de perguntas

- “Quais contratos possuem prazos de pagamento?”
- “Qual é o prazo de entrega previsto no contrato Alfa?”
- “Quais obrigações de confidencialidade são mencionadas?”
- “O texto menciona multa por atraso?”

Adapte os termos aos documentos e confira os recortes antes de tomar decisões.

## Como testar

Com o ambiente virtual ativado:

```bash
python -m pytest tests/test_chat_service.py -q
python -m pytest -q
```

Os testes usam PDFs sintéticos e SQLite temporário. O cliente real é bloqueado por uma fixture automática; respostas e falhas da API são simuladas, sem consumo de tokens. São verificados busca, desempates, limites, seleção vazia ou inexistente, ausência de evidências, fontes inválidas, múltiplos recortes da mesma página, falha de conexão, fontes do histórico e duas perguntas na mesma sessão sem repetição em reruns.

Para validar com a API real, configure a chave, execute `python -m streamlit run app.py`, envie PDFs, selecione-os no Assistente IA e faça duas perguntas completas. Confira as fontes expansíveis. Essa validação manual pode gerar custos.
