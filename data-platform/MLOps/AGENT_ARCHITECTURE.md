# Arquitetura proposta para o agente acelerador de revisão de crédito

## Objetivo

Esta proposta descreve o agente acelerador de revisão de crédito, que utiliza IA para acelerar o processo de revisão humana de solicitações classificadas pela política como `manual_review` e, com isto, reduzir o tempo de espera do cliente e o custo da avaliação.

O agente acelerador de revisão de crédito transforma as informações produzidas pela API de avaliação de risco de crédito em um relatório que ajuda o analista a identificar rapidamente os aspectos relevantes do caso.

## Contexto disponível

Para viabilizar o trabalho do agente acelerador de revisão de crédito, a API de risco de crédito passou a produzir os elementos quantitativos necessários para a análise:

- score de risco e classe prevista;
- recomendação e limites da política de crédito;
- contribuições TreeSHAP locais para os casos em revisão manual;
- posição das features do cliente na população de treinamento;
- estatísticas por classe e referências globais de impacto SHAP.

O arquivo [`config/feature_catalog.json`](config/feature_catalog.json) complementa esses dados com a semântica de negócio das features, suas unidades, fórmulas, regras de interpretação e restrições de governança.

Portanto, o agente acelerador de revisão de crédito não realiza uma nova análise estatística. Sua função é combinar duas fontes já preparadas: a resposta explicativa da API e o catálogo de features.

## Preparação das informações para o agente acelerador de revisão de crédito

A disponibilização de informações para o agente acelerador de revisão de crédito começa no treinamento e continua
na API. As funcionalidades já implementadas formam uma cadeia única:

```text
train.py
   │ treina e versiona o modelo
   ├── lightgbm_abt.pkl
   └── feature_reference.json
          │ baseline estatístico e SHAP global
          ▼
PredictionService + CreditPolicy
          │ score e recomendação
          ▼
ExplanationService
          │ SHAP local + comparação com o baseline
          ▼
Resposta técnica da API
          │ futura mensagem de manual_review
          ▼
Agente acelerador de revisão de crédito + feature_catalog.json
          │ interpretação semântica e governança
          ▼
Relatório para o analista
```

### Informações preparadas no treinamento

O `train.py` gera `feature_reference.json` junto com o artefato do modelo. Esse
arquivo registra distribuições das features e do score, referências por classe e
a distribuição global da magnitude SHAP. Versão e instante de treinamento ligam
as referências ao modelo que as produziu.

Esse processamento foi incorporado ao treinamento para que o agente acelerador de revisão de crédito não precise acessar a ABT, inferir baselines ou calcular estatísticas sobre a população.

### Informações preparadas na API

Quando a política indica `manual_review`, o `ExplanationService` calcula o SHAP
local e usa `feature_reference.json` para situar cada fator em relação ao
treinamento. A resposta passa a informar tanto o efeito local no score quanto o
contexto populacional necessário para interpretá-lo.

Essa resposta enriquecida foi implementada como a entrada quantitativa do futuro
agente acelerador de revisão de crédito. Quando a mensageria for adicionada, ela será publicada sem que o agente acelerador de revisão de crédito
tenha de chamar novamente o modelo ou reconstruir a explicação.

A mensagem deverá acrescentar a versão do modelo disponível no artefato para manter a rastreabilidade. Essa informação ainda não integra o contrato atual de resposta da API.

### Informação acrescentada pelo catálogo

O `feature_catalog.json` não participa do treinamento nem da predição. Ele será
consultado pelo agente acelerador de revisão de crédito para acrescentar nomes legíveis, descrições, unidades,
semântica dos valores e regras de governança às evidências recebidas da API.

Assim, cada camada acrescenta somente a informação de sua responsabilidade:

| Camada | Informação disponibilizada ao agente acelerador de revisão de crédito |
|---|---|
| `feature_reference.py` (invocado por `train.py`) | Baseline populacional e referência SHAP global versionados. |
| API | Score, política, SHAP local e comparação do cliente com o baseline. |
| Catálogo | Significado de negócio e autorização de uso de cada feature. |
| Agente acelerador de revisão de crédito | Organização narrativa das evidências permitidas. |

