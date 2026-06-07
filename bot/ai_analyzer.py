"""
DeepSeek AI 股票分析模块
采集真实数据后调用 DeepSeek API 生成深度分析报告
"""
import json
import logging
import os
import re
import urllib.request
from datetime import datetime

from crypto_utils import load_api_key

logger = logging.getLogger("ai_analyzer")

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"

_ANALYSIS_PROMPT = """你是一位资深A股分析师。请基于以下真实数据，生成一份深度分析报告。

## 股票数据
- 名称: {stock_name}
- 代码: {stock_code}
- 当前价: {price} 元
- 涨跌幅: {change_pct}%
- 市盈率: {pe}
- 总市值: {total_mv}
- 换手率: {turnover}%
- 最高/最低/开盘: {high}/{low}/{open_price}

## 技术指标
- MA5: {ma5}  MA10: {ma10}  MA20: {ma20}  MA60: {ma60}
- MACD DIF: {dif}  DEA: {dea}  柱: {macd_bar}
- RSI(14): {rsi}
- ATR(14): {atr} (占股价 {atr_pct}%)
- 量比(5/20日): {vol_ratio}
- 20日高点: {resistance}  20日低点: {support}

## 最近新闻（含内容摘要）
{news_text}

## 订单/合同公告
{order_news_text}

## 资金流向
{fund_flow_text}

## K线概要（最近10个交易日）
{kline_summary}

## 机构一致预期EPS（来自同花顺）
{eps_forecast_text}

## 同花顺热点归因
{hot_reason_text}

## 行业对比数据（来自同花顺F10）
{industry_compare_text}

## 主力资金累计净流入（同花顺）
{main_net_text}

## 真实财务数据（来自东方财富数据中心）
{financial_data_text}

## 同行业可比公司对比（来自同花顺F10）
{peer_comparison_text}

## 主营业务构成（来自东方财富F10，真实财报数据）
{revenue_composition_text}

---

请严格按照以下JSON格式输出（不要输出其他内容）：

```json
{{
  "summary": "一句话总结，50字以内",
  "tags": ["标签1", "标签2", "标签3"],
  "company_profile": {{
    "full_name": "公司全称",
    "founded_listed": "成立/上市年份",
    "headquarters": "总部",
    "industry": "所属行业",
    "business_segments": [
      {{"name": "主营业务1", "revenue_share": "占比%", "description": "简述"}},
      {{"name": "主营业务2", "revenue_share": "占比%", "description": "简述"}}
    ],
    "transition_notes": "转型/变化趋势说明（如有）"
  }},
  "dupont_analysis": [
    {{"year": "2022", "roe": "~X%", "net_margin": "~X%", "turnover": "~X", "leverage": "~X", "trend": "up/down/stable"}},
    {{"year": "2023", "roe": "~X%", "net_margin": "~X%", "turnover": "~X", "leverage": "~X", "trend": "up/down/stable"}},
    {{"year": "2024", "roe": "~X%", "net_margin": "~X%", "turnover": "~X", "leverage": "~X", "trend": "up/down/stable"}},
    {{"year": "2025", "roe": "~X%", "net_margin": "~X%", "turnover": "~X", "leverage": "~X", "trend": "up/down/stable"}},
    {{"year": "2026Q1", "roe": "~X%", "net_margin": "~X%", "turnover": "~X", "leverage": "~X", "trend": "up/down/stable"}}
  ],
  "financial_snapshot": {{
    "revenue": "最近年度营收（亿）",
    "revenue_yoy": "%",
    "net_profit": "最近年度净利（亿）",
    "net_profit_yoy": "%",
    "gross_margin": "%",
    "debt_ratio": "%",
    "roe": "%",
    "pe_ttm": "0",
    "pb": "0",
    "dividend_yield": "%"
  }},
  "valuation_analysis": "估值分析文字，100-200字",
  "industry_analysis": "行业/竞争分析文字，100-200字",
  "technical_analysis": "技术面分析文字，80-150字",
  "business_structure": [
    {{
      "segment_name": "业务板块名称",
      "revenue_contribution": "2025年营收X亿，占比Y%",
      "market_position": "行业地位描述（如龙头/核心供应商/挑战者/新进入者），30-50字",
      "competitive_advantage": "该板块的核心竞争优势（技术/客户/成本/规模），40-80字",
      "trend": "增长/稳定/下滑",
      "key_customers": "主要客户（如苹果、华为、三星等）"
    }}
  ],
  "core_competitive_advantages": [
    "竞争优势1：具体描述（20-40字）",
    "竞争优势2：具体描述",
    "竞争优势3：具体描述",
    "竞争优势4：具体描述"
  ],
  "investment_logic": [
    {{
      "title": "逻辑一：简短标题（15字以内）",
      "detail": "详细分析（80-150字），包含数据支撑和逻辑推演",
      "catalyst": "催化因素（如新产品发布、政策落地、大单签订）"
    }}
  ],
  "competitive_landscape": {{
    "market_size": "目标市场规模及增速描述（30-50字）",
    "market_position": "公司在行业中的位置（龙头/一线/二线），并说明判断依据",
    "main_competitors": "主要竞争对手及竞争态势（50-80字）",
    "entry_barriers": "行业进入壁垒（技术/资金/客户认证/规模等），40-80字",
    "moat_analysis": "护城河分析（品牌/转换成本/网络效应/成本优势），40-80字",
    "market_share_trend": "市占率变化趋势",
    "comparative_advantage": "基于同行业可比公司数据，对比分析该股票的龙头/垄断地位优势。从营收规模、毛利率、ROE、净利率、市值等维度，与主要竞争对手进行量化对比，说明该股票为什么优于同行、为什么值得选择（80-150字）。如果从数据上看不如同行，也要如实说明差距"
  }},
  "order_analysis": {{
    "total_backlog": "在手订单总额（如'超34亿元'）",
    "major_orders": [
      {{"customer": "客户名称", "order_detail": "订单详情", "amount": "金额", "status": "状态（交付中/已验收/新签）"}}
    ],
    "customer_structure": "客户结构分析（集中度/国内外占比/优化趋势），50-100字",
    "order_visibility": "订单可见度分析（能见度可到哪个季度/年度），30-50字"
  }},
  "strategic_layout": {{
    "rd_investment": "研发投入方向和力度（30-50字）",
    "capacity_expansion": "产能扩张计划（30-50字）",
    "global_expansion": "海外布局情况（30-50字）",
    "new_business": "新业务/第二曲线布局（30-50字）",
    "strategy_summary": "一句话战略总结（如'消费电子压舱石+半导体谋未来'）"
  }},
  "valuation_scenarios": [
    {{"scenario": "保守", "net_profit_forecast": "预测净利润（亿）", "target_pe": "给X倍PE", "target_market_cap": "目标市值（亿）", "target_price": "目标价（元）", "key_assumption": "核心假设"}},
    {{"scenario": "中性", "net_profit_forecast": "预测净利润（亿）", "target_pe": "给X倍PE", "target_market_cap": "目标市值（亿）", "target_price": "目标价（元）", "key_assumption": "核心假设"}},
    {{"scenario": "乐观", "net_profit_forecast": "预测净利润（亿）", "target_pe": "给X倍PE", "target_market_cap": "目标市值（亿）", "target_price": "目标价（元）", "key_assumption": "核心假设"}}
  ],
  "financial_table": [
    {{"year": "2022", "revenue": "营收(亿)", "revenue_growth": "+X%", "net_profit": "净利(亿)", "net_profit_growth": "+X%", "net_margin": "X%", "roe": "~X%", "gross_margin": "~X%"}},
    {{"year": "2023", "revenue": "营收(亿)", "revenue_growth": "+X%", "net_profit": "净利(亿)", "net_profit_growth": "+X%", "net_margin": "X%", "roe": "~X%", "gross_margin": "~X%"}},
    {{"year": "2024", "revenue": "营收(亿)", "revenue_growth": "+X%", "net_profit": "净利(亿)", "net_profit_growth": "+X%", "net_margin": "X%", "roe": "~X%", "gross_margin": "~X%"}},
    {{"year": "2025", "revenue": "营收(亿)", "revenue_growth": "+X%", "net_profit": "净利(亿)", "net_profit_growth": "+X%", "net_margin": "X%", "roe": "~X%", "gross_margin": "~X%"}},
    {{"year": "2026Q1", "revenue": "营收(亿)", "revenue_growth": "+X%", "net_profit": "净利(亿)", "net_profit_growth": "+X%", "net_margin": "X%", "roe": "~X%", "gross_margin": "~X%"}}
  ],
  "investment_conclusion": {{
    "core_summary": "核心结论（100-200字），综合评估投资价值",
    "key_catalysts": ["催化剂1", "催化剂2", "催化剂3"],
    "major_risks": ["主要风险1", "主要风险2", "主要风险3"],
    "suggested_entry_range": "建议布局区间",
    "target_price_range_12m": "12个月目标价区间",
    "investment_horizon": "建议持有期",
    "composite_score": "综合评分 X.X/10"
  }},
  "hot_sectors": [
    {{
      "name": "热门板块名称（如HBM、低空经济、AI算力、固态电池等）",
      "why_hot": "为什么近期热门（政策驱动/技术突破/供需变化等），80-150字",
      "stock_connection": "该股票与热门板块的关联分析（产品/客户/产业链位置），50-100字",
      "impact_level": "高/中/低",
      "reference_links": [
        {{"title": "参考文章标题", "url": "https://...", "source": "来源"}},
        {{"title": "参考文章标题2", "url": "https://...", "source": "来源"}}
      ]
    }}
  ],
  "hot_sector_summary": "如果股票涉及多个热门板块，用一句话总结整体热度（30字以内）；如果没有任何热门板块，填'暂无明确热门板块关联'",
  "expert_opinions": {{
    "基本面大师": {{"conclusion": "一句话结论", "key_points": ["要点1", "要点2", "要点3"]}},
    "技术分析派": {{"conclusion": "一句话结论", "key_points": ["要点1", "要点2", "要点3"]}},
    "量化模型师": {{"conclusion": "一句话结论", "key_points": ["要点1", "要点2", "要点3"]}},
    "风险控制官": {{"conclusion": "一句话结论", "key_points": ["要点1", "要点2", "要点3"]}},
    "宏观策略师": {{"conclusion": "一句话结论", "key_points": ["要点1", "要点2"]}},
    "行业研究家": {{"conclusion": "一句话结论", "key_points": ["要点1", "要点2"]}},
    "消息面猎手": {{"conclusion": "一句话结论（基于真实订单/公告数据）", "key_points": ["要点1：具体订单公告内容", "要点2：消息面影响"]}}
  }},
  "scoring_factors": {{
    "momentum": [["正向因素", "pos"], ["中性因素", "neu"], ["负向因素", "neg"]],
    "revenue": [["正向因素", "pos"], ["中性因素", "neu"], ["负向因素", "neg"]],
    "risk": [["正向因素", "pos"], ["中性因素", "neu"], ["负向因素", "neg"]],
    "hot_sector": [["热门板块因素", "pos"]]
  }},
  "recommendation": {{
    "short_term": "短期操作建议",
    "stop_loss": "止损位（元）",
    "target_price": "目标价区间",
    "position_advice": "仓位建议",
    "risk_warning": "风险提示",
    "invalidation_conditions": ["失效条件1", "失效条件2"]
  }},
  "risk_alerts": [
    {{"level": "green/yellow/red", "title": "标题", "content": "内容"}}
  ]
}}
```

注意：
- 财务数据请严格使用上面「真实财务数据」中提供的数字，不要自己估计。如果真实数据中某字段缺失，填"数据暂缺"
- 若某数据不可得，用 "数据暂缺" 代替
- 分析要专业、客观，有数据支撑
- 最终标签（可做/观察/回避）由后端根据双轨评分算法计算，你不需要给出
- **严禁编造公司间关联关系**：只有在提供的新闻数据中出现的合作关系、关联方、收购等才能引用。禁止凭空猜测或混淆其他公司的业务。关联方名称与股票代码必须严格对应，禁止张冠李戴（如把A公司的6位代码套到B公司头上）。
- **热门板块识别非常重要**：请务必判断该股票是否涉及当前市场热门板块（如HBM、低空经济、AI算力、固态电池、机器人、合成生物等），如果是，请在hot_sectors中详细展开，说明为什么热门、该股与热门板块的关联，并给出2-3条参考链接
- reference_links中的url必须是真实存在的公开链接（如东方财富、同花顺、雪球、新浪财经、证券时报等平台的资讯文章），如果不确定链接，url填"#"并注明"请搜索：关键词"
- **scoring_factors.risk 评分规则**：风险维度的"pos"因素代表降低风险的因素（加分项），"neg"因素代表增加风险的因素（减分项）。技术面过热（高RSI/大涨/高PE）本身是减分项，但以下**定性因素应作为正面风险抵消项（pos）**：
  - 龙头地位（行业市占率第一/前三、技术领先）
  - 国家大基金/国家队持仓（国家集成电路产业基金、社保基金、养老金等）
  - 机构重仓（公募/北向资金大幅持仓）
  - 国家政策重点扶持（国产替代、自主可控、新质生产力等政策方向）
  - 核心专利/技术壁垒/独家供应资格
  例如：一只芯片龙头股即使RSI偏高，如果它是国家大基金重仓+封装龙头，risk维度应包含["国家大基金重仓，政策背书强", "pos"]、["先进封装龙头，技术壁垒高", "pos"]等正面因素，以平衡技术面过热的风险扣分。
"""


