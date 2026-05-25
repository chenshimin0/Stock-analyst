"""
DeepSeek AI 股票分析模块
采集真实数据后调用 DeepSeek API 生成深度分析报告
"""
import json
import logging
import os
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
    "market_position": "公司在行业中的位置（龙头/一线/二线）",
    "main_competitors": "主要竞争对手及竞争态势（50-80字）",
    "entry_barriers": "行业进入壁垒（技术/资金/客户认证/规模等），40-80字",
    "moat_analysis": "护城河分析（品牌/转换成本/网络效应/成本优势），40-80字",
    "market_share_trend": "市占率变化趋势"
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
- 所有财务数据请基于你的知识库估计（标注~），不要编造精确数字
- 若某数据不可得，用 "数据暂缺" 代替
- 分析要专业、客观，有数据支撑
- 最终标签（可做/观察/回避）由后端根据双轨评分算法计算，你不需要给出
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


def _build_analysis_prompt(quote: dict, ind: dict, flow: dict, news: list, kline: list = None, order_news: list = None) -> str:
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

	atr_pct = round(atr / p * 100, 1) if p > 0 else 0
	pe = quote.get("pe", 0)
	total_mv = quote.get("total_mv", 0)

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
	)


def analyze_stock(quote: dict, ind: dict, flow: dict, news: list, kline: list = None, order_news: list = None) -> dict:
	"""调用 DeepSeek API 进行深度分析，返回完整的分析数据 dict"""
	api_key = load_api_key("DEEPSEEK_ENC_KEY")
	prompt = _build_analysis_prompt(quote, ind, flow, news, kline, order_news)

	payload = json.dumps({
		"model": MODEL,
		"messages": [
			{"role": "system", "content": "你是一位资深A股分析师。请基于提供的真实数据做推理分析。始终返回合法JSON，不要编造精确财务数字。"},
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
		# 提取 JSON block
		if "```json" in content:
			json_start = content.index("```json") + 7
			json_end = content.index("```", json_start)
			content = content[json_start:json_end].strip()
		elif "```" in content:
			json_start = content.index("```") + 3
			json_end = content.index("```", json_start)
			content = content[json_start:json_end].strip()
		analysis = json.loads(content)
		logger.info(f"AI 分析完成: {quote.get('code')} {quote.get('name')}")
		return analysis
	except ValueError:
		# No ``` markers — try raw content, then regex-extract JSON object
		try:
			analysis = json.loads(content)
			logger.info(f"AI 分析完成 (raw JSON): {quote.get('code')} {quote.get('name')}")
			return analysis
		except json.JSONDecodeError:
			m = re.search(r'\{.*\}', content, re.DOTALL)
			if m:
				analysis = json.loads(m.group())
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
        analysis = json.loads(content)
        logger.info(f"产业链分析完成: {query}")
        return analysis
    except ValueError:
        try:
            analysis = json.loads(content)
            logger.info(f"产业链分析完成 (raw): {query}")
            return analysis
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                analysis = json.loads(m.group())
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
