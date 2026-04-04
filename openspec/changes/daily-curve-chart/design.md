## Context

当前结果页面的 `PriceTrendChart.vue` 组件仅展示价格趋势（avg_price 和 median_price）。后端 `price_history_service.py` 的 `_build_daily_trend` 函数从 `price_snapshots` 表聚合每日价格数据。想要数数据存储在 `item_metrics_history` 表中，由 `metrics_tracking_service.py` 管理，但未纳入趋势图。

图表使用 SVG 绘制，单 Y 轴（价格），两条线（均价和中位数价）。前端数据通过 `ResultInsights.daily_trend` 传递。

## Goals / Non-Goals

**Goals:**
- 重命名图表标题为 "Daily Curve"
- 新增想要数趋势线，与价格线并列
- 实现双 Y 轴设计，避免量级差异导致的显示问题
- 后端返回数据增加每日想要数统计

**Non-Goals:**
- 不改变现有的 price_snapshots 数据结构
- 不修改 item_metrics_history 的记录逻辑
- 不添加交互功能（如缩放、点击查看详情）

## Decisions

### 1. 数据聚合策略

**选择**: 在 `_build_daily_trend` 中查询 `item_metrics_history` 表，按日期聚合想要数

**理由**:
- `price_snapshots` 表不存储想要数，数据在 `item_metrics_history`
- 按日期聚合可复用现有分组逻辑
- 避免新建表或迁移数据

**备选方案**:
- A) 在 price_snapshots 表增加 want_count 字段 → 需迁移历史数据，风险高
- B) 单独 API 查询想要数趋势 → 前端需合并两数据源，复杂度增加

### 2. 双 Y 轴实现

**选择**: SVG 双 Y 轴，左轴价格，右轴想要数

**理由**:
- 价格和想要数量级差异大（如 ¥500 vs 120人想要）
- 单 Y 轴会导致想要数线几乎平坦
- 纯 SVG 实现轻量，无需引入图表库

**备选方案**:
- A) 引入 Chart.js / ECharts → 增加依赖，与现有风格不一致
- B) 归一化数据 → 用户难以直观读取原始值

### 3. 想要数聚合指标

**选择**: 使用 `avg_want_count`（每日平均想要数）

**理由**:
- 与价格使用 avg_price 保持一致
- 每日商品数量不同，平均值更稳定
- 易于理解

**备选方案**:
- A) 使用 total_want_count（每日总想要数）→ 商品数波动时数据不稳定
- B) 使用 max_want_count → 偏向热门商品，代表性差

## Risks / Trade-offs

### [数据延迟] 想要数记录依赖爬虫触发
- **Mitigation**: 若某日无想要数记录，该点显示 null，图表自动跳过

### [量级差异] 想要数可能远大于价格值
- **Mitigation**: 双 Y 轴设计，各自独立刻度

### [前端复杂度] SVG 双 Y 轴需额外计算
- **Mitigation**: 复用现有 `resolveY` 逻辑，新增 `resolveYWant` 函数