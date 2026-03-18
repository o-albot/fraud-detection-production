#!/bin/bash

set -e

echo "========================================="
echo "🚀 Развертывание Fraud Detection API в Minikube"
echo "========================================="

# Определяем пути относительно скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
K8S_BASE_DIR="$PROJECT_DIR/k8s/base"

echo "📁 Директория проекта: $PROJECT_DIR"
echo "📁 Директория манифестов: $K8S_BASE_DIR"
echo "========================================="

# Проверка наличия файлов
if [ ! -f "$K8S_BASE_DIR/namespace.yaml" ]; then
    echo "❌ Ошибка: Файл namespace.yaml не найден в $K8S_BASE_DIR"
    echo "   Содержимое директории:"
    ls -la "$K8S_BASE_DIR"
    exit 1
fi

# Проверка наличия Minikube
if ! command -v minikube &> /dev/null; then
    echo "❌ Minikube не установлен"
    exit 1
fi

# Проверка статуса Minikube
if ! minikube status | grep -q "host: Running"; then
    echo "🔄 Запуск Minikube..."
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

# Применение манифестов по порядку
echo -e "\n📦 Применение манифестов из $K8S_BASE_DIR:"

# 1. Namespace
echo "  1. Создание namespace..."
kubectl apply -f "$K8S_BASE_DIR/namespace.yaml"

# 2. ConfigMap
echo "  2. Применение ConfigMap..."
kubectl apply -f "$K8S_BASE_DIR/configmap.yaml"

# 3. Deployment
echo "  3. Применение Deployment..."
kubectl apply -f "$K8S_BASE_DIR/deployment.yaml"

# 4. Service
echo "  4. Применение Service..."
kubectl apply -f "$K8S_BASE_DIR/service.yaml"

# 5. HPA
echo "  5. Применение HorizontalPodAutoscaler..."
kubectl apply -f "$K8S_BASE_DIR/hpa.yaml"

echo -e "\n✅ Все манифесты применены!"

# Ожидание запуска подов
echo -e "\n⏳ Ожидание запуска подов..."
sleep 10
kubectl wait --for=condition=ready pod \
  -l app=fraud-detection-api \
  -n fraud-detection \
  --timeout=120s 2>/dev/null || echo "⚠️ Не все поды готовы, проверьте статус вручную"

# Проверка статуса
echo -e "\n📊 Статус подов:"
kubectl get pods -n fraud-detection

echo -e "\n📈 Статус HPA:"
kubectl get hpa -n fraud-detection

echo -e "\n🌐 Статус сервисов:"
kubectl get svc -n fraud-detection

# Проверка доступа к API через port-forward (надежнее чем NodePort)
echo -e "\n🔌 Настройка port-forward для доступа к API..."
kubectl port-forward -n fraud-detection svc/fraud-detection-api 8000:8000 &
PF_PID=$!
sleep 3

# Проверка работы API
echo -e "\n📝 Проверка работы API:"
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✅ API доступно локально через port-forward"
    HEALTH=$(curl -s http://localhost:8000/health)
    echo "   Ответ health: $HEALTH"
    
    INFO=$(curl -s http://localhost:8000/info)
    echo "   Ответ info: $INFO"
else
    echo "   ⚠️ API пока не отвечает, проверьте позже:"
    echo "      kubectl logs -n fraud-detection -l app=fraud-detection-api"
fi

# Остановка port-forward
kill $PF_PID 2>/dev/null

# Инструкции по доступу
echo -e "\n🌐 Способы доступа к API:"
echo "  1. Через port-forward (рекомендуется):"
echo "     kubectl port-forward -n fraud-detection svc/fraud-detection-api 8000:8000"
echo "     curl http://localhost:8000/health"
echo ""
echo "  2. Через NodePort (если настроен):"
MINIKUBE_IP=$(minikube ip)
echo "     curl http://$MINIKUBE_IP:$(kubectl get svc -n fraud-detection fraud-detection-api-lb -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "30080")"

echo -e "\n========================================="
echo "✅ Развертывание завершено!"
echo "========================================="
echo "📋 Полезные команды:"
echo "  kubectl get pods -n fraud-detection -w        # следить за подами"
echo "  kubectl logs -n fraud-detection -l app=fraud-detection-api  # логи"
echo "  kubectl get hpa -n fraud-detection -w         # следить за HPA"
echo "  kubectl delete namespace fraud-detection      # удалить все"
echo "========================================="