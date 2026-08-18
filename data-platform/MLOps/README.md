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

As referências estatísticas e o enriquecimento explicativo da API já estão implementados. O protótipo executável em [`agent-manual-review`](./agent-manual-review/README.md) materializa a preparação governada do contexto, a composição narrativa pelo modelo de linguagem, a validação da resposta, a consolidação do relatório e a renderização do PDF. A integração produtiva com a API, mensageria, execução assíncrona e persistência durável permanece proposta em [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md).

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

## Artefatos de execução

A API consome o conjunto ativo indicado por `Model/artifacts/current_bundle.json`.
`Model/train.py` publica e ativa de forma atômica o modelo e suas referências; as métricas
da avaliação são registradas separadamente no mesmo diretório versionado. A estrutura, os
checksums e os limites dessa ativação estão definidos no
[contrato de artefatos do Model](../Model/docs/artefatos.md).

Na execução oficial, o treinamento é a última tarefa da DAG `pipeline_orchestration`.
O manifesto e os diretórios dos bundles são produzidos localmente e não fazem parte do
checkout do repositório.

Se `current_bundle.json` não existir em `Model/artifacts`, execute a DAG até a tarefa
`train_machine_learning_model`. Se continuar ausente, verifique o estado e os logs dessa
tarefa no Airflow e os logs do `airflow-scheduler` para identificar falhas de dados,
conexão ou treinamento.

O carregamento e a atualização do conjunto ativo estão documentados em
[API.md](API.md#carregamento-do-modelo).

## CLI

Os utilitários de predição e busca de clientes por faixa de score reutilizam o serving
fora do transporte HTTP. Seus contratos e comandos estão em
[DEVELOPMENT.md](DEVELOPMENT.md).

## Limitações atuais

- limites da política demonstrativos;
- score sem calibração probabilística;
- ausência de autenticação e autorização;
- ausência de auditoria persistente das predições;
- dependência da ABT no PostgreSQL;
- sem limpeza automática de bundles antigos nem política de rollback entre versões;
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
