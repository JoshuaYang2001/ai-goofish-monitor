import asyncio
import json
import os
import random
from datetime import datetime
from typing import Optional, Dict, List
from urllib.parse import urlencode

from playwright.async_api import (
    Response,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from src.config import (
    DEBUG_MODE,
    DETAIL_API_URL_PATTERN,
    LOGIN_IS_EDGE,
    RUN_HEADLESS,
    RUNNING_IN_DOCKER,
    get_state_file,
)
from src.parsers import (
    _parse_search_results_json,
    _parse_user_items_data,
    calculate_reputation_from_ratings,
    parse_ratings_data,
    parse_user_head_data,
)
from src.utils import (
    format_registration_days,
    get_link_unique_key,
    log_time,
    random_sleep,
    safe_get,
    save_to_jsonl,
)
from src.rotation import RotationPool, load_state_files, parse_proxy_pool, RotationItem
from src.failure_guard import FailureGuard
from src.services.account_strategy_service import resolve_account_runtime_plan
from src.infrastructure.persistence.storage_names import build_result_filename
from src.services.item_analysis_dispatcher import (
    ItemAnalysisDispatcher,
    ItemAnalysisJob,
    parse_metric_count,
)
from src.services.price_history_service import (
    build_market_reference,
    load_price_snapshots,
    parse_price_value,
    record_market_snapshots,
)
from src.services.result_storage_service import load_processed_link_keys
from src.services.seller_profile_cache import SellerProfileCache
from src.services.search_pagination import (
    advance_search_page,
    is_search_results_response,
)
from src.services.notification_service import build_notification_service


class RiskControlError(Exception):
    pass


class LoginRequiredError(Exception):
    """Raised when Goofish redirects to the passport/mini_login flow."""


FAILURE_GUARD = FailureGuard()
EDGE_DOCKER_WARNING_PRINTED = False


def _is_login_url(url: str) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return "passport.goofish.com" in lowered or "mini_login" in lowered


def _resolve_browser_channel() -> str:
    global EDGE_DOCKER_WARNING_PRINTED
    if RUNNING_IN_DOCKER:
        if LOGIN_IS_EDGE and not EDGE_DOCKER_WARNING_PRINTED:
            print(
                "检测到 LOGIN_IS_EDGE=true，但 Docker 镜像未内置 Edge，"
                "任务运行时将改用 Chromium。"
            )
            EDGE_DOCKER_WARNING_PRINTED = True
        return "chromium"
    return "msedge" if LOGIN_IS_EDGE else "chrome"


async def _send_notification(product_data: dict, reason: str) -> None:
    await build_notification_service().send_notification(product_data, reason)


def _format_failure_reason(reason: str, limit: int = 500) -> str:
    if not reason:
        return "未知错误"
    cleaned = " ".join(str(reason).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


async def _notify_task_failure(
    task_config: dict, reason: str, *, cookie_path: Optional[str]
) -> None:
    task_name = task_config.get("task_name", "未命名任务")
    keyword = task_config.get("keyword", "")
    formatted_reason = _format_failure_reason(reason)

    is_risk_control = any(
        marker in formatted_reason
        for marker in (
            "FAIL_SYS_USER_VALIDATE",
            "baxia-dialog",
            "J_MIDDLEWARE_FRAME_WIDGET",
        )
    )

    # Some failures are deterministic misconfiguration and should pause/notify immediately.
    pause_immediately = any(
        marker in formatted_reason
        for marker in (
            "未找到可用的代理地址",
            "未找到可用的登录状态文件",
        )
    ) or is_risk_control

    risk_pause_seconds = None
    if is_risk_control:
        risk_pause_seconds = max(
            60,
            _as_int(os.getenv("TASK_RISK_CONTROL_PAUSE_SECONDS"), 60 * 60),
        )

    guard_result = FAILURE_GUARD.record_failure(
        task_name,
        formatted_reason,
        cookie_path=cookie_path,
        min_failures_to_pause=1 if pause_immediately else None,
        pause_seconds_override=risk_pause_seconds,
    )

    if not guard_result.get("should_notify"):
        print(
            f"[FailureGuard] 任务 '{task_name}' 失败计数 {guard_result.get('consecutive_failures')}/{FAILURE_GUARD.threshold}，暂不通知。"
        )
        return

    paused_until = guard_result.get("paused_until")
    paused_until_str = (
        paused_until.strftime("%Y-%m-%d %H:%M:%S") if paused_until else "N/A"
    )

    product_data = {
        "商品标题": f"[任务异常] {task_name}",
        "当前售价": "N/A",
        "商品链接": "#",
    }
    notify_reason = (
        f"任务运行失败(已连续 {guard_result.get('consecutive_failures')}/{FAILURE_GUARD.threshold} 次): {formatted_reason}"
        f"\n任务: {task_name}"
        f"\n关键词: {keyword or 'N/A'}"
        f"\n已自动暂停重试，暂停到: {paused_until_str}"
        f"\n修复后(更新登录态/cookies文件)将自动恢复。"
    )

    try:
        await _send_notification(product_data, notify_reason)
    except Exception as e:
        print(f"发送任务异常通知失败: {e}")


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_rotation_settings(task_config: dict) -> dict:
    account_cfg = task_config.get("account_rotation") or {}
    proxy_cfg = task_config.get("proxy_rotation") or {}

    account_enabled = _as_bool(
        account_cfg.get("enabled"),
        _as_bool(os.getenv("ACCOUNT_ROTATION_ENABLED"), False),
    )
    account_mode = (
        account_cfg.get("mode") or os.getenv("ACCOUNT_ROTATION_MODE", "per_task")
    ).lower()
    account_state_dir = account_cfg.get("state_dir") or os.getenv(
        "ACCOUNT_STATE_DIR", "state"
    )
    account_retry_limit = _as_int(
        account_cfg.get("retry_limit"),
        _as_int(os.getenv("ACCOUNT_ROTATION_RETRY_LIMIT"), 2),
    )
    account_blacklist_ttl = _as_int(
        account_cfg.get("blacklist_ttl_sec"),
        _as_int(os.getenv("ACCOUNT_BLACKLIST_TTL"), 300),
    )

    proxy_enabled = _as_bool(
        proxy_cfg.get("enabled"), _as_bool(os.getenv("PROXY_ROTATION_ENABLED"), False)
    )
    proxy_mode = (
        proxy_cfg.get("mode") or os.getenv("PROXY_ROTATION_MODE", "per_task")
    ).lower()
    proxy_pool = proxy_cfg.get("proxy_pool") or os.getenv("PROXY_POOL", "")
    proxy_retry_limit = _as_int(
        proxy_cfg.get("retry_limit"),
        _as_int(os.getenv("PROXY_ROTATION_RETRY_LIMIT"), 2),
    )
    proxy_blacklist_ttl = _as_int(
        proxy_cfg.get("blacklist_ttl_sec"),
        _as_int(os.getenv("PROXY_BLACKLIST_TTL"), 300),
    )

    return {
        "account_enabled": account_enabled,
        "account_mode": account_mode,
        "account_state_dir": account_state_dir,
        "account_retry_limit": max(1, account_retry_limit),
        "account_blacklist_ttl": max(0, account_blacklist_ttl),
        "proxy_enabled": proxy_enabled,
        "proxy_mode": proxy_mode,
        "proxy_pool": proxy_pool,
        "proxy_retry_limit": max(1, proxy_retry_limit),
        "proxy_blacklist_ttl": max(0, proxy_blacklist_ttl),
    }


def _get_processing_concurrency(task_config: dict) -> int:
    configured = task_config.get("processing_concurrency")
    default = _as_int(os.getenv("ITEM_PROCESSING_CONCURRENCY"), 2)
    return max(1, _as_int(configured, default))


def _get_seller_profile_cache_ttl(task_config: dict) -> int:
    configured = task_config.get("seller_profile_cache_ttl")
    default = _as_int(os.getenv("SELLER_PROFILE_CACHE_TTL"), 1800)
    return max(0, _as_int(configured, default))


def _default_context_options() -> dict:
    return {
        "user_agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "permissions": ["geolocation"],
        "geolocation": {"longitude": 121.4737, "latitude": 31.2304},
        "color_scheme": "light",
    }


def _clean_kwargs(options: dict) -> dict:
    return {k: v for k, v in options.items() if v is not None}


def _looks_like_mobile(ua: str) -> Optional[bool]:
    if not ua:
        return None
    ua_lower = ua.lower()
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        return True
    if "windows" in ua_lower or "macintosh" in ua_lower:
        return False
    return None


def _build_context_overrides(snapshot: dict) -> dict:
    env = snapshot.get("env") or {}
    headers = snapshot.get("headers") or {}
    navigator = env.get("navigator") or {}
    screen = env.get("screen") or {}
    intl = env.get("intl") or {}

    overrides = {}

    ua = (
        headers.get("User-Agent")
        or headers.get("user-agent")
        or navigator.get("userAgent")
    )
    if ua:
        overrides["user_agent"] = ua

    accept_language = headers.get("Accept-Language") or headers.get("accept-language")
    locale = None
    if accept_language:
        locale = accept_language.split(",")[0].strip()
    elif navigator.get("language"):
        locale = navigator["language"]
    if locale:
        overrides["locale"] = locale

    tz = intl.get("timeZone")
    if tz:
        overrides["timezone_id"] = tz

    width = screen.get("width")
    height = screen.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        overrides["viewport"] = {"width": int(width), "height": int(height)}

    dpr = screen.get("devicePixelRatio")
    if isinstance(dpr, (int, float)):
        overrides["device_scale_factor"] = float(dpr)

    touch_points = navigator.get("maxTouchPoints")
    if isinstance(touch_points, (int, float)):
        overrides["has_touch"] = touch_points > 0

    mobile_flag = _looks_like_mobile(ua or "")
    if mobile_flag is not None:
        overrides["is_mobile"] = mobile_flag

    return _clean_kwargs(overrides)


def _build_extra_headers(raw_headers: Optional[dict]) -> dict:
    if not raw_headers:
        return {}
    # 浏览器会按请求类型动态生成这些头。登录态快照采集的是页面导航请求，
    # 若把 Sec-Fetch-Dest=document、Accept=text/html 等强制复用到 MTop XHR，
    # 会让详情接口被服务端拒绝或根本无法正常发起。
    excluded = {
        "accept",
        "accept-encoding",
        "accept-language",
        "connection",
        "content-length",
        "cookie",
        "host",
        "origin",
        "referer",
        "user-agent",
    }
    headers = {}
    for key, value in raw_headers.items():
        normalized_key = str(key or "").lower()
        if (
            not normalized_key
            or normalized_key in excluded
            or normalized_key.startswith("sec-")
            or value is None
        ):
            continue
        headers[key] = value
    return headers


async def scrape_user_profile(context, user_id: str) -> dict:
    """
    【新版】访问指定用户的个人主页，按顺序采集其摘要信息、完整的商品列表和完整的评价列表。
    """
    print(f"   -> 开始采集用户ID: {user_id} 的完整信息...")
    profile_data = {}
    page = await context.new_page()

    # 为各项异步任务准备Future和数据容器
    head_api_future = asyncio.get_event_loop().create_future()

    all_items, all_ratings = [], []
    stop_item_scrolling, stop_rating_scrolling = asyncio.Event(), asyncio.Event()

    async def handle_response(response: Response):
        # 捕获头部摘要API
        if (
            "mtop.idle.web.user.page.head" in response.url
            and not head_api_future.done()
        ):
            try:
                head_api_future.set_result(await response.json())
                print(f"      [API捕获] 用户头部信息... 成功")
            except Exception as e:
                if not head_api_future.done():
                    head_api_future.set_exception(e)

        # 捕获商品列表API
        elif "mtop.idle.web.xyh.item.list" in response.url:
            try:
                data = await response.json()
                all_items.extend(data.get("data", {}).get("cardList", []))
                print(f"      [API捕获] 商品列表... 当前已捕获 {len(all_items)} 件")
                if not data.get("data", {}).get("nextPage", True):
                    stop_item_scrolling.set()
            except Exception as e:
                stop_item_scrolling.set()

        # 捕获评价列表API
        elif "mtop.idle.web.trade.rate.list" in response.url:
            try:
                data = await response.json()
                all_ratings.extend(data.get("data", {}).get("cardList", []))
                print(f"      [API捕获] 评价列表... 当前已捕获 {len(all_ratings)} 条")
                if not data.get("data", {}).get("nextPage", True):
                    stop_rating_scrolling.set()
            except Exception as e:
                stop_rating_scrolling.set()

    page.on("response", handle_response)

    try:
        # --- 任务1: 导航并采集头部信息 ---
        await page.goto(
            f"https://www.goofish.com/personal?userId={user_id}",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        head_data = await asyncio.wait_for(head_api_future, timeout=15)
        profile_data = await parse_user_head_data(head_data)

        # --- 任务2: 滚动加载所有商品 (默认页面) ---
        print("      [采集阶段] 开始采集该用户的商品列表...")
        await random_sleep(2, 4)  # 等待第一页商品API完成
        while not stop_item_scrolling.is_set():
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                await asyncio.wait_for(stop_item_scrolling.wait(), timeout=8)
            except asyncio.TimeoutError:
                print("      [滚动超时] 商品列表可能已加载完毕。")
                break
        profile_data["卖家发布的商品列表"] = await _parse_user_items_data(all_items)

        # --- 任务3: 点击并采集所有评价 ---
        print("      [采集阶段] 开始采集该用户的评价列表...")
        rating_tab_locator = page.locator("//div[text()='信用及评价']/ancestor::li")
        if await rating_tab_locator.count() > 0:
            await rating_tab_locator.click()
            await random_sleep(3, 5)  # 等待第一页评价API完成

            while not stop_rating_scrolling.is_set():
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    await asyncio.wait_for(stop_rating_scrolling.wait(), timeout=8)
                except asyncio.TimeoutError:
                    print("      [滚动超时] 评价列表可能已加载完毕。")
                    break

            profile_data["卖家收到的评价列表"] = await parse_ratings_data(all_ratings)
            reputation_stats = await calculate_reputation_from_ratings(all_ratings)
            profile_data.update(reputation_stats)
        else:
            print("      [警告] 未找到评价选项卡，跳过评价采集。")

    except Exception as e:
        print(f"   [错误] 采集用户 {user_id} 信息时发生错误: {e}")
    finally:
        page.remove_listener("response", handle_response)
        await page.close()
        print(f"   -> 用户 {user_id} 信息采集完成。")

    return profile_data


async def scrape_xianyu(task_config: dict, debug_limit: int = 0):
    """
    【核心执行器】
    根据单个任务配置抓取商品，并对每个新商品执行规则匹配、指标记录和通知。
    """
    keyword = task_config["keyword"]
    max_pages = task_config.get("max_pages", 1)
    personal_only = task_config.get("personal_only", False)
    min_price = task_config.get("min_price")
    max_price = task_config.get("max_price")
    keyword_rules = task_config.get("keyword_rules") or []
    if not keyword_rules and keyword:
        keyword_rules = [keyword]
    free_shipping = task_config.get("free_shipping", False)
    raw_new_publish = task_config.get("new_publish_option") or ""
    new_publish_option = raw_new_publish.strip()
    if new_publish_option == "__none__":
        new_publish_option = ""
    region_filter = (task_config.get("region") or "").strip()

    processed_links = set()
    history_run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    history_seen_item_ids: set[str] = set()
    historical_snapshots = load_price_snapshots(keyword)
    result_filename = build_result_filename(keyword)
    processed_links = load_processed_link_keys(keyword)
    if processed_links:
        print(f"LOG: 发现已存在结果集 {result_filename}，已加载 {len(processed_links)} 个历史商品用于去重。")
    else:
        print(f"LOG: 结果集 {result_filename} 当前为空，将写入新记录。")

    rotation_settings = _get_rotation_settings(task_config)
    account_items = load_state_files(rotation_settings["account_state_dir"])
    runtime_plan = resolve_account_runtime_plan(
        strategy=task_config.get("account_strategy"),
        account_state_file=task_config.get("account_state_file"),
        has_root_state_file=os.path.exists(get_state_file()),
        available_account_files=account_items,
    )
    forced_account = runtime_plan["forced_account"]
    if runtime_plan["prefer_root_state"]:
        account_items = [get_state_file()]
        rotation_settings["account_enabled"] = False
    elif runtime_plan["use_account_pool"]:
        rotation_settings["account_enabled"] = True
    else:
        rotation_settings["account_enabled"] = False

    account_pool = RotationPool(
        account_items, rotation_settings["account_blacklist_ttl"], "account"
    )
    proxy_pool = RotationPool(
        parse_proxy_pool(rotation_settings["proxy_pool"]),
        rotation_settings["proxy_blacklist_ttl"],
        "proxy",
    )

    selected_account: Optional[RotationItem] = None
    selected_proxy: Optional[RotationItem] = None

    def _select_account(force_new: bool = False) -> Optional[RotationItem]:
        nonlocal selected_account
        if forced_account:
            return RotationItem(value=forced_account)
        if not rotation_settings["account_enabled"]:
            state_file = get_state_file()
            if os.path.exists(state_file):
                return RotationItem(value=state_file)
            return None
        if (
            rotation_settings["account_mode"] == "per_task"
            and selected_account
            and not force_new
        ):
            return selected_account
        picked = account_pool.pick_random()
        return picked or selected_account

    def _select_proxy(force_new: bool = False) -> Optional[RotationItem]:
        nonlocal selected_proxy
        if not rotation_settings["proxy_enabled"]:
            return None
        if (
            rotation_settings["proxy_mode"] == "per_task"
            and selected_proxy
            and not force_new
        ):
            return selected_proxy
        picked = proxy_pool.pick_random()
        return picked or selected_proxy

    async def _run_scrape_attempt(state_file: str, proxy_server: Optional[str]) -> int:
        processed_item_count = 0
        stop_scraping = False

        if not os.path.exists(state_file):
            raise FileNotFoundError(f"登录状态文件不存在: {state_file}")

        snapshot_data = None
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                snapshot_data = json.load(f)
        except Exception as e:
            print(f"警告：读取登录状态文件失败，将直接按路径使用: {e}")

        async with async_playwright() as p:
            # 反检测启动参数
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ]

            launch_kwargs = {"headless": RUN_HEADLESS, "args": launch_args}
            if proxy_server:
                launch_kwargs["proxy"] = {"server": proxy_server}

            launch_kwargs["channel"] = _resolve_browser_channel()

            browser = await p.chromium.launch(**launch_kwargs)

            context_kwargs = _default_context_options()
            storage_state_arg = state_file
            analysis_dispatcher: Optional[ItemAnalysisDispatcher] = None

            if isinstance(snapshot_data, dict):
                # 新版扩展导出的增强快照，包含环境和Header
                if any(
                    key in snapshot_data
                    for key in ("env", "headers", "page", "storage")
                ):
                    print(f"检测到增强浏览器快照，应用环境参数: {state_file}")
                    storage_state_arg = {"cookies": snapshot_data.get("cookies", [])}
                    context_kwargs.update(_build_context_overrides(snapshot_data))
                    extra_headers = _build_extra_headers(snapshot_data.get("headers"))
                    if extra_headers:
                        context_kwargs["extra_http_headers"] = extra_headers
                else:
                    storage_state_arg = snapshot_data

            context_kwargs = _clean_kwargs(context_kwargs)
            context = await browser.new_context(
                storage_state=storage_state_arg, **context_kwargs
            )
            seller_profile_cache = SellerProfileCache(
                ttl_seconds=_get_seller_profile_cache_ttl(task_config)
            )
            analysis_dispatcher = ItemAnalysisDispatcher(
                concurrency=_get_processing_concurrency(task_config),
                seller_loader=lambda user_id: seller_profile_cache.get_or_load(
                    str(user_id),
                    lambda seller_key: scrape_user_profile(context, seller_key),
                ),
                notifier=_send_notification,
                saver=save_to_jsonl,
            )

            # 增强反检测脚本（模拟真实移动设备）
            await context.add_init_script("""
                // 移除webdriver标识
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

                // 模拟真实移动设备的navigator属性
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});

                // 添加chrome对象
                window.chrome = {runtime: {}, loadTimes: function() {}, csi: function() {}};

                // 模拟触摸支持
                Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5});

                // 覆盖permissions查询（避免暴露自动化）
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({state: Notification.permission}) :
                        originalQuery(parameters)
                );
            """)

            page = await context.new_page()

            try:
                # 步骤 0 - 模拟真实用户：先访问首页（重要的反检测措施）
                log_time("步骤 0 - 模拟真实用户访问首页...")
                await page.goto(
                    "https://www.goofish.com/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                log_time("[反爬] 在首页停留，模拟浏览...")
                await random_sleep(1, 2)

                # 模拟随机滚动（移动设备的触摸滚动）
                await page.evaluate("window.scrollBy(0, Math.random() * 500 + 200)")
                await random_sleep(1, 2)

                log_time("步骤 1 - 导航到搜索结果页...")
                # 使用 'q' 参数构建正确的搜索URL，并进行URL编码
                params = {"q": keyword}
                search_url = f"https://www.goofish.com/search?{urlencode(params)}"
                log_time(f"目标URL: {search_url}")

                # 先监听搜索接口响应，再执行导航，避免错过首次请求
                async with page.expect_response(
                    is_search_results_response, timeout=30000
                ) as initial_response_info:
                    await page.goto(
                        search_url, wait_until="domcontentloaded", timeout=60000
                    )
                if _is_login_url(page.url):
                    raise LoginRequiredError(
                        f"Login required: redirected to {page.url} (cookies/state likely expired)"
                    )

                # 捕获初始搜索的API数据
                initial_response = await initial_response_info.value

                # 等待页面加载出关键筛选元素，以确认已成功进入搜索结果页
                try:
                    await page.wait_for_selector("text=新发布", timeout=15000)
                except PlaywrightTimeoutError as e:
                    if _is_login_url(page.url):
                        raise LoginRequiredError(
                            f"Login required: redirected to {page.url} (cookies/state likely expired)"
                        ) from e
                    raise

                # 模拟真实用户行为：页面加载后的初始停留和浏览
                log_time("[反爬] 模拟用户查看页面...")
                await random_sleep(1, 3)

                # --- 新增：检查是否存在验证弹窗 ---
                baxia_dialog = page.locator("div.baxia-dialog-mask")
                middleware_widget = page.locator("div.J_MIDDLEWARE_FRAME_WIDGET")
                try:
                    # 等待弹窗在2秒内出现。如果出现，则执行块内代码。
                    await baxia_dialog.wait_for(state="visible", timeout=2000)
                    print(
                        "\n==================== CRITICAL BLOCK DETECTED ===================="
                    )
                    print("检测到闲鱼反爬虫验证弹窗 (baxia-dialog)，无法继续操作。")
                    print("这通常是因为操作过于频繁或被识别为机器人。")
                    print("建议：")
                    print("1. 停止脚本一段时间再试。")
                    print(
                        "2. (推荐) 在 .env 文件中设置 RUN_HEADLESS=false，以非无头模式运行，这有助于绕过检测。"
                    )
                    print(f"任务 '{keyword}' 将在此处中止。")
                    print(
                        "==================================================================="
                    )
                    raise RiskControlError("baxia-dialog")
                except PlaywrightTimeoutError:
                    # 2秒内弹窗未出现，这是正常情况，继续执行
                    pass

                # 检查是否有J_MIDDLEWARE_FRAME_WIDGET覆盖层
                try:
                    await middleware_widget.wait_for(state="visible", timeout=2000)
                    print(
                        "\n==================== CRITICAL BLOCK DETECTED ===================="
                    )
                    print(
                        "检测到闲鱼反爬虫验证弹窗 (J_MIDDLEWARE_FRAME_WIDGET)，无法继续操作。"
                    )
                    print("这通常是因为操作过于频繁或被识别为机器人。")
                    print("建议：")
                    print("1. 停止脚本一段时间再试。")
                    print("2. (推荐) 更新登录状态文件，确保登录状态有效。")
                    print("3. 降低任务执行频率，避免被识别为机器人。")
                    print(f"任务 '{keyword}' 将在此处中止。")
                    print(
                        "==================================================================="
                    )
                    raise RiskControlError("J_MIDDLEWARE_FRAME_WIDGET")
                except PlaywrightTimeoutError:
                    # 2秒内弹窗未出现，这是正常情况，继续执行
                    pass
                # --- 结束新增 ---

                try:
                    await page.click("div[class*='closeIconBg']", timeout=3000)
                    print("LOG: 已关闭广告弹窗。")
                except PlaywrightTimeoutError:
                    print("LOG: 未检测到广告弹窗。")

                final_response = None
                log_time("步骤 2 - 应用筛选条件...")
                if new_publish_option:
                    try:
                        await page.click("text=新发布")
                        await random_sleep(1, 2)  # 原来是 (1.5, 2.5)
                        async with page.expect_response(
                            is_search_results_response, timeout=20000
                        ) as response_info:
                            await page.click(f"text={new_publish_option}")
                            # --- 修改: 增加排序后的等待时间 ---
                            await random_sleep(2, 4)  # 原来是 (3, 5)
                        final_response = await response_info.value
                    except PlaywrightTimeoutError:
                        log_time(
                            f"新发布筛选 '{new_publish_option}' 请求超时，继续执行。"
                        )
                    except Exception as e:
                        print(f"LOG: 应用新发布筛选失败: {e}")

                if personal_only:
                    async with page.expect_response(
                        is_search_results_response, timeout=20000
                    ) as response_info:
                        await page.click("text=个人闲置")
                        # --- 修改: 将固定等待改为随机等待，并加长 ---
                        await random_sleep(2, 4)  # 原来是 asyncio.sleep(5)
                    final_response = await response_info.value

                if free_shipping:
                    try:
                        async with page.expect_response(
                            is_search_results_response, timeout=20000
                        ) as response_info:
                            await page.click("text=包邮")
                            await random_sleep(2, 4)
                        final_response = await response_info.value
                    except PlaywrightTimeoutError:
                        log_time("包邮筛选请求超时，继续执行。")
                    except Exception as e:
                        print(f"LOG: 应用包邮筛选失败: {e}")

                if region_filter:
                    try:
                        area_trigger = page.get_by_text("区域", exact=True)
                        if await area_trigger.count():
                            await area_trigger.first.click()
                            await random_sleep(1.5, 2)
                            popover_candidates = page.locator("div.ant-popover")
                            popover = popover_candidates.filter(
                                has=page.locator(
                                    ".areaWrap--FaZHsn8E, [class*='areaWrap']"
                                )
                            ).last
                            if not await popover.count():
                                popover = popover_candidates.filter(
                                    has=page.get_by_text("重新定位")
                                ).last
                            if not await popover.count():
                                popover = popover_candidates.filter(
                                    has=page.get_by_text("查看")
                                ).last
                            if not await popover.count():
                                print("LOG: 未找到区域弹窗，跳过区域筛选。")
                                raise PlaywrightTimeoutError("region-popover-not-found")
                            await popover.wait_for(state="visible", timeout=5000)

                            # 列表容器：第一层 children 即省/市/区三列，不再强依赖具体类名，提升鲁棒性
                            area_wrap = popover.locator(
                                ".areaWrap--FaZHsn8E, [class*='areaWrap']"
                            ).first
                            await area_wrap.wait_for(state="visible", timeout=3000)
                            columns = area_wrap.locator(":scope > div")
                            col_prov = columns.nth(0)
                            col_city = columns.nth(1)
                            col_dist = columns.nth(2)

                            region_parts = [
                                p.strip() for p in region_filter.split("/") if p.strip()
                            ]

                            async def _click_in_column(
                                column_locator, text_value: str, desc: str
                            ) -> None:
                                option = column_locator.locator(
                                    ".provItem--QAdOx8nD", has_text=text_value
                                ).first
                                if await option.count():
                                    await option.click()
                                    await random_sleep(1.5, 2)
                                    try:
                                        await option.wait_for(
                                            state="attached", timeout=1500
                                        )
                                        await option.wait_for(
                                            state="visible", timeout=1500
                                        )
                                    except PlaywrightTimeoutError:
                                        pass
                                else:
                                    print(f"LOG: 未找到{desc} '{text_value}'，跳过。")

                            if len(region_parts) >= 1:
                                await _click_in_column(
                                    col_prov, region_parts[0], "省份"
                                )
                                await random_sleep(1, 2)
                            if len(region_parts) >= 2:
                                await _click_in_column(
                                    col_city, region_parts[1], "城市"
                                )
                                await random_sleep(1, 2)
                            if len(region_parts) >= 3:
                                await _click_in_column(
                                    col_dist, region_parts[2], "区/县"
                                )
                                await random_sleep(1, 2)

                            search_btn = popover.locator(
                                "div.searchBtn--Ic6RKcAb"
                            ).first
                            if await search_btn.count():
                                try:
                                    async with page.expect_response(
                                        is_search_results_response,
                                        timeout=20000,
                                    ) as response_info:
                                        await search_btn.click()
                                        await random_sleep(2, 3)
                                    final_response = await response_info.value
                                except PlaywrightTimeoutError:
                                    log_time("区域筛选提交超时，继续执行。")
                            else:
                                print(
                                    "LOG: 未找到区域弹窗的“查看XX件宝贝”按钮，跳过提交。"
                                )
                        else:
                            print("LOG: 未找到区域筛选触发器。")
                    except PlaywrightTimeoutError:
                        log_time(f"区域筛选 '{region_filter}' 请求超时，继续执行。")
                    except Exception as e:
                        print(f"LOG: 应用区域筛选 '{region_filter}' 失败: {e}")

                if min_price or max_price:
                    price_container = page.locator(
                        'div[class*="search-price-input-container"]'
                    ).first
                    if await price_container.is_visible():
                        if min_price:
                            await price_container.get_by_placeholder("¥").first.fill(
                                min_price
                            )
                            # --- 修改: 将固定等待改为随机等待 ---
                            await random_sleep(1, 2.5)  # 原来是 asyncio.sleep(5)
                        if max_price:
                            await (
                                price_container.get_by_placeholder("¥")
                                .nth(1)
                                .fill(max_price)
                            )
                            # --- 修改: 将固定等待改为随机等待 ---
                            await random_sleep(1, 2.5)  # 原来是 asyncio.sleep(5)

                        async with page.expect_response(
                            is_search_results_response, timeout=20000
                        ) as response_info:
                            await page.keyboard.press("Tab")
                            # --- 修改: 增加确认价格后的等待时间 ---
                            await random_sleep(2, 4)  # 原来是 asyncio.sleep(5)
                        final_response = await response_info.value
                    else:
                        print("LOG: 警告 - 未找到价格输入容器。")

                log_time("所有筛选已完成，开始处理商品列表...")

                current_response = (
                    final_response
                    if final_response and final_response.ok
                    else initial_response
                )
                for page_num in range(1, max_pages + 1):
                    if stop_scraping:
                        break
                    log_time(f"开始处理第 {page_num}/{max_pages} 页 ...")

                    if page_num > 1:
                        page_advance_result = await advance_search_page(
                            page=page,
                            page_num=page_num,
                        )
                        if not page_advance_result.advanced:
                            break
                        current_response = page_advance_result.response

                    if not (current_response and current_response.ok):
                        log_time(f"第 {page_num} 页响应无效，跳过。")
                        continue

                    basic_items = await _parse_search_results_json(
                        await current_response.json(), f"第 {page_num} 页"
                    )
                    if not basic_items:
                        break
                    historical_snapshots.extend(
                        record_market_snapshots(
                            keyword=keyword,
                            task_name=task_config.get("task_name", "Untitled Task"),
                            items=basic_items,
                            run_id=history_run_id,
                            snapshot_time=datetime.now().isoformat(),
                            seen_item_ids=history_seen_item_ids,
                        )
                    )

                    total_items_on_page = len(basic_items)
                    for i, item_data in enumerate(basic_items, 1):
                        if debug_limit > 0 and processed_item_count >= debug_limit:
                            log_time(
                                f"已达到调试上限 ({debug_limit})，停止获取新商品。"
                            )
                            stop_scraping = True
                            break

                        unique_key = get_link_unique_key(item_data["商品链接"])
                        if unique_key in processed_links:
                            log_time(
                                f"[页内进度 {i}/{total_items_on_page}] 商品 '{item_data['商品标题'][:20]}...' 已存在，跳过。"
                            )
                            continue

                        log_time(
                            f"[页内进度 {i}/{total_items_on_page}] 发现新商品，获取详情: {item_data['商品标题'][:30]}..."
                        )
                        # --- 修改: 访问详情页前的等待时间，模拟用户在列表页上看了一会儿 ---
                        await random_sleep(2, 4)  # 原来是 (2, 4)

                        detail_page = await context.new_page()
                        try:
                            async with detail_page.expect_response(
                                lambda r: DETAIL_API_URL_PATTERN in r.url, timeout=25000
                            ) as detail_info:
                                await detail_page.goto(
                                    item_data["商品链接"],
                                    wait_until="domcontentloaded",
                                    timeout=25000,
                                )

                            detail_response = await detail_info.value
                            if detail_response.ok:
                                detail_json = await detail_response.json()

                                ret_string = str(
                                    await safe_get(detail_json, "ret", default=[])
                                )
                                if "FAIL_SYS_USER_VALIDATE" in ret_string:
                                    print(
                                        "\n==================== CRITICAL BLOCK DETECTED ===================="
                                    )
                                    print(
                                        "检测到闲鱼反爬虫验证 (FAIL_SYS_USER_VALIDATE)，程序将终止。"
                                    )
                                    long_sleep_duration = random.randint(3, 60)
                                    print(
                                        f"为避免账户风险，将执行一次长时间休眠 ({long_sleep_duration} 秒) 后再退出..."
                                    )
                                    await asyncio.sleep(long_sleep_duration)
                                    print("长时间休眠结束，现在将安全退出。")
                                    print(
                                        "==================================================================="
                                    )
                                    raise RiskControlError("FAIL_SYS_USER_VALIDATE")

                                # 解析商品详情数据并更新 item_data
                                item_do = await safe_get(
                                    detail_json, "data", "itemDO", default={}
                                )
                                seller_do = await safe_get(
                                    detail_json, "data", "sellerDO", default={}
                                )

                                reg_days_raw = await safe_get(
                                    seller_do, "userRegDay", default=0
                                )
                                registration_duration_text = format_registration_days(
                                    reg_days_raw
                                )

                                # --- START: 新增代码块 ---

                                # 1. 提取卖家的芝麻信用信息
                                zhima_credit_text = await safe_get(
                                    seller_do, "zhimaLevelInfo", "levelName"
                                )

                                # 2. 提取该商品的完整图片列表
                                image_infos = await safe_get(
                                    item_do, "imageInfos", default=[]
                                )
                                if image_infos:
                                    # 使用列表推导式获取所有有效的图片URL
                                    all_image_urls = [
                                        img.get("url")
                                        for img in image_infos
                                        if img.get("url")
                                    ]
                                    if all_image_urls:
                                        # 用新的字段存储图片列表，替换掉旧的单个链接
                                        item_data["商品图片列表"] = all_image_urls
                                        # (可选) 仍然保留主图链接，以防万一
                                        item_data["商品主图链接"] = all_image_urls[0]

                                # --- END: 新增代码块 ---
                                item_data["“想要”人数"] = await safe_get(
                                    item_do,
                                    "wantCnt",
                                    default=item_data.get("“想要”人数", "NaN"),
                                )
                                item_data["浏览量"] = await safe_get(
                                    item_do, "browseCnt", default="-"
                                )
                                # ...[此处可添加更多从详情页解析出的商品信息]...

                                user_id = await safe_get(seller_do, "sellerId")

                                # 构建基础记录
                                final_record = {
                                    "爬取时间": datetime.now().isoformat(),
                                    "搜索关键字": keyword,
                                    "任务名称": task_config.get(
                                        "task_name", "Untitled Task"
                                    ),
                                    "商品信息": item_data,
                                    "卖家信息": {},
                                }
                                price_reference = build_market_reference(
                                    keyword=keyword,
                                    item=item_data,
                                    current_market_items=basic_items,
                                    historical_snapshots=historical_snapshots,
                                )
                                final_record["价格参考"] = price_reference
                                final_record["price_insight"] = price_reference.get(
                                    "本商品价格位置", {}
                                )

                                analysis_dispatcher.submit(
                                    ItemAnalysisJob(
                                        keyword=keyword,
                                        task_name=task_config.get(
                                            "task_name", "Untitled Task"
                                        ),
                                        keyword_rules=tuple(keyword_rules or []),
                                        final_record=final_record,
                                        seller_id=str(user_id) if user_id else None,
                                        zhima_credit_text=zhima_credit_text,
                                        registration_duration_text=registration_duration_text,
                                    )
                                )

                                processed_links.add(unique_key)
                                processed_item_count += 1
                                log_time(
                                    f"商品已提交后台分析。累计处理 {processed_item_count} 个新商品。"
                                )

                                # --- 修改: 增加单个商品处理后的主要延迟 ---
                                log_time(
                                    "[反爬] 执行一次主要的随机延迟以模拟用户浏览间隔..."
                                )
                                await random_sleep(5, 10)
                            else:
                                print(
                                    f"   错误: 获取商品详情API响应失败，状态码: {detail_response.status}"
                                )
                                if DEBUG_MODE:
                                    print(
                                        f"--- [DETAIL DEBUG] FAILED RESPONSE from {item_data['商品链接']} ---"
                                    )
                                    try:
                                        print(await detail_response.text())
                                    except Exception as e:
                                        print(f"无法读取响应内容: {e}")
                                    print(
                                        "----------------------------------------------------"
                                    )

                        except PlaywrightTimeoutError:
                            print(f"   错误: 访问商品详情页或等待API响应超时。")
                        except Exception as e:
                            print(f"   错误: 处理商品详情时发生未知错误: {e}")
                        finally:
                            await detail_page.close()
                            # --- 修改: 增加关闭页面后的短暂整理时间 ---
                            await random_sleep(2, 4)  # 原来是 (1, 2.5)

                    # --- 新增: 在处理完一页所有商品后，翻页前，增加一个更长的“休息”时间 ---
                    if not stop_scraping and page_num < max_pages:
                        print(
                            f"--- 第 {page_num} 页处理完毕，准备翻页。执行一次页面间的长时休息... ---"
                        )
                        await random_sleep(10, 15)

            except PlaywrightTimeoutError as e:
                if _is_login_url(page.url):
                    raise LoginRequiredError(
                        f"Login required: redirected to {page.url} (cookies/state likely expired)"
                    ) from e
                print(f"\n操作超时错误: 页面元素或网络响应未在规定时间内出现。\n{e}")
                raise
            except asyncio.CancelledError:
                log_time("收到取消信号，正在终止当前爬虫任务...")
                raise
            except Exception as e:
                if type(e).__name__ == "TargetClosedError":
                    log_time("浏览器已关闭，忽略后续异常（可能是任务被停止）。")
                    return processed_item_count
                if "passport.goofish.com" in str(e):
                    raise LoginRequiredError(
                        f"Login required: redirected to passport flow ({e})"
                    ) from e
                print(f"\n爬取过程中发生未知错误: {e}")
                raise
            finally:
                if analysis_dispatcher is not None:
                    log_time("等待后台商品处理任务完成...")
                    await analysis_dispatcher.join()
                log_time("任务执行完毕，浏览器将在5秒后自动关闭...")
                await asyncio.sleep(5)
                if debug_limit:
                    input("按回车键关闭浏览器...")
                await browser.close()

        return processed_item_count

    processed_item_count = 0
    attempt_limit = max(
        rotation_settings["account_retry_limit"],
        rotation_settings["proxy_retry_limit"],
        1,
    )
    last_error = ""
    last_state_path: Optional[str] = None

    # If this task is already in a paused state, skip immediately.
    task_name_for_guard = task_config.get("task_name", "未命名任务")
    pause_cookie_path = None
    if (
        isinstance(task_config.get("account_state_file"), str)
        and task_config.get("account_state_file").strip()
    ):
        pause_cookie_path = task_config.get("account_state_file").strip()
    elif os.path.exists(get_state_file()):
        pause_cookie_path = get_state_file()

    decision = FAILURE_GUARD.should_skip_start(
        task_name_for_guard, cookie_path=pause_cookie_path
    )
    if decision.skip:
        print(
            f"[FailureGuard] 任务 '{task_name_for_guard}' 已暂停重试 (连续失败 {decision.consecutive_failures}/{FAILURE_GUARD.threshold})"
        )
        if decision.should_notify:
            try:
                await _send_notification(
                    {
                        "商品标题": f"[任务暂停] {task_name_for_guard}",
                        "当前售价": "N/A",
                        "商品链接": "#",
                    },
                    "任务处于暂停状态，将跳过执行。\n"
                    f"原因: {decision.reason}\n"
                    f"连续失败: {decision.consecutive_failures}/{FAILURE_GUARD.threshold}\n"
                    f"暂停到: {decision.paused_until.strftime('%Y-%m-%d %H:%M:%S') if decision.paused_until else 'N/A'}\n"
                    "修复方法: 更新登录态/cookies文件后会自动恢复。",
                )
            except Exception as e:
                print(f"发送任务暂停通知失败: {e}")

        return 0

    for attempt in range(1, attempt_limit + 1):
        if attempt == 1:
            selected_account = _select_account()
            selected_proxy = _select_proxy()
        else:
            if (
                rotation_settings["account_enabled"]
                and rotation_settings["account_mode"] == "on_failure"
            ):
                account_pool.mark_bad(selected_account, last_error)
                selected_account = _select_account(force_new=True)
            if (
                rotation_settings["proxy_enabled"]
                and rotation_settings["proxy_mode"] == "on_failure"
            ):
                proxy_pool.mark_bad(selected_proxy, last_error)
                selected_proxy = _select_proxy(force_new=True)

        if rotation_settings["account_enabled"] and not selected_account:
            last_error = "未找到可用的登录状态文件，无法继续执行任务。"
            print(last_error)
            break
        if not rotation_settings["account_enabled"] and not selected_account:
            last_error = "未找到可用的登录状态文件，无法继续执行任务。"
            print(last_error)
            break
        if rotation_settings["proxy_enabled"] and not selected_proxy:
            last_error = "未找到可用的代理地址，无法继续执行任务。"
            print(last_error)
            break

        state_path = selected_account.value if selected_account else get_state_file()
        last_state_path = state_path
        proxy_server = selected_proxy.value if selected_proxy else None
        if rotation_settings["account_enabled"]:
            print(f"账号轮换：使用登录状态 {state_path}")
        if rotation_settings["proxy_enabled"] and proxy_server:
            print(f"IP 轮换：使用代理 {proxy_server}")

        try:
            processed_item_count += await _run_scrape_attempt(state_path, proxy_server)
            last_error = ""
            FAILURE_GUARD.record_success(task_name_for_guard)
            break
        except LoginRequiredError as e:
            last_error = str(e)
            print(f"检测到登录失效/重定向: {e}")
            break
        except RiskControlError as e:
            last_error = str(e)
            print(f"检测到风控或验证触发: {e}")
            # 风控验证通常不是简单轮换能解决的，避免无意义重试。
            break
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            print(f"本次尝试失败: {last_error}")
            if attempt < attempt_limit:
                print("将尝试轮换账号/IP 后重试...")

    if last_error:
        await _notify_task_failure(task_config, last_error, cookie_path=last_state_path)

    return processed_item_count


async def _scrape_item_by_id_in_context(context, item_id: str) -> Optional[Dict]:
    """在已有登录会话中读取一个商品详情，供店铺任务复用 Context。"""
    page = await context.new_page()
    item_url = f"https://www.goofish.com/item?id={item_id}"
    try:
        try:
            detail_response = await _navigate_and_wait_for_detail_response(page, item_url)
            if not detail_response.ok:
                print(f"获取商品详情 API 失败：{detail_response.status}")
                return None

            detail_json = await detail_response.json()
            ret_string = str(await safe_get(detail_json, "ret", default=[]))
            if "FAIL_SYS_USER_VALIDATE" in ret_string:
                raise RiskControlError("FAIL_SYS_USER_VALIDATE")

            item_do = await safe_get(detail_json, "data", "itemDO", default={})
            seller_do = await safe_get(detail_json, "data", "sellerDO", default={})
            if not item_do:
                print(f"商品 {item_id} 详情为空，可能已经下架")
                return None

            price_value = next(
                (
                    value
                    for value in (
                        item_do.get("soldPrice"),
                        item_do.get("price"),
                        item_do.get("finalPrice"),
                        item_do.get("displayPrice"),
                    )
                    if value is not None and str(value).strip() != ""
                ),
                None,
            )
            if price_value is None:
                price_info = item_do.get("priceInfo", {})
                if isinstance(price_info, dict):
                    price_value = price_info.get("price")
                    if price_value is None:
                        price_value = price_info.get("displayPrice")

            result = {
                "item_id": item_id,
                "商品 ID": item_id,
                "商品标题": item_do.get("title", ""),
                "当前售价": price_value,
                "商品链接": item_url,
                "想要人数": item_do.get("wantCnt"),
                "浏览量": item_do.get("browseCnt"),
                "卖家 ID": seller_do.get("sellerId"),
                "卖家昵称": seller_do.get("nick"),
                "芝麻信用": (seller_do.get("zhimaLevelInfo") or {}).get(
                    "levelName"
                ),
            }
            image_infos = await safe_get(item_do, "imageInfos", default=[])
            if image_infos:
                result["商品图片列表"] = [
                    image.get("url")
                    for image in image_infos
                    if isinstance(image, dict) and image.get("url")
                ]
            return result
        except PlaywrightTimeoutError:
            print(f"等待商品 {item_id} 详情 API 超时")
            if _is_login_url(page.url):
                raise LoginRequiredError(
                    "商品详情页已跳转到登录页，请重新更新该租户的登录状态"
                )
            try:
                page_content = await page.content()
            except Exception:
                page_content = ""
            if "FAIL_SYS_USER_VALIDATE" in page_content or "验证" in page_content:
                raise RiskControlError("FAIL_SYS_USER_VALIDATE")
            if "立即登录" in page_content:
                raise LoginRequiredError(
                    "商品详情页未识别到有效登录状态，请重新登录闲鱼"
                )
            if "网络不见了" in page_content:
                print("商品详情页显示网络异常，闲鱼未发起详情接口请求")
            return None
    finally:
        await page.close()


async def scrape_item_by_id(item_id: str) -> Optional[Dict]:
    """
    通过商品 ID 精确获取商品详情
    Args:
        item_id: 闲鱼商品 ID
    Returns:
        商品信息字典，如果失败则返回 None
    """
    state_file = get_state_file()
    if not os.path.exists(state_file):
        raise FileNotFoundError(f"登录状态文件不存在：{state_file}")

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            snapshot_data = json.load(f)
    except Exception as e:
        print(f"警告：读取登录状态文件失败：{e}")
        snapshot_data = None

    try:
        async with async_playwright() as p:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]

            launch_kwargs = {"headless": RUN_HEADLESS, "args": launch_args}
            launch_kwargs["channel"] = _resolve_browser_channel()

            browser = await p.chromium.launch(**launch_kwargs)

            context_kwargs = _default_context_options()
            storage_state_arg = state_file

            if isinstance(snapshot_data, dict) and any(
                key in snapshot_data for key in ("env", "headers", "page", "storage")
            ):
                storage_state_arg = {"cookies": snapshot_data.get("cookies", [])}
                context_kwargs.update(_build_context_overrides(snapshot_data))
                extra_headers = _build_extra_headers(snapshot_data.get("headers"))
                if extra_headers:
                    context_kwargs["extra_http_headers"] = extra_headers

            context = await browser.new_context(
                storage_state=storage_state_arg, **_clean_kwargs(context_kwargs)
            )

            try:
                return await _scrape_item_by_id_in_context(context, item_id)
            finally:
                await browser.close()

    except (RiskControlError, LoginRequiredError):
        raise
    except Exception as e:
        print(f"通过 ID 获取商品详情失败：{e}")
        return None


async def _navigate_and_wait_for_detail_response(page, item_url: str) -> Response:
    """在页面导航前监听详情接口，避免漏掉导航期间发出的响应。"""
    async with page.expect_response(
        lambda response: DETAIL_API_URL_PATTERN in response.url,
        timeout=50000,
    ) as detail_info:
        await page.goto(item_url, wait_until="domcontentloaded", timeout=60000)
    return await detail_info.value


def _active_store_items(cards: List[dict]) -> List[dict]:
    """从店铺列表响应中去重并筛出仍在售的商品。"""
    items: List[dict] = []
    seen_item_ids: set[str] = set()
    for card in cards:
        card_data = card.get("cardData", {}) if isinstance(card, dict) else {}
        item_id = str(card_data.get("id") or "").strip()
        item_status = card_data.get("itemStatus")
        if (
            not item_id
            or item_id in seen_item_ids
            or str(item_status).strip() != "0"
        ):
            continue
        seen_item_ids.add(item_id)
        want_count = None
        for key in ("wantCnt", "wantNum", "wantCount"):
            if card_data.get(key) is not None:
                want_count = card_data.get(key)
                break
        browse_count = None
        for key in ("browseCnt", "browseNum", "browseCount"):
            if card_data.get(key) is not None:
                browse_count = card_data.get(key)
                break
        price_info = card_data.get("priceInfo")
        pic_info = card_data.get("picInfo")
        items.append(
            {
                "item_id": item_id,
                "title": str(card_data.get("title") or ""),
                "price": (
                    price_info.get("price") if isinstance(price_info, dict) else None
                ),
                "image_url": (
                    pic_info.get("picUrl") if isinstance(pic_info, dict) else None
                ),
                "want_count": want_count,
                "browse_count": browse_count,
            }
        )
    return items


async def scrape_store_inventory(
    context,
    store_id: str,
    *,
    max_pages: int = 100,
    page_timeout_seconds: int = 30,
) -> dict:
    """完整读取店铺基本信息和全部在售商品。

    当响应声明仍有下一页却无法继续加载时直接失败，避免把半截列表当成完整
    店铺数据并产生误导性的监控结果。
    """
    page = await context.new_page()
    loop = asyncio.get_running_loop()
    head_future = loop.create_future()
    first_items_future = loop.create_future()
    next_page_loaded = asyncio.Event()
    all_cards: List[dict] = []
    response_state = {
        "page_count": 0,
        "has_next_page": True,
        "error": None,
    }

    async def handle_response(response: Response) -> None:
        if "mtop.idle.web.user.page.head" in response.url:
            if head_future.done():
                return
            try:
                head_future.set_result(await response.json())
            except Exception as exc:
                head_future.set_exception(exc)
            return

        if "mtop.idle.web.xyh.item.list" not in response.url:
            return
        try:
            if not response.ok:
                raise RuntimeError(
                    f"店铺商品列表接口 HTTP 状态异常：{response.status}"
                )
            payload = await response.json()
            ret_value = payload.get("ret")
            ret_text = str(ret_value or "")
            if "FAIL_SYS_USER_VALIDATE" in ret_text:
                raise RiskControlError("FAIL_SYS_USER_VALIDATE")
            if not ret_value or "SUCCESS" not in ret_text.upper():
                raise RuntimeError(
                    f"店铺商品列表接口返回失败：{ret_text or '缺少 ret'}"
                )
            data = payload.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("店铺商品列表响应缺少 data 对象")
            if "cardList" not in data:
                raise RuntimeError("店铺商品列表响应缺少 cardList")
            if "nextPage" not in data:
                raise RuntimeError("店铺商品列表响应缺少 nextPage")
            cards = data.get("cardList")
            if not isinstance(cards, list):
                raise RuntimeError("店铺商品列表响应格式异常：cardList 不是数组")
            all_cards.extend(cards)
            response_state["page_count"] = int(response_state["page_count"]) + 1
            response_state["has_next_page"] = _as_bool(
                data.get("nextPage"),
                False,
            )
            if not first_items_future.done():
                first_items_future.set_result(True)
            next_page_loaded.set()
            print(
                "      [店铺API] 已加载 "
                f"{response_state['page_count']} 页、{len(all_cards)} 条商品记录"
            )
        except Exception as exc:
            response_state["error"] = exc
            if not first_items_future.done():
                first_items_future.set_exception(exc)
            next_page_loaded.set()

    page.on("response", handle_response)
    try:
        await page.goto(
            f"https://www.goofish.com/personal?userId={store_id}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        if _is_login_url(page.url):
            raise LoginRequiredError(
                "店铺主页已跳转到登录页，请重新更新该租户的登录状态"
            )

        await asyncio.wait_for(first_items_future, timeout=page_timeout_seconds)
        if response_state["error"]:
            raise response_state["error"]

        while response_state["has_next_page"]:
            if int(response_state["page_count"]) >= max(1, max_pages):
                raise RuntimeError(
                    f"店铺商品分页超过安全上限 {max_pages} 页，未形成完整快照"
                )
            previous_page_count = int(response_state["page_count"])
            next_page_loaded.clear()
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                await asyncio.wait_for(
                    next_page_loaded.wait(), timeout=page_timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    "店铺商品分页加载超时，未形成完整快照，本轮已停止"
                ) from exc
            if response_state["error"]:
                raise response_state["error"]
            if int(response_state["page_count"]) <= previous_page_count:
                raise RuntimeError("店铺商品分页没有前进，本轮已停止")

        head_payload = None
        if head_future.done() and not head_future.cancelled():
            try:
                head_payload = head_future.result()
            except Exception:
                head_payload = None
        else:
            try:
                head_payload = await asyncio.wait_for(
                    asyncio.shield(head_future), timeout=5
                )
            except Exception:
                head_payload = None

        profile = await parse_user_head_data(head_payload or {})
        active_items = _active_store_items(all_cards)
        return {
            "store_id": store_id,
            "store_name": str(profile.get("卖家昵称") or "").strip() or None,
            "profile": profile,
            "items": active_items,
            "raw_item_count": len(all_cards),
            "page_count": int(response_state["page_count"]),
        }
    finally:
        page.remove_listener("response", handle_response)
        if not head_future.done():
            head_future.cancel()
        if not first_items_future.done():
            first_items_future.cancel()
        await page.close()


def _resolve_store_runtime(task_config: dict) -> tuple[str, Optional[str]]:
    """按现有账号/IP 策略为一次店铺运行挑选固定会话。"""
    settings = _get_rotation_settings(task_config)
    account_items = load_state_files(settings["account_state_dir"])
    runtime_plan = resolve_account_runtime_plan(
        strategy=task_config.get("account_strategy"),
        account_state_file=task_config.get("account_state_file"),
        has_root_state_file=os.path.exists(get_state_file()),
        available_account_files=account_items,
    )
    forced_account = runtime_plan["forced_account"]
    if forced_account:
        state_path = str(forced_account)
    elif runtime_plan["prefer_root_state"]:
        state_path = get_state_file()
    elif runtime_plan["use_account_pool"]:
        selected = RotationPool(
            account_items,
            settings["account_blacklist_ttl"],
            "account",
        ).pick_random()
        if not selected:
            raise FileNotFoundError("未找到可用的登录状态文件，无法执行店铺任务")
        state_path = selected.value
    else:
        state_path = get_state_file()

    if not state_path or not os.path.exists(state_path):
        raise FileNotFoundError(f"登录状态文件不存在：{state_path}")

    proxy_server: Optional[str] = None
    if settings["proxy_enabled"]:
        selected_proxy = RotationPool(
            parse_proxy_pool(settings["proxy_pool"]),
            settings["proxy_blacklist_ttl"],
            "proxy",
        ).pick_random()
        if not selected_proxy:
            raise RuntimeError("未找到可用的代理地址，无法执行店铺任务")
        proxy_server = selected_proxy.value
    return state_path, proxy_server


def _load_context_state(state_path: str) -> tuple[object, dict]:
    """读取普通 Playwright storage state 或增强浏览器快照。"""
    snapshot_data = None
    try:
        with open(state_path, "r", encoding="utf-8") as state_file:
            snapshot_data = json.load(state_file)
    except Exception as exc:
        print(f"警告：读取登录状态文件失败，将直接按路径使用：{exc}")

    storage_state: object = state_path
    context_options = _default_context_options()
    if isinstance(snapshot_data, dict):
        if any(
            key in snapshot_data for key in ("env", "headers", "page", "storage")
        ):
            storage_state = {"cookies": snapshot_data.get("cookies", [])}
            context_options.update(_build_context_overrides(snapshot_data))
            extra_headers = _build_extra_headers(snapshot_data.get("headers"))
            if extra_headers:
                context_options["extra_http_headers"] = extra_headers
        else:
            storage_state = snapshot_data
    return storage_state, _clean_kwargs(context_options)


def _persist_discovered_store_name(
    *,
    task_name: str,
    store_id: str,
    store_name: Optional[str],
) -> None:
    """首次发现店铺名称后回填任务，保留用户手工设置的名称。"""
    if not store_name:
        return
    try:
        from src.infrastructure.persistence.sqlite_connection import sqlite_connection

        with sqlite_connection() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET store_name = ?
                WHERE task_name = ?
                  AND task_type = 'store'
                  AND store_id = ?
                  AND (store_name IS NULL OR TRIM(store_name) = '')
                """,
                (store_name, task_name, store_id),
            )
            connection.commit()
    except Exception as exc:
        print(f"回填店铺名称失败，本轮继续使用已发现名称：{exc}")


def _inspect_store_monitor_items(
    *,
    task_name: str,
    items: List[dict],
) -> dict:
    """只读计算完整店铺快照的成员变化。

    真正的 active/inactive 写入由 ``persist_store_run`` 与指标、
    通知 outbox 在同一事务中完成，避免进程中断丢失上下架事件。
    """
    from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
    from src.infrastructure.persistence.sqlite_connection import sqlite_connection

    bootstrap_sqlite_storage()
    with sqlite_connection() as connection:
        previous_rows = connection.execute(
            """
            SELECT item_id, title, is_active
            FROM store_monitor_items
            WHERE task_name = ?
            """,
            (task_name,),
        ).fetchall()
        previous_active = {
            str(row["item_id"]): str(row["title"] or "")
            for row in previous_rows
            if bool(row["is_active"])
        }
        current_items = {
            str(item.get("item_id") or "").strip(): str(item.get("title") or "")
            for item in items
            if str(item.get("item_id") or "").strip()
        }
    added_item_ids = set(current_items) - set(previous_active)
    removed_item_ids = set(previous_active) - set(current_items)
    return {
        "is_first_inventory": not previous_rows,
        "added_items": [
            {"item_id": item_id, "title": current_items[item_id]}
            for item_id in sorted(added_item_ids)
        ],
        "removed_items": [
            {"item_id": item_id, "title": previous_active[item_id]}
            for item_id in sorted(removed_item_ids)
        ],
    }


async def _install_store_context_guards(context) -> None:
    await context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
        window.chrome = {runtime: {}, loadTimes: function() {}, csi: function() {}};
        Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5});
        """
    )


async def _queue_and_deliver_store_notifications(
    *,
    notification_service,
    task_name: str,
    event_key: str,
    digest,
) -> List[str]:
    """持久化当前摘要并重试该店铺之前未成功的通知渠道。"""
    from src.services.store_notification_outbox import (
        enqueue_store_digest,
        list_pending_store_digests,
        update_store_digest_delivery,
    )

    if digest is not None:
        enqueue_store_digest(
            event_key=event_key,
            digest=digest,
            channel_keys=notification_service.enabled_channel_keys(),
        )

    all_failed_channels: set[str] = set()
    for pending in list_pending_store_digests(task_name=task_name):
        results = await notification_service.send_store_digest(
            pending.digest,
            channel_keys=pending.pending_channels,
        )
        failed_channels = []
        error_messages = []
        for channel in pending.pending_channels:
            channel_result = results.get(channel)
            if channel_result and channel_result.get("success"):
                continue
            failed_channels.append(channel)
            if channel_result and channel_result.get("message"):
                error_messages.append(
                    f"{channel}: {channel_result.get('message')}"
                )
            else:
                error_messages.append(f"{channel}: 当前未启用或无发送结果")
        update_store_digest_delivery(
            record_id=pending.id,
            failed_channels=failed_channels,
            last_error="; ".join(error_messages) or None,
        )
        all_failed_channels.update(failed_channels)
    return sorted(all_failed_channels)


async def scrape_store_by_id(
    store_id: str,
    task_config: dict,
    debug_limit: int = 0,
) -> dict:
    """按店铺维度发现全部在售商品、记录指标并发送一条聚合通知。"""
    from src.domain.models.store_monitoring import (
        StoreItemChange,
        StoreItemLifecycle,
        StoreMonitoringDigest,
    )
    from src.services.metrics_tracking_service import get_metrics_service
    from src.services.store_notification_outbox import persist_store_run

    normalized_store_id = str(store_id or "").strip()
    if not normalized_store_id:
        raise ValueError("店铺 ID 不能为空")

    task_name = str(task_config.get("task_name") or f"店铺 {normalized_store_id}")
    configured_store_name = str(task_config.get("store_name") or "").strip() or None
    keyword = str(task_config.get("keyword") or f"store_{normalized_store_id}")
    run_id = f"store_{normalized_store_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    state_path = ""

    try:
        state_path, proxy_server = _resolve_store_runtime(task_config)
        storage_state, context_options = _load_context_state(state_path)
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]
        launch_options = {
            "headless": RUN_HEADLESS,
            "args": launch_args,
            "channel": _resolve_browser_channel(),
        }
        if proxy_server:
            launch_options["proxy"] = {"server": proxy_server}

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_options)
            try:
                context = await browser.new_context(
                    storage_state=storage_state,
                    **context_options,
                )
                await _install_store_context_guards(context)

                warmup_page = await context.new_page()
                try:
                    await warmup_page.goto(
                        "https://www.goofish.com/",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    await random_sleep(1, 3)
                    await warmup_page.evaluate(
                        "window.scrollBy(0, Math.random() * 400 + 150)"
                    )
                    await random_sleep(1, 2)
                finally:
                    await warmup_page.close()

                inventory = await scrape_store_inventory(
                    context,
                    normalized_store_id,
                    max_pages=max(
                        1,
                        _as_int(os.getenv("STORE_INVENTORY_MAX_PAGES"), 100),
                    ),
                    page_timeout_seconds=max(
                        5,
                        _as_int(os.getenv("STORE_PAGE_TIMEOUT_SECONDS"), 30),
                    ),
                )
                store_name = configured_store_name or inventory.get("store_name")
                if not configured_store_name:
                    _persist_discovered_store_name(
                        task_name=task_name,
                        store_id=normalized_store_id,
                        store_name=store_name,
                    )
                inventory_items = list(inventory.get("items") or [])
                membership_changes = _inspect_store_monitor_items(
                    task_name=task_name,
                    items=inventory_items,
                )
                store_items = inventory_items
                if debug_limit > 0:
                    store_items = store_items[:debug_limit]

                print(
                    f"店铺监控组 '{task_name}' 发现 {len(store_items)} 件在售商品，"
                    "开始顺序采集详情。"
                )
                delay_min = max(
                    0,
                    _as_int(os.getenv("STORE_ITEM_DELAY_MIN_SECONDS"), 8),
                )
                delay_max = max(
                    delay_min,
                    _as_int(os.getenv("STORE_ITEM_DELAY_MAX_SECONDS"), 15),
                )
                detail_max_attempts = max(
                    1,
                    _as_int(os.getenv("STORE_ITEM_DETAIL_MAX_ATTEMPTS"), 2),
                )
                metrics_service = get_metrics_service()
                metric_changes = []
                metric_observations: List[dict] = []
                succeeded_count = 0
                failed_item_ids: List[str] = []
                first_seen_count = 0
                seen_snapshot_ids: set[str] = set()
                detail_request_count = 0

                for item_index, store_item in enumerate(store_items):
                    item_id = str(store_item.get("item_id") or "")
                    print(
                        f"   [{item_index + 1}/{len(store_items)}] 采集店铺商品 {item_id}"
                    )
                    raw_list_want_count = store_item.get("want_count")
                    list_want_count = parse_metric_count(raw_list_want_count)
                    if (
                        list_want_count is not None
                        # “1.2万”等展示值已被四舍五入，不能用作精确变化
                        # 基线；这类情况继续访问详情接口。
                        and "万" not in str(raw_list_want_count)
                        and store_item.get("price") is not None
                    ):
                        # 若店铺列表接口已直接给出指标，则无需再打开详情页。这一
                        # 兼容路径会自动降低请求量；字段缺失时仍回退到详情接口。
                        item_result = {
                            "item_id": item_id,
                            "商品 ID": item_id,
                            "商品标题": store_item.get("title"),
                            "当前售价": store_item.get("price"),
                            "商品链接": f"https://www.goofish.com/item?id={item_id}",
                            "想要人数": store_item.get("want_count"),
                            "浏览量": store_item.get("browse_count"),
                            "卖家 ID": normalized_store_id,
                            "卖家昵称": store_name,
                            "商品图片列表": (
                                [store_item["image_url"]]
                                if store_item.get("image_url")
                                else []
                            ),
                        }
                        print("      店铺列表已包含想要数，跳过详情页请求")
                    else:
                        item_result = None
                        for detail_attempt in range(1, detail_max_attempts + 1):
                            if detail_request_count > 0 and delay_max > 0:
                                await random_sleep(delay_min, delay_max)
                            try:
                                item_result = await _scrape_item_by_id_in_context(
                                    context, item_id
                                )
                            except (RiskControlError, LoginRequiredError):
                                # 风控和登录失效必须立即终止整轮，避免继续请求扩大封控。
                                raise
                            except Exception as exc:
                                # 单个详情页的瞬时 JSON/网络异常不应立即放弃
                                # 整家店；按同样的保守节奏做有限重试。
                                print(
                                    f"      商品 {item_id} 详情请求异常："
                                    f"{type(exc).__name__}: {exc}"
                                )
                                item_result = None
                            detail_request_count += 1
                            if item_result and parse_metric_count(
                                item_result.get("想要人数")
                            ) is not None:
                                break
                            if item_result:
                                print(
                                    f"      商品 {item_id} 详情缺少有效想要数，"
                                    "本次不作为成功快照"
                                )
                                item_result = None
                            if detail_attempt < detail_max_attempts:
                                print(
                                    f"      商品 {item_id} 详情采集失败，"
                                    f"将在保守退避后重试 "
                                    f"({detail_attempt + 1}/{detail_max_attempts})"
                                )
                    if not item_result:
                        failed_item_ids.append(item_id)
                        continue
                    seller_id = str(item_result.get("卖家 ID") or "").strip()
                    if seller_id and seller_id != normalized_store_id:
                        print(
                            f"   商品 {item_id} 卖家 ID 为 {seller_id}，"
                            f"与店铺 {normalized_store_id} 不一致，已跳过"
                        )
                        failed_item_ids.append(item_id)
                        continue

                    item_data = {
                        "商品 ID": item_id,
                        "商品标题": item_result.get("商品标题")
                        or store_item.get("title")
                        or "",
                        "当前售价": item_result.get("当前售价"),
                        "商品链接": item_result.get("商品链接"),
                        "想要人数": item_result.get("想要人数"),
                        "浏览量": item_result.get("浏览量"),
                        "卖家 ID": item_result.get("卖家 ID"),
                        "卖家昵称": item_result.get("卖家昵称") or store_name,
                        "芝麻信用": item_result.get("芝麻信用"),
                        "商品图片列表": item_result.get("商品图片列表", []),
                        "发布时间": None,
                    }
                    price_value = parse_price_value(item_data.get("当前售价"))
                    want_count = parse_metric_count(item_data.get("想要人数"))
                    browse_count = parse_metric_count(item_data.get("浏览量"))
                    previous = metrics_service.get_last_snapshot(
                        item_id,
                        task_name=task_name,
                    )
                    change = metrics_service.compare_with_latest(
                        item_id=item_id,
                        current_price=price_value,
                        current_price_display=(
                            str(item_data.get("当前售价"))
                            if item_data.get("当前售价") is not None
                            else None
                        ),
                        current_want_count=want_count,
                        want_count_threshold=1,
                        task_name=task_name,
                    )
                    if change:
                        if change.get("price_change_display"):
                            item_data["price_change_display"] = change[
                                "price_change_display"
                            ]
                        if change.get("want_count_change_display"):
                            item_data["want_count_change_display"] = change[
                                "want_count_change_display"
                            ]

                    snapshot_time = datetime.now().isoformat()
                    final_record = {
                        "搜索关键字": keyword,
                        "任务名称": task_name,
                        "监控店铺 ID": normalized_store_id,
                        "监控店铺名称": store_name,
                        "爬取时间": snapshot_time,
                        "商品信息": item_data,
                        "卖家信息": {
                            "卖家 ID": item_result.get("卖家 ID"),
                            "卖家昵称": item_result.get("卖家昵称") or store_name,
                        },
                        "match_result": {
                            "analysis_source": "store",
                            "is_recommended": True,
                            "reason": "店铺监控组在售商品",
                            "keyword_hit_count": 1,
                            "matched_keywords": [normalized_store_id],
                        },
                    }
                    result_saved = await save_to_jsonl(final_record, keyword)
                    if not result_saved:
                        print(f"   商品 {item_id} 结果记录写入失败，本项标记为失败")
                        failed_item_ids.append(item_id)
                        continue
                    try:
                        record_market_snapshots(
                            keyword=keyword,
                            task_name=task_name,
                            items=[item_data],
                            run_id=run_id,
                            snapshot_time=snapshot_time,
                            seen_item_ids=seen_snapshot_ids,
                        )
                    except Exception as exc:
                        print(
                            f"   商品 {item_id} 价格快照写入失败，本项标记为失败：{exc}"
                        )
                        failed_item_ids.append(item_id)
                        continue
                    metric_observations.append(
                        {
                            "task_name": task_name,
                            "item_id": item_id,
                            "title": str(item_data.get("商品标题") or "")[:200],
                            "snapshot_time": snapshot_time,
                            "price": price_value,
                            "price_display": (
                                str(item_data.get("当前售价"))
                                if item_data.get("当前售价") is not None
                                else None
                            ),
                            "want_count": want_count,
                            "browse_count": browse_count,
                            "seller_id": seller_id or None,
                            "link": item_data.get("商品链接"),
                        }
                    )
                    succeeded_count += 1

                    if previous is None:
                        first_seen_count += 1
                    if previous is None or change:
                        metric_changes.append(
                            StoreItemChange(
                                item_id=item_id,
                                title=str(item_data.get("商品标题") or ""),
                                previous_want_count=(
                                    previous.get("want_count") if previous else None
                                ),
                                current_want_count=want_count,
                                want_count_delta=(
                                    want_count - int(previous["want_count"])
                                    if previous
                                    and previous.get("want_count") is not None
                                    and want_count is not None
                                    else None
                                ),
                                previous_price=(
                                    previous.get("price") if previous else None
                                ),
                                current_price=price_value,
                                link=item_data.get("商品链接"),
                            )
                        )

                failed_count = len(store_items) - succeeded_count
                is_initial_snapshot = (
                    succeeded_count > 0 and first_seen_count == succeeded_count
                )
                digest = StoreMonitoringDigest(
                    store_id=normalized_store_id,
                    task_name=task_name,
                    discovered_count=len(store_items),
                    succeeded_count=succeeded_count,
                    failed_count=failed_count,
                    changes=tuple(metric_changes),
                    added_items=(
                        tuple()
                        if membership_changes["is_first_inventory"]
                        else tuple(
                            StoreItemLifecycle(
                                item_id=item["item_id"],
                                title=item["title"],
                                link=(
                                    f"https://www.goofish.com/item?id={item['item_id']}"
                                ),
                            )
                            for item in membership_changes["added_items"]
                        )
                    ),
                    removed_items=tuple(
                        StoreItemLifecycle(
                            item_id=item["item_id"],
                            title=item["title"],
                            link=(
                                f"https://www.goofish.com/item?id={item['item_id']}"
                            ),
                        )
                        for item in membership_changes["removed_items"]
                    ),
                    store_name=store_name,
                    is_initial_snapshot=is_initial_snapshot,
                )
                should_notify = bool(
                    metric_changes
                    or digest.added_items
                    or digest.removed_items
                    or failed_count > 0
                )
                notification_service = build_notification_service()
                persist_store_run(
                    metric_observations=metric_observations,
                    event_key=run_id,
                    digest=digest if should_notify else None,
                    channel_keys=notification_service.enabled_channel_keys(),
                    store_membership={
                        "task_name": task_name,
                        "store_id": normalized_store_id,
                        # 成员必须使用未被 debug_limit 截断的完整库存。
                        "items": inventory_items,
                    },
                )
                failed_channels = await _queue_and_deliver_store_notifications(
                    notification_service=notification_service,
                    task_name=task_name,
                    event_key=run_id,
                    digest=None,
                )
                if should_notify:
                    if failed_channels:
                        print(
                            "店铺汇总通知发送失败，摘要已进入待发队列："
                            + ", ".join(failed_channels)
                        )
                else:
                    print("本轮店铺商品指标无变化，不发送重复通知。")

                if failed_count > 0:
                    raise RuntimeError(
                        f"店铺监控部分失败：成功 {succeeded_count}/"
                        f"{len(store_items)}，失败商品："
                        f"{', '.join(failed_item_ids) or '未知'}"
                    )

                FAILURE_GUARD.record_success(task_name)
                print(
                    f"店铺监控完成：成功 {succeeded_count}/{len(store_items)}，"
                    f"变化或新纳入 {len(metric_changes)} 件。"
                )
                return {
                    "processed_count": succeeded_count,
                    "discovered_count": len(store_items),
                    "failed_count": failed_count,
                    "changed_count": len(metric_changes),
                    "store_name": store_name,
                }
            finally:
                await browser.close()
    except Exception as exc:
        await _notify_task_failure(
            task_config,
            str(exc),
            cookie_path=state_path or None,
        )
        raise


async def scrape_items_by_id_batch(
    item_ids: List[str],
    task_config: dict,
    debug_limit: int = 0,
) -> int:
    """
    批量通过商品 ID 获取商品详情并执行规则处理
    Args:
        item_ids: 商品 ID 列表
        task_config: 任务配置（包含匹配规则、通知设置等）
        debug_limit: 调试模式限制数量（0 表示不限制）
    Returns:
        成功处理的商品数量
    """
    from src.services.item_analysis_dispatcher import (
        ItemAnalysisDispatcher,
        ItemAnalysisJob,
    )
    task_name = task_config.get("task_name", "商品 ID 监控")
    keyword = task_config.get("keyword") or task_name or "item_id_monitor"
    keyword_rules = list(dict.fromkeys(str(item_id).strip() for item_id in item_ids if str(item_id).strip()))

    # 限制调试模式数量
    if debug_limit > 0:
        item_ids = item_ids[:debug_limit]

    print(f"开始批量抓取 {len(item_ids)} 个商品 ID...")

    async def _load_seller_info(_seller_id: str) -> dict:
        # 商品详情响应已经包含 ID 模式所需的卖家昵称与芝麻信用。
        # 这里不再额外启动浏览器抓取卖家主页，避免重复请求和无效缓存调用。
        return {}

    async def _send_notification(item_data: dict, reason: str) -> None:
        await build_notification_service().send_notification(item_data, reason)

    async def _save_result(record: dict, kw: str) -> bool:
        from src.services.result_storage_service import save_result_record
        return await save_result_record(record, kw)

    analysis_dispatcher = ItemAnalysisDispatcher(
        concurrency=_get_processing_concurrency(task_config),
        seller_loader=_load_seller_info,
        notifier=_send_notification,
        saver=_save_result,
    )

    processed_count = 0
    failed_item_ids: List[str] = []
    request_delay_min = max(
        0,
        _as_int(os.getenv("ITEM_ID_REQUEST_DELAY_MIN_SECONDS"), 3),
    )
    request_delay_max = max(
        request_delay_min,
        _as_int(os.getenv("ITEM_ID_REQUEST_DELAY_MAX_SECONDS"), 7),
    )

    for item_index, item_id in enumerate(item_ids):
        if item_index > 0 and request_delay_max > 0:
            await random_sleep(request_delay_min, request_delay_max)
        try:
            print(f"正在抓取商品 ID: {item_id}")
            result = await scrape_item_by_id(item_id)
            if not result:
                print(f"   商品 {item_id} 获取失败，跳过")
                failed_item_ids.append(str(item_id))
                continue

            # 构建记录结构（与关键词搜索保持一致）
            final_record = {
                "搜索关键字": keyword,
                "任务名称": task_name,
                "爬取时间": datetime.now().isoformat(),
                "商品信息": {
                    "商品 ID": result.get("item_id"),
                    "商品标题": result.get("商品标题"),
                    "当前售价": result.get("当前售价"),
                    "商品链接": result.get("商品链接"),
                    "想要人数": result.get("想要人数"),
                    "浏览量": result.get("浏览量"),
                    "卖家 ID": result.get("卖家 ID"),
                    "卖家昵称": result.get("卖家昵称"),
                    "芝麻信用": result.get("芝麻信用"),
                    "发布时间": None,  # 商品 ID 模式无发布时间
                    "商品图片列表": result.get("商品图片列表", []),
                },
            }

            # 记录价格快照（商品 ID 模式也需要记录价格历史）
            try:
                record_market_snapshots(
                    keyword=keyword,
                    task_name=task_name,
                    items=[final_record["商品信息"]],
                    run_id=f"id_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    snapshot_time=final_record["爬取时间"],
                )
            except Exception as e:
                print(f"记录价格快照失败：{e}")

            # 提取卖家信息
            seller_id = str(result.get("卖家 ID") or "")
            zhima_credit_text = result.get("芝麻信用", "")
            registration_duration_text = ""

            # 提交分析任务
            analysis_dispatcher.submit(
                ItemAnalysisJob(
                    keyword=keyword,
                    task_name=task_name,
                    keyword_rules=tuple(keyword_rules),
                    final_record=final_record,
                    seller_id=seller_id if seller_id else None,
                    zhima_credit_text=zhima_credit_text,
                    registration_duration_text=registration_duration_text,
                )
            )
            processed_count += 1

        except (RiskControlError, LoginRequiredError) as exc:
            await analysis_dispatcher.join()
            await _notify_task_failure(
                task_config,
                str(exc),
                cookie_path=get_state_file(),
            )
            raise
        except Exception as e:
            print(f"   商品 {item_id} 处理失败：{e}")
            failed_item_ids.append(str(item_id))
            continue

    # 等待所有商品处理任务完成
    log_time("等待后台商品处理任务完成...")
    await analysis_dispatcher.join()

    if processed_count == 0 and item_ids:
        failure_reason = (
            f"本次未成功采集任何商品（0/{len(item_ids)}），"
            f"失败商品 ID：{', '.join(failed_item_ids) or '未知'}"
        )
        await _notify_task_failure(
            task_config,
            failure_reason,
            cookie_path=get_state_file(),
        )
        raise RuntimeError(failure_reason)

    if processed_count > 0:
        FAILURE_GUARD.record_success(task_name)

    print(f"批量抓取完成，成功处理 {processed_count}/{len(item_ids)} 个商品")

    # 返回统计信息（用于进程服务解析想要数和价格变化）
    return {
        "processed_count": processed_count,
    }