## Visão arquitetural

```text
Cliente
   │
   ▼
API de predição
   │
   ├── resposta síncrona ao cliente
   │
   └── se recommendation = manual_review
            │ publica solicitação de relatório
            ▼
        RabbitMQ
            │ entrega assíncrona
            ▼
      Agente acelerador de revisão de crédito ◄──── feature_catalog.json
            │
            ├── consulta o modelo de linguagem
            ├── persiste relatório estruturado ───→ PostgreSQL ou object storage
            │
            └── publica referência do relatório
                         ▼
                     RabbitMQ
                         │ entrega assíncrona
                         ▼
              Renderizador determinístico
                         │ aplica template uniforme
                         ▼
                  Relatório em PDF
                         │
                         ▼
              Repositório de relatórios ───→ Analista humano
```

A comunicação entre os componentes é assíncrona e ocorre por filas mantidas por um *message broker*. Para esta proposta, o broker é o RabbitMQ: a API publica a solicitação de revisão para o agente acelerador de revisão de crédito, que posteriormente publica a disponibilidade do relatório estruturado para o renderizador.

## Componentes

### API de predição

A API permanece como autoridade sobre o resultado técnico. Ela:

- recupera ou recebe as features do cliente;
- calcula o score com o modelo carregado;
- aplica a política de crédito;
- calcula a explicação local quando a recomendação é `manual_review`;
- publica no RabbitMQ uma solicitação de relatório com esse resultado técnico.

A publicação não altera o contrato matemático da predição. A API também não consulta o catálogo e não chama o modelo de linguagem.

### RabbitMQ

O RabbitMQ desacopla o tempo de resposta da predição do tempo necessário para gerar o relatório e separa a geração do conteúdo de sua renderização. Sua responsabilidade é transportar as mensagens publicadas pela API e pelo agente acelerador de revisão de crédito até os respectivos consumidores.

Se o agente acelerador de revisão de crédito estiver temporariamente indisponível, a API continua realizando predições e a solicitação permanece pendente para processamento posterior.

### Agente acelerador de revisão de crédito

O agente acelerador de revisão de crédito é um processo independente da API e consumidor da fila. Ele:

- recebe o resultado técnico completo do caso em revisão;
- cruza os nomes das features com o catálogo;
- aplica as restrições de governança antes da geração textual;
- seleciona e contextualiza as evidências mais relevantes;
- solicita ao modelo de linguagem a composição do relatório;
- valida e persiste o conteúdo estruturado produzido;
- publica no RabbitMQ uma mensagem informando que o relatório está disponível para renderização.

O agente acelerador de revisão de crédito organiza em linguagem natural os resultados técnicos e as referências estatísticas autorizadas, preservando os valores recebidos, mas não substitui o modelo, a política nem o analista.

### Catálogo de features

Nesta proposta, o catálogo é consumido pelo agente acelerador de revisão de crédito, não pelo serviço de predição. Ele permanece um artefato genérico e reutilizável, que traduz os campos técnicos para conceitos de negócio e informa quais features podem ser usadas em cada finalidade.

Features com `allowed_in_report: false` não são enviadas ao modelo de linguagem como justificativas da avaliação. Elas podem continuar disponíveis em fluxos separados de auditoria de *fairness*.

### Modelo de linguagem

O modelo de linguagem recebe somente as evidências autorizadas e já calculadas. Sua função é organizar essas evidências em linguagem clara, sem inferir causalidade e sem produzir uma nova decisão de crédito.

O provedor do modelo é uma dependência externa ao domínio de predição. Sua indisponibilidade afeta a geração do relatório, mas não impede a API de calcular e devolver o score.

### System prompt

O comportamento do modelo de linguagem será orientado por um *system prompt* versionado. Esse artefato limita o relatório às evidências recebidas, impede o recálculo ou a alteração da recomendação, proíbe interpretações causais das contribuições SHAP, exige uma saída estruturada compatível com o renderizador e reforça que a decisão final permanece humana.

