# Processamento de documentos — etapa 2

## Fluxo de upload

1. A inicialização prepara `uploads/` e o SQLite, preservando dados existentes.
2. Em Documentos, o usuário seleciona até três PDFs e clica em **Processar documentos**.
3. A apresentação envia nome e bytes aos serviços Python diretamente.
4. Cada arquivo é validado e aberto pelo PyMuPDF, com extração de texto das primeiras dez páginas.
5. O serviço gera um UUID, salva o original e insere os metadados e páginas em uma transação SQLite.
6. A interface exibe sucesso ou erro por arquivo e lista os registros salvos. O texto é consultado por documento e exibido em expansores numerados por página.

Erros de um arquivo não impedem o processamento dos demais. Arquivos inválidos não são armazenados nem geram registros de documento. PDFs válidos sem texto são armazenados e recebem aviso específico.

## Validações

- Extensão `.pdf`, sem diferenciar maiúsculas e minúsculas.
- Tamanho maior que zero e máximo de 10 MB (10 × 1024 × 1024 bytes), inclusive.
- Assinatura `%PDF-` no início do arquivo.
- Abertura válida pelo PyMuPDF, com pelo menos uma página.
- PDFs que exigem senha são rejeitados; não há formulário de senha.
- Uma operação deve conter de um a três documentos. A validação existe na interface e no serviço de lote.

O seletor nativo limita extensão e tamanho para orientar o usuário, mas as validações são repetidas no serviço. O nome original é reduzido ao nome do arquivo; nunca é usado como caminho de armazenamento.

## Extração de texto

`pdf_service.extract_pdf_text` abre os bytes com `pymupdf.open`, verifica o documento e usa `get_text("text", sort=True)` por página. O contexto `with` fecha o documento também em falhas. O resultado validado por Pydantic contém `total_pages` e uma lista de páginas com `page_number` (iniciando em 1) e `extracted_text`.

Páginas sem texto permanecem na lista com texto vazio, mantendo a numeração original. Se nenhuma das páginas processadas contiver texto não vazio, o documento recebe status `no_text`. Esse resultado não permite concluir se existem textos nas páginas além do limite.

Status persistidos:

| Valor | Interface | Significado |
| --- | --- | --- |
| `processed` | Processado | Todas as páginas foram lidas e há algum texto extraível. |
| `partial` | Parcial | Foram lidas apenas as dez primeiras páginas e há algum texto extraível. |
| `no_text` | Sem texto extraível | Nenhuma página processada forneceu texto. |

O processamento parcial é também calculado por `processed_pages < total_pages` e mostrado separadamente. Assim, um PDF longo sem texto apresenta ambos os avisos. **Páginas processadas** significa páginas lidas, inclusive as vazias.

## Armazenamento e consistência

- `uploads/<uuid>.pdf`: bytes originais do PDF, com criação exclusiva para evitar sobrescrita.
- `database/insightflow.db`: banco SQLite local.
- `documents`: `id` (UUID textual), `original_filename`, `stored_filename`, `uploaded_at` (ISO 8601 em UTC), `total_pages`, `processed_pages` e `status`.
- `document_pages`: `id` inteiro, `document_id` com chave estrangeira, `page_number` e `extracted_text`; documento e número da página são únicos em conjunto.
- `app_metadata`: versão do esquema. A inicialização atualiza versões anteriores para 4 sem apagar metadados ou documentos; a etapa 6 acrescenta a identificação das análises simuladas.

Metadados e páginas compartilham a mesma transação. Em falhas normais de escrita ou persistência, o serviço desfaz a transação e remove o arquivo recém-criado. Não há transação distribuída entre sistema de arquivos e SQLite: encerramento abrupto do processo entre salvar o PDF e confirmar o banco pode deixar um arquivo órfão. Não há rotina automática de recuperação nesta etapa.

A listagem e o texto são lidos do banco em novas conexões. Reiniciar a aplicação não remove dados; mantenha tanto o banco quanto `uploads/`. A interface apresenta datas em UTC-3. O upload e a extração não fazem chamadas externas nem registram conteúdo em logs; PDFs e SQLite continuam ignorados pelo Git. A análise explícita na área Análises envia trechos à OpenAI, conforme o [fluxo dos agentes](agent-flow.md).

## Reruns do Streamlit

O processamento ocorre somente dentro da ação do botão. Após concluir a operação, os resultados ficam em `st.session_state`, a chave do seletor de upload muda e um rerun limpa a seleção. Consultar páginas, mudar de tela ou executar outro rerun não repete extração ou gravação. Resultados da última operação permanecem visíveis na sessão; a lista persistente funciona também em uma nova sessão.

Selecionar e enviar novamente o mesmo PDF de propósito cria outro documento. Não há deduplicação global por conteúdo, processamento em segundo plano ou fila.

## Limitações

Sem OCR, edição de PDF, IA, análise de riscos ou chat. PDFs digitalizados podem não fornecer texto. Tabelas, colunas e elementos visuais podem perder a diagramação na extração de texto simples. O processamento é síncrono e limitado às dez primeiras páginas de cada PDF.

## Como testar

Com o ambiente virtual ativado, na raiz:

```bash
python -m pytest -q
python -m compileall -q app.py config.py pages services database models tests
python -m pip check
```

Os testes geram PDFs sintéticos em memória e armazenam os resultados em pastas temporárias. Cobrem validação, páginas e texto, PDFs sem texto e com senha, limites, upgrade do banco, rollback e limpeza após falha. `AppTest` exercita processamento pelo botão, visualização, reinício da sessão e reruns sem duplicação. O seletor de arquivos é simulado nos testes de interface; PyMuPDF, arquivos e SQLite são reais.

Verificação manual: execute `python -m streamlit run app.py`, envie um PDF de texto e um digitalizado, processe e confira os avisos e expansores. Envie um PDF com mais de dez páginas para conferir o aviso parcial. Pare com `Ctrl+C`, execute novamente e verifique que a listagem e os textos permanecem disponíveis.
