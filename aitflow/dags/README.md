# Airflow DAGs for Fraud Detection

## DAG: fraud_detection_retraining
Периодическое переобучение модели каждые 6 часов.

### Что делает:
1. Загружает данные из MinIO (`mlops-bucket/data/train.csv`)
2. Обучает RandomForest модель
3. Логирует метрики в MLflow
4. Сравнивает с champion моделью
5. Если лучше - регистрирует новую версию
6. Сохраняет модель в MinIO (`mlops-bucket/models/champion.pkl`)

### Требования:
- Подключение к MinIO: `minio_default`
- MLflow tracking URI: `http://mlflow:5000`
