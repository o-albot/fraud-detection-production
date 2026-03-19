from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import requests
import logging

default_args = {
    'owner': 'mlops',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def train_model():
    logger = logging.getLogger(__name__)
    logger.info("📞 Calling trainer service...")
    
    response = requests.post("http://trainer:8000/train", timeout=300)
    response.raise_for_status()
    result = response.json()
    
    logger.info(f"✅ Training completed: {result}")
    return result

dag = DAG(
    'fraud_detection_retraining',
    default_args=default_args,
    description='Periodic model retraining',
    schedule_interval='0 */6 * * *',
    catchup=False,
)

train_task = PythonOperator(
    task_id='train_model',
    python_callable=train_model,
    dag=dag,
)

## новый даг