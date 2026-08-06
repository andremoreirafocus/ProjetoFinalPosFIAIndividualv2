from datetime import datetime
import sys
import os

# Mapeamento dos caminhos do projeto
sys.path.append("/opt/airflow/DataPipeline")
sys.path.append("/opt/airflow/Model")

from ingestion import run_csv_ingestion
from ingestion_index import run_create_indexes
from utils import load_pipeline_config
from data_sanitization import (
    run_sanitization,
    run_prev_sanitization,
    run_bureau_sanitization,
    run_installments_sanitization,
)
from data_sanitization_index import run_abt_indexes
from abt_transform import (
    create_agg_previous_application,
    create_agg_bureau,
    create_agg_installments,
    run_abt_generation,
)
from train import run_training_pipeline

from airflow import DAG
from airflow.decorators import task

# Parâmetros de Infraestrutura imutáveis
CONN_ID = "postgres_data_db"
PASTA_DATA = "/opt/airflow/data/csv"
CONFIG_PATH = "/opt/airflow/DataPipeline/config_pipeline.json"

config = load_pipeline_config(CONFIG_PATH)

# Extração das chaves do JSON para distribuição nas tasks
tabelas_para_ingerir = config.get("ingestion_table", {}).get("using_csv", [])
db_config = config.get("database", {})
sanitization_params = config["sanitization"]

with DAG(
    dag_id="pipeline_orchestration",
    start_date=datetime(2026, 6, 24),
    schedule=None,
    catchup=False,
) as dag:
    # --- TASK DE INGESTÃO ---
    @task(task_id="ingest_csv_source", pool="pool_ingestao")
    def task_ingest(
        config_tabela: dict, conn_id: str, pasta_origem: str, config: dict
    ):

        nome_tabela = config_tabela["table_name"]

        print(f"Iniciando carga da tabela '{nome_tabela}'...")

        run_csv_ingestion(
            pasta_origem=pasta_origem,
            table_name=nome_tabela,
            conn_id=conn_id,
            config=config,
        )

    @task
    def task_criar_indices(conn_id: str, config: dict):
        """Cria os índices de performance antes de rodar os SQLs de limpeza"""
        run_create_indexes(conn_id, config)

    # --- TASKS DE HIGIENIZAÇÃO ---
    @task(task_id="task_sanitize_installments", pool="pool_sanitization")
    def task_sanitize_installments(conn_id: str, input_t: str, output_t: str):
        run_installments_sanitization(conn_id, input_t, output_t)

    @task(task_id="task_sanitize_app", pool="pool_sanitization")
    def task_sanitize_app(
        conn_id: str, input_t: str, output_t: str, min_freq: int, winsor_q: float
    ):
        """Sanitiza application_train usando parâmetros explícitos (sem chunk_size)"""
        run_sanitization(conn_id, input_t, output_t, min_freq, winsor_q)

    @task(task_id="task_sanitize_prev", pool="pool_sanitization")
    def task_sanitize_prev(conn_id: str, input_t: str, output_t: str):
        run_prev_sanitization(conn_id, input_t, output_t)

    @task(task_id="task_sanitize_bureau", pool="pool_sanitization")
    def task_sanitize_bureau(conn_id: str, input_t: str, output_t: str):
        run_bureau_sanitization(conn_id, input_t, output_t)

    @task
    def task_abt_indexes(conn_id: str, config: dict):
        """Cria os índices nas tabelas_clean preparatórias para a ABT."""
        run_abt_indexes(conn_id, config)

    # --- TASKS INTERMEDIÁRIAS PARA AGREGACAO (PROCESSADAS VIA SQL NO BANCO) ---
    @task(task_id="agg_intermediate_prev", pool="pool_aggregation")
    def task_agg_prev(conn_id: str, out_tb: str):
        create_agg_previous_application(conn_id, out_tb)

    @task(task_id="agg_intermediate_bureau", pool="pool_aggregation")
    def task_agg_bureau(conn_id: str, out_tb: str):
        create_agg_bureau(conn_id, out_tb)

    @task(task_id="agg_intermediate_installments", pool="pool_aggregation")
    def task_agg_inst(conn_id: str, out_tb: str):
        create_agg_installments(conn_id, out_tb)

    # --- TASK DA CONSTRUÇÃO DA ABT EM LOTES ---
    @task(task_id="generate_analytical_base_table")
    def task_abt_final_generation(conn_id: str, config: dict):
        """Gera a ABT final via ELT."""
        run_abt_generation(conn_id, config)

    # --- TASK DE TREINAMENTO ---
    @task(task_id="train_machine_learning_model")
    def task_train(conn_id: str, abt_table: str):
        run_training_pipeline(conn_id=conn_id, abt_table=abt_table)

    # --- INSTANCIANDO AS TAREFAS ---
    carga_inicial = task_ingest.partial(
        conn_id=CONN_ID, pasta_origem=PASTA_DATA, config=config
    ).expand(config_tabela=tabelas_para_ingerir)

    cria_indices = task_criar_indices(CONN_ID, config)
    
    limpeza_installments = task_sanitize_installments(
        conn_id=CONN_ID,
        input_t=db_config.get("input_installments_table"),
        output_t=db_config.get("output_installments_table"),
    )

    limpeza_app = task_sanitize_app(
        conn_id=CONN_ID,
        input_t=db_config.get("input_table"),
        output_t=db_config.get("output_table"),
        min_freq=sanitization_params["cardinalidade_min_freq"],
        winsor_q=sanitization_params["income_winsor_q"],
    )

    limpeza_prev = task_sanitize_prev(
        conn_id=CONN_ID,
        input_t=db_config.get("input_prev_table"),
        output_t=db_config.get("output_prev_table"),
    )

    limpeza_bureau = task_sanitize_bureau(
        conn_id=CONN_ID,
        input_t=db_config.get("input_bureau_table"),
        output_t=db_config.get("output_bureau_table"),
    )
    
    t_abt_index = task_abt_indexes(CONN_ID, config)
    t_inst = task_agg_inst(CONN_ID, db_config.get("output_installments_table"))
    t_prev = task_agg_prev(CONN_ID, db_config.get("output_prev_table"))
    t_bureau = task_agg_bureau(CONN_ID, db_config.get("output_bureau_table"))
    t_abt_final = task_abt_final_generation(CONN_ID, db_config)

    treino_modelo = task_train(CONN_ID, db_config.get("abt_table"))

    # --- DEFINIÇÃO DO FLUXO (DEPENDÊNCIAS) ---
    (
        carga_inicial
        >> cria_indices
        >> [limpeza_installments, limpeza_app, limpeza_prev, limpeza_bureau]
        >> t_abt_index
    )
    t_abt_index >> [t_prev, t_bureau, t_inst] >> t_abt_final >> treino_modelo
