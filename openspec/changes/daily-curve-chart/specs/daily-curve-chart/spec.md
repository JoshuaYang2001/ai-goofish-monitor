## ADDED Requirements

### Requirement: Daily Curve 图表展示价格和想要数趋势

系统 SHALL 在结果页面的 Daily Curve 图表中同时展示价格趋势线和想要数趋势线。

#### Scenario: 正常数据展示
- **WHEN** daily_trend 数据包含有效的价格和想要数值
- **THEN** 图表显示两条趋势线：价格线（蓝色）和想要数线（橙色）

#### Scenario: 缺失想要数数据
- **WHEN** 某日无想要数记录
- **THEN** 想要数线在该点跳过，不显示断点标记

#### Scenario: 完全无数据
- **WHEN** daily_trend 为空数组
- **THEN** 显示 "暂无趋势数据" 提示

### Requirement: 双 Y 轴设计

系统 SHALL 使用双 Y 轴设计，左轴显示价格刻度，右轴显示想要数刻度。

#### Scenario: Y 轴刻度独立
- **WHEN** 价格范围和想要数范围差异显著
- **THEN** 两个 Y 轴各自独立计算刻度范围

### Requirement: 图表标题和图例

系统 SHALL 显示图表标题 "Daily Curve" 和两条线的图例说明。

#### Scenario: 图例展示
- **WHEN** 图表渲染完成
- **THEN** 显示图例：价格（蓝色圆点）和想要数（橙色圆点）