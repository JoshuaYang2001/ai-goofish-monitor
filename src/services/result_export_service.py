"""
结果导出服务
"""
import csv
from io import StringIO


EXPORT_HEADERS = [
    "任务名称",
    "搜索关键字",
    "商品ID",
    "商品标题",
    "当前售价",
    "发布时间",
    "卖家昵称",
    "规则是否命中",
    "匹配来源",
    "匹配原因",
    "价格观察次数",
    "价格最低值",
    "价格最高值",
    "市场均价",
    "性价比分数",
    "性价比标签",
    "商品链接",
]


def build_results_csv(records: list[dict]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_HEADERS)
    writer.writeheader()

    for record in records:
        item = record.get("商品信息", {}) or {}
        seller = record.get("卖家信息", {}) or {}
        match_result = record.get("match_result", {}) or {}
        price_insight = record.get("price_insight", {}) or {}
        writer.writerow(
            {
                "任务名称": record.get("任务名称", ""),
                "搜索关键字": record.get("搜索关键字", ""),
                "商品ID": item.get("商品ID", ""),
                "商品标题": item.get("商品标题", ""),
                "当前售价": item.get("当前售价", ""),
                "发布时间": item.get("发布时间", ""),
                "卖家昵称": seller.get("卖家昵称") or item.get("卖家昵称", ""),
                "规则是否命中": "是" if match_result.get("is_recommended") else "否",
                "匹配来源": match_result.get("analysis_source", ""),
                "匹配原因": match_result.get("reason", ""),
                "价格观察次数": price_insight.get("observation_count", ""),
                "价格最低值": price_insight.get("min_price", ""),
                "价格最高值": price_insight.get("max_price", ""),
                "市场均价": price_insight.get("market_avg_price", ""),
                "性价比分数": price_insight.get("deal_score", ""),
                "性价比标签": price_insight.get("deal_label", ""),
                "商品链接": item.get("商品链接", ""),
            }
        )

    return buffer.getvalue()
