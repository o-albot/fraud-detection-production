import os
import logging
from fastapi import FastAPI, HTTPException
import mlflow
from mlflow.tracking import MlflowClient
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
import boto3
import io
import tempfile
import joblib
import json

app = FastAPI(title="Model Trainer")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio123")
BUCKET_NAME = os.getenv("BUCKET_NAME", "mlops-bucket")

def get_minio_client():
    """Возвращает клиент MinIO"""
    return boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        use_ssl=False
    )

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/train")
def train():
    """Запускает обучение модели и сохраняет champion в MinIO"""
    logger.info("🚀 Starting model training...")
    try:
        # 1. Загрузка данных из MinIO
        logger.info("📥 Loading data from MinIO...")
        s3 = get_minio_client()

        response = s3.get_object(Bucket=BUCKET_NAME, Key="data/train.csv")
        df = pd.read_csv(io.BytesIO(response['Body'].read()))
        logger.info(f"✅ Data loaded. Shape: {df.shape}")

        # 2. Подготовка данных
        feature_cols = ['amount', 'hour_of_day', 'day_of_week', 'distance_from_home',
                        'distance_from_last_transaction', 'ratio_to_median_purchase_price',
                        'repeat_retailer', 'used_chip', 'used_pin_number', 'online_order']

        X = df[feature_cols]
        y = df['fraud']

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        # 3. Настройка MLflow
        os.environ['AWS_ACCESS_KEY_ID'] = MINIO_ACCESS_KEY
        os.environ['AWS_SECRET_ACCESS_KEY'] = MINIO_SECRET_KEY
        os.environ['MLFLOW_S3_ENDPOINT_URL'] = MINIO_ENDPOINT
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment("fraud_detection_retraining")
        client = MlflowClient()

        # 4. Обучение модели
        with mlflow.start_run() as run:
            params = {
                'n_estimators': 100,
                'max_depth': 10,
                'random_state': 42,
                'n_jobs': -1
            }
            mlflow.log_params(params)

            model = RandomForestClassifier(**params)
            model.fit(X_train, y_train)

            y_pred = model.predict(X_test)
            metrics = {
                'accuracy': accuracy_score(y_test, y_pred),
                'precision': precision_score(y_test, y_pred),
                'recall': recall_score(y_test, y_pred),
                'f1': f1_score(y_test, y_pred)
            }
            mlflow.log_metrics(metrics)

            for feat, imp in zip(feature_cols, model.feature_importances_):
                mlflow.log_metric(f"importance_{feat}", imp)

            # Сохранение модели как артефакт в MLflow
            with tempfile.TemporaryDirectory() as tmpdir:
                model_path = f"{tmpdir}/model.pkl"
                joblib.dump(model, model_path)
                mlflow.log_artifact(model_path, artifact_path="model")

            logger.info(f"✅ Model trained. Run ID: {run.info.run_id}")
            logger.info(f"📊 Metrics: {metrics}")

        # 5. Регистрация модели в MLflow Model Registry
        model_name = "fraud_detection_model"
        model_uri = f"runs:/{run.info.run_id}/model"
        
        registered_version = None
        try:
            # Проверяем, существует ли модель
            try:
                client.get_registered_model(model_name)
                logger.info(f"📦 Model {model_name} already exists")
            except:
                # Если нет, создаем
                client.create_registered_model(model_name)
                logger.info(f"✅ Created model {model_name}")
            
            # Создаем новую версию
            result = client.create_model_version(
                name=model_name,
                source=model_uri,
                run_id=run.info.run_id
            )
            registered_version = result.version
            logger.info(f"✅ Created version {registered_version} for model {model_name}")
            
            # Устанавливаем алиас champion
            try:
                client.set_registered_model_alias(model_name, "champion", registered_version)
                logger.info(f"✅ Set alias 'champion' to version {registered_version}")
            except Exception as e:
                logger.warning(f"⚠️ Could not set alias: {e}")
                # Альтернативный способ - через теги
                client.set_model_version_tag(model_name, registered_version, "alias", "champion")
                logger.info(f"✅ Set tag 'alias=champion' on version {registered_version}")
                
        except Exception as e:
            logger.error(f"❌ Failed to register model in MLflow: {e}")

        # 6. Сохраняем champion модель в MinIO для API
        if registered_version:
            try:
                logger.info("📦 Saving champion model to MinIO for API...")
                
                # Сохраняем саму модель (не pyfunc обертку)
                with tempfile.TemporaryDirectory() as tmpdir:
                    # Просто сохраняем модель напрямую, не через mlflow.pyfunc.load_model
                    champion_path = f"{tmpdir}/champion.pkl"
                    joblib.dump(model, champion_path)  # model уже есть из обучения
                    
                    # Загружаем в MinIO
                    s3.upload_file(
                        Filename=champion_path,
                        Bucket=BUCKET_NAME,
                        Key="models/champion.pkl"
                    )
                    logger.info(f"✅ Champion model saved to MinIO: {BUCKET_NAME}/models/champion.pkl")
                    
                    # Сохраняем также метаданные
                    metadata = {
                        "run_id": run.info.run_id,
                        "version": registered_version,
                        "metrics": metrics,
                        "feature_columns": feature_cols,
                        "params": params
                    }
                    
                    metadata_path = f"{tmpdir}/champion_metadata.json"
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=2)
                    
                    s3.upload_file(
                        Filename=metadata_path,
                        Bucket=BUCKET_NAME,
                        Key="models/champion_metadata.json"
                    )
                    logger.info(f"✅ Champion metadata saved to MinIO")
                    
            except Exception as e:
                logger.error(f"❌ Failed to save champion model to MinIO: {e}")

        return {
            "status": "success",
            "run_id": run.info.run_id,
            "metrics": metrics,
            "model_version": registered_version,
            "champion_saved": registered_version is not None
        }
        
    except Exception as e:
        logger.error(f"❌ Training failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/champion/info")
def get_champion_info():
    """Возвращает информацию о текущей champion модели"""
    try:
        s3 = get_minio_client()
        
        # Пытаемся получить метаданные
        try:
            response = s3.get_object(Bucket=BUCKET_NAME, Key="models/champion_metadata.json")
            metadata = json.loads(response['Body'].read().decode('utf-8'))
            return metadata
        except s3.exceptions.NoSuchKey:
            return {"error": "No champion model found"}
            
    except Exception as e:
        logger.error(f"❌ Failed to get champion info: {e}")
        raise HTTPException(status_code=500, detail=str(e))