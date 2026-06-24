"""
pywencai API 使用示例 — 股票数据抽取
=====================================
所有接口实测可用，在你 Mac 上直接跑: python3 bot/pywencai_api_demo.py

依赖: pip3 install pywencai pandas
"""

import pywencai
import json

CODE = "002913"  # 改这里测试不同股票


# ===================================================================
# 1. 资金流向 — 历史主力资金流向（与同花顺网页一致）
# ===================================================================
def demo_fund_flow(code):
    print("=" * 60)
    print("1. 资金流向 — pywencai.get(query=code) -> 历史主力资金流向")
    print("=" * 60)
    r = pywencai.get(query=code)
    flow = r.get("历史主力资金流向", {})
    df = flow.get("barline3")  # 字段: 时间, 成交额, 主力资金
    print("   最近 5 天:")
    for _, row in df.tail(5).iterrows():
        print(f"     {row['时间']} | 主力={float(row['主力资金'])/1e4:>10.2f}万 | 成交额={float(row['成交额'])/1e8:.2f}亿")


# ===================================================================
# 2. 资金流向拆分 — 特大单/大单/中单/小单（仅最新几天）
# ===================================================================
def demo_breakdown(code):
    print("\n" + "=" * 60)
    print("2. 资金拆分 — 逐日资金流向 特大单 大单 中单 小单")
    print("=" * 60)
    r = pywencai.get(query=f"{code} 逐日资金流向 特大单 大单 中单 小单")
    df = r.get("tableV1")
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            sl = float(row.get("特大单净额", 0)) / 1e4 if row.get("特大单净额") and str(row["特大单净额"]) != "nan" else 0
            dl = float(row.get("dde大单净额", 0)) / 1e4 if row.get("dde大单净额") and str(row["dde大单净额"]) != "nan" else 0
            md = float(row.get("中单净额", 0)) / 1e4 if row.get("中单净额") and str(row["中单净额"]) != "nan" else 0
            sm = float(row.get("小单净额", 0)) / 1e4 if row.get("小单净额") and str(row["小单净额"]) != "nan" else 0
            print(f"     {row['时间区间']} | 特大单={sl:>8.2f}万 | DDE大单={dl:>8.2f}万 | 中单={md:>8.2f}万 | 小单={sm:>8.2f}万")


# ===================================================================
# 3. 概念板块
# ===================================================================
def demo_concept_boards(code):
    print("\n" + "=" * 60)
    print("3. 概念板块 — 所属概念列表")
    print("=" * 60)
    r = pywencai.get(query=code)
    df = r.get("所属概念列表")
    if df is not None and not df.empty:
        for _, row in df.head(10).iterrows():
            print(f"     {row.get('诊股概念分类名称', '')} ({row.get('诊股概念分类类型', '')})")


# ===================================================================
# 4. 近期重要事件（涨停/跌停/高管增持等）
# ===================================================================
def demo_events(code):
    print("\n" + "=" * 60)
    print("4. 近期重要事件")
    print("=" * 60)
    r = pywencai.get(query=code)
    df = r.get("近期重要事件")
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            print(f"     {row.get('重要事件公告时间', '')} | {row.get('重要事件名称', '')}")
            content = str(row.get('重要事件内容', ''))[:80]
            print(f"       {content}")


# ===================================================================
# 5. 估值指标 — PE/PB/PS 当前值 + 历史分位点
# ===================================================================
def demo_valuation(code):
    print("\n" + "=" * 60)
    print("5. 估值指标 — PE/PB/PS 分位点")
    print("=" * 60)
    r = pywencai.get(query=code)
    val = r.get("估值指标", {})
    for metric in ("市盈率", "市净率", "市销率"):
        section = val.get(metric, {})
        df = section.get("labelLine")
        if df is not None and not df.empty:
            prefix = {"市盈率": "PE", "市净率": "PB", "市销率": "PS"}[metric]
            # 找当前值和分位点
            latest = df.iloc[-1]
            current = None
            pct = None
            for c in df.columns:
                if "估值分位点" in c:
                    pct = float(latest[c])
                elif any(kw in c for kw in ["市盈率(pe)", "市净率(pb)", "市销率(ps)"]):
                    current = float(latest[c])
            print(f"     {prefix}: 当前={current:.2f}, 分位点={pct:.2f}%")


# ===================================================================
# 6. 财务数据
# ===================================================================
def demo_financial(code):
    print("\n" + "=" * 60)
    print("6. 财务数据（最新季度）")
    print("=" * 60)
    r = pywencai.get(query=code)
    df = r.get("财务数据")
    if df is not None and not df.empty:
        latest = df.iloc[0]
        for c in ["营业收入", "净利润", "净资产收益率roe(加权,公布值)", "销售毛利率",
                   "基本每股收益", "营业收入(同比增长率)", "净利润(同比增长率)"]:
            val = latest.get(c, "N/A")
            print(f"     {c}: {val}")


# ===================================================================
# 7. 牛叉诊股
# ===================================================================
def demo_diagnosis(code):
    print("\n" + "=" * 60)
    print("7. 牛叉诊股（综合评分）")
    print("=" * 60)
    r = pywencai.get(query=code)
    df = r.get("牛叉诊股")
    if df is not None and not df.empty:
        score = df.iloc[0].get("牛叉诊股综合评分", "N/A")
        rank = df.iloc[0].get("牛叉诊股综合评分行业排名", "N/A")
        print(f"     综合评分: {score}, 行业排名: {rank}")


# ===================================================================
# 8. DDE散户数量
# ===================================================================
def demo_dde_retail(code):
    print("\n" + "=" * 60)
    print("8. DDE散户数量（最近 3 天）")
    print("=" * 60)
    r = pywencai.get(query=code)
    dde = r.get("DDE散户数量变化", {})
    df = dde.get("barline3")
    if df is not None and not df.empty:
        for _, row in df.tail(3).iterrows():
            print(f"     {row['时间']} | dde散户数量={row['dde散户数量']:.2f}")


# ===================================================================
# 主程序
# ===================================================================
if __name__ == "__main__":
    print(f"\n{'#' * 60}")
    print(f"# pywencai 数据演示 — {CODE}")
    print(f"{'#' * 60}")

    demo_fund_flow(CODE)
    demo_breakdown(CODE)
    demo_concept_boards(CODE)
    demo_events(CODE)
    demo_valuation(CODE)
    demo_financial(CODE)
    demo_diagnosis(CODE)
    demo_dde_retail(CODE)

    print("\n" + "=" * 60)
    print("完成！")
    print(f"同花顺参考页面: https://stockpage.10jqka.com.cn/{CODE}/funds/#funds_lszjsj")
