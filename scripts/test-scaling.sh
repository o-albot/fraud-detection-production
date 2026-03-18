#!/bin/bash

NAMESPACE="fraud-detection"
SERVICE="fraud-detection-api"

echo "========================================="
echo "🧪 Тестирование масштабирования"
echo "========================================="

# Получение URL для доступа
kubectl port-forward -n $NAMESPACE svc/$SERVICE 8000:8000 &
PF_PID=$!
sleep 3

echo "🚀 Запуск генерации нагрузки..."
echo "Нажмите Ctrl+C для остановки"
echo ""

# Функция для отправки запросов
send_request() {
    while true; do
        curl -s -X POST http://localhost:8000/predict \
            -H "Content-Type: application/json" \
            -d '{
                "amount": 317.31,
                "hour_of_day": 15,
                "day_of_week": 6,
                "distance_from_home": 9.01,
                "distance_from_last_transaction": 2.84,
                "ratio_to_median_purchase_price": 0.39,
                "repeat_retailer": 1,
                "used_chip": 1,
                "used_pin_number": 0,
                "online_order": 0
            }' > /dev/null 2>&1
    done
}

# Запуск 10 параллельных процессов генерации нагрузки
for i in {1..10}; do
    send_request &
    PIDS[$i]=$!
    echo "  Запущен процесс $i"
done

# Мониторинг HPA
echo ""
echo "📊 Мониторинг HPA (нажмите Ctrl+C для остановки):"
echo "----------------------------------------"

while true; do
    clear
    echo "Время: $(date +%H:%M:%S)"
    echo "----------------------------------------"
    kubectl get hpa -n $NAMESPACE
    echo "----------------------------------------"
    echo "Поды:"
    kubectl get pods -n $NAMESPACE | grep fraud-detection-api
    sleep 5
done

# Очистка при остановке
cleanup() {
    echo ""
    echo "🛑 Остановка генерации нагрузки..."
    for pid in "${PIDS[@]}"; do
        kill $pid 2>/dev/null
    done
    kill $PF_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM
wait