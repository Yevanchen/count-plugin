FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装git和procps（用于克隆和更新仓库，以及进程管理）
RUN apt-get update && apt-get install -y git procps && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 创建必要的目录
RUN mkdir -p /app/logs /app/repos

# 复制需要的文件
COPY count_plugins.py /app/
COPY requirements.txt /app/

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 设置定时任务（如果需要）
COPY cron-task /etc/cron.d/plugin-counter
RUN chmod 0644 /etc/cron.d/plugin-counter
RUN apt-get update && apt-get install -y cron && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 设置入口点
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"] 