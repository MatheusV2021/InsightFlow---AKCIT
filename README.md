# InsightFlow AI

MVP de inteligência documental empresarial para o hackathon. O sistema reúne PDFs, extrai texto, identifica obrigações e prazos, propõe possíveis riscos e inconsistências, recomenda ações e permite perguntas com fontes verificáveis.

## Problema e solução

Informações de contratos, políticas e manuais ficam dispersas. Conferir prazos e aprovações manualmente exige tempo e pode deixar divergências passar. O InsightFlow AI transforma o texto disponível em achados rastreáveis e indicadores para orientar a revisão humana. Não substitui auditoria ou parecer jurídico.

## Funcionalidades implementadas

- **Documentos:** upload de até três PDFs por operação, até 10 MB cada; validação de extensão, assinatura e abertura; extração das primeiras dez páginas; biblioteca persistente e texto por página.
- **Análises:** seleção de até três documentos; fluxo sequencial Analista → Auditor/Recomendador; prioridade, recomendações e citações verificadas; histórico e filtros por prioridade, categoria e documento.
- **Dashboard:** quatro indicadores, gráficos Plotly por prioridade/categoria, alertas, últimas análises e recomendações. Consultas locais, sem chamadas à IA.
- **Assistente IA:** perguntas explícitas, recuperação lexical sem embeddings, fontes expansíveis e histórico somente durante a sessão. Cada pergunta é independente.
- **Demonstração local:** três PDFs claramente fictícios, análise previsível identificada como simulada e chat extrativo. Nenhuma chamada à API nesse modo.

## Arquitetura e stack

Monólito modular em três camadas, sem API REST interna:

1. **Apresentação:** Streamlit, componentes nativos e Plotly.
2. **Negócios:** funções Python nos serviços de documentos, PDF, análise, demonstração, dashboard, chat e integração com IA.
3. **Dados:** SQLite com `sqlite3` nativo e PDFs locais em `uploads/`.

A apresentação chama os serviços diretamente; queries ficam no repositório. Configurações e caminhos usam `config.py` e `pathlib`. A navegação usa somente `st.navigation` com quatro páginas.

Stack: Python 3.11+, Streamlit, SQLite, PyMuPDF, SDK oficial OpenAI, Pydantic, python-dotenv, Plotly e pytest. Dependências diretas fixadas em `requirements.txt`; nenhuma dependência nova foi necessária para gerar os exemplos.

## Organização

```text
insightflow-ai/
├── app.py
├── config.py
├── .streamlit/config.toml
├── pages/                  # dashboard.py, documents.py, analyses.py, assistant.py
├── services/               # regras e integrações Python
│   ├── document_service.py
│   ├── pdf_service.py
│   ├── analysis_service.py
│   ├── demo_service.py
│   ├── llm_service.py
│   ├── dashboard_service.py
│   └── chat_service.py
├── database/               # db.py, repository.py; banco criado automaticamente
├── models/schemas.py
├── uploads/                # PDFs recebidos, fora do Git
├── scripts/create_sample_pdfs.py
├── output/pdf/             # exemplos gerados, fora do Git
├── tests/
├── docs/                   # arquitetura, agentes, processamento, chat, demo e negócio
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Requisitos

Python 3.11 ou superior, acesso de escrita à pasta do projeto e um ambiente virtual. Validação local feita no Windows com Python 3.13. Internet e chave OpenAI são necessárias somente para novas análises e respostas geradas no modo normal. O modo demonstração funciona sem chave e sem rede após instalar as dependências.

## Instalação no Windows PowerShell

Na raiz do repositório, com Python 3.13 instalado:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/create_sample_pdfs.py
python -m streamlit run app.py
```

Se a ativação for bloqueada pela política do PowerShell, use diretamente o executável do ambiente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/create_sample_pdfs.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Instalação no Linux

Com Python 3.11+ e `venv` disponíveis:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python scripts/create_sample_pdfs.py
python -m streamlit run app.py
```

Abra o endereço exibido pelo Streamlit, normalmente `http://localhost:8501`. Encerre com `Ctrl+C`.

