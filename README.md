# 闲鱼商品监控系统

[English README](README_EN.md)

基于 Playwright 的多租户闲鱼商品监控工具，提供规则匹配、指定商品 ID 批量监控、指标变化和通知推送。


## 核心特性

- **Web 可视化管理**: 任务、账号、运行日志、结果和指标变化统一管理
- **本地规则匹配**: 使用关键词规则判断结果，不依赖外部模型服务
- **指定 ID 监控**: 一次输入多个商品 ID，直接批量加入监控
- **24/48 小时变化**: 查看 1/3/6/12/24/48/72 小时及自定义窗口的价格、想要数变化
- **高级筛选**: 包邮、新发布时间范围、省/市/区三级区域筛选
- **即时通知**: 支持 ntfy.sh、企业微信、Bark、Telegram、Webhook
- **定时调度**: Cron 表达式配置周期性任务
- **账号与代理轮换**: 多账号管理、任务绑定账号、代理池轮换与失败重试
- **Docker 部署**: 一键容器化部署

## 截图

![监控概览](static/img.png)
![任务管理](static/img_1.png)
![结果查看](static/img_2.png)
![通知推送](static/img_3.png)

## 🐳 Docker 部署（推荐）

```bash
git clone https://github.com/Usagi-org/ai-goofish-monitor && cd ai-goofish-monitor
cp .env.example .env
vim .env # 填写相关配置项
docker compose up -d
docker compose logs -f app
docker compose down
```

如果镜像无法访问或下载速度慢，可尝试使用加速：
```bash

docker pull ghcr.nju.edu.cn/usagi-org/ai-goofish:latest
docker tag ghcr.nju.edu.cn/usagi-org/ai-goofish:latest ghcr.io/usagi-org/ai-goofish:latest
docker compose up -d

```

- 默认 Web UI 地址：`http://127.0.0.1:8000`
- Docker 镜像已内置 Chromium，无需宿主机额外安装浏览器。
- 官方镜像地址：`ghcr.io/usagi-org/ai-goofish:latest`
- 更新镜像：`docker compose pull && docker compose up -d`
- 如果你修改了 `.env` 中的 `SERVER_PORT`，请同步更新 `docker-compose.yaml` 里的端口映射。
- `docker-compose.yaml` 默认会把 SQLite 主库挂载到 `./data:/app/data`，数据库文件默认为 `data/app.sqlite3`
- 目前默认持久化这些目录：
    - `data/`  SQLite 主存储（任务、结果、价格历史）
    - `state/`  登录状态 cookie 文件
    - `logs/`  运行日志
    - `images/`  商品图片与任务临时图片目录
    - `config.json`、`jsonl/`、`price_history/`  首次升级到 SQLite 时用于兼容导入的旧数据源

### 数据存储与迁移

- 当前在线主存储为 SQLite，默认路径 `data/app.sqlite3`
- 可通过环境变量 `APP_DATABASE_FILE` 自定义数据库路径；Docker 默认设置为 `/app/data/app.sqlite3`
- 应用启动时会自动建库建表，并尝试从旧的 `config.json`、`jsonl/`、`price_history/` 导入一次历史数据
- `state/`、`logs/`、`images/` 仍然是文件系统目录，不在 SQLite 中
- 首次升级完成并确认 `data/app.sqlite3` 中数据正确后，可视部署方式决定是否继续保留旧的 `config.json`、`jsonl/`、`price_history/` 挂载

### 最少配置

| 变量 | 说明 | 必填 |
|------|------|------|
| `WEB_USERNAME` / `WEB_PASSWORD` | Web UI 登录账号密码，默认 `admin/admin123` | 否 |
| `AUTH_SECRET_KEY` | 多租户登录令牌签名密钥，生产环境至少 32 字符 | 是 |

其余配置见下方"配置说明"。


### 第一次使用

