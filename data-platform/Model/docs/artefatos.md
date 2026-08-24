# Model — Artefatos e contratos

Este documento descreve o que o treinamento publica, o contrato de cada artefato e as
condições para que os consumidores os aceitem. O [README do componente](../README.md)
mantém o resumo e a regra de versionamento.

## Artefatos da execução e bundle ativo

Cada execução de `train.py` produz artefatos com a mesma identidade — `config_version` e
`trained_at_utc` — em um diretório versionado de `Model/artifacts/`. O contrato do bundle
ativo compreende o modelo, a referência estatística e o contrato de transformação
declarados por `current_bundle.json`. As métricas da avaliação pertencem à mesma execução,
mas são mantidas como informação auxiliar fora desse contrato:

| Artefato | Conteúdo | Participação na ativação |
|---|---|---|
| `bundles/<bundle_id>/lightgbm_abt.pkl` | Modelo LightGBM oficial e os metadados necessários à inferência. | declarado no manifesto, com checksum |
| `bundles/<bundle_id>/feature_reference.json` | Baseline populacional: distribuições das features e do score, referências por target e importância TreeSHAP global. | declarado no manifesto, com checksum |
| `bundles/<bundle_id>/transformation_contract.json` | Estatísticas, listas de categorias válidas e digests de projeção que a sanitização e a geração da ABT registraram na execução do pipeline que produziu esses dados — reproduz a transformação de um cliente novo. | declarado no manifesto, com checksum |
| `bundles/<bundle_id>/eval_model_metrics.json` | Métricas do modelo de avaliação no holdout, com algoritmo, hiperparâmetros e threshold. | informativo; não integra o manifesto nem possui checksum |
| `current_bundle.json` | Schema, `bundle_id`, identidade e caminhos dos três artefatos que formam o bundle ativo. | sua substituição ativa a versão |

`bundle_id` é `model-<config_version>-<trained_at_utc compactado>`. O
`artifact_bundle_publisher.py` valida primeiro que modelo e referência pertencem ao mesmo
treinamento — o contrato de transformação não carrega essa identidade e não participa da
checagem, porque só transporta o que o pipeline já registrou. Em seguida, grava os três
arquivos em um diretório temporário no mesmo filesystem, calcula seus checksums, publica o
diretório versionado por renomeação e, por último, substitui atomicamente
`current_bundle.json`. Somente essa última operação muda o bundle ativo; uma falha anterior
preserva o manifesto que já estava em uso.

Depois que o bundle foi ativado, `save_artifacts` grava `eval_model_metrics.json` no mesmo
diretório versionado. Como esse arquivo não integra o manifesto, sua escrita não participa
da ativação atômica nem desfaz a versão já ativada caso falhe. O contrato está declarado
em `artifact_bundle_contract.py` e a publicação é implementada em
`artifact_bundle_publisher.py`.

O diretório publicado é aberto para leitura por qualquer processo (`chmod 0o755`, aplicado
logo após a renomeação atômica) — `tempfile.mkdtemp` cria em modo `0700` por padrão, e sem
esse ajuste o conteúdo ficaria ilegível para quem não seja o usuário do SO que publicou (a
API roda como root no contêiner e não seria afetada, mas o Jupyter roda como um usuário sem
relação nenhuma com quem publica).

Isso substitui a publicação anterior — três arquivos de caminho fixo, sobrescritos a cada
execução — descrita no plano de refatoração do carregamento, predição e explicação
(`.internal/plano_refatoracao_carregamento_predicao_explicacao.md`). A proposta de
[monitoramento do modelo em produção](../../MLOps/MONITORING_ARCHITECTURE.md) introduz,
adicionalmente, um *model registry* para controlar promoção e rollback — o versionamento
por `bundle_id` não decide isso: qualquer manifesto válido é ativado, sem distinguir
publicação de retrocesso.

`model_comparison.csv` também vive em `artifacts/`, mas não é saída do treinamento: é o
resultado histórico da comparação de modelos, produzido na etapa de seleção.

## Contrato do artefato LightGBM

O Pickle oficial é um dicionário com os elementos necessários para que outro processo reproduza a inferência:

| Chave | Conteúdo |
|---|---|
| `model` | Instância treinada do `LGBMClassifier`. |
| `features` | Lista ordenada das features esperadas. |
| `categorical_features` | Features que precisam manter dtype categórico. |
| `categories` | Categorias conhecidas durante o treinamento. |
| `decision_threshold` | Corte usado para produzir `predicted_class`. |
| `algorithm` | Identificação do algoritmo. |
| `hyperparameters` | Configuração utilizada no ajuste. |
| `trained_at_utc` | Data e hora do treinamento. |
| `config_version` | Versão lógica da configuração. |

O `train.py` salva a lista ordenada na chave `features`, que é consumida diretamente pela API como contrato de entrada do modelo.

As métricas não integram o Pickle. Elas medem o **modelo de avaliação** no holdout, não
o modelo final do artefato, e nenhum consumidor da inferência as utiliza — por isso
vivem apenas em `eval_model_metrics.json`, legível sem carregar o binário.

## Referências para explicação e para o agente acelerador de revisão de crédito

Após ajustar o modelo final, `train.py` gera `feature_reference.json` com a mesma
versão e instante de treinamento do artefato. Para features numéricas, o arquivo
registra contagem, ausências, média, desvio-padrão, mínimo, máximo, percentis de
0 a 100 e medianas por target. Para flags binárias, registra também a proporção
geral e por target. Para categóricas, registra contagem, frequência e taxa
histórica de inadimplência por categoria. Também inclui a distribuição do score
e, para cada feature, média e percentis 50, 75, 90, 95 e 99 do valor SHAP
absoluto em uma amostra reproduzível, cujo tamanho é definido por
`parameters.reference.shap_sample_size`.

Para que o bundle seja ativado pela API, cada feature registrada no artefato deve
possuir exatamente uma referência estatística em `numeric_features` ou
`categorical_features` e uma entrada em `global_shap.feature_importance`.
Referências extras são aceitas, mas geram um warning no log da API.

Esse baseline permite combinar a contribuição SHAP local retornada pela API com
a posição estatística do cliente na população usada pelo treinamento. Os valores
SHAP permanecem na escala bruta do modelo e não representam variação percentual
de probabilidade.

Essas referências foram acrescentadas ao treinamento para preparar informações
determinísticas e versionadas que possam ser consumidas pelo futuro agente acelerador de revisão de crédito. O agente acelerador de revisão de crédito não acessará os dados de treino nem calculará estatísticas:
receberá da API a explicação local já enriquecida com este baseline e apenas a
converterá em um relatório para o analista. A arquitetura desse fluxo está em
[Arquitetura proposta para o agente acelerador de revisão de crédito](../../MLOps/AGENT_ARCHITECTURE.md).

## Reprodutibilidade e compatibilidade

- use a mesma versão de LightGBM e dependências registrada em [`requirements.txt`](../requirements.txt);
- não altere a ordem ou o tipo das features sem retreinar;
- mudanças na ABT devem ser refletidas em `config_model.json`;
- Pickle deve ser carregado apenas de origem confiável;
- alterações de categorias exigem novo artefato para preservar o contrato de inferência.
