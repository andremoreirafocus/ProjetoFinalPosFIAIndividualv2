# DataPipeline — Metodologia de EDA

Como a análise exploratória originou as regras de preparação, e o papel de cada notebook. Parte do [DataPipeline](../README.md).

## Metodologia da EDA e das decisões de preparação

As regras de limpeza e de engenharia de atributos descritas em [transformações](./transformacoes.md) não são arbitrárias: derivam de uma **análise exploratória sistemática**, organizada em **duas etapas** e com **métodos de avaliação escolhidos por tipo de variável**.

### EDA em duas etapas

- **Diagnóstico dos dados brutos** (`exp_analysis_raw.ipynb`): mede qualidade e comportamento das fontes *antes* de qualquer tratamento, para **decidir** cada regra de sanitização e cada feature derivada.
- **Validação da base limpa** (`exp_analysis_abt.ipynb`): roda *depois* do pipeline, sobre a ABT materializada, para **confirmar** que a sanitização atingiu o objetivo (sem nulos, sem duplicatas, sem constantes, redundâncias removidas) e que o sinal preditivo se preservou.

Separar as duas etapas evita misturar exploração com transformação e deixa explícito qual decisão veio de qual evidência.

### Métodos de avaliação de variáveis

A força de um preditor é sempre **medida**, nunca presumida — cada tipo de variável com o método adequado:

- **Pearson** — correlação linear das numéricas com o target;
- **Cramér's V** — associação das categóricas com o target (independe de ordem);
- **WOE / IV** (*Weight of Evidence / Information Value*) — métrica-padrão de força preditiva em risco de crédito, usada para manter ou descartar variáveis;
- **Matriz de correlação** — detecção de **multicolinearidade** entre preditoras redundantes.

### Regras de qualidade de dados (o método por trás da sanitização)

O tratamento segue um conjunto de regras, não decisões caso a caso:

- **descartar** blocos majoritariamente vazios (imputar só adicionaria ruído);
- separar **ausência de valor** criando **flag + imputação**, para não confundir "não tem" com "valor baixo";
- isolar **códigos-sentinela/anomalias** em flags próprias, em vez de deixá-los distorcer a distribuição;
- **winsorizar** outliers monetários extremos;
- **imputar variáveis assimétricas pela mediana** (robusta à cauda);
- **condensar categorias raras** e normalizar códigos inválidos;
- **podar pares redundantes** (manter uma variável de cada par de alta correlação).

A mesma lógica separa **ausência de histórico** de **histórico observado** por meio das flags de presença (`has_prev_app`, `has_bureau`, `has_installments_history`), evitando mascarar "sem dado" como se fosse comportamento.

## Notebooks

Os notebooks **aplicam** a metodologia acima; os resultados numéricos ficam neles, não nesta documentação.

### [`exp_analysis_raw.ipynb`](../exp_analysis_raw.ipynb) — diagnóstico dos dados brutos

- **O que analisa:** as quatro fontes em estado bruto (`application_train`, `previous_application`, `bureau`, `installments_payments`).
- **O que busca estabelecer:** qualidade e comportamento (nulos, duplicatas, constantes, desbalanceamento do target, anomalias, cardinalidade) e o **poder preditivo** de cada variável — para **decidir** as regras de sanitização e as features da ABT.
- **Dados que cria e apresenta:** rankings de correlação (Pearson) e de associação (Cramér's V), tabelas de WOE/IV, distribuições e taxas de risco por faixa/categoria, e a lista de tratamentos/derivações que alimentam `data_sanitization.py` e `abt_transform.py`.

### [`exp_analysis_abt.ipynb`](../exp_analysis_abt.ipynb) — validação da base limpa

- **O que analisa:** a ABT final (`application_abt`) já materializada pelo pipeline.
- **O que busca estabelecer:** que a sanitização cumpriu seu papel (integridade: sem nulos/duplicatas/constantes; redundâncias removidas) e que o sinal preditivo e as features de histórico se comportam como esperado — além de sinalizar atributos sensíveis para governança.
- **Dados que cria e apresenta:** validações de integridade, rankings de correlação/associação e WOE/IV sobre a base limpa, matriz de multicolinearidade e a nota de fairness.

Os notebooks podem ser abertos pelo ambiente descrito em [Jupyter](../../jupyter/README.md).
