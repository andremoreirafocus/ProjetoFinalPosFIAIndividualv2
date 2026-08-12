"""`load_training_data` — leitura da ABT a partir de uma conexão recebida.

A função deixou de abrir a própria conexão: ela chega pronta, aberta pelo entrypoint que
conhece o contexto (`PostgresHook` na DAG, SQLAlchemy fora dela). O teste injeta uma
conexão DBAPI falsa pela mesma fronteira que a produção usa — é o que a injeção de
dependência torna possível, e dispensa banco para exercitar o contrato de leitura.

A conexão real é coberta no `DataPipeline`, onde as funções que a abrem são exercitadas
contra o banco de testes dedicado.
"""

import pandas as pd
import pytest

from train import load_training_data


ABT_COLUNAS = [
    "sk_id_curr",
    "target",
    "amt_credit",
    "days_employed",
    "code_gender",
    "name_contract_type",
]

ABT_CLIENTES = [
    (100001, 0, 406597.5, -637, "M", "Cash loans"),
    (100002, 1, 1293502.5, -1188, "F", "Revolving loans"),
    (100003, 0, 135000.0, -225, "F", "Cash loans"),
]

CONFIG = {
    "metadata": {"abt_table": "application_abt"},
    "variables": {
        "id": "sk_id_curr",
        "target": "target",
        "input_features": [
            "amt_credit",
            "days_employed",
            "code_gender",
            "name_contract_type",
        ],
        "categorical_features": ["code_gender", "name_contract_type"],
    },
}


class CursorFalso:
    """Cursor DBAPI mínimo: o que `pandas.read_sql_query` consome de uma conexão crua."""

    def __init__(self, conexao, colunas, linhas):
        self._conexao = conexao
        self.description = [(coluna,) for coluna in colunas]
        self._linhas = list(linhas)

    def execute(self, sql, params=None):
        self._conexao.consultas.append(sql)

    def fetchall(self):
        linhas, self._linhas = self._linhas, []
        return linhas

    def fetchmany(self, size):
        linhas, self._linhas = self._linhas[:size], self._linhas[size:]
        return linhas

    def close(self):
        pass


class ConexaoFalsa:
    """Conexão DBAPI que devolve uma ABT fixa e registra as consultas recebidas.

    O registro faz parte do contrato observado: `sample_size` só é verificável pela
    consulta que a conexão recebe. `fechada` fixa a inversão de responsabilidade — quem
    abre a conexão é quem a fecha, e não `load_training_data`.
    """

    def __init__(self, colunas, linhas):
        self._colunas = colunas
        self._linhas = linhas
        self.consultas = []
        self.fechada = False

    def cursor(self):
        return CursorFalso(self, self._colunas, self._linhas)

    def rollback(self):
        pass

    def close(self):
        self.fechada = True


@pytest.fixture
def conexao():
    return ConexaoFalsa(ABT_COLUNAS, ABT_CLIENTES)


def test_devolve_as_features_configuradas_com_categoricas_convertidas(conexao):
    variaveis = CONFIG["variables"]

    X, y = load_training_data(CONFIG, conexao)

    assert list(X.columns) == variaveis["input_features"]
    assert len(X) == len(ABT_CLIENTES)
    assert [str(X[coluna].dtype) for coluna in variaveis["categorical_features"]] == [
        "category" for _ in variaveis["categorical_features"]
    ]
    assert y.tolist() == [linha[ABT_COLUNAS.index(variaveis["target"])] for linha in ABT_CLIENTES]
    assert pd.api.types.is_integer_dtype(y)


def test_nao_fecha_a_conexao_recebida(conexao):
    load_training_data(CONFIG, conexao)

    assert conexao.fechada is False


def test_consulta_a_tabela_configurada_sem_limite_por_padrao(conexao):
    load_training_data(CONFIG, conexao)

    assert conexao.consultas == [f'SELECT * FROM "{CONFIG["metadata"]["abt_table"]}"']


def test_sample_size_limita_a_consulta(conexao):
    amostra = len(ABT_CLIENTES) - 1

    load_training_data(CONFIG, conexao, sample_size=amostra)

    assert conexao.consultas == [
        f'SELECT * FROM "{CONFIG["metadata"]["abt_table"]}" LIMIT {amostra}'
    ]


def test_coluna_configurada_ausente_na_abt_falha_nomeando_qual():
    ausente = CONFIG["variables"]["input_features"][0]
    indice = ABT_COLUNAS.index(ausente)
    colunas = [coluna for coluna in ABT_COLUNAS if coluna != ausente]
    linhas = [tuple(v for i, v in enumerate(linha) if i != indice) for linha in ABT_CLIENTES]

    with pytest.raises(ValueError) as erro:
        load_training_data(CONFIG, ConexaoFalsa(colunas, linhas))

    assert ausente in str(erro.value)
