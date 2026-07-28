# Histórico do protótipo do relatório de apoio à revisão humana

> Este documento registra a etapa manual que antecedeu a criação dos scripts do
> protótipo. Ele não é o guia operacional vigente. Para executar o fluxo atual,
> consulte o [`README.md` principal](../README.md). Os outputs deste diretório estão
> arquivados e não devem ser usados como destino de novas execuções.

Esta etapa reuniu os artefatos usados para **materializar a proposta de relatório de
apoio à revisão manual de crédito e validar, com o usuário, a utilidade do documento
gerado**.

A intenção do protótipo é tornar concreta a evolução descrita na arquitetura: em vez
de avaliar apenas uma descrição abstrata do agente, é possível examinar um relatório
completo, verificar se ele reúne as informações necessárias e decidir se realmente
reduz o trabalho de investigação do analista.

O resultado não busca apenas encurtar a leitura. Ele concentra no mesmo documento a
explicação contextualizada do caso, as evidências que a sustentam, as limitações da
explicação e os dados técnicos necessários para conferência. Assim, a utilidade pode
ser avaliada em termos de compreensão, confiança, verificabilidade e redução de
consultas a outras fontes.

## Fluxo materializado

```text
resposta da API + catálogo de features
                  │
                  ▼
       contexto governado pelo agente
                  │
                  ▼
          prompt estruturado do LLM
                  │
                  ▼
          conteúdo narrativo do LLM
                  │
                  ▼
 agente valida a narrativa e a reassocia aos dados controlados
                  │
                  ▼
          JSON consolidado do relatório
                  │
                  ▼
        template HTML/Jinja → PDF
```

Os dados utilizados na demonstração tiveram como origem:

- [`sample_api_response_with_explanation.json`](../sample_api_response_with_explanation.json):
  resposta técnica da API contendo score, política e objeto de explicação;
- [`../config/feature_catalog.json`](../../config/feature_catalog.json): catálogo com a
  semântica, as regras de interpretação e as restrições de uso das features;
- [`sample_agent_context_before_llm.json`](sample_agent_context_before_llm.json):
  contexto preparado pelo agente antes da chamada ao LLM, produzido pela associação
  entre a resposta da API e o catálogo e pela exclusão das evidências não autorizadas.

## Artefatos produzidos nesta etapa

Na etapa registrada por este documento, `sample_credit_review_report_v3.pdf` foi a
versão final usada para validar o relatório. Atualmente, as três versões do PDF e os
outputs intermediários estão preservados como histórico. Novas execuções devem seguir
o fluxo e as regras de saída descritos no [`README.md` principal](../README.md).

### `../agent_report_prompt_v1.json`

Contrato utilizado para orientar a composição textual pelo LLM. O arquivo define:

- o contrato de entrada, que recebe somente o `llm_context` já preparado e governado;
- as instruções que impedem o LLM de recalcular score, métricas, percentis, limites ou
  recomendação;
- a obrigação de explicar o caso e produzir uma conclusão contextualizada para cada
  fator autorizado;
- o schema JSON obrigatório da resposta;
- as verificações que o agente deve executar após receber a resposta.

Foi criado manualmente a partir do comportamento proposto para o agente e da estrutura
de [`sample_agent_context_before_llm.json`](sample_agent_context_before_llm.json).
Sua função no protótipo é explicitar e testar a divisão de responsabilidades: o LLM
produz a narrativa, enquanto os valores técnicos permanecem sob controle da solução.

### `sample_llm_response_to_report_request.json`

Exemplo da resposta que o LLM produziria ao receber o contexto preparado por meio do
prompt anterior. Contém somente o conteúdo narrativo estruturado, incluindo:

- síntese do caso e enquadramento na política;
- explicação dos fatores que elevaram ou reduziram o score;
- conclusão contextualizada de cada fator;
- limitações e aviso sobre a decisão humana.

Foi gerado por uma **simulação da atuação do LLM** sobre o contexto do caso. Os valores
provenientes das fontes controladas não foram repetidos nesse arquivo porque são
reassociados pelo agente na etapa seguinte. Portanto, este arquivo representa a
contribuição específica do LLM, e não o relatório completo.

### `sample_agent_report.json`

Representa a saída consolidada do agente, pronta para renderização. Foi produzido pela
combinação de duas fontes:

