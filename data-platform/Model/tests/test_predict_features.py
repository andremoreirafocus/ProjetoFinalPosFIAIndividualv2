"""`load_features_from_abt` — leitura do cliente na ABT a partir de uma conexão recebida.

A função deixou de abrir a própria conexão: ela chega pronta, aberta por quem conhece o
contexto. O teste injeta uma conexão DBAPI falsa pela mesma fronteira que a produção usa —
a função só lê, então não há banco envolvido.

O que fica fixado aqui: a linha do cliente é devolvida, o cliente inexistente falha
nomeando o identificador, a consulta filtra pelo `sk_id` recebido e a conexão recebida não
é fechada.
"""

import pytest

from predict import load_features_from_abt


CLIENTE = {
    "sk_id_curr": 100002,
    "target": 1,
    "amt_credit": 1293502.5,
    "code_gender": "F",
}

INEXISTENTE = 999999


class CursorFalso:
    """Cursor DBAPI mínimo: o que `pandas.read_sql` consome de uma conexão crua."""

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

    O registro faz parte do contrato observado: filtrar pelo `sk_id` só é verificável pela
    consulta que a conexão recebe. `fechada` fixa a inversão de responsabilidade — quem
    abre a conexão é quem a fecha, e não `load_features_from_abt`.
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
def conexao_com_o_cliente():
    return ConexaoFalsa(list(CLIENTE), [tuple(CLIENTE.values())])


@pytest.fixture
def conexao_sem_clientes():
    return ConexaoFalsa(list(CLIENTE), [])


def test_devolve_a_linha_do_cliente(conexao_com_o_cliente):
    frame = load_features_from_abt(conexao_com_o_cliente, CLIENTE["sk_id_curr"])

    assert frame.to_dict("records") == [CLIENTE]


def test_consulta_filtra_pelo_identificador_recebido(conexao_com_o_cliente):
    load_features_from_abt(conexao_com_o_cliente, CLIENTE["sk_id_curr"])

    assert str(CLIENTE["sk_id_curr"]) in conexao_com_o_cliente.consultas[-1]


def test_cliente_inexistente_falha_nomeando_o_identificador(conexao_sem_clientes):
    with pytest.raises(ValueError) as erro:
        load_features_from_abt(conexao_sem_clientes, INEXISTENTE)

    assert str(INEXISTENTE) in str(erro.value)


def test_nao_fecha_a_conexao_recebida(conexao_com_o_cliente):
    load_features_from_abt(conexao_com_o_cliente, CLIENTE["sk_id_curr"])

    assert conexao_com_o_cliente.fechada is False
