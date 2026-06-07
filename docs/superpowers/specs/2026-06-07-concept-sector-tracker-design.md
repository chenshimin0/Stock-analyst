# 概念板块追踪功能 — Design Spec

**Date:** 2026-06-07
**Status:** Approved
**Author:** Claude (brainstorming session with user)

## Background & Motivation

用户希望在 Telegram bot 输入一个**概念板块名**（如 pvdf、太赫兹、固态电池），自动按规则从该概念中精选 3 只 A 股，并在 T+5 / T+10 / T+20 个交易日后追踪其涨跌幅表现，按板块聚合展示，用于验证选股策略的有效性。

与现有"个股分析报告"功能的关系：现有功能是用户报单只股票 → 立即分析 → 落地为单个 HTML 报告。本功能是用户报一个概念 → 选 3 只 → 在 30 个交易日内持续追踪 → 按板块汇总。

## Goals

- **入口简单**：Telegram bot 一个 inline 按钮 + 输入概念名即可
- **选股可解释**：每次选股结果都记录原因（DeepSeek 30 字内）
- **数据有兜底**：成分股 API 挂掉时回退到 AI 知识库
- **追踪自动化**：scheduler 每天 20:00 自动跑，无需人工干预
- **UI 聚合**：左侧菜单"📊 板块追踪"一键查看所有进行中/已归档的板块

## Non-Goals

- 不做板块成分股的实时新闻/情绪分析
- 不做仓位建议、不做回测、不做收益归因
- 不接入交易系统
- 不做用户多账户/多权限

## Design

### 1. 数据模型

#### 1.1 `sector_picks`（板块追踪主表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK, autoincrement | |
| `sector_name` | String(100) | NOT NULL, indexed | 概念板块名 |
| `status` | String(20) | NOT NULL, default='in_progress' | `in_progress` / `completed` / `archived` |
| `selection_source` | String(20) | NOT NULL | `api_driven` / `ai_knowledge` |
| `created_at` | DateTime | NOT NULL, default=now() | T+0 起点 |
| `completed_at` | DateTime | nullable | scheduler 在 T+20 全部填齐时设置 |
| `archived_at` | DateTime | nullable | 用户手动归档时设置 |

应用层约束：同 `sector_name` 至多一条 `status IN ('in_progress', 'completed')` 的记录。

#### 1.2 `sector_pick_stocks`（每轮选股明细）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK, autoincrement | |
| `sector_pick_id` | Integer | FK→sector_picks.id, NOT NULL | |
| `stock_code` | String(6) | NOT NULL | 6 位代码 |
| `stock_name` | String(50) | NOT NULL | |
| `selection_reason` | Text | NOT NULL | DeepSeek 30 字内理由 |
| `t0_date` | Date | NOT NULL | T+0 自然日 |
| `t0_price` | Float | nullable | T+0 收盘价（qfq） |
| `t0_avg_price` | Float | nullable | T+0 均价（qfq） |
| `t5_date` / `t5_price` / `t5_avg_price` / `t5_pct` | Date / Float / Float / Float | all nullable | T+5 交易日数据 |
| `t10_date` / `t10_price` / `t10_avg_price` / `t10_pct` | 同上 | | T+10 |
| `t20_date` / `t20_price` / `t20_avg_price` / `t20_pct` | 同上 | | T+20 |

唯一索引：`(sector_pick_id, stock_code)`。

#### 1.3 `sector_member_cache`（概念成分股缓存表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `sector_name` | String(100) | composite PK | |
| `stock_code` | String(6) | composite PK | |
| `stock_name` | String(50) | NOT NULL | |
| `last_fetched_at` | DateTime | NOT NULL | |

TTL：24 小时（每次 scheduler 跑时检查并刷新过期记录）。

### 2. Telegram Bot 流程

#### 2.1 入口

用户在 bot 菜单看到 `[📊 板块追踪]` inline 按钮。点 → bot 回复 `请输入概念名（如 pvdf / 太赫兹 / 固态电池）` → 用户输入。

#### 2.2 状态判断

