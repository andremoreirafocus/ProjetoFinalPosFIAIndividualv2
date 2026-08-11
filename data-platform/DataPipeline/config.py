"""Carga da configuração do pipeline de dados.

Lê `config_pipeline.json`, o contrato que descreve fontes, tabelas e parâmetros de
sanitização. Não acessa banco de dados: é apenas a fronteira de leitura desse arquivo,
isolada da camada de orquestração que a consome.
"""

import json


def load_pipeline_config(path: str) -> dict:
    """Carrega e retorna o conteúdo de `config_pipeline.json` a partir de `path`.

    `path` é obrigatório: não há caminho default nem inferência de arquivo "ao
    lado" deste módulo. Isola o I/O de configuração da camada de orquestração.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
