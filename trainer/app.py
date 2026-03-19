import os
import logging
from fastapi import FastAPI, HTTPException
import mlflow
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
import boto3
import io
import tempfile
import joblib

app = FastAPI(title="Model Trainer")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio123")
BUCKET_NAME = os.getenv("BUCKET_NAME", "mlops-bucket")

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/train")
def train():
    """Запускает обучение модели"""
    logger.info("🚀 Starting model training...")
    try:
        # 1. Загрузка данных из MinIO
        logger.info("📥 Loading data from MinIO...")
        s3 = boto3.client(
            's3',
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            use_ssl=False
        )
        
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

        # 3. Настройка MLflow с переменными для MinIO
        os.environ['AWS_ACCESS_KEY_ID'] = MINIO_ACCESS_KEY
        os.environ['AWS_SECRET_ACCESS_KEY'] = MINIO_SECRET_KEY
        os.environ['MLFLOW_S3_ENDPOINT_URL'] = MINIO_ENDPOINT
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
        
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment("fraud_detection_retraining")

        # 4. Обучение и логирование
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

            # Предсказания
            y_pred = model.predict(X_test)

            # Метрики
            metrics = {
                'accuracy': accuracy_score(y_test, y_pred),
                'precision': precision_score(y_test, y_pred),
                'recall': recall_score(y_test, y_pred),
                'f1': f1_score(y_test, y_pred)
            }
            mlflow.log_metrics(metrics)
            
            # Важность признаков
            for feat, imp in zip(feature_cols, model.feature_importances_):
                mlflow.log_metric(f"importance_{feat}", imp)

            # Сохранение модели
            with tempfile.TemporaryDirectory() as tmpdir:
                model_path = f"{tmpdir}/model.pkl"
                joblib.dump(model, model_path)
                mlflow.log_artifact(model_path, artifact_path="model")
                
            logger.info(f"✅ Model trained. Run ID: {run.info.run_id}")
            logger.info(f"📊 Metrics: {metrics}")

        return {
            "status": "success", 
            "run_id": run.info.run_id, 
            "metrics": metrics
        }
    except Exception as e:
        logger.error(f"❌ Training failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))