"""`get_database_engine` — o Engine do SQLAlchemy consumido pelos notebooks.

É a única função de banco do componente que nenhuma outra suíte alcança: seus consumidores
são `Model/validacao_modelos.ipynb`, `DataPipeline/exp_analysis_raw.ipynb` e
`DataPipeline/exp_analysis_abt.ipynb`, que não são exercitados por teste algum. Sem este
teste, uma alteração na função só apareceria ao abrir um notebook.

Contrato: devolve um Engine ligado ao banco configurado, capaz de executar consulta e de
alimentar `pandas.read_sql` — que é o uso real nos três notebooks.
"""

import pandas as pd
import pytest
from sqlalchemy import text

from db import get_database_engine


CLIENTES = [
    {"sk_id_curr": 100001, "target": 0},
    {"sk_id_curr": 100002, "target": 1},
]
TABELA = "application_abt"


@pytest.mark.integration
def test_engine_executa_consulta_no_banco_configurado(test_db):
    test_db.create_table(TABELA, {"sk_id_curr": "BIGINT", "target": "BIGINT"})
    test_db.insert(TABELA, CLIENTES)

    engine = get_database_engine(silent=True)

    with engine.connect() as conexao:
        total = conexao.execute(text(f'SELECT COUNT(*) FROM "{TABELA}"')).scalar()

    assert total == len(CLIENTES)


@pytest.mark.integration
def test_engine_alimenta_read_sql_como_nos_notebooks(test_db):
    test_db.create_table(TABELA, {"sk_id_curr": "BIGINT", "target": "BIGINT"})
    test_db.insert(TABELA, CLIENTES)

    engine = get_database_engine(silent=True)
    frame = pd.read_sql(f'SELECT * FROM "{TABELA}" ORDER BY sk_id_curr', engine)

    assert frame.to_dict("records") == CLIENTES
