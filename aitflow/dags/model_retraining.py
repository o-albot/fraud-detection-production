"""
DAG для периодического переобучения модели fraud-detection
с автоматической установкой зависимостей
"""

import subprocess
import sys

# ============================================
# АВТОМАТИЧЕСКАЯ УСТАНОВКА ЗАВИСИМОСТЕЙ
# ============================================
required_packages = ['mlflow', 'scikit-learn', 'pandas', 'numpy', 'boto3']

for package in required_packages:
    try:
        if package == 'scikit-learn':
            import sklearn
            print(f"✅ Пакет 'scikit-learn' уже установлен (версия {sklearn.__version__})")
        elif package == 'boto3':
            import boto3
            print(f"✅ Пакет 'boto3' уже установлен (версия {boto3.__version__})")
        else:
            module = __import__(package)
            print(f"✅ Пакет '{package}' уже установлен (версия {module.__version__})")
    except ImportError:
        print(f"📦 Устанавливаю пакет '{package}'...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            check=False,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"✅ Пакет '{package}' успешно установлен")
        else:
            print(f"❌ Ошибка установки пакета '{package}': {result.stderr}")
            raise Exception(f"Failed to install {package}")

print("="*50)
print("🚀 Все зависимости установлены, запускаем DAG")
print("="*50)

# ============================================
# ИМПОРТЫ ПОСЛЕ УСТАНОВКИ
# ============================================
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
import mlflow
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import io
import json
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================
# ПАРАМЕТРЫ DAG
# ============================================
default_args = {
    'owner': 'mlops',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# ============================================
# ФУНКЦИИ ДЛЯ ЗАДАЧ
# ============================================
def load_data_from_minio():
    """Загрузка данных из MinIO"""
    try:
        hook = S3Hook(aws_conn_id='minio_default')
        file_obj = hook.get_key('data/train.csv', bucket_name='mlops-bucket')
        df = pd.read_csv(io.BytesIO(file_obj.get()['Body'].read()))
        logger.info(f"📊 Загружено {len(df)} записей из MinIO")
        logger.info(f"📊 Колонки: {list(df.columns)}")
        return df
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки данных: {e}")
        raise

def train_model(**context):
    """Обучение модели и логирование в MLflow"""
    
    # Загрузка данных
    df = load_data_from_minio()
    
    # Подготовка признаков
    feature_cols = ['amount', 'hour_of_day', 'day_of_week', 'distance_from_home',
                    'distance_from_last_transaction', 'ratio_to_median_purchase_price',
                    'repeat_retailer', 'used_chip', 'used_pin_number', 'online_order']
    
    X = df[feature_cols]
    y = df['fraud']
    
    # Разделение на train/test
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    logger.info(f"📊 Размер обучающей выборки: {len(X_train)}")
    logger.info(f"📊 Размер тестовой выборки: {len(X_test)}")
    logger.info(f"📊 Доля целевого класса: {y.mean():.2%}")
    
    # Настройка MLflow
    mlflow.set_tracking_uri('http://mlflow:5000')
    mlflow.set_experiment('fraud_detection_retraining')
    
    # Параметры модели
    params = {
        'n_estimators': 100,
        'max_depth': 10,
        'random_state': 42,
        'n_jobs': -1
    }
    
    with mlflow.start_run() as run:
        # Логирование параметров
        mlflow.log_params(params)
        mlflow.log_param("train_size", len(X_train))
        mlflow.log_param("test_size", len(X_test))
        mlflow.log_param("features", feature_cols)
        
        # Обучение
        model = RandomForestClassifier(**params)
        model.fit(X_train, y_train)
        
        # Предсказания
        y_pred = model.predict(X_test)
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        
        # Метрики
        metrics = {
            'accuracy': accuracy_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred),
            'recall': recall_score(y_test, y_pred),
            'f1': f1_score(y_test, y_pred)
        }
        mlflow.log_metrics(metrics)
        
        # Логирование важности признаков
        for feat, imp in zip(feature_cols, model.feature_importances_):
            mlflow.log_metric(f"importance_{feat}", imp)
        
        # Логирование модели
        mlflow.sklearn.log_model(model, "model")
        
        logger.info(f"✅ Модель обучена. Run ID: {run.info.run_id}")
        logger.info(f"📊 Метрики: {metrics}")
        
        # Сохраняем run_id для следующих задач
        context['task_instance'].xcom_push(key='run_id', value=run.info.run_id)
        context['task_instance'].xcom_push(key='metrics', value=metrics)
        
        return run.info.run_id

def compare_with_champion(**context):
    """Сравнение с лучшей моделью"""
    
    mlflow.set_tracking_uri('http://mlflow:5000')
    client = mlflow.tracking.MlflowClient()
    
    new_metrics = context['task_instance'].xcom_pull(task_ids='train_model', key='metrics')
    new_f1 = new_metrics['f1']
    
    # Пытаемся получить champion модель
    try:
        champion_model = mlflow.pyfunc.load_model("models:/fraud_detection_model@champion")
        champion_run_id = champion_model.run_id
        champion_run = client.get_run(champion_run_id)
        champion_f1 = champion_run.data.metrics.get('f1', 0)
        logger.info(f"🏆 Champion model F1: {champion_f1:.4f}")
    except Exception as e:
        logger.info(f"🏆 No champion model found: {e}")
        champion_f1 = 0
    
    logger.info(f"🆕 New model F1: {new_f1:.4f}")
    
    if new_f1 > champion_f1:
        logger.info("✅ New model is better! Promoting to champion")
        context['task_instance'].xcom_push(key='promote', value=True)
        context['task_instance'].xcom_push(key='improvement', value=new_f1 - champion_f1)
    else:
        logger.info("❌ Champion remains better")
        context['task_instance'].xcom_push(key='promote', value=False)

def promote_to_champion(**context):
    """Регистрация новой модели как champion"""
    
    promote = context['task_instance'].xcom_pull(task_ids='compare_models', key='promote')
    
    if not promote:
        logger.info("⏭️ Skipping promotion")
        return
    
    mlflow.set_tracking_uri('http://mlflow:5000')
    client = mlflow.tracking.MlflowClient()
    
    run_id = context['task_instance'].xcom_pull(task_ids='train_model', key='run_id')
    improvement = context['task_instance'].xcom_pull(task_ids='compare_models', key='improvement')
    
    # Регистрация модели
    model_uri = f"runs:/{run_id}/model"
    registered_model = mlflow.register_model(model_uri, "fraud_detection_model")
    
    # Установка алиаса champion
    client.set_registered_model_alias("fraud_detection_model", "champion", registered_model.version)
    
    logger.info(f"✅ Model version {registered_model.version} promoted to champion")
    if improvement:
        logger.info(f"📈 Improvement: {improvement:.4f}")

# ============================================
# СОЗДАНИЕ DAG
# ============================================
dag = DAG(
    'fraud_detection_retraining',
    default_args=default_args,
    description='Периодическое переобучение модели fraud detection',
    schedule_interval='0 */6 * * *',  # Каждые 6 часов
    catchup=False,
    tags=['mlops', 'fraud-detection'],
)

# ============================================
# ЗАДАЧИ
# ============================================
train_task = PythonOperator(
    task_id='train_model',
    python_callable=train_model,
    provide_context=True,
    dag=dag,
)

compare_task = PythonOperator(
    task_id='compare_models',
    python_callable=compare_with_champion,
    provide_context=True,
    dag=dag,
)

promote_task = PythonOperator(
    task_id='promote_to_champion',
    python_callable=promote_to_champion,
    provide_context=True,
    dag=dag,
)

# ============================================
# ПОРЯДОК ВЫПОЛНЕНИЯ
# ============================================
train_task >> compare_task >> promote_task
