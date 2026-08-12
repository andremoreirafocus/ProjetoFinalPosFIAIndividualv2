"""Exportação de tabela para CSV (`run_postgres_to_csv_export`).

Utilitário manual de entrega: transporta uma tabela do PostgreSQL para um arquivo CSV via
`COPY TO STDOUT`, sem carregar a tabela em memória. Não tinha cobertura — os contratos
abaixo são os que o script promete a quem prepara a entrega acadêmica.

A conexão chega pronta, como nas demais funções do pipeline: aqui ela vem do `data_test`.
"""

import csv

import psycopg2
import pytest

from export_data import run_postgres_to_csv_export


TABELA = "application_clean"

CLIENTES = [
    {"sk_id_curr": 100001, "code_gender": "F", "amt_credit": 406597.5},
    {"sk_id_curr": 100002, "code_gender": "M", "amt_credit": 1293502.5},
]

ESQUEMA = {"sk_id_curr": "BIGINT", "code_gender": "TEXT", "amt_credit": "DOUBLE PRECISION"}


def _linhas_do_csv(caminho):
    with caminho.open(newline="", encoding="utf-8") as arquivo:
        return list(csv.reader(arquivo))


@pytest.mark.integration
def test_exporta_tabela_com_cabecalho_e_uma_linha_por_registro(test_db, conexao, tmp_path):
    test_db.create_table(TABELA, ESQUEMA)
    test_db.insert(TABELA, CLIENTES)

    run_postgres_to_csv_export(conexao, TABELA, str(tmp_path))

    linhas = _linhas_do_csv(tmp_path / f"{TABELA}.csv")
    assert linhas[0] == list(ESQUEMA)
    assert len(linhas) == len(CLIENTES) + 1
    assert linhas[1][0] == str(CLIENTES[0]["sk_id_curr"])


@pytest.mark.integration
def test_cria_a_pasta_de_destino_quando_ausente(test_db, conexao, tmp_path):
    test_db.create_table(TABELA, ESQUEMA)
    test_db.insert(TABELA, CLIENTES)
    destino = tmp_path / "entrega" / "csv"

    run_postgres_to_csv_export(conexao, TABELA, str(destino))

    assert (destino / f"{TABELA}.csv").is_file()


@pytest.mark.integration
def test_valor_nulo_vira_campo_vazio(test_db, conexao, tmp_path):
    test_db.create_table(TABELA, ESQUEMA)
    test_db.insert(TABELA, [{"sk_id_curr": 100003, "code_gender": None, "amt_credit": None}])

    run_postgres_to_csv_export(conexao, TABELA, str(tmp_path))

    linhas = _linhas_do_csv(tmp_path / f"{TABELA}.csv")
    assert linhas[1] == ["100003", "", ""]


@pytest.mark.integration
def test_tabela_inexistente_falha_nomeando_a_tabela(test_db, conexao, tmp_path):
    ausente = "tabela_que_nao_existe"

    with pytest.raises(RuntimeError) as erro:
        run_postgres_to_csv_export(conexao, ausente, str(tmp_path))

    assert ausente in str(erro.value)


@pytest.mark.integration
def test_exportacao_opera_na_conexao_recebida(test_db, conexao, tmp_path):
    """A exportação não commita, então o critério se inverte.

    As linhas escritas nesta transação em aberto só aparecem no CSV se for a conexão
    recebida que executa o `COPY` — uma conexão própria não enxerga transação alheia.
    """
    test_db.create_table(TABELA, ESQUEMA)
    with conexao.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{TABELA}" (sk_id_curr) VALUES (%s)', (CLIENTES[0]["sk_id_curr"],)
        )

    run_postgres_to_csv_export(conexao, TABELA, str(tmp_path))

    linhas = _linhas_do_csv(tmp_path / f"{TABELA}.csv")
    assert len(linhas) == 2
    assert linhas[1][0] == str(CLIENTES[0]["sk_id_curr"])


@pytest.mark.integration
def test_nao_fecha_a_conexao_recebida(test_db, conexao, tmp_path):
    test_db.create_table(TABELA, ESQUEMA)
    test_db.insert(TABELA, CLIENTES)

    run_postgres_to_csv_export(conexao, TABELA, str(tmp_path))

    with conexao.cursor() as cursor:
        cursor.execute(f'SELECT COUNT(*) FROM "{TABELA}"')
        assert cursor.fetchone()[0] == len(CLIENTES)