def _build_analysis_prompt(quote: dict, ind: dict, flow: dict, news: list, kline: list = None, order_news: list = None, data_10jqka: dict = None, financial_data: dict = None, peer_comparison: dict = None, revenue_composition: dict = None) -> str:
	"""构建分析 prompt"""
	name = quote.get("name", "")
	code = quote.get("code", "")
	p = quote.get("price", 0)
	atr = ind.get("atr", 0)

	# 格式化K线摘要
	kline_text = "无K线数据"
	if kline and len(kline) > 0:
		recent = kline[-10:]
		lines = [f"{k['date']}: O={k['open']:.2f} H={k['high']:.2f} L={k['low']:.2f} C={k['close']:.2f} V={k['volume']:.0f}"
		         for k in recent]
		kline_text = "\n".join(lines)

	# 格式化新闻（含内容摘要）
	news_text = "暂无新闻数据"
	if news:
		lines = []
		for i, n in enumerate(news[:10]):
			title = n.get('title', '')
			source = n.get('source', '资讯')
			content = n.get('content', '')
			date = n.get('date', '')
			date_str = f" [{date[:10]}]" if date else ""
			lines.append(f"{i+1}. [{source}{date_str}] {title}")
			if content:
				content_short = content[:200].replace('\n', ' ')
				lines.append(f"   摘要: {content_short}")
		news_text = "\n".join(lines) if lines else "暂无新闻数据"

	# 格式化订单/合同新闻
	order_news_text = "暂无订单/合同相关公告"
	if order_news:
		order_lines = []
		for item in order_news[:6]:
			title = item.get('title', '')
			source = item.get('source', '公告')
			content = item.get('content', '')
			order_lines.append(f"- [{source}] {title}: {(content or '')[:150]}")
		if order_lines:
			order_news_text = "\n".join(order_lines)

	# 格式化资金流向
	fund_text = "暂无资金流向数据"
	if flow and flow.get("main_net"):
		fund_text = (
			f"主力净流入: {flow.get('main_net', 0) / 1e4:.2f}亿元\n"
			f"主力占比: {flow.get('main_pct', 0)}%\n"
			f"超大单净流入: {flow.get('super_large_net', 0) / 1e4:.2f}亿元\n"
			f"散户净流入: {flow.get('retail_net', 0) / 1e4:.2f}亿元"
		)

	# ---- 10jqka data enrichment ----
	eps_forecast_text = "无机构一致预期数据"
	hot_reason_text = "无热点归因数据"
	industry_compare_text = "无行业对比数据"
	main_net_text = "无主力资金数据"

	if data_10jqka:
		eps = data_10jqka.get("eps_forecast", {}) or {}
		eps_rows = eps.get("rows", [])
		if eps_rows:
			eps_cols = eps.get("raw_html_cols", [])
			eps_lines = [f"列: {', '.join(str(c) for c in eps_cols)}"]
			for i, row in enumerate(eps_rows[:5]):
				parts = [f"{k}: {v}" for k, v in row.items()]
				eps_lines.append(f"  第{i + 1}行: {' | '.join(parts)}")
			eps_forecast_text = "\n".join(eps_lines)

		hot_reason = data_10jqka.get("hot_reason")
		if hot_reason:
			hot_reason_text = f"该股票今日登上同花顺强势股榜单，题材归因: {hot_reason}"

		ind_compare = data_10jqka.get("industry_compare", {}) or {}
		tables = ind_compare.get("tables", [])
		if tables:
			ic_lines = []
			for t in tables[:3]:
				ic_lines.append(f"表格{t.get('index', '')}: 列={t.get('columns', [])}")
				for row in t.get("rows", [])[:5]:
					parts = [f"{k}: {v}" for k, v in row.items()]
					ic_lines.append(f"  {', '.join(parts)}")
			if ic_lines:
				industry_compare_text = "\n".join(ic_lines)

		rt = data_10jqka.get("realtime", {}) or {}
		if rt:
			parts = []
			for key, label in [("main_net_5d", "5日"), ("main_net_10d", "10日"),
							   ("main_net_20d", "20日"), ("main_net_60d", "60日")]:
				val = rt.get(key)
				if val is not None:
					parts.append(f"{label}: {val / 1e4:.2f}万元")
			if parts:
				main_net_text = "主力资金累计净流入（来自10jqka）: " + ", ".join(parts)

	atr_pct = round(atr / p * 100, 1) if p > 0 else 0
	pe = quote.get("pe", 0)
	total_mv = quote.get("total_mv", 0)

	# ---- financial data from East Money ----
	financial_data_text = "无真实财务数据"
	if financial_data:
		annual = financial_data.get("annual", [])
		if annual:
			lines = ["| 年份 | 营收(亿) | 营收增速 | 净利(亿) | 净利增速 | 毛利率 | 净利率 | ROE | 负债率 | EPS | 经营现金流(亿) | 研发费用(亿) |",
				 "|------|----------|----------|----------|----------|--------|--------|-----|--------|-----|----------------|----------------|"]
			for row in annual:
				rev = row.get("revenue", "")
				rev_yoy = f"{row.get('revenue_yoy', ''):+.1f}%" if row.get("revenue_yoy") is not None else ""
				np_val = row.get("net_profit", "")
				np_yoy = f"{row.get('net_profit_yoy', ''):+.1f}%" if row.get("net_profit_yoy") is not None else ""
				gm = f"{row.get('gross_margin', ''):.1f}%" if row.get("gross_margin") is not None else ""
				nm = f"{row.get('net_margin', ''):.1f}%" if row.get("net_margin") is not None else ""
				roe = f"{row.get('roe_weighted', ''):.1f}%" if row.get("roe_weighted") is not None else ""
				debt = f"{row.get('debt_ratio', ''):.1f}%" if row.get("debt_ratio") is not None else ""
				eps = f"{row.get('eps', ''):.2f}" if row.get('eps') is not None else ""
				cf = f"{row.get('cf_oper', ''):.2f}" if row.get("cf_oper") is not None else ""
				rd = f"{row.get('rd_expense', ''):.2f}" if row.get("rd_expense") is not None else ""
				lines.append(f"| {row.get('year', '')} | {rev} | {rev_yoy} | {np_val} | {np_yoy} | {gm} | {nm} | {roe} | {debt} | {eps} | {cf} | {rd} |")
			latest = financial_data.get("latest_quarter", {})
			if latest:
				rev = latest.get("revenue", "")
				rev_yoy = f"{latest.get('revenue_yoy', ''):+.1f}%" if latest.get("revenue_yoy") is not None else ""
				np_val = latest.get("net_profit", "")
				np_yoy = f"{latest.get('net_profit_yoy', ''):+.1f}%" if latest.get("net_profit_yoy") is not None else ""
				gm = f"{latest.get('gross_margin', ''):.1f}%" if latest.get("gross_margin") is not None else ""
				nm = f"{latest.get('net_margin', ''):.1f}%" if latest.get("net_margin") is not None else ""
				roe = f"{latest.get('roe_weighted', ''):.1f}%" if latest.get("roe_weighted") is not None else ""
				lines.append(f"| {latest.get('year', '最新季')} | {rev} | {rev_yoy} | {np_val} | {np_yoy} | {gm} | {nm} | {roe} | - | - | - | - |")
			financial_data_text = "\n".join(lines)

	# ---- peer comparison ----
	peer_comparison_text = "无同行业对比数据"
	if peer_comparison:
		peers = peer_comparison.get("peers", [])
		if peers:
			lines = ["| 代码 | 名称 | 营收(亿) | 净利(亿) | 毛利率 | ROE | 负债率 | 市值(亿) | PE | PB |",
				 "|------|------|----------|----------|--------|-----|--------|----------|-----|-----|"]
			for p in peers:
				lines.append(f"| {p.get('code', '')} | {p.get('name', '')} | {p.get('revenue', '')} | {p.get('net_profit', '')} | {p.get('gross_margin', '')} | {p.get('roe', '')} | {p.get('debt_ratio', '')} | {p.get('market_cap', '')} | {p.get('pe', '')} | {p.get('pb', '')} |")
			peer_comparison_text = "\n".join(lines)
		else:
			raw_html = peer_comparison.get("_raw_tables", "")
			if raw_html:
				peer_comparison_text = f"同行业对比原始数据（HTML表格）:\n{raw_html[:3000]}"

	# ---- revenue composition (主营构成) ----
	revenue_composition_text = "无主营业务构成数据"
	if revenue_composition:
		by_product = revenue_composition.get("by_product", [])
		by_region = revenue_composition.get("by_region", [])
		rpt_date = revenue_composition.get("report_date", "")
		rc_lines = [f"报告期: {rpt_date}\n"]
		if by_product:
			rc_lines.append("【按产品分类】")
			for item in by_product:
				gm = f"，毛利率 {item['gross_margin_pct']}%" if item.get('gross_margin_pct') is not None else ""
				rc_lines.append(
					f"  - {item['name']}: 收入 {item['revenue']:.0f}元，" \
					f"占比 {item['ratio_pct']}%{gm}"
				)
		if by_region:
			rc_lines.append("\n【按地区分类】")
			for item in by_region:
				gm = f"，毛利率 {item['gross_margin_pct']}%" if item.get('gross_margin_pct') is not None else ""
				rc_lines.append(
					f"  - {item['name']}: 收入 {item['revenue']:.0f}元，" \
					f"占比 {item['ratio_pct']}%{gm}"
				)
		if len(rc_lines) > 1:
			revenue_composition_text = "\n".join(rc_lines)

	return _ANALYSIS_PROMPT.format(
		stock_name=name,
		stock_code=code,
		price=p,
		change_pct=quote.get("change_pct", 0),
		pe=f"{pe:.1f}倍" if pe > 0 else "数据暂缺",
		total_mv=f"{total_mv / 1e8:.1f}亿" if total_mv > 0 else "数据暂缺",
		turnover=f"{quote.get('turnover', 0):.2f}%" if quote.get("turnover", 0) else "数据暂缺",
		high=quote.get("high", 0),
		low=quote.get("low", 0),
		open_price=quote.get("open", 0),
		ma5=ind.get("ma5", "N/A"), ma10=ind.get("ma10", "N/A"),
		ma20=ind.get("ma20", "N/A"), ma60=ind.get("ma60", "N/A"),
		dif=ind.get("dif", "N/A"), dea=ind.get("dea", "N/A"), macd_bar=ind.get("macd_bar", "N/A"),
		rsi=ind.get("rsi", "N/A"),
		atr=atr, atr_pct=atr_pct,
		vol_ratio=ind.get("vol_ratio", "N/A"),
		resistance=ind.get("resistance", "N/A"),
		support=ind.get("support", "N/A"),
		news_text=news_text,
		order_news_text=order_news_text,
		fund_flow_text=fund_text,
		kline_summary=kline_text,
		eps_forecast_text=eps_forecast_text,
		hot_reason_text=hot_reason_text,
		industry_compare_text=industry_compare_text,
		main_net_text=main_net_text,
		financial_data_text=financial_data_text,
		peer_comparison_text=peer_comparison_text,
		revenue_composition_text=revenue_composition_text,
	)


