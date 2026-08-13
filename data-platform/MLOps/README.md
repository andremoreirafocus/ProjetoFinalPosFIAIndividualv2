# MLOps

Esta pasta reúne a disponibilização do modelo de risco de crédito e as propostas arquiteturais para sua evolução. A implementação atual oferece uma API FastAPI e uma interface Streamlit; as propostas tratam do monitoramento do modelo em produção e do agente acelerador de revisão de crédito.

O modelo fornece um score de ordenação de risco. A política transforma faixas desse score em recomendações demonstrativas, e a decisão final permanece humana.

## Visão geral

A camada MLOps conecta o artefato treinado aos consumidores por meio de um contrato HTTP único, mantendo modelo, política de crédito e apresentação como responsabilidades separadas.

```text
Streamlit e outros consumidores
               │
               │ features fornecidas ou ID do cliente
               ▼
     API de risco de crédito
       ├── consulta à ABT no PostgreSQL quando recebe um ID
       ├── usa os artefatos do modelo
       ├── calcula score e classe prevista
       ├── aplica a política de recomendação
       └── gera explicação em manual_review
               │
               │ resposta HTTP
               ▼
Streamlit e outros consumidores
```

A API é implementada com FastAPI e executada no container `credit-api`. O framework foi escolhido por integrar naturalmente o ecossistema Python do modelo, validar contratos tipados de entrada e saída e disponibilizar automaticamente documentação OpenAPI aos consumidores.

A API recebe features prontas ou recupera um cliente da ABT, calcula o resultado técnico, aplica a política e acrescenta a explicação local nos casos encaminhados para revisão humana. O score não deve ser interpretado como probabilidade calibrada de inadimplência.

O frontend é implementado com Streamlit e executado no container `credit-frontend`. O framework foi escolhido por permitir construir rapidamente uma interface interativa em Python, gerar formulários dinâmicos para as features e demonstrar o consumo da API sem introduzir uma stack web adicional no projeto.

Os contratos, endpoints e componentes internos da API estão documentados em [API.md](API.md). As jornadas da interface estão em [FRONTEND.md](FRONTEND.md).

## Propostas arquiteturais

### Monitoramento do modelo em produção

A proposta abrange o monitoramento de falhas operacionais, mudanças nas distribuições, drift do score e perda de performance após a maturação dos desfechos. Também prevê o versionamento dos modelos por meio de um model registry, com MLflow como implementação inicial sugerida, e o armazenamento dos artefatos de cada versão em um object storage, com MinIO como implementação inicial sugerida.

O fluxo completo, incluindo baselines, Airflow, PostgreSQL, Prometheus, Grafana, Alertmanager, promoção e rollback, está em [MONITORING_ARCHITECTURE.md](MONITORING_ARCHITECTURE.md).

### Agente acelerador de revisão de crédito

Nos casos em que a API recomendar revisão humana, em vez de aprovação ou rejeição, um agente poderá ser acionado de forma assíncrona para combinar a explicação técnica da API com o catálogo semântico das features e, assim, produzir um relatório sobre o cliente, permitindo que o analista avalie o caso com maior agilidade e tome a decisão final sobre a concessão do crédito.

As referências estatísticas e o enriquecimento explicativo da API já estão implementados. Mensageria, agente, modelo de linguagem, persistência e renderização permanecem propostos em [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md).

## Início rápido

Na pasta `data-platform`:

```bash
docker compose up -d --build postgres credit-api credit-frontend
```

| Serviço | URL |
|---|---|
| Swagger | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |
| Streamlit | http://localhost:8501 |

Para acompanhar os serviços:

```bash
docker compose logs -f credit-api credit-frontend
```

Build, execução local e testes estão documentados em [DEVELOPMENT.md](DEVELOPMENT.md).

A suíte do componente fixa os contratos e os erros HTTP dos endpoints, a carga do modelo em
segundo plano com seus caminhos de falha, a política de crédito que traduz score em decisão,
a explicabilidade servida ao analista e a inicialização do frontend. Roda offline, sem
PostgreSQL e sem LightGBM, com fakes injetados por composição; os casos que dependem do
artefato treinado são pulados quando ele não está presente.

## Artefatos de execução

```text
Model/artifacts/
├── lightgbm_abt.pkl          # gerado pelo treinamento, não versionado
├── eval_model_metrics.json   # gerado pelo treinamento, não versionado
├── feature_reference.json    # gerado pelo treinamento, não versionado
└── model_comparison.csv      # resultado histórico, versionado
```

Os três primeiros são gerados por `Model/train.py` na mesma execução. Na execução
oficial, o treinamento é a última tarefa da DAG `pipeline_orchestration` do Airflow.
Como são reproduzíveis e sobrescritos a cada treino, não são versionados: podem não
estar presentes em uma nova cópia do repositório.

Versioná-los seria ativamente prejudicial. O clone os criaria com o dono e a permissão
do usuário local, e o processo do Airflow — que roda com outro usuário — não
conseguiria sobrescrevê-los. A gravação falharia no meio da sequência de três arquivos
e o conjunto publicado ficaria incoerente: modelo de um treino, referências de outro.

Se esses arquivos não estiverem em `Model/artifacts`, execute a DAG até a tarefa
`train_machine_learning_model`. Se continuarem ausentes, verifique o estado e os logs
dessa tarefa no Airflow e os logs do `airflow-scheduler` para identificar falhas de
dados, conexão ou treinamento.

O diretório é compartilhado entre os containers por *bind mounts*. Cada treinamento sobrescreve os arquivos, sem histórico físico de versões ou *model registry*. A API verifica os arquivos a cada requisição e recarrega automaticamente o modelo e suas referências quando os dois pertencem ao mesmo treinamento; durante uma atualização parcial, mantém em memória a última versão válida.

## Limitações atuais

- limites da política demonstrativos;
- score sem calibração probabilística;
- ausência de autenticação e autorização;
- ausência de auditoria persistente das predições;
- dependência da ABT no PostgreSQL;
- artefatos sobrescritos no diretório compartilhado;
- ausência de monitoramento contínuo pós-deploy.

## Documentação

| Documento | Conteúdo |
|---|---|
| [API.md](API.md) | Arquitetura interna, configuração, contratos, endpoints, exemplos e erros. |
| [FRONTEND.md](FRONTEND.md) | Interface Streamlit e jornadas do analista. |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Estrutura, Docker, execução local e testes. |
| [MONITORING_ARCHITECTURE.md](MONITORING_ARCHITECTURE.md) | Proposta de monitoramento, registry e versionamento. |
| [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md) | Proposta do agente acelerador de revisão de crédito. |
| [Modelo](../Model/README.md) | Treinamento, avaliação e artefatos. |
| [Airflow](../airflow/README.md) | Orquestração do pipeline. |
| [PostgreSQL](../postgres/README.md) | Persistência relacional. |
| [Plataforma](../README.md) | Arquitetura e operação do projeto completo. |