A versão do *system prompt* utilizada deve acompanhar os metadados do relatório para garantir rastreabilidade. O texto completo será definido e mantido junto à implementação do agente acelerador de revisão de crédito, não neste documento arquitetural.

### Renderizador de relatórios

O renderizador é um componente independente e consumidor da fila de relatórios disponíveis. Ao receber a mensagem, utiliza a referência informada para recuperar o conteúdo estruturado no PostgreSQL ou no *object storage*, conforme a decisão de armazenamento adotada, e aplica um template fixo para gerar um PDF legível pelo analista. Essa etapa é determinística e não utiliza outro modelo de linguagem, garantindo uniformidade de layout, seções e identidade visual.

A separação entre conteúdo e apresentação também permite regenerar o PDF sem executar novamente o agente acelerador de revisão de crédito.

### Repositório de relatórios

Os relatórios precisam ser persistidos para consulta, rastreabilidade e eventual reprocessamento. O PostgreSQL é tecnicamente adequado para armazenar os metadados e o conteúdo estruturado porque combina suporte transacional e relacional com JSONB. O volume e o padrão de acesso previstos não exigem um datastore especializado; sua reutilização atende aos requisitos sem criar dívida técnica ou complexidade operacional desnecessária.

O repositório mantém a associação entre o caso analisado, o resultado técnico que originou o relatório e o conteúdo produzido pelo agente acelerador de revisão de crédito.

Dependendo do tamanho dos relatórios estruturados, dos PDFs gerados e do volume acumulado, poderá ser necessário armazenar um ou ambos os conteúdos em um *object storage*. Nesse cenário, o PostgreSQL manterá os metadados e as referências estáveis aos objetos, compostas por `bucket` e `object key`. Para esta proposta, o MinIO é a escolha inicial sugerida para implementar esse armazenamento. O renderizador permanece independente dessa escolha porque recebe na mensagem a referência do relatório estruturado que deverá recuperar.

### Interface do analista

O analista humano consulta o relatório persistido por uma interface de revisão. Essa interface pode evoluir a partir do frontend existente, mas permanece um consumidor do relatório: não executa o agente acelerador de revisão de crédito nem acessa diretamente o modelo de linguagem.

## Fluxo da revisão humana

1. A API realiza uma predição e aplica a política de crédito.
2. Quando a recomendação é `manual_review`, o `ExplanationService` acrescenta as evidências locais e as referências populacionais.
3. A API publica no RabbitMQ uma solicitação de relatório contendo esse resultado técnico.
4. A resposta da predição é devolvida sem aguardar a geração narrativa.
5. O agente acelerador de revisão de crédito consome a solicitação e consulta o catálogo de features.
6. O agente acelerador de revisão de crédito remove do contexto narrativo as features não autorizadas.
7. O modelo de linguagem transforma as evidências permitidas em um relatório estruturado.
8. O agente acelerador de revisão de crédito valida e persiste o conteúdo produzido no repositório definido para o relatório estruturado.
9. O agente acelerador de revisão de crédito publica no RabbitMQ uma mensagem com a referência do relatório disponível.
10. O renderizador consome a mensagem e recupera o conteúdo estruturado no PostgreSQL ou no *object storage*, conforme a referência recebida.
11. O renderizador aplica um template fixo e gera o PDF.
12. O PDF ou sua referência é persistido e fica disponível para o analista responsável pela decisão final.

## Separação de responsabilidades