1. 打开默认 Web UI `http://127.0.0.1:8000` 并登录。
2. 进入"闲鱼账号管理"，使用 [Chrome 扩展](https://chromewebstore.google.com/detail/xianyu-login-state-extrac/eidlpfjiodpigmfcahkmlenhppfklcoa) 导出并粘贴闲鱼登录态 JSON。
3. 登录态文件会保存到 `state/` 目录，例如 `state/acc_1.json`。
4. 回到"任务管理"，创建任务并绑定账号后即可运行。

### 创建第一个任务

- `关键词监控`：填写搜索词和可选匹配规则；未填写规则时默认使用搜索词。
- `商品 ID 监控`：可用换行、空格或逗号输入多个数字 ID，系统去重后直接创建任务。
- `区域筛选`：已改为省 / 市 / 区三级选择器，数据基于闲鱼页面抓取快照内置。

### 通知推送规则

通知只由明确规则触发：

| 任务类型 | 通知触发条件 |
|----------|--------------|
| `关键词监控` | 商品标题、描述或卖家资料命中任一配置关键词 |
| `商品 ID 监控` | 成功获取指定 ID 的商品详情后直接通知 |

**配置建议：**
- 如果想监控某类商品，使用关键词任务并配置精准匹配词。
- 如果已经知道商品链接中的 ID，使用商品 ID 任务批量添加，避免额外生成步骤。



## 用户使用说明

<details>
<summary>点击展开 Web UI 功能说明</summary>

### 任务管理

- 支持关键词规则、商品 ID 批量添加、价格范围、新发布范围、区域筛选、账号绑定和定时规则。
- 区域筛选会显著缩小结果集，默认留空。

### 账号管理

- 支持导入、更新、删除闲鱼账号登录态。
- 每个任务可指定账号，也可不绑定并交给系统自动选择。

### 结果查看与运行日志

- 结果页和导出功能现在从 SQLite 查询，不再直接扫描 `jsonl` 文件。
- 日志页按任务展示运行过程，便于排查登录态失效和风控问题。

### 系统设置

- 可查看系统状态、配置飞书等通知渠道、调整代理与账号轮换。

</details>



## 开发者开发

### 环境要求

- Python 3.10+
- Node.js + npm（本地验证 `Node v20.18.3` 可完成前端构建）
- Playwright CLI 与 Chromium，首次运行前建议执行 `python3 -m pip install playwright && python3 -m playwright install chromium`
- Chrome / Edge 浏览器（Linux 环境也可使用 Chromium；`start.sh` 会先检查浏览器是否存在）

```bash
git clone https://github.com/Usagi-org/ai-goofish-monitor
cd ai-goofish-monitor
cp .env.example .env
```

### 一键启动

```bash
chmod +x start.sh
./start.sh
```

`start.sh` 会先检查 Playwright CLI 和浏览器前置条件；在前置条件满足后自动安装项目依赖、构建前端、复制构建产物并启动后端。

### 手动启动

```bash
# 后端
python -m src.app
# 或
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd web-ui
npm install
npm run dev
```

- FastAPI 启动时会自动初始化 SQLite，并在首次启动时尝试导入旧的 `config.json/jsonl/price_history`
- `spider_v2.py` 默认从 SQLite 读取任务；只有显式传入 `--config <path>` 时才会走 JSON 配置兼容模式
- 默认数据库路径为 `data/app.sqlite3`
- Vite 开发服务器会将 `/api`、`/auth`、`/ws` 代理到 `http://127.0.0.1:8000`。
- `npm run build` 先生成 `web-ui/dist/`，`start.sh` 再复制到仓库根目录 `dist/`。
- FastAPI 负责提供根目录 `dist/index.html` 和 `dist/assets/`。
- `./start.sh` 默认输出访问地址 `http://localhost:8000` 和 API 文档 `http://localhost:8000/docs`。

### 测试与校验

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest
cd web-ui && npm run build
```

### 任务创建 API

<details>
<summary>点击展开 API 行为说明</summary>

- `POST /api/tasks/`：直接创建关键词或商品 ID 任务。
- `GET /api/metrics/changes?interval=24&interval=48`：查询价格和想要数变化。
- `POST /auth/status`：校验 Web UI 登录凭据。

</details>

## 配置说明

<details>
<summary>点击展开常用配置项</summary>

### 运行时
- `RUN_HEADLESS`：是否以无头模式运行爬虫；Docker 中应保持 `true`。
- `SERVER_PORT`：后端监听端口，默认 `8000`。
- `LOGIN_IS_EDGE`：本地环境可切换为 Edge 内核；Docker 镜像未内置 Edge，容器内会固定使用 Chromium。
- `PCURL_TO_MOBILE`：是否将 PC 商品链接转换为移动端链接。
- `MAX_CONCURRENT_TASKS`：同时运行的定时爬虫数量，默认 `1`；小型服务器建议保持 `1`，资源充足时可设为 `2`。
- `MAX_TASKS`：每个租户最多允许创建的监控任务数量，默认 `30`。
- `MONITORING_DATA_RETENTION_DAYS`：价格快照和想要数/浏览量指标历史保留天数，默认 `20`；商品搜索结果会保留，用于结果展示和历史去重。
- `TASK_LOG_RETENTION_DAYS`：任务运行日志保留天数，默认 `20`。

### 通知

- `NTFY_TOPIC_URL`
- `GOTIFY_URL` / `GOTIFY_TOKEN`
- `BARK_URL`
- `WX_BOT_URL`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `TELEGRAM_API_BASE_URL`
- `WEBHOOK_*`

### 代理轮换与失败保护

- `PROXY_ROTATION_ENABLED`
- `PROXY_ROTATION_MODE`
- `PROXY_POOL`
- `PROXY_ROTATION_RETRY_LIMIT`
- `PROXY_BLACKLIST_TTL`
- `TASK_FAILURE_THRESHOLD`
- `TASK_FAILURE_PAUSE_SECONDS`
- `TASK_FAILURE_GUARD_PATH`

完整示例见 `.env.example`。

</details>

## Web 界面认证

<details>
<summary>点击展开认证说明</summary>

- Web UI 当前使用登录页收集账号密码，并通过 `POST /auth/status` 校验。
- 登录成功后，前端会在浏览器本地保存登录状态，用于路由守卫和 WebSocket 初始化。
- 默认账号密码为 `admin/admin123`，生产环境请务必修改。

</details>

## 🚀 工作流程

下图描述了单个监控任务从启动到完成的核心处理逻辑。主服务运行于 `src.app`，按用户操作或定时调度启动一个或多个任务进程。

```mermaid
graph TD
    A[启动监控任务] --> B[选择账号/代理配置];
    B --> C[任务：搜索商品];
    C --> D{发现新商品？};
    D -- 是 --> E[抓取商品详情 & 卖家信息];
    E --> F{任务类型};
    F -- 关键词 --> G[本地规则匹配];
    F -- 指定ID --> H[直接命中];
    G --> I{是否命中};
    H --> J[发送通知];
    I -- 是 --> J;
    I -- 否 --> K[仅保存记录];
    J --> K[保存记录和指标快照];
    D -- 否 --> L[翻页/等待];
    L --> C;
    K --> C;
    C --> M{触发风控/异常？};
    M -- 是 --> N[账号/代理轮换并重试];
    N --> C;
```

## 常见问题

<details>
<summary>点击展开常见问题</summary>

### 为什么商品 ID 任务会立即创建？

商品 ID 不再经过标准生成流程。前端完成格式校验和去重后，后端直接保存整批 ID。

### 区域筛选为什么默认建议留空？

区域筛选会显著减少搜索结果，适合明确只看某个区域的场景。若你先验证整体市场，建议先不填。

### 本地页面打开后提示前端构建产物不存在？

说明根目录 `dist/` 缺失。可直接执行 `./start.sh`，或先在 `web-ui/` 里执行 `npm run build`，再确认构建产物已复制到仓库根目录。

### `./start.sh` 为什么提示缺少 Playwright 或浏览器？

这是脚本的前置检查。请先安装 Playwright CLI 与 Chromium，并确保系统中可用 Chrome / Edge（Linux 环境也可用 Chromium），然后重新执行 `./start.sh`。

</details>



## 致谢

<details>
<summary>点击展开致谢内容</summary>

本项目在开发过程中参考了以下优秀项目，特此感谢：

- [superboyyy/xianyu_spider](https://github.com/superboyyy/xianyu_spider)

以及感谢 LinuxDo 相关人员的脚本贡献

- [@jooooody](https://linux.do/u/jooooody/summary)

以及感谢 [LinuxDo](https://linux.do/) 社区。

以及感谢 ClaudeCode/Gemini/Codex 等模型工具，解放双手 体验 Vibe Coding 的快乐。

</details>


## 注意事项

<details>
<summary>点击展开注意事项详情</summary>

- 请遵守闲鱼的用户协议和 robots.txt 规则，不要进行过于频繁的请求，以免对服务器造成负担或导致账号被限制。
- 本项目仅供学习和技术研究使用，请勿用于非法用途。
- 本项目采用 [MIT 许可证](LICENSE) 发布，按"现状"提供，不提供任何形式的担保。
- 项目作者及贡献者不对因使用本软件而导致的任何直接、间接、附带或特殊的损害或损失承担责任。
- 如需了解更多详细信息，请查看 [免责声明](DISCLAIMER.md) 文件。

</details>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Usagi-org/ai-goofish-monitor&type=Date)](https://www.star-history.com/#Usagi-org/ai-goofish-monitor&Date)

![Alt](https://repobeats.axiom.co/api/embed/b40d8a112271b4bddabadd8fe2635be3c1aa28a3.svg "Repobeats analytics image")