def _parse_json_robust(text: str) -> dict:
	"""Parse JSON with repair fallbacks for common LLM errors."""
	try:
		return json.loads(text)
	except json.JSONDecodeError:
		pass

	# Repair 1: close unclosed braces/brackets (truncated JSON)
	open_braces = text.count("{") - text.count("}")
	open_brackets = text.count("[") - text.count("]")
	repaired = text
	if open_braces > 0:
		repaired += "}" * open_braces
	if open_brackets > 0:
		repaired += "]" * open_brackets
	try:
		return json.loads(repaired)
	except json.JSONDecodeError:
		pass

	# Repair 2: fix trailing comma before closing brace/bracket
	repaired = re.sub(r",\s*([}\]])", r"\1", text)
	try:
		return json.loads(repaired)
	except json.JSONDecodeError:
		pass

	# Repair 3: combine both fixes
	open_braces = repaired.count("{") - repaired.count("}")
	open_brackets = repaired.count("[") - repaired.count("]")
	if open_braces > 0:
		repaired += "}" * open_braces
	if open_brackets > 0:
		repaired += "]" * open_brackets
	return json.loads(repaired)


def analyze_stock(quote: dict, ind: dict, flow: dict, news: list, kline: list = None, order_news: list = None, data_10jqka: dict = None, financial_data: dict = None, peer_comparison: dict = None, revenue_composition: dict = None) -> dict:
	"""调用 DeepSeek API 进行深度分析，返回完整的分析数据 dict"""
	api_key = load_api_key("DEEPSEEK_ENC_KEY")
	prompt = _build_analysis_prompt(quote, ind, flow, news, kline, order_news, data_10jqka, financial_data, peer_comparison, revenue_composition)

	payload = json.dumps({
		"model": MODEL,
		"messages": [
			{"role": "system", "content": "你是一位资深A股分析师。请基于提供的真实数据做推理分析。始终返回合法JSON，不要编造精确财务数字。\n\n严格规则：\n1. 分析对象仅为上面「股票数据」中的那只股票，不要混淆其他公司。\n2. 禁止编造公司间的关联关系——只有新闻数据中明确提到的合作关系、关联方、收购等才能引用。\n3. 股票代码6位数字必须准确，禁止把A公司的代码写成B公司的代码。极易混淆的代码（如000628与000682、000001与000002等）要格外小心。\n4. 如果某信息在数据中找不到依据，写「数据暂缺」而非猜测。"},
			{"role": "user", "content": prompt},
		],
		"temperature": 0.7,
		"max_tokens": 16384,
	}, ensure_ascii=False).encode("utf-8")

	req = urllib.request.Request(
		DEEPSEEK_URL,
		data=payload,
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {api_key}",
		},
	)

	try:
		resp = urllib.request.urlopen(req, timeout=90)
		result = json.loads(resp.read())
		content = result["choices"][0]["message"]["content"]
		# 提取 JSON block
		if "```json" in content:
			json_start = content.index("```json") + 7
			json_end = content.index("```", json_start)
			content = content[json_start:json_end].strip()
		elif "```" in content:
			json_start = content.index("```") + 3
			json_end = content.index("```", json_start)
			content = content[json_start:json_end].strip()
		analysis = _parse_json_robust(content)
		logger.info(f"AI 分析完成: {quote.get('code')} {quote.get('name')}")
		return analysis
	except ValueError:
		# No ``` markers — try raw content, then regex-extract JSON object
		try:
			analysis = _parse_json_robust(content)
			logger.info(f"AI 分析完成 (raw JSON): {quote.get('code')} {quote.get('name')}")
			return analysis
		except json.JSONDecodeError:
			m = re.search(r'\{.*\}', content, re.DOTALL)
			if m:
				analysis = _parse_json_robust(m.group())
				logger.info(f"AI 分析完成 (regex): {quote.get('code')} {quote.get('name')}")
				return analysis
			raise
	except Exception as e:
		logger.error(f"DeepSeek API 调用失败: {e}")
		raise