| Componente | Responsabilidade | Limite |
|---|---|---|
| `FeatureInputProcessor` | Aplicar o contrato do bundle: verificar, ordenar e tipar as features e restaurar as categorias do treinamento. | Recebe as features já recuperadas e não executa o modelo. |
| `PredictionService` | Calcular score e classe sobre a entrada preparada. | Não prepara features, aplica política nem produz explicação narrativa. |
| `CreditPolicy` | Converter o score em recomendação de negócio. | Não conhece SHAP, catálogo ou modelo de linguagem. |
| `ExplanationService` | Calcular SHAP local e comparações com o treinamento. | Não interpreta semanticamente nem redige relatório. |
| API | Expor o contrato e publicar a solicitação de relatório. | Não aguarda nem executa o agente acelerador de revisão de crédito. |
| RabbitMQ | Transportar solicitações de revisão e avisos de relatório disponível. | Não interpreta nem persiste o relatório final. |
| Agente acelerador de revisão de crédito | Produzir e persistir o conteúdo estruturado e publicar sua referência. | Não recalcula risco, altera a recomendação ou define o layout. |
| System prompt | Definir os limites de comportamento e o contrato de saída do modelo de linguagem. | Não contém cálculos, evidências específicas do cliente ou regras de decisão de crédito. |
| Renderizador | Consumir a referência, recuperar o conteúdo no repositório indicado e gerar o PDF de forma determinística. | Não interpreta evidências nem cria conteúdo. |
| PostgreSQL | Persistir metadados, referências, rastreabilidade e, quando adequado, o conteúdo estruturado em JSONB. | Não participa da geração textual ou visual. |
| Object storage — inicialmente MinIO | Armazenar o relatório estruturado, o PDF ou ambos quando seu tamanho ou volume justificar o armazenamento de objetos. | Não substitui os metadados e relacionamentos mantidos no PostgreSQL. |
| Analista humano | Avaliar o caso e tomar a decisão final. | Não precisa interpretar diretamente valores SHAP brutos. |

## Fronteiras de dados e governança

A mensagem enviada ao agente acelerador de revisão de crédito contém somente os dados necessários para produzir o relatório. O resultado quantitativo da API permanece imutável durante todo o fluxo.

Antes da chamada ao modelo de linguagem, o agente acelerador de revisão de crédito usa o catálogo para separar evidências autorizadas de atributos reservados à auditoria. Isso evita depender apenas de uma instrução textual para impedir o uso de features sensíveis.

O relatório deve deixar explícito que:

- o score é uma medida de ordenação de risco, não uma probabilidade calibrada;
- contribuições SHAP explicam o comportamento do modelo naquele caso, não relações causais;
- o conteúdo é apoio à revisão, e não uma decisão autônoma;
- a decisão final permanece sob responsabilidade humana e da política de crédito.

## Comportamento em falhas

O desacoplamento por mensageria mantém a predição independente da geração do relatório:

- indisponibilidade do agente acelerador de revisão de crédito ou do modelo de linguagem não interrompe a API;
- uma solicitação não confirmada pelo agente acelerador de revisão de crédito pode voltar à fila;
- falhas definitivas ficam identificadas para inspeção e reprocessamento;
- o relatório só é considerado concluído depois de validado e persistido.

Essas garantias pertencem ao fluxo de relatório. Elas não modificam o comportamento atual do modelo nem da política.

## Estado da proposta

Já estão implementados os pré-requisitos determinísticos do agente acelerador de revisão de crédito:

- predição e política de crédito;
- explicação TreeSHAP local;
- referências estatísticas geradas no treinamento;
- catálogo semântico e de governança das 42 features.

Um exemplo de implementação executável, documentado em
[`agent-manual-review/README.md`](./agent-manual-review/README.md), materializa a preparação
governada do contexto, a composição pelo modelo de linguagem via Groq, a validação e a
reassociação dos dados técnicos, a montagem do JSON final e a renderização determinística
do PDF. Esse exemplo valida a utilidade do artefato e os contratos entre as etapas.

Permanecem como proposta de integração produtiva:

- inclusão do RabbitMQ na plataforma;
- publicação das solicitações pela API;
- execução do agente como consumidor assíncrono, utilizando em produção as etapas e os contratos validados pelo exemplo;
- persistência e versionamento produtivos do *system prompt*, do contexto, da resposta e do relatório estruturado;
- execução do renderizador como consumidor integrado à mensageria e ao armazenamento;
- persistência e consulta dos relatórios de revisão, com possível adoção de *object storage*, inicialmente MinIO, para o conteúdo estruturado, o PDF ou ambos, conforme o tamanho e o volume acumulado.
