## Why

当前结果页面的价格趋势图 "Daily Price Curve" 仅展示价格走向，缺少想要数（want_count）的趋势信息。用户希望同时查看价格和想要数的变化趋势，以便更好地判断商品的市场热度和性价比时机。

## What Changes

- 重命名图表标题：`Daily Price Curve` → `Daily Curve`
- 新增想要数趋势线，与价格趋势线并列展示
- 使用双 Y 轴设计：价格轴（左）和想要数轴（右）
- 更新图表图例：价格线 + 想要数线
- 后端 API 返回数据增加每日想要数聚合值

## Capabilities

### New Capabilities
- `daily-curve-chart`: 新的 Daily Curve 图表组件，支持双指标（价格 + 想要数）趋势展示

### Modified Capabilities
- `price-history-service`: 修改 `build_price_history_insights` 和 `_build_daily_trend` 函数，返回数据增加每日想要数统计（avg_want_count, total_want_count）

## Impact

**前端**：
- `web-ui/src/components/results/PriceTrendChart.vue` - 重命名为 `DailyCurveChart.vue`，重构为双指标图表
- `web-ui/src/components/results/ResultsInsightsPanel.vue` - 引用新组件名
- `web-ui/src/types/result.d.ts` - `daily_trend` 数据结构增加想要数字段
- `web-ui/src/i18n/messages/*.ts` - 国际化文案更新

**后端**：
- `src/services/price_history_service.py` - `_build_daily_trend` 增加 want_count 聚合逻辑
- `src/services/metrics_tracking_service.py` - 可能需要新增按日期聚合想要数的方法

**数据库**：
- 查询 `item_metrics_history` 表获取每日想要数数据