_SECTOR_REC_PROMPT = """你是一位资深A股分析师和行业研究员。用户向你咨询一个投资主题/板块，请你基于专业知识推荐相关股票。

## 用户咨询
{query}

## 要求
请推荐 {top_n} 只与上述主题最相关的A股股票。严格按以下JSON格式输出：

```json
{{
  "theme_analysis": "对该主题/板块的简要分析（60-100字），包括市场热度和投资逻辑",
  "stocks": [
    {{
      "code": "6位股票代码",
      "name": "股票名称",
      "relevance": "与该主题的关联度说明（30-50字）",
      "reason": "推荐理由（40-80字）",
      "price_estimate": "当前股价区间估计（如 ~25元）",
      "risk_note": "风险提示（20字以内）"
    }}
  ],
  "overall_advice": "整体投资建议（50-80字）"
}}
```

注意：
- 只推荐A股（6位代码，0/3/6开头）
- 股票代码必须真实存在，名称与代码必须匹配
- 按关联度和投资价值从高到低排序
- 每只股票的分析要具体，有数据支撑
- 风险提示要实事求是
"""


_SECTOR_INDUSTRY_CHAIN_PROMPT = """你是一位资深A股产业研究员。请对以下板块进行深度产业链分析，并筛选出符合标准的股票。

## 分析板块
{query}

## 分析要求

### 1. 产业链结构分析
请绘制该板块的上下游产业链图谱：
- **上游**：原材料、核心零部件、设备供应商（列出3-5个关键环节）
- **中游**：制造/加工/集成环节（列出3-5个关键环节）
- **下游**：终端应用、客户、消费场景（列出3-5个关键环节）

### 2. 选股标准
在产业链的每个环节中，按以下标准筛选最具投资价值的A股股票（{top_n}只）：
- ✅ **市盈率低**：PE（TTM）低于行业平均，或处于历史低位
- ✅ **股价低**：绝对股价相对较低，或处于合理估值区间
- ✅ **持续分红**：近3年有稳定的现金分红记录，股息率较高
- ✅ **龙头地位**：在所属产业链环节具有龙头地位（技术/市占率/客户壁垒）

### 3. 对每只推荐股票详细说明
- 在产业链中的具体位置（上游/中游/下游哪个环节）
- 龙头地位的证据（市占率、核心客户、技术壁垒）
- 当前估值水平（PE、PB、股息率）
- 与板块核心逻辑的关联度

### 4. 输出格式

严格按以下JSON格式输出：

```json
{{
  "sector_name": "板块名称",
  "sector_overview": "板块整体分析，80-150字",
  "industry_chain": {{
    "upstream": [
      {{"segment": "环节名称", "description": "简述（30-50字）", "key_players": ["代表公司A", "代表公司B"]}}
    ],
    "midstream": [
      {{"segment": "环节名称", "description": "简述（30-50字）", "key_players": ["代表公司A", "代表公司B"]}}
    ],
    "downstream": [
      {{"segment": "环节名称", "description": "简述（30-50字）", "key_players": ["代表公司A", "代表公司B"]}}
    ]
  }},
  "recommended_stocks": [
    {{
      "code": "6位股票代码",
      "name": "股票名称",
      "chain_position": "上游/中游/下游 - 具体环节",
      "price": "当前股价区间（如 ~25元）",
      "pe": "市盈率水平（如 ~15倍，行业均值25倍）",
      "pb": "市净率（如 ~2.1倍）",
      "dividend_yield": "股息率（如 ~3.5%）",
      "market_cap": "总市值（如 ~180亿）",
      "leader_evidence": "龙头地位证据（市占率/核心客户/技术实力，50-80字）",
      "investment_logic": "投资逻辑（低估值+高股息+龙头地位的具体分析，80-120字）",
      "risk_factors": ["风险1", "风险2"],
      "score": "综合评分 X.X/10"
    }}
  ],
  "sector_summary": {{
    "avg_pe": "板块平均PE",
    "avg_dividend_yield": "板块平均股息率",
    "investment_rating": "积极/中性/谨慎",
    "key_catalysts": ["催化剂1", "催化剂2"],
    "major_risks": ["风险1", "风险2"],
    "position_advice": "仓位配置建议（50-80字）"
  }}
}}
```

注意：
- 股票代码必须真实存在，6位数字，0/3/6开头
- 所有财务数据基于你的知识库估计（标注~）
- 优先推荐有真实分红记录的公司
- 龙头地位必须具体说明（市占率/%排名/核心客户等证据）
- 产业链分析要逻辑清晰，上下游关系正确
"""