## Configuração do .env e modos

O arquivo de exemplo vem preparado para demonstração:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
DEMO_MODE=true
```

- **`DEMO_MODE=true`:** bloqueia a API no cliente compartilhado; análises usam regras locais somente sobre os PDFs fictícios originais. A interface identifica a simulação, inclusive no dashboard. O chat mostra trechos encontrados localmente, sem gerar interpretações por IA.
- **`DEMO_MODE=false`:** habilita o fluxo real da OpenAI. A lista, os indicadores e as consultas de análises excluem resultados simulados. Não há achados predefinidos nesse fluxo.
- **`OPENAI_API_KEY`:** obrigatória para gerar resultados com IA no modo normal; nunca é necessária para abrir a interface, fazer uploads ou consultar resultados existentes.
- **`OPENAI_MODEL`:** modelo com suporte à API Responses e saídas estruturadas. O exemplo usa `gpt-4.1-mini`; disponibilidade e cota dependem da conta.

Sem `.env` ou variável de ambiente, `DEMO_MODE` assume **false**. Copiar o `.env.example` ativa a demonstração. Variáveis do processo têm prioridade sobre o arquivo. Após alterar o modo, reinicie a aplicação. O histórico do chat é separado por modo e não é persistido no banco.

Análises têm a marca persistente `is_demo`. A migração automática do esquema para a versão 4 preserva os dados anteriores e classifica análises antigas como reais, pois o antigo modo demonstração era apenas visual. Nenhum resultado antigo é convertido em simulação. A biblioteca de documentos é compartilhada entre os modos; os exemplos continuam claramente nomeados como fictícios.

## Gerar e usar os PDFs fictícios

```bash
python scripts/create_sample_pdfs.py
```

São criados em `output/pdf/`:

1. `FICTICIO_01_contrato_fornecedor.pdf`: pagamento em dez dias, multa de 2%, obrigações e exigência de autorização financeira.
2. `FICTICIO_02_politica_financeira.pdf`: padrão de trinta dias, aprovação prévia e procedimento de exceção escrita.
3. `FICTICIO_03_manual_operacional.pdf`: aprovação antes da compra, responsabilidades operacionais e documentação.

É possível definir outra pasta com `--output-dir CAMINHO`. O gerador não cadastra PDFs nem análises automaticamente. Em Documentos, envie os três arquivos; em Análises, selecione uma cópia de cada e clique em **Analisar documentos**.

Com esses três PDFs, a análise simulada produz quatro achados: prazo de dez dias, possível exposição à multa, possível divergência de prazos e obrigação de formalizar aprovação. Em uma biblioteca nova, o dashboard mostra **3 documentos, 1 análise, 2 riscos e 1 risco de alta prioridade**. As mesmas entradas reutilizam o resultado salvo. Novos uploads geram outros registros e podem aumentar as contagens históricas.

O exemplo admite exceções autorizadas e não demonstra atraso nem infração efetiva. O modo simulado valida todo o texto esperado, não apenas o nome do PDF. Arquivos editados, não reconhecidos ou cópias repetidas do mesmo exemplo na seleção são recusados, sem chamar a IA. Use o modo normal para outros documentos.

## Indicadores e interpretação

- **Documentos cadastrados:** todos os PDFs persistidos na biblioteca compartilhada, inclusive parciais ou sem texto.
- **Análises realizadas:** resultados salvos apenas do modo atual, inclusive análises sem achados.
- **Riscos identificados:** achados `risk` e `inconsistency` do modo atual, com citações reconferidas. Obrigações e prazos isolados não entram.
- **Riscos de alta prioridade:** subconjunto anterior com prioridade `high`.

Cada achado conta uma vez por análise, mesmo com várias evidências. Uma questão recorrente pode ser contada em análises diferentes; não há deduplicação semântica ou controle de resolução. Gráficos usam a mesma população. Alertas destacam até cinco riscos de prioridade alta e recomendações mostram até cinco ações por prioridade e recência.

Alta prioridade representa impacto potencial grave ou urgência justificada; média, revisão relevante; baixa, atenção preventiva. No modo simulado, as classificações são predefinidas para o roteiro. No modo normal, são propostas pelo modelo. Citação conferida comprova a existência do trecho, não a correção da interpretação ou uma violação contratual.

## Limites de processamento e custos

- Upload: PDF, máximo de 10 × 1024 × 1024 bytes por arquivo, três arquivos por operação e dez páginas extraídas por PDF. Sem OCR e sem senha.
- Análise real: até três documentos, 16.000 caracteres de origem divididos entre eles, até duas chamadas sequenciais, sem retentativas automáticas.
- Chat real: pergunta de até 1.000 caracteres, até seis trechos e 10.000 caracteres de origem, uma chamada quando houver contexto relevante. Sem contexto, retorna evidência insuficiente sem chamar a API.
- Cliente compartilhado: até 24.000 caracteres por carga JSON, até 4.000 tokens de saída por chamada, timeout de sessenta segundos e `store=False`.
- Demonstração: zero chamadas à API; resultados locais claramente identificados.

O histórico do chat é visual, somente na sessão, sem envio das mensagens anteriores ao modelo. Cada pergunta deve ser completa. Reenviar perguntas no modo normal pode gerar novo custo. Consultar, filtrar e renderizar resultados não chama a IA.

## Testes e verificações

Com o ambiente virtual ativado:

```bash
python -m pytest -q
python -m compileall -q app.py config.py pages services database models scripts tests
python -m pip check
```

Os testes bloqueiam o cliente OpenAI real por uma fixture automática. PDFs, PyMuPDF e SQLite são reais em pastas temporárias; respostas e falhas da API são simuladas. Cobertura inclui banco, migração, uploads válidos/inválidos, extração, persistência, evidências, erros, filtros, gráficos, chat, reruns, análise demonstrativa e isolamento entre modos.

O fluxo demonstrativo é exercitado pelo `AppTest` do Streamlit, inclusive recuperação em uma nova sessão. Os PDFs gerados foram renderizados e inspecionados visualmente. Integração com uma conta OpenAI e qualidade dos resultados reais exigem validação com chave; os testes não consomem créditos. A instalação Linux está documentada, mas não foi executada neste ambiente Windows.

## Segurança e armazenamento

SQL parametrizado; arquivos recebidos salvos com UUID; credenciais somente no ambiente ou `.env`; sem logs de conteúdo ou chaves. PDFs, SQLite, `.env`, saídas geradas e arquivos temporários ficam fora do Git. O esquema é inicializado automaticamente. Preserve `database/insightflow.db` e `uploads/` para manter a biblioteca e os resultados.

Textos de PDFs são tratados como dados não confiáveis, sem ferramentas executáveis para o modelo. Citações são validadas por documento, nome, página e trecho literal; respostas do chat sem fontes verificáveis são ocultadas. As interpretações ainda podem conter erros.

## Limitações e pendências

Sem autenticação, OCR, edição de PDF, embeddings, pesquisa externa, filas ou execução paralela. Busca lexical perde sinônimos e contexto; recortes e extração simples podem perder diagramação e condições relevantes. Ausência de achados não garante ausência de riscos. Não há transação única entre sistema de arquivos e SQLite: uma interrupção abrupta durante o upload pode deixar um arquivo órfão. O dashboard agrega todo o histórico do modo atual e não acompanha resolução de riscos. A conversa não sobrevive a uma nova sessão.

Não foram aferidas precisão jurídica, escala empresarial, disponibilidade da API real ou execução no Linux. O MVP é uma ferramenta de apoio à revisão humana.

## Documentação complementar

- [Arquitetura](docs/architecture.md)
- [Fluxo dos agentes](docs/agent-flow.md)
- [Processamento de PDFs](docs/document-processing.md)
- [Chat e busca lexical](docs/chat.md)
- [Roteiro de demonstração de três minutos](docs/demo.md)
- [Proposta de negócio](docs/business.md)
