# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

基于 Playwright + AI 的闲鱼智能监控机器人。FastAPI 后端 + Vue 3 前端，支持多任务并发监控、多模态 AI 商品分析、多渠道通知推送。

## 核心架构

```
API层 (src/api/routes/)
    ↓
服务层 (src/services/)
    ↓
领域层 (src/domain/)
    ↓
基础设施层 (src/infrastructure/)
```

关键入口：
- `src/app.py` - FastAPI 应用主入口
- `spider_v2.py` - 爬虫 CLI 入口
- `src/scraper.py` - Playwright 爬虫核心逻辑

服务层：
- `TaskService` - 任务 CRUD
- `ProcessService` - 爬虫子进程管理
- `SchedulerService` - APScheduler 定时调度
- `AIAnalysisService` - 多模态 AI 分析
- `NotificationService` - 多渠道通知（ntfy/Bark/企业微信/Telegram/Webhook）

前端 (`web-ui/`)：Vue 3 + Vite + shadcn-vue + Tailwind CSS

## 开发命令

```bash
# 后端开发
python -m src.app
# 或
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

# 前端开发
cd web-ui && npm install && npm run dev

# 前端构建
cd web-ui && npm run build

# 一键本地启动（构建前端 + 启动后端）
bash start.sh

# Docker 部署
docker compose up --build -d
```

## 爬虫命令

```bash
python spider_v2.py                          # 运行所有启用任务
python spider_v2.py --task-name "MacBook"    # 运行指定任务
python spider_v2.py --debug-limit 3          # 调试模式，限制商品数
python spider_v2.py --config custom.json     # 自定义配置文件
```

## 测试

```bash
pytest                              # 运行所有测试
pytest --cov=src                    # 覆盖率报告
pytest tests/unit/test_utils.py    # 运行单个测试文件
pytest tests/unit/test_utils.py::test_safe_get  # 运行单个测试函数
```

测试规范：文件 `tests/**/test_*.py`，函数 `test_*`

## 配置

环境变量 (`.env`)：
- AI 模型：`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL_NAME`
- 通知：`NTFY_TOPIC_URL`, `BARK_URL`, `WX_BOT_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FEISHU_WEBHOOK_URL`, `DINGTALK_WEBHOOK_URL`
- 爬虫：`RUN_HEADLESS`, `LOGIN_IS_EDGE`
- Web 认证：`WEB_USERNAME`, `WEB_PASSWORD`
- 端口：`SERVER_PORT`

任务配置 (`config.json`)：定义监控任务（关键词、价格范围、cron 表达式、AI prompt 文件等）

## 数据流

1. Web UI / config.json 创建任务
2. SchedulerService 按 cron 触发或手动启动
3. ProcessService 启动 spider_v2.py 子进程
4. scraper.py 使用 Playwright 抓取商品
5. AIAnalysisService 调用多模态模型分析
6. NotificationService 推送符合条件的商品
7. 结果存储：`jsonl/`（数据）、`images/`（图片）、`logs/`（日志）

## 新增功能（v2.1+）

### 商家维度监控
- 服务：`SellerMonitoringService` (`src/services/seller_monitoring_service.py`)
- API：`/api/sellers/*`
- 功能：卖家黑名单/白名单、卖家信息采集、店铺商品监控

### 商品 ID 精确搜索
- 方法：`scrape_item_by_id()` in `src/scraper.py`
- API：`POST /api/sellers/search/item-id`
- 历史记录存储在 `search_history` 表

### 指标追踪（价格/想要数）
- 服务：`MetricsTrackingService` (`src/services/metrics_tracking_service.py`)
- API：`/api/metrics/item/{item_id}/*`
- 自动记录每次爬取的价格和想要数，支持变化检测

### 通知渠道扩展
- 飞书：`FeishuClient` (`src/infrastructure/external/notification_clients/feishu_client.py`)
- 钉钉：`DingtalkClient` (`src/infrastructure/external/notification_clients/dingtalk_client.py`)
- 内置重试机制（3 次，指数退避）

### PWA 支持
- 前端：`web-ui/vite.config.ts` 配置 `vite-plugin-pwa`
- 安装提示组件：`web-ui/src/components/PWAInstallPrompt.vue`
- 构建后生成 `dist/manifest.webmanifest` 和 Service Worker

## 数据库表

新增表（`src/infrastructure/persistence/sqlite_connection.py`）：
- `seller_info` - 卖家信息（ID、昵称、芝麻信用等）
- `item_metrics_history` - 商品指标历史（价格、想要数、浏览量）
- `seller_list` - 卖家黑名单/白名单
- `search_history` - 商品 ID 搜索历史

## 注意事项

- AI 模型必须支持图片上传（多模态）
- Docker 部署需通过 Web UI 手动更新登录状态（`state.json`）
- 遇到滑动验证码时设置 `RUN_HEADLESS=false` 手动处理
- 生产环境务必修改默认 Web 认证密码
- PWA 功能需要 HTTPS 环境（本地开发除外）