def analyze_sector_industry_chain(query: str, top_n: int = 5) -> dict:
    """板块产业链深度分析：上下游图谱 + 低PE/低股价/分红/龙头筛选"""
    api_key = load_api_key("DEEPSEEK_ENC_KEY")
    prompt = _SECTOR_INDUSTRY_CHAIN_PROMPT.format(query=query, top_n=top_n)

    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是一位资深A股产业研究员，擅长产业链分析和价值选股。请基于专业知识做深度分析，始终返回合法JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.6,
        "max_tokens": 4096,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=90)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"]
        if "```json" in content:
            json_start = content.index("```json") + 7
            json_end = content.index("```", json_start)
            content = content[json_start:json_end].strip()
        elif "```" in content:
            json_start = content.index("```") + 3
            json_end = content.index("```", json_start)
            content = content[json_start:json_end].strip()
        analysis = _parse_json_robust(content)
        logger.info(f"产业链分析完成: {query}")
        return analysis
    except ValueError:
        try:
            analysis = _parse_json_robust(content)
            logger.info(f"产业链分析完成 (raw): {query}")
            return analysis
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                analysis = _parse_json_robust(m.group())
                logger.info(f"产业链分析完成 (regex): {query}")
                return analysis
            raise
    except Exception as e:
        logger.error(f"产业链分析API调用失败: {e}")
        raise


