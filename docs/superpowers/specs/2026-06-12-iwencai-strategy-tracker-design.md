# 同花顺 iwencai 自动选股策略追踪 — Design Spec

**Date:** 2026-06-12
**Status:** Approved
**Author:** Claude (brainstorming session with user)

## Background & Motivation

用户在 2026-06-12 验证了同花顺 iwencai `get-robot-data` 接口在 server 上能稳定访问（带登录 cookie + `hexin-v` header），但手动维护 cookie 不可持续。

用户希望把"连续三日流入"这一类 iwencai 选股查询**自动化**：每个交易日 14:30 自动跑一次 → 把命中的股票入库 → 按 T+3 / T+7 / T+15 / T+30 跟踪收盘价 → 在 web 上做一个类似 `板块追踪` 的看板供复盘。

与现有 `板块追踪`（sector-tracker）的关系：

- 板块追踪是**手动触发**（用户在 Telegram 报概念名）
- 本功能是**自动触发**（cron 14:30 每天跑）— 但**底层 T+N 跟踪、看板、归档状态机**与 sector-tracker 共用同一套模式

## Goals

- **自动登录**：用 `10jqka.enc` 里的账号密码登录同花顺，cookie 自动刷新写回 `10jqka_cookies.enc`
- **每日跑批**：交易日 14:30 跑一次 iwencai query，命中 N 只股票写一个 batch
- **持续追踪**：每个交易日 20:00 拉所有 active batch 的 T+3/7/15/30 收盘价
- **看板**：左侧菜单加"策略"，页面类似 `板块追踪`（进行中 / 已归档 tab）
- **详情页**：每个 batch 看每只股的 T+N 涨跌幅（参考 `SectorDetail.jsx`）

## Non-Goals

- 不做仓位/资金/交易
- 不做多策略并行（先跑 1 个："连续三日流入"）
- 不做归因分析（不会算"为什么这只涨了"）
- 不做实时刷新（每天 2 次 cron 够了）

## Query 选股条件

```
均线多头排列;
非st的股票;
主板上市公司;
大单3日净量持续流入;
成交额>=1亿;
总市值>=200亿;
涨幅小于10%
```

策略名：**连续三日流入**（用户命名）。  
跑批时间：每个交易日 14:30（A股午盘后，行情已稳）。  
T+0 起点：跑批当天（即 query 返回的"今日"）。

## Design

### 1. 数据模型

#### 1.1 `strategy_picks`（批次主表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK, autoincrement | |
| `strategy_name` | String(50) | NOT NULL, indexed | 固定为 `'连续三日流入'` |
| `query_text` | Text | NOT NULL | 完整 iwencai query（冗余存，便于审计） |
| `status` | String(20) | NOT NULL, default='in_progress' | `in_progress` / `completed` / `archived` |
| `created_at` | DateTime | NOT NULL, default=now() | T+0 |
| `completed_at` | DateTime | nullable | T+30 全部填齐时设置 |
| `archived_at` | DateTime | nullable | 用户手动归档时设置 |

应用层约束：同时至多 N 个 in_progress + completed 的 batch（N 可为 10，UI 自动裁剪）。

#### 1.2 `strategy_pick_stocks`（每只股明细）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK, autoincrement | |
| `strategy_pick_id` | Integer | FK, NOT NULL, indexed | |
| `stock_code` | String(6) | NOT NULL | |
| `stock_name` | String(50) | NOT NULL | |
| `industry` | String(50) | nullable | 行业（从 10jqka F10 拿，失败可空） |
| `business_summary` | Text | nullable | 主营业务（从 10jqka F10 拿，截前 200 字） |
| `selection_reason` | Text | nullable | iwencai 给的"被选中的原因"（如有） |
| `t0_date` | Date | NOT NULL | 跑批当天 |
| `t0_price` | Float | nullable | 当日收盘价，跑批后由 scheduler 在 20:00 拉 |
| `t3_date` / `t3_price` / `t3_pct` | Date / Float / Float | nullable | T+3 收盘价 + 涨跌幅 |
| `t7_date` / `t7_price` / `t7_pct` | Date / Float / Float | nullable | T+7 |
| `t15_date` / `t15_price` / `t15_pct` | Date / Float / Float | nullable | T+15 |
| `t30_date` / `t30_price` / `t30_pct` | Date / Float / Float | nullable | T+30 |

Unique index: `(strategy_pick_id, stock_code)`，重复入选时 upsert（不报错）。

### 2. 组件

#### 2.1 `bot/iwc_client.py`（新文件）

封装 iwencai 调用：

```
class IwcClient:
    def __init__(self, creds_path="10jqka.enc", cookies_path="10jqka_cookies.enc"):
        # 解密 creds（只在内存中短暂持有 password）

    def _is_cookie_fresh(self) -> bool:
        # 检查 10jqka_cookies.enc 的 mtime，< 24h 视为新鲜

    def _login_and_save(self) -> dict:
        # 调 10jqka 登录接口，提取 userid / sess_tk / v / hexin-v 等
        # 加密写回 10jqka_cookies.enc

    def get_valid_cookies(self) -> dict:
        # 公开：fresh → load；stale → _login_and_save()

    def query(self, question: str, perpage: int = 50) -> list[dict]:
        # POST get-robot-data，组装 cookie + hexin-v header
        # 解析 data.answer[0].txt[0].content.components[0].data.datas
        # 返回 [{code, name, latest_price, change_pct, dde_main_net, total_mv, ...}, ...]
        # 失败抛 IwcError
```

错误处理：登录失败 → 抛 `IwcLoginError`；query 失败/0 条 → 抛 `IwcQueryError`。上层决定重试 / 告警。