handler 查询 DB：
```sql
SELECT * FROM sector_picks
WHERE sector_name = ? AND status IN ('in_progress', 'completed')
```

**命中** → bot 发消息：
> 该板块 `{sector_name}` 已有进行中的追踪（状态：{status}，创建于 {created_at}）。60 秒后将自动重开一轮。`[立即重开]` `[取消]`
- 用户点 `[立即重开]` 或 60s 超时 → 旧记录 `archived_at=now()`, `status='archived'` → 进入新选股
- 用户点 `[取消]` → 终止

**未命中** → 进入新选股流程。

#### 2.3 选股流程（A+B 兜底组合）

**Step 1：成分股获取（方案 B 优先）**

```
查 sector_member_cache
  WHERE sector_name = ?
  AND last_fetched_at > now() - 24h
```

- **命中** → 直接用缓存的成分股列表
- **未命中** → 调 a-stock-data skill 接口拉成分股：
  - 首选：百度股市通概念归属接口
  - 备选：同花顺热点 reason 反查
  - 都失败 → fallback 到方案 A

**Step 2：成分股估值过滤（仅方案 B）**

用 `tencent_quote()` 批量拉所有候选成分股的实时估值：
- 过滤主板（6/0/3 字头，去 8 字头北交所/4/9 字头）
- 过滤非 ST（股票简称不含 "ST"）
- 过滤市值 < 500 亿
- 用东财分红接口确认近 3 年有现金分红
- 计算 PE-TTM 中位数

**Step 3：DeepSeek 选股**

**Prompt 模板（方案 B / API 驱动）**：
```
概念名称：{concept_name}
该概念成分股（已通过 API 实时拉取，{date}）：

| 代码 | 名称 | 市值(亿) | PE-TTM | 主板 | 非ST | 近3年有分红 |
| 002812 | 恩捷股份 | 450 | 28 | ✅ | ✅ | ✅ |
| 002407 | 多氟多 | 180 | 35 | ✅ | ✅ | ✅ |
| ... |

请从上述成分股中，挑选 **3 只** 最符合以下条件的：
1. 行业龙头地位
2. PE-TTM 低于本概念中位数（{median_pe}）
3. 总市值 < 500 亿
4. 主板上市、非 ST
5. 历史上连续 3 年有现金分红
6. 给出每只的简短推荐理由（30 字内）

输出严格 JSON：{"picks":[{"code":"002812","name":"恩捷股份","reason":"全球 PVDF 隔膜涂覆龙头..."}]}
```

**Prompt 模板（方案 A / AI 知识）**：
```
请从"{concept_name}"这一**概念板块**中，推荐 3 只符合以下条件的 A 股：
- 沪深主板上市（6/0/3 字头），非 ST
- 总市值 < 500 亿
- 行业龙头地位
- PE-TTM 较低（在你的知识库范围内评估）
- 历史上连续 3 年有现金分红
- 输出严格 JSON：{"picks":[{"code":"002812","name":"恩捷股份","reason":"..."}]}
- 如果该概念不存在或成分股 < 3 只，返回 {"error":"原因"} 而非猜测
```

**Step 4：落库**

```python
sector_pick = SectorPick(
    sector_name=concept_name,
    status='in_progress',
    selection_source='api_driven' if used_step_b else 'ai_knowledge',
)
# 3 只 stocks
for pick in ai_response['picks']:
    quote = tencent_quote([pick['code']])[pick['code']]
    stock = SectorPickStock(
        sector_pick_id=sector_pick.id,
        stock_code=pick['code'],
        stock_name=pick['name'],
        selection_reason=pick['reason'],
        t0_date=today(),
        t0_price=quote['price'],         # 收盘价
        t0_avg_price=quote.get('avg_price'),  # 如有
    )
```

**Step 5：回复用户**

> 已记录 3 只：
> - 002812 恩捷股份 — 全球 PVDF 隔膜涂覆龙头...
> - 002407 多氟多 — 六氟磷酸锂国内龙头...
> - 002460 赣锋锂业 — 锂盐产能国内第一...
>
> 数据源：API 实时 / AI 知识
> 将在 T+5/10/20 个交易日后自动追踪

