"""
半自动下单建议单：生成 + Server酱微信推送。

设计原则（安全硬限制，代码强制）：
1. 白名单：建议单只能从 StrategyPickStock 批次里的股票生成，
   AI / 任何模块都无权引入批次外的标的。
2. 系统永远不碰真实交易——只生成建议并推送微信，由用户手动下单。
3. 金额风控：单笔金额不足一手 / 超单日总额上限 的标的标记 risk_ok=False，
   不进入推送的下单建议（仍落库存档）。
4. Token 安全：Server酱 SendKey 用 Fernet 加密存于 bot/serverchan.enc，
   不出现明文、不进 git。
"""
import json
import logging
import math
import sys
from datetime import date, datetime
from pathlib import Path

from typing import Optional

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import Strategy, StrategyPick, StrategyPickStock  # noqa: E402
from app.models.order_suggestion import OrderSuggestion, OrderConfig  # noqa: E402

logger = logging.getLogger("order_notifier")

SERVERCHAN_API = "https://sctapi.ftqq.com/{key}.send"


# =========================================================================
# Config
# =========================================================================

def get_config(db) -> OrderConfig:
    """Get singleton config row, creating the default one if missing."""
    cfg = db.query(OrderConfig).first()
    if not cfg:
        cfg = OrderConfig()
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


# =========================================================================
# Server酱 push
# =========================================================================

WX_API = "https://api.weixin.qq.com/cgi-bin"


def _wx_access_token(appid: str, secret: str) -> str:
    r = requests.get(f"{WX_API}/token",
                     params={"grant_type": "client_credential", "appid": appid,
                             "secret": secret},
                     timeout=15).json()
    if "access_token" not in r:
        raise RuntimeError(f"获取 access_token 失败: {r}")
    return r["access_token"]


def send_wechat_template(fields: dict) -> bool:
    """微信测试号模板消息：内容直接显示在聊天气泡里，不跳网页。
    fields: {strategy, batch, stocks, total, note}，值为纯文本。
    失败返回 False（由调用方决定是否走 Server酱 兜底）。
    """
    try:
        from crypto_utils import load_wxtest_credentials
        creds = load_wxtest_credentials()
    except Exception as e:
        logger.warning(f"wxtest 凭据不可用，跳过模板消息: {e}")
        return False
    try:
        tok = _wx_access_token(creds["appid"], creds["secret"])
        payload = {
            "touser": creds["openid"],
            "template_id": creds["template_id"],
            "data": {k: {"value": str(v)} for k, v in fields.items() if v},
        }
        r = requests.post(f"{WX_API}/message/template/send",
                          params={"access_token": tok},
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          timeout=15).json()
        if r.get("errcode") == 0:
            return True
        logger.error(f"wx template send failed: {r}")
        return False
    except Exception as e:
        logger.error(f"wx template send error: {e}")
        return False


def send_serverchan(title: str, desp: str) -> bool:
    """Push one message via ServerChan Turbo. Returns True on code==0."""
    from crypto_utils import load_serverchan_token

    key = load_serverchan_token()
    # Server酱 Turbo title 上限约 32 字符
    title = title[:32]
    try:
        resp = requests.post(
            SERVERCHAN_API.format(key=key),
            data={"title": title, "desp": desp},
            timeout=15,
        )
        data = resp.json()
        if data.get("code") == 0:
            return True
        logger.error(f"Server酱 push failed: {data}")
        return False
    except Exception as e:
        logger.error(f"Server酱 push error: {e}")
        return False


def test_push() -> bool:
    """发一条测试消息验证推送通道。优先微信模板，失败走 Server酱。"""
    ok = send_wechat_template({
        "strategy": "通道测试",
        "batch": datetime.now().strftime("%m-%d %H:%M"),
        "stocks": "收到即代表微信模板消息通道正常",
        "total": "—",
        "note": "之后策略跑批的建议单会推送到这里。",
    })
    if not ok:
        ok = send_serverchan(
            "✅ 股票系统推送通道测试",
            "这是股票分析系统的测试消息（微信模板通道失败，Server酱 兜底）。",
        )
    logger.info(f"test_push -> {ok}")
    return ok