def recommend_stocks_by_sector(query: str, top_n: int = 3) -> dict:
	"""根据用户主题/板块查询，推荐相关A股股票"""
	api_key = load_api_key("DEEPSEEK_ENC_KEY")
	prompt = _SECTOR_REC_PROMPT.format(query=query, top_n=top_n)

	payload = json.dumps({
		"model": MODEL,
		"messages": [
			{"role": "system", "content": "你是一位资深A股分析师和行业研究员。请基于专业知识推荐真实存在的A股股票。始终返回合法JSON。"},
			{"role": "user", "content": prompt},
		],
		"temperature": 0.6,
		"max_tokens": 2048,
	}, ensure_ascii=False).encode("utf-8")

	req = urllib.request.Request(
		DEEPSEEK_URL,
		data=payload,
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {api_key}",
		},
	)

	try:
		resp = urllib.request.urlopen(req, timeout=60)
		result = json.loads(resp.read())
		content = result["choices"][0]["message"]["content"]
		if "```json" in content:
			json_start = content.index("```json") + 7
			json_end = content.index("```", json_start)
			content = content[json_start:json_end].strip()
		elif "```" in content:
			json_start = content.index("```") + 3
			json_end = content.index("```", json_start)
			content = content[json_start:json_end].strip()
		rec = json.loads(content)
		logger.info(f"板块推荐完成: {query} -> {len(rec.get('stocks', []))} 只股票")
		return rec
	except ValueError:
		try:
			rec = json.loads(content)
			logger.info(f"板块推荐完成 (raw): {query}")
			return rec
		except json.JSONDecodeError:
			m = re.search(r'\{.*\}', content, re.DOTALL)
			if m:
				rec = json.loads(m.group())
				logger.info(f"板块推荐完成 (regex): {query}")
				return rec
			raise
	except Exception as e:
		logger.error(f"板块推荐API调用失败: {e}")
		raise


def call_deepseek_raw(prompt: str, system: str = "You are a Chinese A-share stock analyst.") -> str:
	"""Generic DeepSeek call: takes a prompt, returns raw text response.

	Does NOT parse JSON. Caller is responsible for parsing.
	Raises RuntimeError on API failure.
	"""
	api_key = load_api_key("DEEPSEEK_ENC_KEY")

	payload = json.dumps({
		"model": MODEL,
		"messages": [
			{"role": "system", "content": system},
			{"role": "user", "content": prompt},
		],
		"temperature": 0.7,
		"max_tokens": 4096,
	}, ensure_ascii=False).encode("utf-8")

	req = urllib.request.Request(
		DEEPSEEK_URL,
		data=payload,
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {api_key}",
		},
	)

	try:
		resp = urllib.request.urlopen(req, timeout=90)
		result = json.loads(resp.read())
		content = result["choices"][0]["message"]["content"]
		logger.info(f"DeepSeek raw call completed ({len(content)} chars)")
		return content
	except Exception as e:
		logger.error(f"DeepSeek API 调用失败: {e}")
		raise RuntimeError(f"DeepSeek API call failed: {e}") from e


# ============================================================
# V2: Natural Language Analysis (Markdown output, section parsing)
# ============================================================

_NATURAL_PROMPT = """你是一位资深A股分析师。请基于以下真实数据，对 {stock_name}（{stock_code}）进行深度分析。

## 实时行情
- 当前价: {price} 元（{change_pct:+.2f}%）
- 市盈率: {pe}  总市值: {total_mv}
- 换手率: {turnover}%  最高/最低: {high}/{low}

## 技术指标
- MA5: {ma5}  MA10: {ma10}  MA20: {ma20}  MA60: {ma60}
- MACD DIF: {dif}  DEA: {dea}  柱: {macd_bar}
- RSI(14): {rsi}  量比(5/20日): {vol_ratio}
- 20日高/低: {resistance} / {support}

## 资金流向
{fund_flow_text}

## K线概要（近10日）
{kline_summary}

## 机构一致预期EPS
{eps_forecast_text}

## 同花顺热点归因
{hot_reason_text}

## 主力资金累计净流入
{main_net_text}

## 真实财务数据（东方财富数据中心）
{financial_data_text}

## 同行业可比公司（同花顺F10）
{peer_comparison_text}

## 主营业务构成（东方财富F10，真实财报数据）
{revenue_composition_text}

## 行业对比数据
{industry_compare_text}

## 近期新闻
{news_text}

## 订单/合同公告
{order_news_text}

---

请对 {stock_name}（{stock_code}）进行深度分析，以Markdown格式输出。要求：

**第一行**输出标签：**标签:** 标签1, 标签2, 标签3
**第二行**输出一句话总结（50字以内）

然后按以下章节展开（每个章节用 ## 标题，2-3段自然语言分析）：

## 公司概况
公司全称、成立上市时间、总部、主营业务构成、行业地位

## 行业与竞争格局
所处行业分析、竞争态势、护城河、市占率趋势。重点基于同行业可比公司数据进行量化对比，从营收规模、毛利率、ROE、净利率、市值等维度，分析该股票的龙头地位或垄断优势，说明为什么该股票优于同行、值得选择（如有不足也要如实指出）

## 财务分析
基于上面真实财务数据，分析营收/利润趋势、盈利能力、资产负债状况

## 业务结构与投资逻辑
各业务板块分析、核心竞争力、投资逻辑（含催化剂）

## 订单与战略布局
在手订单、客户结构、研发投入、产能扩张、新业务方向

## 估值分析
当前估值水平评估、估值情景分析（保守/中性/乐观）

## 技术面分析
均线、MACD、RSI等技术指标解读、支撑阻力位

## 操作建议与风险
短期/中期操作建议、止损位、目标价区间、主要风险提示
同时在最后用以下格式给出评分因素：
**动量因素(pos):** ...
**动量因素(neg):** ...
**基本面因素(pos):** ...
**基本面因素(neg):** ...
**风险因素(pos):** ...
**风险因素(neg):** ...
**热门板块因素:** ...

注意：
- 财务数据请严格使用上面「真实财务数据」中提供的数字
- 分析要专业客观，有理有据
- 每个章节写2-3段，不要过于简略
- 不要编造数据，不确定的写"数据暂缺"
"""

# Mapping from Markdown ## headers to ai_analysis dict keys
_SECTION_MAP = {
    "公司概况": "company_profile",
    "行业与竞争格局": "competitive_landscape",
    "财务分析": "financial_analysis",
    "业务结构与投资逻辑": "business_and_logic",
    "订单与战略布局": "order_and_strategy",
    "估值分析": "valuation_analysis",
    "技术面分析": "technical_analysis",
    "操作建议与风险": "recommendation_and_risk",
}


def analyze_stock_natural(quote: dict, ind: dict, flow: dict, news: list,
                           kline: list = None, order_news: list = None,
                           data_10jqka: dict = None, financial_data: dict = None,
                           peer_comparison: dict = None,
                           revenue_composition: dict = None) -> dict:
    """Call DeepSeek with natural language prompt, get Markdown analysis back.

    Returns parsed dict compatible with existing ai_analysis structure.
    """
    api_key = load_api_key("DEEPSEEK_ENC_KEY")
    prompt = _build_natural_prompt(quote, ind, flow, news, kline, order_news,
                                    data_10jqka, financial_data, peer_comparison,
                                    revenue_composition)

    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是一位资深A股分析师。请基于提供的真实数据做深度分析，输出Markdown格式报告。分析要专业、客观、有数据支撑。不要编造数据。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 16384,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(api_key),
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"]
        logger.info("AI natural analysis done: %s %s (%d chars)",
                   quote.get("code"), quote.get("name"), len(content))
        return parse_ai_markdown(content, quote.get("code", ""))
    except Exception as e:
        logger.error("DeepSeek natural analysis failed: %s", e)
        raise