### 3. Scheduler 流程

`bot/sector_scheduler.py` 独立进程，由 `nohup` 启动。

#### 3.1 触发

APScheduler `CronTrigger(hour=20, minute=0)` 每天。

#### 3.2 交易日判断

查询腾讯 K-line：当天能拉到 K-line → 视为交易日 → 执行；否则 skip。

#### 3.3 主循环

```python
for pick in sector_picks.filter(status.in_(['in_progress', 'completed'])):
    all_completed = True
    for stock in pick.stocks:
        # 拉取 K-line
        klines = tencent_kline(stock.stock_code, days=30, qfq=True)

        # 计算 T+0 后的第 5/10/20 个交易日
        trading_days_after_t0 = get_trading_days_after(
            klines, pick.created_at.date(), [5, 10, 20]
        )

        # 填库
        for n in [5, 10, 20]:
            if trading_days_after_t0[n]:
                t_date, t_close, t_avg = trading_days_after_t0[n]
                pct = (t_close - stock.t0_price) / stock.t0_price * 100
                setattr(stock, f't{n}_date', t_date)
                setattr(stock, f't{n}_price', t_close)
                setattr(stock, f't{n}_avg_price', t_avg)
                setattr(stock, f't{n}_pct', pct)

        # 校验所有时间点是否都填齐
        if not all([stock.t5_pct, stock.t10_pct, stock.t20_pct]):
            all_completed = False

    # 全部填齐 → 标 completed
    if all_completed and pick.status == 'in_progress':
        pick.status = 'completed'
        pick.completed_at = now()
```

#### 3.4 失败处理

- 拉 K-line 失败 → skip 本只 stock，warning 日志，次日 20:00 重试
- 计算 5/10/20 交易日时 K-line 数据不足（如节假日）→ 该天点保持 None

### 4. 前端 UI

#### 4.1 左侧菜单

新增菜单项 `📊 板块追踪`，点击跳转 `/sector-tracker`。

#### 4.2 列表页 `/sector-tracker`

- 顶部 Tab：`进行中`（含 in_progress + completed）/ `已归档`
- 列表行：板块名、状态徽章、创建时间、3 个 cell（T+5/10/20 板块平均）
- 涨跌幅配色：红涨绿跌（中国惯例）
- 空状态："还没有追踪板块，去 Telegram bot 发送 `/pick` 试试"

#### 4.3 详情页 `/sector-tracker/{id}`

- 板块名 + 状态 + 创建时间
- 表格：
  | 代码 | 名称 | 推荐理由 | T+0 价 | T+5 涨幅 | T+10 涨幅 | T+20 涨幅 |
  | 002812 | 恩捷股份 | ... | 45.20 | +3.2% | -1.5% | +8.7% |
- 底部"板块平均"行
- 按钮：`[归档]`（in_progress / completed 时显示）

#### 4.4 新增文件

- `frontend/src/pages/SectorList.jsx`
- `frontend/src/pages/SectorDetail.jsx`
- `frontend/src/api/sector.js`
- `frontend/src/components/Sidebar.jsx`（修改）

### 5. API（FastAPI）

新增 `backend/app/routers/sector_picks.py`：

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/sector-picks?status=` | 列表 |
| GET | `/api/sector-picks/{id}` | 详情 |
| POST | `/api/sector-picks` | 新建（bot 内部调用） |
| POST | `/api/sector-picks/{id}/archive` | 手动归档 |

**Schema** (`backend/app/schemas/sector_pick.py`)：

```python
class StockMetric(BaseModel):
    code: str
    name: str
    reason: str
    t0_price: Optional[float]
    t5_pct: Optional[float]
    t10_pct: Optional[float]
    t20_pct: Optional[float]

class SectorPickListItem(BaseModel):
    id: int
    sector_name: str
    status: str
    created_at: datetime
    selection_source: str
    avg_t5_pct: Optional[float]
    avg_t10_pct: Optional[float]
    avg_t20_pct: Optional[float]