# =========================================================================
# Suggestion generation
# =========================================================================

def generate_for_batch(batch_id: int, push: bool = True, db=None,
                       force: bool = False) -> dict:
    """为一个批次生成建议单（可选推送）。

    Returns: {ok, created, pushed, message}
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        pick = db.query(StrategyPick).filter(StrategyPick.id == batch_id).first()
        if not pick:
            return {"ok": False, "created": 0, "pushed": False,
                    "message": f"batch {batch_id} 不存在"}
        strategy = db.query(Strategy).filter(Strategy.id == pick.strategy_id).first()

        existing = db.query(OrderSuggestion).filter(
            OrderSuggestion.batch_id == batch_id).all()
        if existing:
            # 幂等：同批次不重复生成；若还没推送成功则允许重推
            not_pushed = [s for s in existing if not s.pushed]
            if push and (not_pushed or force):
                # force=True 时连同已推送过的一起重推（换推送通道后补推用）
                return _push_batch(db, pick, strategy, existing if force else not_pushed)
            return {"ok": True, "created": 0, "pushed": False,
                    "message": f"batch {batch_id} 已生成过 {len(existing)} 条建议单，跳过"}

        cfg = get_config(db)

        # 单日已用金额（只统计风控通过的建议单）
        today_start = datetime.combine(date.today(), datetime.min.time())
        used_today = db.query(OrderSuggestion).filter(
            OrderSuggestion.created_at >= today_start,
            OrderSuggestion.risk_ok == True,  # noqa: E712
        ).all()
        daily_used = sum(s.amount for s in used_today)

        # 按插入顺序迭代 = 问财排名顺序，单日额度优先给排名靠前的标的
        stocks = db.query(StrategyPickStock).filter(
            StrategyPickStock.strategy_pick_id == batch_id
        ).order_by(StrategyPickStock.id).all()
        if not stocks:
            return {"ok": False, "created": 0, "pushed": False,
                    "message": f"batch {batch_id} 没有股票"}

        rows = []
        for st in stocks:
            risk_ok, note = True, None
            price = st.t0_price
            shares, amount = 0, 0.0
            if not price or price <= 0:
                risk_ok, note = False, "批次未记录参考价，无法生成建议"
            else:
                shares = math.floor(cfg.per_order_amount / price / 100) * 100
                if shares <= 0:
                    risk_ok, note = False, (
                        f"单笔金额 {cfg.per_order_amount:.0f} 元买不起一手"
                        f"（价格 {price:.2f}）")
                else:
                    if cfg.max_shares_per_stock and shares > cfg.max_shares_per_stock:
                        shares = math.floor(cfg.max_shares_per_stock / 100) * 100
                        note = f"股数按单股上限调整为 {shares} 股"
                    amount = round(shares * price, 2)
                    # 单日总额风控：超限的标记不通过，不推进 daily_used
                    if daily_used + amount > cfg.max_daily_amount:
                        risk_ok, note = False, (
                            f"超单日总额上限 {cfg.max_daily_amount:.0f} 元"
                            f"（今日已建议 {daily_used:.0f} 元）")
                    else:
                        daily_used += amount
            rows.append(OrderSuggestion(
                batch_id=batch_id,
                strategy_id=pick.strategy_id,
                stock_code=st.stock_code,
                stock_name=st.stock_name,
                suggested_price=price,
                shares=shares,
                amount=amount,
                risk_ok=risk_ok,
                risk_note=note,
            ))
        db.add_all(rows)
        db.commit()

        logger.info(f"batch {batch_id}: 生成 {len(rows)} 条建议单"
                    f"（通过 {sum(1 for r in rows if r.risk_ok)} 条）")
        if push:
            return _push_batch(db, pick, strategy, rows)
        return {"ok": True, "created": len(rows), "pushed": False,
                "message": f"已生成 {len(rows)} 条建议单（未推送）"}
    finally:
        if own_db:
            db.close()


def _push_batch(db, pick: StrategyPick, strategy: Optional[Strategy],
                rows: list[OrderSuggestion]) -> dict:
    """把一个批次的建议单合成一条 Server酱消息推送。"""
    cfg = get_config(db)
    if not cfg.push_enabled:
        return {"ok": True, "created": 0, "pushed": False,
                "message": "push_enabled=False，未推送"}

    sname = strategy.name if strategy else f"策略#{pick.strategy_id}"
    ok_rows = [r for r in rows if r.risk_ok]
    if not ok_rows:
        return {"ok": True, "created": 0, "pushed": False,
                "message": "该批次没有通过风控的标的，未推送"}

    total = sum(r.amount for r in ok_rows)
    lines = [
        f"## {sname} · 批次 #{pick.id} 建议单",
        "",
        f"生成时间 {datetime.now().strftime('%m-%d %H:%M')}，"
        f"建议委托价参考跑批时现价，下单前请核对实时行情。",
        "",
        "| 代码 | 名称 | 建议价 | 股数 | 金额 |",
        "|---|---|---|---|---|",
    ]
    for r in ok_rows:
        lines.append(
            f"| {r.stock_code} | {r.stock_name} | {r.suggested_price:.2f} "
            f"| {r.shares} | {r.amount:,.0f} |")
    lines += [
        "",
        f"**合计 ¥{total:,.0f} · {len(ok_rows)} 只**",
        "",
    ]
    # 风控被拒的标的一并告知（透明）
    rejected = [r for r in rows if not r.risk_ok]
    if rejected:
        lines.append("**未通过风控（不建议下单）**")
        lines.append("")
        for r in rejected:
            lines.append(f"- {r.stock_code} {r.stock_name}：{r.risk_note}")
        lines.append("")
    lines.append("> 半自动提醒：系统不下单，请自行核实后在券商 App 操作。")

    title = f"📈 {sname} 建议单 · {datetime.now().strftime('%m-%d')}"
    # PC 微信对模板消息只渲染前两个字段（策略/批次），且字段内多行会折叠。
    # 因此改为：每只股票一条 + 一条汇总，全部只用 strategy/batch 两个字段、单行文本。
    suffix = f"（另有{len(rejected)}只未过风控）" if rejected else ""
    n = len(ok_rows)
    sent = True
    for i, r in enumerate(ok_rows, 1):
        ok = send_wechat_template({
            "strategy": f"{sname} 建议单 {i}/{n}",
            "batch": f"{r.stock_name} {r.suggested_price:.2f} x {r.shares}股"
                     f" = {r.amount:,.0f}元",
        })
        if not ok:
            sent = False
            break
    if sent:
        sent = send_wechat_template({
            "strategy": f"{sname} 建议单汇总",
            "batch": f"{n}只 · 合计{total:,.0f}元{suffix}",
        })
    if not sent:
        # 微信模板通道失败 → Server酱 网页卡片兜底（一整条带完整表格）
        sent = send_serverchan(title, "\n".join(lines))
    now = datetime.utcnow()
    for r in rows:
        if sent:
            r.pushed = True
            r.pushed_at = now
        db.add(r)
    db.commit()
    if not sent:
        return {"ok": False, "created": 0, "pushed": False,
                "message": "Server酱推送失败，建议单已保存（可重推）"}
    return {"ok": True, "created": 0, "pushed": True,
            "message": f"已推送 {len(ok_rows)} 条建议单到微信"}


def maybe_push_after_pick(strategy_id: int, batch_id: int) -> dict:
    """跑批成功后调用：该策略开了 notify_wechat 才生成+推送。"""
    db = SessionLocal()
    try:
        s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if not s or not getattr(s, "notify_wechat", False):
            return {"ok": True, "pushed": False,
                    "message": "策略未开启微信推送，跳过"}
        return generate_for_batch(batch_id, push=True, db=db)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [order-notifier] %(levelname)s %(message)s")
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true", help="send a test message")
    p.add_argument("--batch", type=int, help="generate + push suggestions for a batch")
    p.add_argument("--no-push", action="store_true", help="generate only, don't push")
    args = p.parse_args()
    if args.test:
        sys.exit(0 if test_push() else 1)
    if args.batch:
        out = generate_for_batch(args.batch, push=not args.no_push)
        for k, v in out.items():
            print(f"  {k}: {v}")
        sys.exit(0 if out["ok"] else 1)
    p.print_help()
