# Airflow DAGs for Fraud Detection

This directory contains DAGs for:
- Periodic model retraining
- Git synchronization
- Model performance monitoring

## Structure
- `retrain_model.py` - Main DAG for model retraining
- `git-sync.py` - DAG for syncing DAGs from Git
- `monitoring.py` - DAG for monitoring model performance

## Requirements
- MLflow tracking server: http://mlflow:5000
- PostgreSQL connection configured
- Git access token for private repos
