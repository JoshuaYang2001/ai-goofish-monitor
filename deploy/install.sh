#!/usr/bin/env bash

set -Eeuo pipefail

DEFAULT_INSTALL_DIR="/opt/ai-goofish-monitor"
DEFAULT_IMAGE="joshuayang2001/ai-goofish-monitor:latest"
DEFAULT_HOST_PORT="8000"
BACKUP_RETENTION_COUNT="7"

ACTION="install"
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
APP_IMAGE="${APP_IMAGE:-$DEFAULT_IMAGE}"
HOST_PORT="${HOST_PORT:-$DEFAULT_HOST_PORT}"
WEB_USERNAME="${WEB_USERNAME:-admin}"
SKIP_DOCKER_INSTALL="${SKIP_DOCKER_INSTALL:-false}"

log() {
  printf '\033[32m[闲鱼监控]\033[0m %s\n' "$*"
}

warn() {
  printf '\033[33m[警告]\033[0m %s\n' "$*" >&2
}

fail() {
  printf '\033[31m[错误]\033[0m %s\n' "$*" >&2
  exit 1
}

show_help() {
  cat <<'EOF'
闲鱼监控一键部署脚本

用法：
  install.sh [install|update|start|stop|restart|status|logs|backup|render] [选项]

操作：
  install   首次安装或幂等地重新部署（默认）
  update    备份数据后拉取最新镜像并更新
  start     启动服务
  stop      停止服务
  restart   重启服务
  status    查看容器状态
  logs      持续查看容器日志
  backup    备份数据库、账号状态和配置
  render    只生成部署文件，不启动容器

选项：
  --dir PATH       安装目录，默认 /opt/ai-goofish-monitor
  --port PORT      Web 对外端口，默认 8000
  --image IMAGE    Docker 镜像
  --skip-docker-install  Docker 不存在时直接报错，不自动安装
  -h, --help       显示帮助

可通过环境变量预设：INSTALL_DIR、APP_IMAGE、HOST_PORT、WEB_USERNAME、
WEB_PASSWORD、AUTH_SECRET_KEY、SKIP_DOCKER_INSTALL。
EOF
}

if [[ $# -gt 0 && "${1:-}" != --* && "${1:-}" != "-h" ]]; then
  ACTION="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      [[ $# -ge 2 ]] || fail "--dir 缺少路径"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || fail "--port 缺少端口"
      HOST_PORT="$2"
      shift 2
      ;;
    --image)
      [[ $# -ge 2 ]] || fail "--image 缺少镜像名称"
      APP_IMAGE="$2"
      shift 2
      ;;
    --skip-docker-install)
      SKIP_DOCKER_INSTALL="true"
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      fail "未知参数：$1"
      ;;
  esac
done

case "$ACTION" in
  install|update|start|stop|restart|status|logs|backup|render) ;;
  *) fail "未知操作：$ACTION" ;;
esac

