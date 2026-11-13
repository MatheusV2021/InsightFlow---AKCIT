# Demonstração do hackathon - três minutos

## Preparação antes de apresentar

1. Instale as dependências e copie `.env.example` para `.env`.
2. Confirme `DEMO_MODE=true`. A chave pode ficar vazia. Variáveis do processo têm prioridade sobre o arquivo; reinicie após trocar o modo.
3. Execute `python scripts/create_sample_pdfs.py` e `python -m streamlit run app.py`.
4. Abra a aplicação e confirme o aviso **MODO DEMONSTRAÇÃO**. Não é necessário acesso à OpenAI.
5. Deixe os três arquivos de `output/pdf/` acessíveis. Não importe cópias repetidas para a mesma seleção.

O gerador não cadastra dados automaticamente. A apresentação usa uploads e análise acionados pelo usuário. Se a biblioteca já tiver envios, o total de documentos e o histórico podem ser maiores que os números abaixo.

## Roteiro cronometrado

| Tempo | Ação | Mensagem principal |
| --- | --- | --- |
| 0:00-0:20 | Mostrar o cabeçalho e o aviso de simulação. | “Informações dispersas em contratos e políticas dificultam decisões. Esta é uma demonstração local, fictícia e sem chamadas à IA.” |
| 0:20-0:55 | Em Documentos, enviar os três PDFs e processar. Abrir uma página. | “O texto é extraído por página e persistido. Todos os exemplos são identificados como fictícios.” |
| 0:55-1:40 | Em Análises, selecionar os três e clicar em analisar. Abrir a possível divergência. | “O contrato prevê dez dias; a política estabelece trinta, mas admite exceções autorizadas. O sistema recomenda confirmar a aprovação, sem afirmar infração.” |
| 1:40-2:15 | Mostrar recomendação, evidências e um filtro. Ir ao Dashboard. | “Em uma biblioteca nova: três documentos, uma análise, dois possíveis riscos e um de prioridade alta. São indicadores do SQLite, neste modo derivados de uma simulação explícita.” |
| 2:15-2:45 | No Assistente IA, selecionar os PDFs e perguntar “Qual o prazo de pagamento?”. Abrir fontes. | “Na demonstração, o chat apenas recupera trechos locais, sem IA. No modo normal, o mesmo contexto fundamenta uma resposta gerada pela OpenAI.” |
| 2:45-3:00 | Encerrar com valor, limites e evolução. | “A proposta é reduzir o trabalho de triagem com rastreabilidade. A revisão humana continua necessária; o fluxo real depende de chave e validação da qualidade.” |

## Resultados previsíveis com os três exemplos

- Prazo contratual de dez dias: categoria prazo, prioridade baixa.
- Possível exposição a multa: risco, prioridade alta; não afirma atraso ocorrido.
- Possível divergência entre padrão e prazo negociado: inconsistência, prioridade média; considera exceção escrita.
- Formalizar aprovação e documentação: obrigação, prioridade média.

Os dois últimos documentos descrevem responsabilidades e aprovações, mas não comprovam sua falta em um caso real. Todas as citações correspondem aos PDFs gerados. A análise simulada usa regras locais, não avalia a qualidade da OpenAI.

## Persistência e plano de contingência

Após salvar a análise, reiniciar a aplicação mantém documentos, achados e gráficos. Consultar novamente ou analisar a mesma entrada reutiliza o resultado. O histórico do chat é apenas de sessão e será perdido em nova sessão.

Se os exemplos forem recusados, gere-os novamente e envie os arquivos originais. Nome correto sem conteúdo correspondente não é suficiente. Não é necessário configurar uma chave para resolver a demonstração. Caso já existam análises, consulte a simulação salva no modo demonstrativo; não apresente contagens históricas como se fossem somente uma execução.

Para o fluxo real, use `DEMO_MODE=false`, configure a chave e reinicie. Resultados simulados deixam de aparecer nas consultas e no dashboard. Essa opção pode gerar custos e exige internet; não é necessária para o roteiro de três minutos.
