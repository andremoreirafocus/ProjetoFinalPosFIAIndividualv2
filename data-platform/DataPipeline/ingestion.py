import os
import pandas as pd
from infra.db import map_pandas_to_postgres_types, append_dataframe_to_postgres, log_row_count

def run_csv_ingestion(pasta_origem: str, table_name: str, conn, config: dict):
    """Executa a ingestão de um único arquivo em chunks controlados.

    O escopo da fonte e o ``chunk_size`` são resolvidos do objeto ``config`` já
    carregado — nenhum arquivo de configuração é lido aqui.
    """
    # 1. Resolve a definição da fonte no escopo de ingestão do config
    fontes = config["ingestion_table"]["using_csv"]
    por_nome = {f["table_name"]: f for f in fontes}
    if table_name not in por_nome:
        raise ValueError(
            f"A tabela '{table_name}' não está no escopo de ingestão do config: {list(por_nome)}"
        )
    definicao = por_nome[table_name]

    chunk_size = definicao["chunk_size"]

    if not os.path.exists(pasta_origem):
        raise FileNotFoundError(f"A pasta de origem {pasta_origem} não existe.")

    # 2. Localização flexível e resiliente do arquivo correspondente na pasta
    arquivo_alvo = None
    for arquivo in os.listdir(pasta_origem):
        nome_arq, extensao = os.path.splitext(arquivo)
        if nome_arq.lower().replace("-", "_").replace(" ", "_") == table_name.lower():
            arquivo_alvo = arquivo
            break
            
    if not arquivo_alvo:
        raise FileNotFoundError(f"Nenhum arquivo correspondente à tabela '{table_name}' foi encontrado em {pasta_origem}")
        
    caminho_completo = os.path.join(pasta_origem, arquivo_alvo)
    _, extensao = os.path.splitext(arquivo_alvo)

    print(f"[INGESTÃO] Processando '{arquivo_alvo}' para a tabela '{table_name}' em blocos de {chunk_size}...")

    # 3. Leitura resiliente de Encodings via Iterator (Chunks)
    try:
        chunks_iterator = pd.read_csv(caminho_completo, encoding='utf-8', chunksize=chunk_size)
        # Força um teste de leitura rápido no primeiro chunk para capturar erro de encoding antes do loop
        first_chunk = pd.read_csv(caminho_completo, encoding='utf-8', nrows=5)
    except UnicodeDecodeError:
        chunks_iterator = pd.read_csv(caminho_completo, encoding='latin-1', chunksize=chunk_size)

    # 4. Gravação de alta performance via COPY EXPERT estruturado por chunks
    is_first_chunk = True

    cursor = conn.cursor()
    
    try:
        for num_lote, chunk_df in enumerate(chunks_iterator):
            print(f"Processando e salvando lote #{num_lote + 1} para a tabela '{table_name}'...")
            
            # Se for o primeiro pedaço do arquivo, limpa a tabela antiga e cria o Schema novo
            if is_first_chunk:
                print(f"Reiniciando estrutura da tabela '{table_name}' no banco de dados...")
                cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')
                
                # Mapeia dinamicamente as colunas usando função do db.py
                colunas_sql = map_pandas_to_postgres_types(chunk_df)
                cursor.execute(f'CREATE TABLE "{table_name}" ({", ".join(colunas_sql)});')
                conn.commit()
                is_first_chunk = False
            
            append_dataframe_to_postgres(chunk_df, table_name, conn)

            log_row_count(cursor, table_name, "Saída")
            
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Falha crítica durante a ingestão por chunks da tabela {table_name}: {str(e)}")
    finally:
        cursor.close()

    print(f"Ingestão da tabela '{table_name}' concluída com sucesso")