#### 2.2 `bot/strategy_picker.py`（新文件）

单次跑批的纯函数：

```
async def run_strategy() -> dict:
    """
    1. IwcClient().query(QUERY) → 命中 N 只
    2. 对每只股调 10jqka F10 拿 industry / business_summary（失败容忍）
    3. 在 db 创建 StrategyPick（status=in_progress）
    4. 批量 insert StrategyPickStock（t0_price = 14:30 当时 `tencent_quote` 实时价）
    5. 返回 {batch_id, hit_count, errors}
    """
```

#### 2.3 `bot/strategy_tracker.py`（新文件）

复用 `sector_tracker.py` 的 `find_trading_day_after` 和 `calc_t_n_metrics`，扩展支持 T+3/7/15/30：

```
def get_t_n_data_for_stock(stock_code, t0_date, t0_price) -> dict:
    # K-line 拉 35 天，循环填 t3 / t7 / t15 / t30

def track_all_picks() -> dict:
    # 拉所有 in_progress / completed 的 batch
    # 对每只 stock 调 get_t_n_data_for_stock，upsert 到 db
    # 当 batch 内全部 t30_pct 非空时，把 batch.status 标 completed
```

#### 2.4 `bot/strategy_scheduler.py`（新文件）

参考 `sector_scheduler.py` 的结构：

```
scheduler = BlockingScheduler()
scheduler.add_job(run_strategy,    CronTrigger(hour=14, minute=30, day_of_week='mon-fri'))
scheduler.add_job(track_all_picks, CronTrigger(hour=20, minute=0,  day_of_week='mon-fri'))
scheduler.start()
```

部署：在 server 上用 systemd 或 nohup 跑。复用 `deploy_sector_scheduler.sh` 模式新增一个 `deploy_strategy_scheduler.sh`。

#### 2.5 `backend/app/routers/strategy.py`（新文件）

```
GET  /strategy-picks?status=in_progress|completed|archived
GET  /strategy-picks/{id}
POST /strategy-picks/{id}/archive   # 手动归档
```

返回结构与 `sector_picks` 路由镜像，pydantic schema 放 `backend/app/schemas/strategy_pick.py`。

#### 2.6 前端（2 个新页 + 1 处改）

- `frontend/src/pages/StrategyList.jsx`：仿 `SectorList.jsx`，tabs `进行中` / `已归档`
- `frontend/src/pages/StrategyDetail.jsx`：仿 `SectorDetail.jsx`，表格列：`代码 / 名称 / 行业 / 主营 / T+3 / T+7 / T+15 / T+30`
- `frontend/src/components/Layout.jsx`：菜单加 `🎯 策略` 入口（链接到 `/strategy`）
- `frontend/src/App.jsx`：加 `/strategy` 和 `/strategy/:id` 路由
- `frontend/src/api/strategy.js`：3 个 fetch 封装

### 3. 数据流（一天的生命周期）

```
09:00-14:30  A 股交易中
14:30  [cron] run_strategy() 跑 iwencai
         ├─ IwcClient.get_valid_cookies()  → 复用 24h 内 cookie
         ├─ query → 命中 N 只
         ├─ 调 10jqka F10 补 industry/business
         └─ 写 strategy_picks + strategy_pick_stocks（t0_price 空）

15:00  A 股收盘
20:00  [cron] track_all_picks()
         ├─ 对所有 active batch 拉 K-line
         └─ 填 t3 / t7 / t15 / t30（如已到时间，不动 t0_price）
         
未来 30 天：每天 20:00 继续 track_all_picks
第 30 天后：t30 填齐，batch.status = completed
手动归档 → status = archived
```

### 4. 失败模式与告警

| 场景 | 行为 |
|------|------|
| Cookie 过期且登录失败 | 抛 IwcLoginError，scheduler 写日志 + 发送 Telegram 消息给用户（复用 `telegram_bot.py` 现有的 notify 机制） |
| iwencai 返回 0 条 | 记录 log，不创建 batch |
| iwencai 返回但 F10 失败 | 股票写入时 industry/business 留空，UI 显示 `—` |
| 跑批日是非交易日 | `is_trading_day_today()` 返回 False → skip |
| Tracker 拉 K-line 失败 | 标记本次失败，下一天补；不会丢历史数据 |

### 5. 与现有 sector-tracker 的边界

- **不复用 sector_picks 表** — 这是独立的 strategy，schema 不同（T+3/7/15/30 vs T+5/10/20）
- **可复用 `sector_tracker.py` 的工具函数** — `find_trading_day_after` / `calc_t_n_metrics` / `is_trading_day_today` 直接 import
- **不复用 `bot/sector_selector.py`** — 这是按板块名选股，strategy 是按 query 选股

## Verification

1. 手动跑 `run_strategy()` 在 server 上 → 确认写入 strategy_picks + pick_stocks，cookie 自动刷新
2. 手动跑 `track_all_picks()` → 确认 t0_price 被填
3. 访问 `http://101.36.106.113:8888/strategy` → 看到 batch 列表 + 详情
4. 部署 scheduler systemd → 等下一个交易日 14:30 观察 cron.log
5. 30 天后回头看 completed batches 的 T+30 分布

## Open Questions

- [x] `T+0` 当天的"最新价"是否等同于"收盘价"？— **决定用 14:30 当时的实时价（`tencent_quote`）作为 t0_price**，不再覆盖
- [ ] F10 行业数据从 `astock_data_10jqka.py` 的 `get_concept_boards_10jqka` 同源的 endpoint 拿，需要新加 `get_industry_business` 函数
- [ ] 同时保留多少 in_progress batch — 暂定 10 个
