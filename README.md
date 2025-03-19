# Dify 插件计数器

这个Docker镜像用于定期统计Dify社区和官方插件仓库中的插件数量，并将结果发送到飞书群组。

## 功能特点

- 自动克隆并更新Dify插件仓库
- 统计社区和官方插件数量
- 计算24小时内新增的插件数量
- 将结果通过飞书webhook发送通知
- 支持定时自动运行

## 使用方法

### 本地运行

使用docker-compose运行容器：

```bash
# 修改docker-compose.yml中的飞书webhook地址
# 然后启动容器
docker-compose up -d
```

### AWS ECS部署

1. 构建并推送镜像到ECR：

```bash
# 登录到ECR
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <aws-account-id>.dkr.ecr.<region>.amazonaws.com

# 构建镜像
docker build -t plugin-counter .

# 标记镜像
docker tag plugin-counter:latest <aws-account-id>.dkr.ecr.<region>.amazonaws.com/plugin-counter:latest

# 推送镜像
docker push <aws-account-id>.dkr.ecr.<region>.amazonaws.com/plugin-counter:latest
```

2. 在ECS控制台创建任务定义和服务，设置环境变量：

- `FEISHU_WEBHOOK`: 飞书机器人webhook地址
- `LOGS_DIR`: 日志目录，默认 `/app/logs`
- `REPOS_DIR`: 仓库存储目录，默认 `/app/repos`
- `DATA_DIR`: 数据存储目录，默认 `/app/data`

### AWS Lambda部署（定时触发）

在Lambda中，可以使用Container Image部署方式：

1. 在ECS任务定义中添加命令 `run`，使容器在完成任务后退出
2. 使用EventBridge（CloudWatch Events）设置定时触发

## 环境变量配置

| 环境变量 | 描述 | 默认值 |
|---------|------|-------|
| FEISHU_WEBHOOK | 飞书webhook URL | 默认webhook |
| LOGS_DIR | 日志存储目录 | /app/logs |
| REPOS_DIR | Git仓库存储目录 | /app/repos |
| DATA_DIR | 数据文件存储目录 | /app/data |

## 运行模式

容器支持三种运行模式：

1. 默认模式（无参数）：立即运行一次，然后保持容器运行，按计划执行
2. 运行一次模式（`run`）：运行一次后退出，适合Lambda或批处理任务
3. 仅定时模式（`cron-only`）：不立即运行，仅设置定时任务

例如：
```bash
# 运行一次后退出
docker run plugin-counter run

# 仅设置定时任务
docker run -d plugin-counter cron-only
```

## 数据持久化

为了持久化数据，可以挂载以下目录：

- `/app/logs`: 日志文件
- `/app/data`: 历史数据
- `/app/repos`: Git仓库（可选，如果不挂载则每次都会重新克隆）

使用AWS ECS时，可以使用EFS挂载点来持久化这些目录。 