# Fluxo dos agentes e modos de execução

Os agentes são funções especializadas no monólito Python. Não há execução paralela, filas ou autonomia. Uma análise começa somente após a ação explícita do usuário.

## Entradas e preparação

1. O usuário envia até três PDFs por operação. Extensão, assinatura, tamanho e abertura são validados.
2. PyMuPDF extrai até dez páginas, sem OCR. O banco preserva texto e número original de cada página.
3. O usuário seleciona de um a três documentos diferentes e clica em **Analisar documentos**.
4. `prepare_sources` exige texto suficiente, distribui até 16.000 caracteres de origem entre os documentos e gera avisos sobre recortes e páginas indisponíveis.
5. O serviço procura uma análise salva da mesma entrada, modo, modelo e versão. Um resultado existente é reutilizado sem novas chamadas.

## Modo normal: DEMO_MODE=false

### Analista - chamada 1 à IA

`run_analyst` usa a API Responses para extrair até vinte fatos, obrigações e prazos com evidências. Não calcula datas ausentes nem presume descumprimento. O retorno é validado por `AnalystOutput`.

A checagem local elimina fatos cujas citações não correspondam aos trechos enviados. Se nenhum fato permanecer, uma análise vazia é salva sem a segunda chamada.

### Auditor e Recomendador - chamada 2 combinada

`run_auditor_and_recommender` recebe somente fatos com citações conferidas. Compara documentos relacionados, avalia possíveis riscos e sugere ações. Uma inconsistência precisa ter evidências de pelo menos dois documentos distintos.

O modelo propõe categoria (`obligation`, `deadline`, `risk`, `inconsistency`) e prioridade (`low`, `medium`, `high`). Alta indica impacto potencial grave ou urgência justificada; média, revisão relevante; baixa, atenção preventiva. Setor responsável só deve ser sugerido quando houver fundamento. A ausência de comprovante não demonstra automaticamente atraso ou infração.

## Modo demonstração: DEMO_MODE=true

Nenhuma etapa chama o modelo. `build_demo_findings` identifica o texto integral dos PDFs fictícios gerados por `scripts/create_sample_pdfs.py`, desconsiderando apenas diferenças de espaços e quebras de linha na identificação. O nome do arquivo sozinho não basta. Arquivos diferentes ou alterados e duas cópias do mesmo exemplo na seleção são recusados.

Regras determinísticas produzem até quatro achados conforme os exemplos selecionados. Com os três exemplos: prazo de dez dias, possível exposição a multa, possível divergência de dez versus trinta dias e obrigação de formalizar aprovação. O cenário ressalva que a política admite exceção escrita e que não há prova de atraso ou falta efetiva de aprovação.

Os achados locais passam pela mesma validação literal das evidências. Se uma citação não puder ser conferida, a demonstração falha com mensagem, sem fabricar evidências ou usar a API. O cliente compartilhado também bloqueia chamadas diretas nesse modo.

A análise recebe `is_demo=True`, modelo `demo-local-v1` e aviso de simulação. O modo normal não a apresenta na lista, na recuperação por ID ou nos indicadores. Os dois modos preservam seus históricos no SQLite sem converter resultados reais em fictícios.

## Validação e saídas - processamento determinístico

`evidence_matches` exige documento, nome e página correspondentes, citação não vazia e trecho literal existente em uma das fontes enviadas. A normalização usada para identificar PDFs fictícios não é usada para aprovar citações. O Auditor real só pode reutilizar citações válidas dos fatos extraídos.

Um achado com qualquer evidência inválida é descartado integralmente. Possíveis inconsistências sem duas fontes distintas também são descartadas. A contagem descartada e os avisos são salvos; o resumo não inclui propostas sem fonte válida.

Os IDs são gerados localmente. `prioritize_findings` ordena prioridades e `summarize_findings` calcula quantidades a partir dos achados aceitos. Cada resultado contém resumo, avisos, achados, recomendações e fontes com documento e página. Ao recuperá-lo, as citações são reconferidas; achados incompatíveis com o texto atual são ocultados.

Existência literal não prova correção da interpretação, violação contratual ou completude. Recomendações apoiam a revisão humana e não são executadas automaticamente nem enviadas a terceiros.

## Persistência e dashboard

Análise, associações, achados e evidências são gravados em uma única transação. O campo `is_demo` diferencia a origem. A versão 4 do banco preserva dados anteriores como reais.

O dashboard consulta apenas análises do modo atual e conta possíveis riscos e inconsistências uma vez por achado, independentemente do número de fontes. Pode haver a mesma questão em várias análises históricas. A contagem de documentos considera a biblioteca compartilhada. Alertas e recomendações vêm dos achados persistidos; não são gerados para preencher a tela.

## Chat

O fluxo do assistente é independente da análise: busca lexical, seleção de trechos, resposta e validação de fontes. No modo normal, faz até uma chamada por pergunta com contexto relevante. Sem contexto, responde localmente sobre evidência insuficiente. Na demonstração, mostra trechos locais identificados, sem interpretação gerada por IA. O histórico é de sessão e separado por modo. Detalhes em [chat.md](chat.md).

## Custos, erros e limites

No modo normal há até duas chamadas sequenciais por análise nova, com até 24.000 caracteres por carga JSON e 4.000 tokens de saída por chamada, além de instruções e schemas fixos. Timeout de sessenta segundos e nenhuma retentativa automática. No modo demonstrativo, o número de chamadas é zero.

Chave ausente/rejeitada, conexão, cota, recusa, resposta incompleta, estrutura inválida, documentos ausentes e falhas de armazenamento geram mensagens sem stack traces ou conteúdo bruto. Os testes usam mocks e bloqueiam o cliente real por padrão.

Não há OCR, pesquisa externa ou validação semântica automática. Contexto recortado ou fatos omitidos pelo Analista podem reduzir a cobertura. A simulação comprova o fluxo local e a rastreabilidade, não a qualidade da IA em documentos reais.
