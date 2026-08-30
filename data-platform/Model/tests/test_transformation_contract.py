"""`load_transformation_contract` — leitura das duas tabelas `*_last_run` que o pipeline grava.

A função não calcula nada: transporta o que `run_sanitization` e `run_abt_generation` já
registraram em `application_sanitization_last_run` e `application_abt_generation_last_run`. O fake de
conexão é próprio deste arquivo — diferente de `ConexaoFalsa` em `test_load_training_data.py`,
que devolve o mesmo conteúdo para qualquer `cursor()`, aqui cada tabela consultada responde com
suas próprias colunas e sua própria linha, porque a função lê duas tabelas de formas diferentes.

A conexão real é coberta no `DataPipeline`, onde `run_sanitization` e `run_abt_generation` são
exercitadas contra o banco de testes dedicado.
"""

import pytest

from artifact_bundle_contract import REQUIRED_TRANSFORMATION_CONTRACT_KEYS
from train import load_transformation_contract


SANITIZATION_TABLE = "application_sanitization_last_run"
ABT_TABLE = "application_abt_generation_last_run"

SANITIZATION_COLUNAS = [
    "median_es1", "median_es2", "median_es3", "median_es_mean", "median_phone",
    "median_fam", "median_annuity", "median_income", "p_limit_income", "median_car_age",
    "valid_orgs", "valid_incs", "cardinalidade_min_freq", "income_winsor_q",
    "employment_days_anomaly_sentinel",
    "application_sanitization_projection_sha256", "run_at",
]
SANITIZATION_LINHA = (
    0.5052, 0.5659, 0.5352, 0.4432, -757.0, 2.0, 24903.0, 147150.0, 472500.0, 9.0,
    ["Business Entity Type 3", "Self-employed"], ["Working", "Commercial associate"],
    500, 0.99, 365243, "3f7a" + "0" * 60, "2026-08-24T00:00:00+00:00",
)

ABT_COLUNAS = ["application_abt_record_projection_sha256", "run_at"]
ABT_LINHA = ("9c21" + "0" * 60, "2026-08-24T00:05:00+00:00")

STATS_EXCLUDED_COLUMNS = {
    "valid_orgs", "valid_incs", "cardinalidade_min_freq", "income_winsor_q",
    "employment_days_anomaly_sentinel",
    "application_sanitization_projection_sha256", "run_at",
}


class CursorFalso:
    """Cursor DBAPI mínimo: `description` e `fetchone`, o que a função consome."""

    def __init__(self, conexao, tabelas):
        self._conexao = conexao
        self._tabelas = tabelas
        self._tabela_atual = None

    def execute(self, sql, params=None):
        self._conexao.consultas.append(sql)
        for nome, tabela in self._tabelas.items():
            if f'"{nome}"' in sql:
                self._tabela_atual = tabela
                return
        raise AssertionError(f"fake não configurada para esta consulta: {sql}")

    @property
    def description(self):
        colunas, _ = self._tabela_atual
        return [(coluna,) for coluna in colunas]

    def fetchone(self):
        _, linha = self._tabela_atual
        return linha

    def close(self):
        pass


class ConexaoFalsa:
    """Conexão DBAPI que responde conforme a tabela nomeada na consulta recebida.

    `consultas` registra o SQL de cada `execute`, na ordem — é o que prova que as duas
    tabelas nomeadas nos parâmetros são consultadas. `fechada` fixa que quem abre a
    conexão é quem a fecha, não `load_transformation_contract`.
    """

    def __init__(self, tabelas: dict):
        self._tabelas = tabelas
        self.consultas = []
        self.fechada = False

    def cursor(self):
        return CursorFalso(self, self._tabelas)

    def close(self):
        self.fechada = True


def _conexao(**tabelas_sobrepostas):
    tabelas = {
        SANITIZATION_TABLE: (SANITIZATION_COLUNAS, SANITIZATION_LINHA),
        ABT_TABLE: (ABT_COLUNAS, ABT_LINHA),
    }
    tabelas.update(tabelas_sobrepostas)
    return ConexaoFalsa(tabelas)