[[ "$HOST_PORT" =~ ^[0-9]+$ ]] || fail "端口必须是数字"
(( HOST_PORT >= 1 && HOST_PORT <= 65535 )) || fail "端口必须在 1 到 65535 之间"
[[ "$INSTALL_DIR" == /* ]] || fail "安装目录必须使用绝对路径"
[[ "$INSTALL_DIR" != "/" ]] || fail "安装目录不能是根目录"

ADMIN_SUDO=""
SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || fail "请使用 root 用户运行，或先安装 sudo"
  ADMIN_SUDO="sudo"
  writable_parent="$INSTALL_DIR"
  while [[ ! -e "$writable_parent" && "$writable_parent" != "/" ]]; do
    writable_parent="$(dirname "$writable_parent")"
  done
  if [[ ! -w "$writable_parent" ]]; then
    SUDO="$ADMIN_SUDO"
  fi
fi

compose() {
  if docker compose version >/dev/null 2>&1; then
    $SUDO docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    $SUDO docker-compose "$@"
  else
    fail "未找到 Docker Compose"
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return
  fi
  [[ "$SKIP_DOCKER_INSTALL" != "true" ]] || fail "未检测到 Docker 与 Compose"
  command -v curl >/dev/null 2>&1 || fail "自动安装 Docker 需要 curl"

  log "未检测到完整 Docker 环境，正在调用 Docker 官方安装脚本..."
  local installer
  installer="$(mktemp)"
  curl -fsSL https://get.docker.com -o "$installer"
  $ADMIN_SUDO sh "$installer"
  $ADMIN_SUDO rm -f "$installer"
  $ADMIN_SUDO systemctl enable --now docker 2>/dev/null || true
  docker compose version >/dev/null 2>&1 || fail "Docker Compose 安装失败"
}

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
  fi
}

validate_env_value() {
  local name="$1"
  local value="$2"
  [[ -n "$value" ]] || fail "$name 不能为空"
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || fail "$name 不能包含换行"
}

write_compose_file() {
  $SUDO tee "$INSTALL_DIR/compose.yaml" >/dev/null <<'YAML' || fail "无法写入 compose.yaml"
services:
  app:
    image: ${APP_IMAGE:-joshuayang2001/ai-goofish-monitor:latest}
    container_name: ai-goofish-monitor-app
    init: true
    pull_policy: always
    ports:
      - "${HOST_PORT:-8000}:8000"
    env_file:
      - .env
    environment:
      SERVER_PORT: 8000
      RUN_HEADLESS: "true"
      CONTROL_DATABASE_FILE: /app/data/control.sqlite3
      TENANT_DATA_ROOT: /app/data/tenants
    volumes:
      - ./.env:/app/.env
      - ./data:/app/data
      - ./state:/app/state
      - ./logs:/app/logs
      - ./images:/app/images
      - ./jsonl:/app/jsonl
      - ./price_history:/app/price_history
      - ./config.json:/app/config.json
    shm_size: "1gb"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "20m"
        max-file: "5"
    restart: unless-stopped
YAML
}

append_env_if_missing() {
  local key="$1"
  local value="$2"
  if ! $SUDO grep -q "^${key}=" "$INSTALL_DIR/.env"; then
    printf '%s=%s\n' "$key" "$value" | $SUDO tee -a "$INSTALL_DIR/.env" >/dev/null
  fi
}

write_env_file() {
  local env_file="$INSTALL_DIR/.env"
  local generated_password=""
  if [[ ! -f "$env_file" ]]; then
    local password="${WEB_PASSWORD:-}"
    local auth_secret="${AUTH_SECRET_KEY:-}"
    if [[ -z "$password" ]]; then
      password="$(generate_secret | cut -c1-20)"
      generated_password="$password"
    fi
    if [[ -z "$auth_secret" ]]; then
      auth_secret="$(generate_secret)"
    fi
    validate_env_value "WEB_USERNAME" "$WEB_USERNAME"
    validate_env_value "WEB_PASSWORD" "$password"
    validate_env_value "AUTH_SECRET_KEY" "$auth_secret"

    $SUDO tee "$env_file" >/dev/null <<EOF
APP_IMAGE=$APP_IMAGE
HOST_PORT=$HOST_PORT
SERVER_PORT=8000
WEB_USERNAME=$WEB_USERNAME
WEB_PASSWORD=$password
AUTH_SECRET_KEY=$auth_secret
DEFAULT_TENANT_ID=default
DEFAULT_TENANT_NAME=默认租户
CONTROL_DATABASE_FILE=/app/data/control.sqlite3
TENANT_DATA_ROOT=/app/data/tenants
RUN_HEADLESS=true
LOGIN_IS_EDGE=false
PCURL_TO_MOBILE=true
MAX_CONCURRENT_TASKS=1
MAX_TASKS=30
ITEM_ID_REQUEST_DELAY_MIN_SECONDS=3
ITEM_ID_REQUEST_DELAY_MAX_SECONDS=7
TASK_FAILURE_THRESHOLD=3
TASK_FAILURE_PAUSE_SECONDS=86400
TASK_RISK_CONTROL_PAUSE_SECONDS=3600
MONITORING_DATA_RETENTION_DAYS=90
TASK_LOG_RETENTION_DAYS=20
EOF
    $SUDO chmod 600 "$env_file"
  else
    append_env_if_missing APP_IMAGE "$APP_IMAGE"
    append_env_if_missing HOST_PORT "$HOST_PORT"
    append_env_if_missing ITEM_ID_REQUEST_DELAY_MIN_SECONDS "3"
    append_env_if_missing ITEM_ID_REQUEST_DELAY_MAX_SECONDS "7"
    append_env_if_missing TASK_RISK_CONTROL_PAUSE_SECONDS "3600"
    append_env_if_missing MONITORING_DATA_RETENTION_DAYS "90"
  fi

  if [[ -n "$generated_password" ]]; then
    GENERATED_WEB_PASSWORD="$generated_password"
  fi
}

prepare_files() {
  log "准备部署目录：$INSTALL_DIR"
  $SUDO mkdir -p "$INSTALL_DIR"/{data,state,logs,images,jsonl,price_history,backups} \
    || fail "无法创建部署目录"
  if [[ -f "${BASH_SOURCE[0]}" ]]; then
    script_source="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
    script_target="$INSTALL_DIR/install.sh"
    if [[ "$script_source" != "$script_target" ]]; then
      $SUDO install -m 755 "$script_source" "$script_target" \
        || fail "无法保存安装脚本"
    fi
  fi
  write_compose_file || fail "无法生成 Compose 配置"
  write_env_file || fail "无法生成环境配置"
  if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
    printf '[]\n' | $SUDO tee "$INSTALL_DIR/config.json" >/dev/null \
      || fail "无法创建 config.json"
  fi
}

backup_data() {
  [[ -d "$INSTALL_DIR" ]] || fail "部署目录不存在：$INSTALL_DIR"
  local backup_file="$INSTALL_DIR/backups/ai-goofish-$(date +%Y%m%d-%H%M%S).tar.gz"
  $SUDO mkdir -p "$INSTALL_DIR/backups"
  log "正在备份数据库、登录状态与配置..."
  $SUDO tar -czf "$backup_file" \
    -C "$INSTALL_DIR" \
    --exclude='backups' \
    .env compose.yaml config.json data state
  local backup_index=0
  while IFS= read -r old_backup; do
    backup_index=$((backup_index + 1))
    if (( backup_index > BACKUP_RETENTION_COUNT )); then
      $SUDO rm -f -- "$old_backup"
    fi
  done < <($SUDO find "$INSTALL_DIR/backups" -maxdepth 1 -type f -name 'ai-goofish-*.tar.gz' -print | sort -r)
  log "备份完成：$backup_file"
}

wait_for_health() {
  local health_url="http://127.0.0.1:${HOST_PORT}/health"
  log "等待服务健康检查：$health_url"
  for _ in {1..30}; do
    if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "$health_url" >/dev/null 2>&1; then
      log "服务已健康运行"
      return
    fi
    sleep 2
  done
  compose -f "$INSTALL_DIR/compose.yaml" --env-file "$INSTALL_DIR/.env" ps || true
  compose -f "$INSTALL_DIR/compose.yaml" --env-file "$INSTALL_DIR/.env" logs --tail=80 app || true
  fail "服务在 60 秒内未通过健康检查"
}

run_compose() {
  compose -f "$INSTALL_DIR/compose.yaml" --env-file "$INSTALL_DIR/.env" "$@"
}

case "$ACTION" in
  render)
    prepare_files
    log "部署文件已生成，未启动容器"
    ;;
  install)
    install_docker
    prepare_files
    run_compose pull
    run_compose up -d --remove-orphans
    wait_for_health
    ;;
  update)
    install_docker
    prepare_files
    backup_data
    run_compose pull
    run_compose up -d --remove-orphans
    wait_for_health
    ;;
  start)
    install_docker
    run_compose up -d
    wait_for_health
    ;;
  stop)
    install_docker
    run_compose down
    ;;
  restart)
    install_docker
    run_compose restart
    wait_for_health
    ;;
  status)
    install_docker
    run_compose ps
    ;;
  logs)
    install_docker
    run_compose logs -f --tail=200 app
    ;;
  backup)
    backup_data
    ;;
esac

if [[ "$ACTION" == "install" || "$ACTION" == "update" ]]; then
  log "访问地址：http://服务器IP:${HOST_PORT}"
  log "安装目录：$INSTALL_DIR"
  if [[ -n "${GENERATED_WEB_PASSWORD:-}" ]]; then
    warn "首次登录账号：$WEB_USERNAME"
    warn "首次登录密码：$GENERATED_WEB_PASSWORD"
    warn "请立即保存密码；它不会再次显示。"
  fi
  log "后续更新：bash $INSTALL_DIR/install.sh update"
fi
