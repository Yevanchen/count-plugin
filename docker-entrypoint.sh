#!/bin/bash
set -e

echo "Starting Dify Plugin Counter container..."

# 确保目录和文件存在
mkdir -p /app/logs /app/data
touch /app/logs/cron.log

# 设置cron任务权限
chmod 0644 /etc/cron.d/plugin-counter
crontab /etc/cron.d/plugin-counter

# 启动cron服务
service cron start

if [ "$1" = "run" ]; then
    cd /app && python count_plugins.py
    exit 0
elif [ "$1" = "cron-only" ]; then
    echo "Starting in cron mode..."
else
    cd /app && python count_plugins.py
fi

# 保持容器运行并监控cron服务
while true; do
    if ! service cron status > /dev/null 2>&1; then
        echo "Cron service died, restarting..."
        service cron restart
    fi
    sleep 60
done