# Protótipo do relatório de apoio à revisão humana

Esta pasta reúne os artefatos usados para **materializar a proposta de relatório de
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
 agente valida e reassocia evidências determinísticas
                  │
                  ▼
          JSON consolidado do relatório
                  │
                  ▼
        template HTML/Jinja → PDF
```

Os dados utilizados na demonstração tiveram como origem:

- [`../sample_api_response_with_explanation.json`](../sample_api_response_with_explanation.json):
  resposta técnica da API contendo score, política e objeto de explicação;
- [`../config/feature_catalog.json`](../config/feature_catalog.json): catálogo com a
  semântica, as regras de interpretação e as restrições de uso das features;
- [`../sample_agent_context_before_llm.json`](../sample_agent_context_before_llm.json):
  contexto preparado pelo agente antes da chamada ao LLM, produzido pela associação
  entre a resposta da API e o catálogo e pela exclusão das evidências não autorizadas.

## Artefatos ativos

O arquivo `sample_credit_review_report_v3.pdf` é a versão vigente do relatório e deve
ser a única utilizada em validações, demonstrações e apresentações. As versões
anteriores foram preservadas apenas como histórico e estão descritas em
[Versões arquivadas](#versões-arquivadas).

### `agent_report_prompt_v1.json`

Contrato utilizado para orientar a composição textual pelo LLM. O arquivo define:

- o contrato de entrada, que recebe somente o `llm_context` já preparado e governado;
- as instruções que impedem o LLM de recalcular score, métricas, percentis, limites ou
  recomendação;
- a obrigação de explicar o caso e produzir uma conclusão contextualizada para cada
  fator autorizado;
- o schema JSON obrigatório da resposta;
- as verificações que o agente deve executar após receber a resposta.

Foi criado manualmente a partir do comportamento proposto para o agente e da estrutura
de [`../sample_agent_context_before_llm.json`](../sample_agent_context_before_llm.json).
Sua função no protótipo é explicitar e testar a divisão de responsabilidades: o LLM
produz a narrativa, enquanto os valores técnicos permanecem sob controle da solução.

### `sample_llm_report.json`

Exemplo da resposta que o LLM produziria ao receber o contexto preparado por meio do
prompt anterior. Contém somente o conteúdo narrativo estruturado, incluindo:

- síntese do caso e enquadramento na política;
- explicação dos fatores que elevaram ou reduziram o score;
- conclusão contextualizada de cada fator;
- limitações e aviso sobre a decisão humana.

Foi gerado por uma **simulação da atuação do LLM** sobre o contexto do caso. Os números
determinísticos não foram repetidos nesse arquivo porque são reassociados pelo agente
na etapa seguinte. Portanto, este arquivo representa a contribuição específica do
LLM, e não o relatório completo.

### `sample_agent_report.json`

Representa a saída consolidada do agente, pronta para renderização. Foi produzido pela
combinação de duas fontes:

1. o conteúdo narrativo de `sample_llm_report.json`;
2. os dados determinísticos preservados em
   [`../sample_agent_context_before_llm.json`](../sample_agent_context_before_llm.json).

Nessa etapa, a resposta narrativa é validada contra o schema, as features e suas
direções são confrontadas com o contexto autorizado e, em seguida, cada explicação é
reassociada ao valor do cliente, SHAP, referências populacionais, política e dados de
rastreabilidade. Essa associação é determinística: o LLM não cria nem modifica esses
valores.

O arquivo demonstra o contrato final entre a preparação do caso e a camada de
apresentação.

### `credit_review_report_v1.html.j2`

Template HTML/Jinja usado para transformar `sample_agent_report.json` no documento
visual. Foi criado especificamente para validar uma apresentação híbrida:

- o corpo principal prioriza a conclusão contextualizada e apresenta uma síntese das
  evidências relevantes;
- o apêndice técnico conserva as métricas determinísticas completas para conferência;
- a seção de rastreabilidade identifica as versões associadas ao resultado;
- scores e razões são exibidos com no máximo quatro casas decimais, enquanto
  percentis são apresentados sem casas decimais.

O template apenas formata dados existentes. Ele não recalcula risco, não altera a
recomendação e não produz conclusões.

O sufixo `v1` identifica a versão do **template**, enquanto o sufixo `v3` do PDF
identifica a terceira iteração do **artefato renderizado**. Essas versões pertencem a
contratos diferentes e não indicam que o PDF vigente utilize um template obsoleto.

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

## Versões arquivadas

A pasta [`archive`](archive) mantém as duas iterações que antecederam o relatório
vigente. Elas não devem ser utilizadas como referência funcional nem como material de
apresentação.

### `archive/sample_credit_review_report.pdf` — v1

Primeira materialização do relatório. Validou a utilidade de apresentar uma conclusão
contextualizada para cada fator, mas exibia os números com precisão excessiva e ainda
não separava adequadamente a leitura principal da conferência técnica.

### `archive/sample_credit_review_report_v2.pdf` — v2

Iteração intermediária voltada à apresentação mais adequada dos valores e ao
detalhamento das evidências determinísticas. A experiência mostrou, porém, que a
evidência técnica sem a mesma força narrativa da primeira versão reduziria a utilidade
do documento para o analista.

### Evolução consolidada na v3

A v3 substitui as duas anteriores ao combinar suas contribuições:

- mantém a conclusão contextualizada que torna o caso compreensível;
- apresenta evidências resumidas junto à conclusão;
- preserva as métricas determinísticas completas em um apêndice verificável;
- reduz a necessidade de consultas externas sem sacrificar profundidade.

O arquivamento permite documentar a evolução do protótipo sem criar ambiguidade sobre
qual relatório representa a solução atualmente validada.

## Limites do protótipo

Estes arquivos demonstram o comportamento e o resultado esperado, mas não constituem
uma implementação produtiva completa do agente. A chamada ao LLM e a montagem do JSON
final foram simuladas para permitir a validação antecipada do artefato.

O relatório:

- não recalcula o risco;
- não altera a recomendação da política;
- não transforma o score em probabilidade calibrada;
- não atribui causalidade às contribuições SHAP;
- não substitui a decisão do analista humano.

Depois que a utilidade e o conteúdo forem validados pelo usuário, estes contratos e
artefatos podem orientar a implementação produtiva descrita em
[`../AGENT_ARCHITECTURE.md`](../AGENT_ARCHITECTURE.md).
