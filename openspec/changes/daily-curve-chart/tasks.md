## 1. 后端数据层

- [x] 1.1 在 `price_history_service.py` 中新增 `_fetch_daily_want_counts` 函数，从 `item_metrics_history` 查询每日想要数
- [x] 1.2 修改 `_build_daily_trend` 函数，合并每日想要数数据到返回结果
- [x] 1.3 更新 `build_price_history_insights` 返回结构，确保 `daily_trend` 包含 `avg_want_count` 字段

## 2. 前端类型定义

- [x] 2.1 更新 `web-ui/src/types/result.d.ts` 中 `daily_trend` 数组元素类型，添加 `avg_want_count: number | null`
- [x] 2.2 更新 `web-ui/src/i18n/messages/zh-CN.ts` 图表相关文案（标题改为 "Daily Curve"，新增 "想要数" 图例）
- [x] 2.3 更新 `web-ui/src/i18n/messages/en-US.ts` 图表相关文案

## 3. 前端组件重构

- [x] 3.1 将 `PriceTrendChart.vue` 重命名为 `DailyCurveChart.vue`
- [x] 3.2 重构 SVG 图表为双 Y 轴设计（左轴价格，右轴想要数）
- [x] 3.3 新增 `resolveYWant` 函数计算想要数 Y 坐标
- [x] 3.4 新增想要数趋势线（橙色）和对应数据点
- [x] 3.5 更新图例显示：价格（蓝色）+ 想要数（橙色）
- [x] 3.6 更新图表标题为 "Daily Curve"

## 4. 组件引用更新

- [x] 4.1 更新 `ResultsInsightsPanel.vue` 中的组件引用，改为 `DailyCurveChart`

## 5. 测试验证

- [x] 5.1 后端单元测试：验证 `_build_daily_trend` 返回正确的 `avg_want_count`
- [x] 5.2 前端组件测试：验证双 Y 轴渲染正确
- [x] 5.3 集成测试：验证 API 返回数据结构与前端类型匹配