def test_dicionario_tem_exatamente_as_chaves_declaradas_do_contrato():
    contrato = load_transformation_contract(_conexao(), SANITIZATION_TABLE, ABT_TABLE)

    assert set(contrato) == REQUIRED_TRANSFORMATION_CONTRACT_KEYS


def test_valores_vem_das_duas_tabelas_nas_posicoes_declaradas():
    contrato = load_transformation_contract(_conexao(), SANITIZATION_TABLE, ABT_TABLE)

    san = dict(zip(SANITIZATION_COLUNAS, SANITIZATION_LINHA))
    abt = dict(zip(ABT_COLUNAS, ABT_LINHA))

    assert contrato["valid_orgs"] == san["valid_orgs"]
    assert contrato["valid_incs"] == san["valid_incs"]
    assert contrato["cardinalidade_min_freq"] == san["cardinalidade_min_freq"]
    assert contrato["income_winsor_q"] == san["income_winsor_q"]
    assert contrato["employment_days_anomaly_sentinel"] == san["employment_days_anomaly_sentinel"]
    assert contrato["application_sanitization_projection_sha256"] == san[
        "application_sanitization_projection_sha256"
    ]
    assert contrato["application_abt_record_projection_sha256"] == abt[
        "application_abt_record_projection_sha256"
    ]


def test_valid_orgs_e_valid_incs_ficam_no_primeiro_nivel_nao_em_stats():
    contrato = load_transformation_contract(_conexao(), SANITIZATION_TABLE, ABT_TABLE)

    assert "valid_orgs" not in contrato["stats"]
    assert "valid_incs" not in contrato["stats"]


def test_estatisticas_ficam_aninhadas_em_stats():
    contrato = load_transformation_contract(_conexao(), SANITIZATION_TABLE, ABT_TABLE)

    san = dict(zip(SANITIZATION_COLUNAS, SANITIZATION_LINHA))
    nomes_stats = [c for c in SANITIZATION_COLUNAS if c not in STATS_EXCLUDED_COLUMNS]

    assert set(contrato["stats"]) == set(nomes_stats)
    for nome in nomes_stats:
        assert contrato["stats"][nome] == san[nome]


def test_run_at_nao_entra_no_contrato():
    contrato = load_transformation_contract(_conexao(), SANITIZATION_TABLE, ABT_TABLE)

    assert "run_at" not in contrato
    assert "run_at" not in contrato["stats"]


def test_uma_estatistica_a_mais_na_tabela_aparece_em_stats_sem_mudar_o_codigo():
    colunas = SANITIZATION_COLUNAS + ["median_nova_estatistica"]
    linha = SANITIZATION_LINHA + (1.23,)

    contrato = load_transformation_contract(
        _conexao(**{SANITIZATION_TABLE: (colunas, linha)}), SANITIZATION_TABLE, ABT_TABLE
    )

    assert contrato["stats"]["median_nova_estatistica"] == 1.23


def test_consulta_as_tabelas_nomeadas_nos_parametros():
    conexao = _conexao()

    load_transformation_contract(conexao, SANITIZATION_TABLE, ABT_TABLE)

    assert conexao.consultas == [
        f'SELECT * FROM "{SANITIZATION_TABLE}"',
        f'SELECT * FROM "{ABT_TABLE}"',
    ]


def test_nao_fecha_a_conexao_recebida():
    conexao = _conexao()

    load_transformation_contract(conexao, SANITIZATION_TABLE, ABT_TABLE)

    assert conexao.fechada is False


def test_sanitizacao_sem_linha_falha_nomeando_a_tabela():
    conexao = _conexao(**{SANITIZATION_TABLE: (SANITIZATION_COLUNAS, None)})

    with pytest.raises(ValueError) as erro:
        load_transformation_contract(conexao, SANITIZATION_TABLE, ABT_TABLE)

    assert SANITIZATION_TABLE in str(erro.value)


def test_abt_sem_linha_falha_nomeando_a_tabela():
    conexao = _conexao(**{ABT_TABLE: (ABT_COLUNAS, None)})

    with pytest.raises(ValueError) as erro:
        load_transformation_contract(conexao, SANITIZATION_TABLE, ABT_TABLE)

    assert ABT_TABLE in str(erro.value)
