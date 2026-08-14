"""`load_customer_ids` — leitura dos identificadores da ABT a partir de uma conexão recebida.

O utilitário de busca varre a ABT procurando um cliente cujo score caia numa faixa. A
leitura dos identificadores é a única parte dele que toca o banco, e passa a receber a
conexão de quem a abre.

`run_prediction` fica fora: executa `predict.py` por `subprocess` e exige artefato treinado
e banco disponível — é utilitário manual, não contrato exercitável sem ambiente.
"""

import pytest

from find_customer_by_score import load_customer_ids


# O banco devolve já ordenado, porque a consulta carrega `ORDER BY`; o fake reproduz isso.
CLIENTES = [(100001,), (100002,), (100003,)]


class CursorFalso:
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
    """Conexão DBAPI que devolve identificadores fixos e registra se foi fechada."""

    def __init__(self, linhas):
        self._linhas = linhas
        self.consultas = []
        self.fechada = False

    def cursor(self):
        return CursorFalso(self, ["sk_id_curr"], self._linhas)

    def rollback(self):
        pass

    def close(self):
        self.fechada = True


@pytest.fixture
def conexao():
    return ConexaoFalsa(CLIENTES)


def test_devolve_os_identificadores_como_inteiros(conexao):
    identificadores = load_customer_ids(conexao)

    assert identificadores == [linha[0] for linha in CLIENTES]
    assert all(isinstance(identificador, int) for identificador in identificadores)


def test_a_ordenacao_vem_da_consulta(conexao):
    """A ordem é responsabilidade do banco, não do Python: a consulta carrega `ORDER BY`."""
    load_customer_ids(conexao)

    assert "ORDER BY sk_id_curr" in conexao.consultas[-1]


def test_nao_fecha_a_conexao_recebida(conexao):
    load_customer_ids(conexao)

    assert conexao.fechada is False
