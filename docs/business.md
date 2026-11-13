# Proposta de negócio do InsightFlow AI

## Problema

Contratos, políticas e manuais registram condições em lugares diferentes. Equipes pequenas gastam tempo procurando prazos, conferindo aprovações e comparando regras. Uma leitura apressada pode tanto deixar riscos passar quanto tratar uma exceção autorizada como infração.

## Público-alvo

Pequenas e médias empresas e equipes de compras, financeiro, operações e conformidade que precisam fazer uma triagem inicial de documentos. O MVP foi pensado para uso local e demonstração, sem recursos para uma operação corporativa multiusuário.

## Proposta de valor

Reunir texto, obrigações, prazos, possíveis riscos, recomendações e perguntas em um fluxo simples. Cada achado aponta documento, página e citação para facilitar a revisão. O dashboard ajuda a priorizar a leitura, sem substituir julgamento profissional.

## Diferencial proposto

Rastreabilidade dos achados, citações conferidas deterministicamente e transparência sobre recortes, simulação e limites. A comparação procura contextualizar regras e exceções antes de sugerir revisão. Esses são diferenciais de produto propostos; não há estudo competitivo ou ganho de produtividade medido que demonstre superioridade frente a soluções existentes.

## Modelo de receita proposto

Hipótese inicial: assinatura por equipe, com franquia de documentos ou análises e cobrança adicional por uso. Uma oferta de implantação poderia adaptar critérios e vocabulário ao processo do cliente. Valores, disposição a pagar e custos unitários ainda precisam ser validados; nenhuma cobrança ou plano comercial foi implementado.

## Limitações atuais

Aplicação local, sem autenticação, permissões, colaboração ou controle de resolução de riscos. Limites de tamanho, páginas e contexto. Sem OCR; a busca semântica pode omitir conteúdo ou selecionar trechos inadequados. O índice Qdrant local suporta um único processo por pasta e a geração de embeddings depende do provedor ativo (Gemini ou OpenAI) no modo normal. A interpretação da IA pode falhar mesmo com citações existentes. O modo normal depende da API externa, da cota e da conexão. A demonstração é predefinida e não serve como prova de precisão.

## Próximas evoluções sugeridas

1. Avaliar respostas com documentos autorizados e revisão de especialistas, medindo erros e cobertura.
2. Validar a utilidade com equipes de compras e financeiro antes de ampliar funcionalidades.
3. Medir custo e tempo por análise e melhorar a seleção de contexto conforme os resultados.
4. Investigar OCR e critérios de relevância somente se forem necessários aos casos reais.
5. Antes de uso corporativo compartilhado, definir segurança, controle de acesso, retenção e operação adequada.

Essas evoluções são propostas de trabalho futuro e não funcionalidades entregues pelo MVP.