class SectorPickDetail(SectorPickListItem):
    completed_at: Optional[datetime]
    archived_at: Optional[datetime]
    stocks: List[StockMetric]
```

### 6. 异常处理

| 场景 | 处理 |
|------|------|
| DeepSeek 返回非 JSON | bot 提示"选股失败，请重试" |
| DeepSeek 字段缺失 | bot 提示"选股结果不完整，请重试" |
| 方案 B 接口全挂 | 自动 fallback 方案 A，记录 selection_source='ai_knowledge' |
| Tencent K-line 拉取失败 | scheduler skip + warning，次日重试 |
| 成分股 cache 24h 过期 | scheduler 触发时自动重拉 |
| 同板块重复推送 | bot 显示"已有进行中"，60s 倒计时默认重开 |
| 用户取消重开 | 旧 pick 保持原状态，新 pick 不创建 |
| 腾讯返回 PE/市值为 0 | 标记为"无数据"，DeepSeek prompt 里说明 |

### 7. 测试

#### 7.1 单测

| 文件 | 测试 |
|------|------|
| `bot/tests/test_sector_kline.py` | `calculate_t_n_pct` 5/10/20 交易日逻辑（mock K-line） |
| `bot/tests/test_sector_ai.py` | DeepSeek 返回 JSON 解析（正常 / 异常 / 字段缺失） |
| `bot/tests/test_sector_cache.py` | 24h TTL 判断 |
| `bot/tests/test_sector_quote.py` | `tencent_quote` mock 数据 |
| `bot/tests/test_sector_filter.py` | 主板/非ST/市值/分红 过滤 |

#### 7.2 集成测

端到端：
1. 模拟 bot 收到"pvdf" → 选股 → 落库
2. 模拟 scheduler 跑（mock 日期到 T+5/10/20）→ 数据写入
3. API 查询 → 返回正确 JSON
4. POST /archive → 状态变 archived
5. 列表页 API → archived 不出现在"进行中" tab

### 8. 部署

#### 8.1 新增文件

- `deploy-scheduler.sh`：复制 `bot/sector_scheduler.py` 到 server，`nohup` 启动
- `bot/sector_scheduler.py`：scheduler 主程序
- `bot/sector_handler.py`：bot handler（与现有 `telegram_bot.py` 集成）
- `bot/sector_selector.py`：选股逻辑（A+B 兜底）
- `bot/sector_tracker.py`：K-line 拉取 + T+N 计算

#### 8.2 进程管理

```bash
# 启动
nohup python3 bot/sector_scheduler.py > logs/sector_scheduler.log 2>&1 &
disown

# 健康检查
ps aux | grep sector_scheduler

# 重启
pkill -f sector_scheduler
nohup python3 bot/sector_scheduler.py > logs/sector_scheduler.log 2>&1 &
```

#### 8.3 watchdog（可选）

写个 cron 每天 19:55 检查进程是否在跑，没在就拉起：
```cron
55 19 * * * /path/to/check_scheduler.sh
```

### 9. 风险点

| 风险 | 缓解 |
|------|------|
| Telegram rate limit 触发 | bot 端加 5s 间隔 |
| APScheduler 进程挂掉不自启 | watchdog cron 拉起 |
| DeepSeek 知识陈旧（2024 年初） | 方案 B 优先（实时成分股） |
| 同名概念歧义（"光伏" 是行业还是概念？） | 用户输入即用，不歧义处理 |
| 节假日判断错误 | 腾讯 K-line 是否能拉到数据为唯一判断标准 |
| bot 被滥用 | 当前不考虑（个人用），未来加白名单 |

## Open Questions

无（所有关键决策已与用户确认）。

## Verification Plan

1. 启动 bot → 发送"pvdf" → 选股成功 → DB 落库验证
2. 启动 scheduler → 模拟 5/10/20 个交易日后 → 数据落库验证
3. 前端访问 `/sector-tracker` → 列表显示正确
4. 点击详情页 → 表格 + 板块平均 + 归档按钮显示正确
5. 点击归档 → API 状态变更 + 列表 tab 切换正确
