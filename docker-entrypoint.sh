#!/bin/bash
set -e

# 打印环境信息
echo "Starting Dify Plugin Counter container..."
echo "Current time: $(date)"

# 确保日志目录和文件存在
mkdir -p /app/logs
touch /app/logs/cron.log
echo "$(date): Container started" >> /app/logs/cron.log

# 启动cron服务
service cron start
echo "Cron service started"

# 检查是否需要立即运行
if [ "$1" = "run" ]; then
  echo "Running plugin counter now..."
  cd /app && python count_plugins.py
elif [ "$1" = "cron-only" ]; then
  echo "Container started in cron-only mode. Will run at scheduled times."
else
  # 默认操作：立即运行一次，然后保持容器运行以便按计划运行
  echo "Running plugin counter now and setting up for scheduled runs..."
  cd /app && python count_plugins.py
  
  # 保持容器运行（否则Docker会退出）
  echo "Initial run complete. Container will now run on schedule according to cron configuration."
  tail -f /app/logs/cron.log
fi

# 如果执行到这里，说明指定了运行一次后退出
echo "Execution complete." 