"""
DAG для автоматической синхронизации DAG-ов из Git
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'mlops',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'git_sync_dags',
    default_args=default_args,
    description='Синхронизация DAG-ов из Git репозитория',
    schedule_interval='*/5 * * * *',  # Каждые 5 минут
    catchup=False,
    tags=['mlops', 'git-sync'],
)

sync_task = BashOperator(
    task_id='git_pull',
    bash_command='cd /opt/airflow/dags && git pull origin main',
    dag=dag,
)