def parse_ai_markdown(markdown_text: str, stock_code: str = "") -> dict:
    """Parse AI Markdown output into structured ai_analysis dict.

    Extracts: tags, summary, ## sections, scoring factors.
    Compatible with existing report template structure.
    """
    import re

    result = {"_raw_markdown": markdown_text}
    lines = markdown_text.strip().split("\n")

    # Extract tags from first line: **标签:** tag1, tag2, tag3
    tag_match = re.search(r"\*\*标签[:：]\s*\*\*\s*(.+?)$", lines[0]) if lines else None
    if not tag_match and len(lines) > 1:
        tag_match = re.search(r"\*\*标签[:：]\s*\*\*\s*(.+?)$", lines[1])
    if tag_match:
        tags_raw = tag_match.group(1).strip()
        result["tags"] = [t.strip() for t in re.split(r"[,，、]", tags_raw) if t.strip()]
    else:
        result["tags"] = []

    # Extract summary: first non-empty line after tags line, before any ##
    summary_lines = []
    in_summary = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("##"):
            break
        if in_summary and stripped and not stripped.startswith("**标签"):
            summary_lines.append(stripped)
        if re.search(r"\*\*标签[:：]", stripped):
            in_summary = True
    result["summary"] = " ".join(summary_lines)[:200] if summary_lines else ""

    # Split by ## sections
    sections = {}
    current_section = None
    current_content = []

    for line in lines:
        if line.startswith("## "):
            if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line[3:].strip()
            current_content = []
        elif current_section:
            current_content.append(line)

    # Don't forget the last section
    if current_section and current_content:
        sections[current_section] = "\n".join(current_content).strip()

    # Map sections to ai_analysis keys
    for section_name, content in sections.items():
        # Try exact match first
        key = _SECTION_MAP.get(section_name)
        if not key:
            # Fuzzy match: check if section_name contains or is contained by any map key
            for map_name, map_key in _SECTION_MAP.items():
                if section_name in map_name or map_name in section_name:
                    key = map_key
                    break
        if key:
            result[key] = content
        else:
            # Store unrecognized sections under their lowercase name
            safe_key = re.sub(r"[^\w]", "_", section_name).strip("_")
            result[safe_key] = content

    # Extract scoring factors from the last section
    full_text = markdown_text
    scoring = {"momentum": [], "revenue": [], "risk": [], "hot_sector": []}

    for factor_type, pos_key, neg_key in [
        ("动量因素", "momentum_pos", "momentum_neg"),
        ("基本面因素", "revenue_pos", "revenue_neg"),
        ("风险因素", "risk_pos", "risk_neg"),
    ]:
        pos_pattern = r"\*\*{}[(]pos[)]\s*[:：]\s*\*\*\s*(.+?)$".format(factor_type)
        neg_pattern = r"\*\*{}[(]neg[)]\s*[:：]\s*\*\*\s*(.+?)$".format(factor_type)

        for line in lines:
            pm = re.search(pos_pattern, line)
            if pm:
                scoring["momentum" if "动量" in factor_type else "revenue" if "基本面" in factor_type else "risk"].append(
                    [pm.group(1).strip(), "pos"])
            nm = re.search(neg_pattern, line)
            if nm:
                scoring["momentum" if "动量" in factor_type else "revenue" if "基本面" in factor_type else "risk"].append(
                    [nm.group(1).strip(), "neg"])

    # Hot sector factor
    for line in lines:
        hm = re.search(r"\*\*热门板块因素\s*[:：]\s*\*\*\s*(.+?)$", line)
        if hm:
            scoring["hot_sector"].append([hm.group(1).strip(), "pos"])

    result["scoring_factors"] = scoring
    result["_format"] = "markdown_v2"

    logger.info("Parsed AI Markdown for %s: %d sections, %d tags",
               stock_code, len(sections), len(result.get("tags", [])))
    return result


