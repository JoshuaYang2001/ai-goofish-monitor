# 生产环境一键部署

默认镜像：`joshuayang2001/ai-goofish-monitor:latest`

## 新服务器一键安装

适用于主流 Linux 服务器。建议至少 2 核 CPU、4 GB 内存和 20 GB 可用磁盘。

```bash
curl -fsSL https://raw.githubusercontent.com/JoshuaYang2001/ai-goofish-monitor/master/deploy/install.sh \
  -o /tmp/ai-goofish-install.sh
sudo bash /tmp/ai-goofish-install.sh install
```

脚本会自动完成：

- 检查并按需安装 Docker 与 Compose；
- 创建 `/opt/ai-goofish-monitor` 及持久化目录；
- 自动生成管理员密码和认证密钥；
- 拉取多架构镜像并启动服务；
- 配置健康检查、自动重启、日志轮转和 Chromium 共享内存；
- 等待 `/health` 检查通过后输出访问地址。

可以用环境变量自定义：

```bash
sudo HOST_PORT=9000 \
  WEB_USERNAME=admin \
  WEB_PASSWORD='请替换为强密码' \
  bash /tmp/ai-goofish-install.sh install
```

不要把真实密码写进仓库、聊天记录或公开脚本。

## 更新、备份和排查

安装完成后把脚本保存到部署目录，或重新下载脚本执行：

```bash
# 更新前自动备份，再拉取 latest
sudo bash /opt/ai-goofish-monitor/install.sh update

# 单独备份数据库、账号状态和配置
sudo bash /opt/ai-goofish-monitor/install.sh backup

# 查看状态或日志
sudo bash /opt/ai-goofish-monitor/install.sh status
sudo bash /opt/ai-goofish-monitor/install.sh logs
```

备份保存在 `/opt/ai-goofish-monitor/backups/`，默认保留最近 7 份。

## 1Panel 部署

在 1Panel 的“容器 → 编排”中使用仓库根目录的 `docker-compose.yaml`，并在同一目录准备 `.env`、`config.json` 以及这些持久化目录：

```text
data/  state/  logs/  images/  jsonl/  price_history/
```

更新时先备份 `data/` 和 `state/`，然后在 1Panel 中执行“拉取镜像”与“重建”。不要删除宿主机上的持久化目录。

## 防火墙与 HTTPS

- 只需放行实际使用的 `HOST_PORT`，默认 TCP 8000。
- 公网生产环境建议通过 1Panel/OpenResty 配置域名、HTTPS 和访问限制。
- 不建议把 Docker API、数据库文件或 `/opt/ai-goofish-monitor` 目录暴露到公网。