1. o conteúdo narrativo de `sample_llm_response_to_report_request.json`;
2. os dados do caso e as referências estatísticas preservados em
   [`sample_agent_context_before_llm.json`](sample_agent_context_before_llm.json).

Nessa etapa, a resposta narrativa é validada contra o schema, as features e suas
direções são confrontadas com o contexto autorizado e, em seguida, cada explicação é
reassociada ao valor do cliente, SHAP, referências populacionais, política e dados de
rastreabilidade. O processo de associação é determinístico: o LLM não cria nem
modifica esses valores.

O arquivo demonstra o contrato final entre a preparação do caso e a camada de
apresentação.

### `../credit_review_report_v1.html.j2`

Template HTML/Jinja usado para transformar `sample_agent_report.json` no documento
visual. Foi criado especificamente para validar uma apresentação híbrida:

- o corpo principal prioriza a conclusão contextualizada e apresenta uma síntese das
  evidências relevantes;
- o apêndice técnico conserva as medidas e referências estatísticas completas para
  conferência;
- a seção de rastreabilidade identifica as versões associadas ao resultado;
- scores e razões são exibidos com no máximo quatro casas decimais, enquanto
  percentis são apresentados sem casas decimais.

O template apenas formata dados existentes. Ele não recalcula risco, não altera a
recomendação e não produz conclusões.

O sufixo `v1` identifica a versão do **template**, enquanto o sufixo `v3` do PDF
identifica a terceira iteração do **artefato renderizado**. Essas versões pertencem a
contratos diferentes e não indicam que o PDF então validado utilizasse um template
obsoleto.

### `sample_credit_review_report_v3.pdf`

Artefato final apresentado ao usuário para validação. Foi renderizado com um conversor
HTML para PDF a partir de:

- `sample_agent_report.json`, como fonte de dados;
- `credit_review_report_v1.html.j2`, como definição de conteúdo e layout.

A versão 3 combina a interpretação contextualizada com um apêndice verificável. Essa
estrutura busca reduzir o tempo total da revisão sem sacrificar profundidade: o
analista recebe a conclusão, consegue entender as evidências que a sustentam e pode
conferir os valores no próprio relatório, sem precisar reconstruir o caso consultando
fontes dispersas.

## Evolução dos PDFs arquivados

Este diretório preserva as três iterações produzidas durante a validação. Elas
documentam a evolução do protótipo e não representam outputs de uma nova execução dos
scripts.

### `sample_credit_review_report.pdf` — v1

Primeira materialização do relatório. Validou a utilidade de apresentar uma conclusão
contextualizada para cada fator, mas exibia os números com precisão excessiva e ainda
não separava adequadamente a leitura principal da conferência técnica.

### `sample_credit_review_report_v2.pdf` — v2

Iteração intermediária voltada à apresentação mais adequada dos valores e ao
detalhamento das medidas e referências estatísticas. A experiência mostrou, porém,
que a evidência técnica sem a mesma força narrativa da primeira versão reduziria a
utilidade do documento para o analista.

### Evolução consolidada na v3

A v3 combinou as contribuições das duas versões anteriores:

- mantém a conclusão contextualizada que torna o caso compreensível;
- apresenta evidências resumidas junto à conclusão;
- preserva as medidas e referências estatísticas completas em um apêndice
  verificável;
- reduz a necessidade de consultas externas sem sacrificar profundidade.

O arquivamento documenta a evolução do protótipo sem misturar esses resultados com os
outputs de futuras execuções.

## Limites do protótipo

Estes arquivos demonstraram o comportamento e o resultado esperado, mas não
constituem uma implementação produtiva completa do agente. Nesta etapa histórica, a
chamada ao LLM e a montagem do JSON final foram simuladas para permitir a validação
antecipada do artefato. Os scripts criados posteriormente materializam essas etapas e
estão documentados no [`README.md` principal](../README.md).

O relatório:

- não recalcula o risco;
- não altera a recomendação da política;
- não transforma o score em probabilidade calibrada;
- não atribui causalidade às contribuições SHAP;
- não substitui a decisão do analista humano.

Depois que a utilidade e o conteúdo forem validados pelo usuário, estes contratos e
artefatos podem orientar a implementação produtiva descrita em
[`../AGENT_ARCHITECTURE.md`](../../AGENT_ARCHITECTURE.md).