def _build_natural_prompt(quote: dict, ind: dict, flow: dict, news: list,
                           kline: list = None, order_news: list = None,
                           data_10jqka: dict = None, financial_data: dict = None,
                           peer_comparison: dict = None,
                           revenue_composition: dict = None) -> str:
    """Build natural language analysis prompt with all crawled data."""
    name = quote.get("name", "")
    code = quote.get("code", "")
    p = quote.get("price", 0)

    # K-line summary
    kline_text = "无K线数据"
    if kline and len(kline) > 0:
        recent = kline[-10:]
        lines_k = []
        for k in recent:
            lines_k.append("{}: O={:.2f} H={:.2f} L={:.2f} C={:.2f} V={:.0f}".format(
                k["date"], k["open"], k["high"], k["low"], k["close"], k["volume"]))
        kline_text = "\n".join(lines_k)

    # News summary
    news_text = "暂无新闻数据"
    if news:
        lines_n = []
        for i, n in enumerate(news[:10]):
            title = n.get("title", "")
            source = n.get("source", "资讯")
            content = n.get("content", "")
            date = n.get("date", "")
            date_str = " [{}]".format(date[:10]) if date else ""
            lines_n.append("{}. [{}{}] {}".format(i + 1, source, date_str, title))
            if content:
                lines_n.append("   摘要: {}".format(content[:200].replace("\n", " ")))
        news_text = "\n".join(lines_n) if lines_n else "暂无新闻数据"

    # Order news
    order_news_text = "暂无订单/合同公告"
    if order_news:
        ol = []
        for item in order_news[:6]:
            title = item.get("title", "")
            source = item.get("source", "公告")
            content = item.get("content", "")
            ol.append("- [{}] {}: {}".format(source, title, (content or "")[:150]))
        if ol:
            order_news_text = "\n".join(ol)

    # Fund flow
    fund_text = "暂无资金流向数据"
    if flow and flow.get("main_net"):
        fund_text = "主力净流入: {:.2f}亿元\n主力占比: {}%\n超大单净流入: {:.2f}亿元\n散户净流入: {:.2f}亿元".format(
            flow.get("main_net", 0) / 1e4, flow.get("main_pct", 0),
            flow.get("super_large_net", 0) / 1e4, flow.get("retail_net", 0) / 1e4)

    # 10jqka enrichments
    eps_forecast_text = "无机构一致预期数据"
    hot_reason_text = "无热点归因数据"
    industry_compare_text = "无行业对比数据"
    main_net_text = "无主力资金数据"

    if data_10jqka:
        eps = data_10jqka.get("eps_forecast", {}) or {}
        eps_rows = eps.get("rows", [])
        if eps_rows:
            eps_cols = eps.get("raw_html_cols", [])
            eps_lines = ["列: {}".format(", ".join(str(c) for c in eps_cols))]
            for i, row in enumerate(eps_rows[:5]):
                parts = ["{}: {}".format(k, v) for k, v in row.items()]
                eps_lines.append("  第{}行: {}".format(i + 1, " | ".join(parts)))
            eps_forecast_text = "\n".join(eps_lines)

        hot_reason = data_10jqka.get("hot_reason")
        if hot_reason:
            hot_reason_text = "该股票今日登上同花顺强势股榜单，题材归因: {}".format(hot_reason)

        ind_compare = data_10jqka.get("industry_compare", {}) or {}
        tables = ind_compare.get("tables", [])
        if tables:
            ic_lines = []
            for t in tables[:3]:
                ic_lines.append("表格{}: 列={}".format(t.get("index", ""), t.get("columns", [])))
                for row in t.get("rows", [])[:5]:
                    parts = ["{}: {}".format(k, v) for k, v in row.items()]
                    ic_lines.append("  {}".format(", ".join(parts)))
            if ic_lines:
                industry_compare_text = "\n".join(ic_lines)

        rt = data_10jqka.get("realtime", {}) or {}
        if rt:
            parts = []
            for key, label in [("main_net_5d", "5日"), ("main_net_10d", "10日"),
                               ("main_net_20d", "20日"), ("main_net_60d", "60日")]:
                val = rt.get(key)
                if val is not None:
                    parts.append("{}: {:.2f}万元".format(label, val / 1e4))
            if parts:
                main_net_text = "主力资金累计净流入: " + ", ".join(parts)

    pe = quote.get("pe", 0)
    total_mv = quote.get("total_mv", 0)

    # Financial data table (same formatting as old prompt)
    financial_data_text = "无真实财务数据"
    if financial_data:
        annual = financial_data.get("annual", [])
        if annual:
            lines_fd = ["| 年份 | 营收(亿) | 营收增速 | 净利(亿) | 净利增速 | 毛利率 | 净利率 | ROE | 负债率 | EPS | 经营现金流(亿) | 研发费用(亿) |",
                      "|------|----------|----------|----------|----------|--------|--------|-----|--------|-----|----------------|----------------|"]
            for row in annual:
                rev = row.get("revenue", "")
                rev_yoy = "{:+.1f}%".format(row["revenue_yoy"]) if row.get("revenue_yoy") is not None else ""
                np_val = row.get("net_profit", "")
                np_yoy = "{:+.1f}%".format(row["net_profit_yoy"]) if row.get("net_profit_yoy") is not None else ""
                gm = "{:.1f}%".format(row["gross_margin"]) if row.get("gross_margin") is not None else ""
                nm = "{:.1f}%".format(row["net_margin"]) if row.get("net_margin") is not None else ""
                roe = "{:.1f}%".format(row["roe_weighted"]) if row.get("roe_weighted") is not None else ""
                debt = "{:.1f}%".format(row["debt_ratio"]) if row.get("debt_ratio") is not None else ""
                eps = "{:.2f}".format(row["eps"]) if row.get("eps") is not None else ""
                cf = "{:.2f}".format(row["cf_oper"]) if row.get("cf_oper") is not None else ""
                rd = "{:.2f}".format(row["rd_expense"]) if row.get("rd_expense") is not None else ""
                lines_fd.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                    row.get("year", ""), rev, rev_yoy, np_val, np_yoy, gm, nm, roe, debt, eps, cf, rd))
            latest = financial_data.get("latest_quarter", {})
            if latest:
                rev = latest.get("revenue", "")
                gm = "{:.1f}%".format(latest["gross_margin"]) if latest.get("gross_margin") is not None else ""
                lines_fd.append("| {} | {} | - | {} | - | {} | - | - | - | - | - | - |".format(
                    latest.get("year", "最新季"), rev, latest.get("net_profit", ""), gm))
            financial_data_text = "\n".join(lines_fd)

    # Peer comparison table
    peer_comparison_text = "无同行业对比数据"
    if peer_comparison:
        peers = peer_comparison.get("peers", [])
        if peers:
            lines_p = ["| 代码 | 名称 | 营收(亿) | 净利(亿) | 毛利率 | ROE | 负债率 | 市值(亿) | PE | PB |",
                      "|------|------|----------|----------|--------|-----|--------|----------|-----|-----|"]
            for p in peers[:15]:
                lines_p.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                    p.get("code", ""), p.get("name", ""), p.get("revenue", ""),
                    p.get("net_profit", ""), p.get("gross_margin", ""),
                    p.get("roe", ""), p.get("debt_ratio", ""),
                    p.get("market_cap", ""), p.get("pe", ""), p.get("pb", "")))
            peer_comparison_text = "\n".join(lines_p)

    # Revenue composition
    revenue_composition_text = "无主营业务构成数据"
    if revenue_composition:
        by_product = revenue_composition.get("by_product", [])
        by_region = revenue_composition.get("by_region", [])
        rpt_date = revenue_composition.get("report_date", "")
        rc_lines = ["报告期: {}\n".format(rpt_date)]
        if by_product:
            rc_lines.append("【按产品分类】")
            for item in by_product:
                gm = "，毛利率 {}%".format(item["gross_margin_pct"]) if item.get("gross_margin_pct") is not None else ""
                rc_lines.append("  - {}: 收入 {:.0f}元，占比 {}%{}".format(
                    item["name"], item["revenue"], item["ratio_pct"], gm))
        if by_region:
            rc_lines.append("\n【按地区分类】")
            for item in by_region:
                gm = "，毛利率 {}%".format(item["gross_margin_pct"]) if item.get("gross_margin_pct") is not None else ""
                rc_lines.append("  - {}: 收入 {:.0f}元，占比 {}%{}".format(
                    item["name"], item["revenue"], item["ratio_pct"], gm))
        if len(rc_lines) > 1:
            revenue_composition_text = "\n".join(rc_lines)

    return _NATURAL_PROMPT.format(
        stock_name=name, stock_code=code, price=p,
        change_pct=quote.get("change_pct", 0),
        pe="{:.1f}倍".format(pe) if pe > 0 else "数据暂缺",
        total_mv="{:.1f}亿".format(total_mv / 1e8) if total_mv > 0 else "数据暂缺",
        turnover="{:.2f}%".format(quote.get("turnover", 0)) if quote.get("turnover", 0) else "数据暂缺",
        high=quote.get("high", 0), low=quote.get("low", 0),
        ma5=ind.get("ma5", "N/A"), ma10=ind.get("ma10", "N/A"),
        ma20=ind.get("ma20", "N/A"), ma60=ind.get("ma60", "N/A"),
        dif=ind.get("dif", "N/A"), dea=ind.get("dea", "N/A"),
        macd_bar=ind.get("macd_bar", "N/A"),
        rsi=ind.get("rsi", "N/A"), vol_ratio=ind.get("vol_ratio", "N/A"),
        resistance=ind.get("resistance", "N/A"), support=ind.get("support", "N/A"),
        fund_flow_text=fund_text, kline_summary=kline_text,
        eps_forecast_text=eps_forecast_text, hot_reason_text=hot_reason_text,
        industry_compare_text=industry_compare_text, main_net_text=main_net_text,
        financial_data_text=financial_data_text, peer_comparison_text=peer_comparison_text,
        revenue_composition_text=revenue_composition_text,
        news_text=news_text, order_news_text=order_news_text,
    )
