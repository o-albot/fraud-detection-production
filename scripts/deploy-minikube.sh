#!/bin/bash

set -e

echo "========================================="
echo "🚀 Развертывание Fraud Detection API в Minikube"
echo "========================================="

# Определение путей относительно скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
K8S_MINIKUBE_DIR="$PROJECT_DIR/k8s/minikube"
AITFLOW_DAGS_DIR="$PROJECT_DIR/aitflow/dags"

echo "📁 Директория проекта: $PROJECT_DIR"
echo "📁 Директория манифестов: $K8S_MINIKUBE_DIR"
echo "📁 Директория DAG-ов: $AITFLOW_DAGS_DIR"
echo "========================================="

# Проверка наличия манифестов
if [ ! -f "$K8S_MINIKUBE_DIR/namespace.yaml" ]; then
    echo "❌ Ошибка: Манифесты не найдены в $K8S_MINIKUBE_DIR"
    ls -la "$K8S_MINIKUBE_DIR"
    exit 1
fi

# Проверка наличия Minikube
if ! command -v minikube &> /dev/null; then
    echo "❌ Minikube не установлен"
    exit 1
fi

# Проверка статуса Minikube
if ! minikube status | grep -q "host: Running"; then
    echo "🔄 Запуск Minikube с достаточными ресурсами..."
    minikube start --cpus=4 --memory=8192 --driver=docker
fi

# Включение metrics-server
echo "📊 Включение metrics-server..."
minikube addons enable metrics-server

# Ожидание готовности metrics-server
echo "⏳ Ожидание запуска metrics-server..."
kubectl wait --namespace=kube-system \
  --for=condition=ready pod \
  --selector=k8s-app=metrics-server \
  --timeout=120s 2>/dev/null || echo "⚠️ Metrics-server не готов, продолжаем..."

# Применение манифестов в правильном порядке
echo -e "\n📦 Применение манифестов из $K8S_MINIKUBE_DIR:"

# 1. Namespace
echo "  1. Создание namespace..."
kubectl apply -f "$K8S_MINIKUBE_DIR/namespace.yaml"

# 2. PostgreSQL
echo "  2. Развертывание PostgreSQL..."
kubectl apply -f "$K8S_MINIKUBE_DIR/postgres.yaml"

# Ожидание PostgreSQL
echo "     ⏳ Ожидание запуска PostgreSQL..."
kubectl wait --for=condition=ready pod -l app=postgres -n fraud-detection --timeout=60s 2>/dev/null || echo "     ⚠️ PostgreSQL не готов, продолжаем..."

# 3. MLflow
echo "  3. Развертывание MLflow..."
kubectl apply -f "$K8S_MINIKUBE_DIR/mlflow.yaml"

# 4. Airflow
echo "  4. Развертывание Airflow..."
kubectl apply -f "$K8S_MINIKUBE_DIR/airflow.yaml"

# 5. Модель
echo "  5. Развертывание модели с HPA..."
kubectl apply -f "$K8S_MINIKUBE_DIR/deployment.yaml"
kubectl apply -f "$K8S_MINIKUBE_DIR/service.yaml"
kubectl apply -f "$K8S_MINIKUBE_DIR/hpa.yaml"

# Ожидание запуска подов
echo -e "\n⏳ Ожидание запуска всех подов (может занять до 2 минут)..."
sleep 10

# Проверка статуса подов
echo -e "\n📊 Статус подов в namespace fraud-detection:"
kubectl get pods -n fraud-detection

# Проверка HPA
echo -e "\n📈 Статус HPA:"
kubectl get hpa -n fraud-detection

# Проверка сервисов
echo -e "\n🌐 Статус сервисов:"
kubectl get svc -n fraud-detection

# Проверка доступности MLflow
echo -e "\n🔍 Проверка доступности MLflow..."
kubectl port-forward -n fraud-detection svc/mlflow 5000:5000 &
MLFLOW_PF_PID=$!
sleep 3
if curl -s http://localhost:5000/health > /dev/null 2>&1; then
    echo "   ✅ MLflow доступен"
else
    echo "   ⚠️ MLflow пока не отвечает"
fi
kill $MLFLOW_PF_PID 2>/dev/null

# Проверка доступности Airflow
echo -e "\n🔍 Проверка доступности Airflow..."
kubectl port-forward -n fraud-detection svc/airflow 8080:8080 &
AIRFLOW_PF_PID=$!
sleep 3
if curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "   ✅ Airflow доступен"
else
    echo "   ⚠️ Airflow пока не отвечает"
fi
kill $AIRFLOW_PF_PID 2>/dev/null

# Проверка доступности модели
echo -e "\n🔍 Проверка доступности модели..."
kubectl port-forward -n fraud-detection svc/fraud-detection-api 8000:8000 &
MODEL_PF_PID=$!
sleep 3
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✅ Модель доступна"
    HEALTH=$(curl -s http://localhost:8000/health)
    echo "   Ответ health: $HEALTH"
else
    echo "   ⚠️ Модель пока не отвечает"
fi
kill $MODEL_PF_PID 2>/dev/null

# Инструкции по доступу
echo -e "\n========================================="
echo "✅ Развертывание завершено!"
echo "========================================="
echo -e "\n🌐 Доступ к сервисам:"

# Получение IP Minikube
MINIKUBE_IP=$(minikube ip)

echo ""
echo "📌 Для доступа к сервисам используйте port-forward:"
echo ""
echo "  MLflow:"
echo "    kubectl port-forward -n fraud-detection svc/mlflow 5000:5000"
echo "    http://localhost:5000"
echo ""
echo "  Airflow:"
echo "    kubectl port-forward -n fraud-detection svc/airflow 8080:8080"
echo "    http://localhost:8080 (admin/admin)"
echo ""
echo "  Модель:"
echo "    kubectl port-forward -n fraud-detection svc/fraud-detection-api 8000:8000"
echo "    curl http://localhost:8000/health"
echo "    curl http://localhost:8000/info"
echo ""
echo "  NodePort (прямой доступ):"
echo "    Модель: http://$MINIKUBE_IP:$(kubectl get svc -n fraud-detection fraud-detection-api-lb -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null)"
echo "    Airflow: http://$MINIKUBE_IP:$(kubectl get svc -n fraud-detection airflow -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null)"
echo "    MLflow: http://$MINIKUBE_IP:$(kubectl get svc -n fraud-detection mlflow -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null)"
echo ""
echo "📋 Полезные команды:"
echo "  kubectl get pods -n fraud-detection -w              # следить за подами"
echo "  kubectl logs -n fraud-detection -l app=airflow -c webserver  # логи Airflow"
echo "  kubectl logs -n fraud-detection -l app=mlflow       # логи MLflow"
echo "  kubectl logs -n fraud-detection -l app=postgres     # логи PostgreSQL"
echo "  kubectl delete namespace fraud-detection            # удалить все"
echo "========================================="