## ADDED Requirements

### Requirement: 每日趋势数据包含想要数统计

系统 SHALL 在 `daily_trend` 返回数据中包含每日想要数统计值。

#### Scenario: 数据结构扩展
- **WHEN** 调用 `build_price_history_insights` 函数
- **THEN** 返回的 `daily_trend` 数组中每个元素包含 `avg_want_count` 字段

#### Scenario: 想要数聚合计算
- **WHEN** 存在某日的 item_metrics_history 记录
- **THEN** 该日的 avg_want_count 为所有商品想要数的平均值

#### Scenario: 无想要数记录
- **WHEN** 某日无 item_metrics_history 记录
- **THEN** 该日的 avg_want_count 为 null

### Requirement: 跨表查询支持

系统 SHALL 在 `_build_daily_trend` 函数中查询 `item_metrics_history` 表获取想要数数据。

#### Scenario: 按日期关联
- **WHEN** 处理某日的快照数据
- **THEN** 从 item_metrics_history 查询该日（snapshot_day）的想要数记录

#### Scenario: 性能优化
- **WHEN** 查询跨越多日数据
- **THEN** 使用单次批量查询而非逐日查询