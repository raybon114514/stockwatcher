"""
AI 股票策略回測引擎
只做純技術面，不含情緒面（PTT / Yahoo 新聞無歷史資料）

使用方式：
# 一般回測
python backtest.py --stock 2330 --name 台積電 --period 6mo

# 美股
python backtest.py --stock NVDA --name NVIDIA --market 美股 --period 1y

# 參數掃描（測 3 種 lookback × 3 種 temperature = 9 種組合）
python backtest.py --stock 2330 --name 台積電 --sweep

# 用 Gemini 跑（速度快很多）
python backtest.py --stock 2330 --name 台積電 --provider gemini --gemini-key YOUR_KEY
"""

import argparse
import json
import re
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf

from analyzer import StockAI


# ─────────────────────────────────────────────
#  核心引擎
# ─────────────────────────────────────────────

class BacktestEngine:
    def __init__(
        self,
        stock_code: str,
        market: str = "台股",
        period: str = "6mo",
        initial_capital: int = 5_000_000,
        lookback: int = 17,
        temperature: float = 0.2,
        provider: str = "local",
        gemini_key: str = None,
    ):
        self.stock_code   = stock_code
        self.market       = market
        self.yf_code      = f"{stock_code}.TW" if market == "台股" else stock_code
        self.period       = period
        self.initial_capital = initial_capital
        self.lookback     = lookback   # 每次餵給 AI 的歷史天數
        self.temperature  = temperature

        self.ai = StockAI(
            provider=provider,
            model_name="gemini-3-flash-preview" if provider == "gemini" else "gpt-oss-20b",
            gemini_api_key=gemini_key,
        )

        # 回測結果容器
        self.trades: list[dict] = []
        self.daily_log: list[dict] = []

    # ── 資料下載與指標計算 ─────────────────────

    def _download_data(self) -> pd.DataFrame:
        ticker = yf.Ticker(self.yf_code)
        hist   = ticker.history(period=self.period)

        if hist.empty:
            raise ValueError(f"找不到 {self.yf_code} 的歷史資料，請確認代號。")

        # 技術指標
        hist["MA5"]  = hist["Close"].rolling(5).mean()
        hist["MA20"] = hist["Close"].rolling(20).mean()

        delta = hist["Close"].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        hist["RSI"] = 100 - (100 / (1 + gain / loss))

        exp1 = hist["Close"].ewm(span=12, adjust=False).mean()
        exp2 = hist["Close"].ewm(span=26, adjust=False).mean()
        hist["MACD"]        = exp1 - exp2
        hist["MACD_Signal"] = hist["MACD"].ewm(span=9, adjust=False).mean()
        hist["MACD_Hist"]   = hist["MACD"] - hist["MACD_Signal"]

        return hist.dropna().reset_index()

    def _to_records(self, df_slice: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df_slice.iterrows():
            date_val = row["Date"]
            date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)[:10]
            records.append({
                "Date":         date_str,
                "ClosingPrice": round(row["Close"], 2),
                "TradeVolume":  int(row["Volume"] / 1000) if self.market == "台股" else int(row["Volume"]),
                "MA5":          round(row["MA5"],  2),
                "MA20":         round(row["MA20"], 2),
                "RSI":          round(row["RSI"],  2),
                "MACD_Hist":    round(row["MACD_Hist"], 2),
            })
        return records

    # ── AI 決策解析 ───────────────────────────

    def _parse_decision(self, text: str) -> tuple[str, int]:
        """從 manager_decision 的輸出中抓取決策與比例"""
        decision_matches = re.findall(r"[\[【［]\s*(買入|賣出|觀望)\s*[\]】］]", text)
        decision = decision_matches[-1] if decision_matches else "觀望"

        ratio_matches = re.findall(r"比例[：:]\s*[\[【［]\s*(\d+)%\s*[\]】］]", text)
        percentage = int(ratio_matches[-1]) if ratio_matches else 50

        return decision, percentage

    # ── 模擬錢包 ──────────────────────────────

    def _execute_trade(
        self,
        action: str,
        percentage: int,
        price: float,
        balance: float,
        position: dict,
        date_str: str,
    ) -> tuple[float, dict, str | None]:
        """執行模擬交易，回傳 (新餘額, 新部位, 交易摘要字串)"""
        msg = None

        if action == "買入":
            budget = balance * (percentage / 100)
            shares = int(budget // price)

            cost = price * shares
            if shares > 0 and balance >= cost:
                total_cost      = position["shares"] * position["avg_cost"] + cost
                position["shares"] += shares
                position["avg_cost"] = total_cost / position["shares"]
                balance -= cost
                msg = f"買入 {shares:,} 股  花費 {cost:,.0f}"

        elif action == "賣出" and position["shares"] > 0:
            if self.market == "台股":
                lots = int((position["shares"] / 1000) * (percentage / 100))
                if lots == 0 and position["shares"] >= 1000:
                    lots = 1
                shares = lots * 1000
            else:
                shares = int(position["shares"] * (percentage / 100))
                if shares == 0 and position["shares"] > 0:
                    shares = 1

            if shares > 0:
                profit  = (price - position["avg_cost"]) * shares
                balance += price * shares
                position["shares"] -= shares
                if position["shares"] <= 0:
                    position = {"shares": 0, "avg_cost": 0.0}

                self.trades.append({
                    "date":   date_str,
                    "action": "賣出",
                    "price":  price,
                    "shares": shares,
                    "profit": round(profit, 2),
                    "win":    profit > 0,
                })
                msg = f"賣出 {shares:,} 股  損益 {profit:,.0f}"

        return balance, position, msg

    # ── 主回測迴圈 ────────────────────────────

    def run(self, stock_name: str = "股票") -> dict:
        print(f"\n{'═'*55}")
        print(f"  回測開始：{stock_name} ({self.yf_code})")
        print(f"  期間：{self.period}  初始資金：{self.initial_capital:,}")
        print(f"  AI lookback：{self.lookback} 天  temperature：{self.temperature}")
        print(f"{'═'*55}\n")

        df = self._download_data()

        # 至少需要 lookback 天才能開始
        if len(df) <= self.lookback:
            raise ValueError(f"歷史資料不足（只有 {len(df)} 筆），請拉長 period。")

        balance  = float(self.initial_capital)
        position = {"shares": 0, "avg_cost": 0.0}
        peak     = float(self.initial_capital)
        max_dd   = 0.0

        for i in range(self.lookback, len(df)):
            row      = df.iloc[i]
            date_str = str(row["Date"])[:10]
            price    = round(float(row["Close"]), 2)

            # 只用「當天以前」的資料，不偷看未來
            window       = df.iloc[i - self.lookback: i]
            records      = self._to_records(window)
            period_high  = round(float(window["High"].max()), 2)
            period_low   = round(float(window["Low"].min()),  2)

            print(f"[{date_str}]  收盤 {price:>10.2f}  呼叫 AI...", end="  ", flush=True)

            try:
                # Step 1：技術分析報告
                tech_report = self.ai.analyze_trend(
                    stock_name, records, period_high, period_low
                )
                # Step 2：純技術決策（情緒面填「無」）
                decision_text = self.ai.manager_decision(
                    stock_name,
                    technical_report=tech_report,
                    ptt_report="無（回測模式，無情緒資料）",
                    news_report="無（回測模式，無新聞資料）",
                )
                decision, percentage = self._parse_decision(decision_text)

            except Exception as e:
                print(f"⚠️ AI 失敗：{e}，跳過")
                decision, percentage = "觀望", 0

            balance, position, trade_msg = self._execute_trade(
                decision, percentage, price, balance, position, date_str
            )

            portfolio_value = balance + position["shares"] * price
            if portfolio_value > peak:
                peak = portfolio_value
            drawdown = (peak - portfolio_value) / peak * 100
            if drawdown > max_dd:
                max_dd = drawdown

            self.daily_log.append({
                "date":            date_str,
                "price":           price,
                "decision":        decision,
                "percentage":      percentage,
                "portfolio_value": round(portfolio_value, 2),
                "balance":         round(balance, 2),
                "shares":          position["shares"],
            })

            status = trade_msg or "觀望"
            print(f"決策：{decision} {percentage}%  {status}  總值：{portfolio_value:,.0f}")

        # ── 清算剩餘部位 ──
        final_price = float(df.iloc[-1]["Close"])
        final_value = balance + position["shares"] * final_price

        # ── 買入持有基準 ──
        start_price = float(df.iloc[self.lookback]["Close"])
        if self.market == "台股":
            bh_shares = int(self.initial_capital // (start_price * 1000)) * 1000
        else:
            bh_shares = int(self.initial_capital // start_price)
        bh_cost  = bh_shares * start_price
        bh_value = bh_shares * final_price + (self.initial_capital - bh_cost)

        # ── 統計 ──
        winning   = [t for t in self.trades if t["win"]]
        win_rate  = len(winning) / len(self.trades) * 100 if self.trades else 0.0
        ai_return = (final_value - self.initial_capital) / self.initial_capital * 100
        bh_return = (bh_value   - self.initial_capital) / self.initial_capital * 100

        report = {
            "stock":               f"{stock_name} ({self.yf_code})",
            "period":              self.period,
            "lookback":            self.lookback,
            "temperature":         self.temperature,
            "initial_capital":     self.initial_capital,
            "final_value":         round(final_value, 2),
            "ai_return_pct":       round(ai_return, 2),
            "buy_hold_return_pct": round(bh_return, 2),
            "alpha_pct":           round(ai_return - bh_return, 2),
            "total_trades":        len(self.trades),
            "win_rate_pct":        round(win_rate, 2),
            "max_drawdown_pct":    round(max_dd, 2),
            "trade_log":           self.trades,
            "daily_log":           self.daily_log,
        }

        self._print_report(report)
        filename = self._save_report(report)
        print(f"\n📁 完整報告已儲存：{filename}")

        return report

    # ── 報告輸出 ──────────────────────────────

    def _print_report(self, r: dict):
        alpha_sign = "+" if r["alpha_pct"] >= 0 else ""
        print(f"\n{'═'*55}")
        print(f"  📊 回測報告：{r['stock']}")
        print(f"{'═'*55}")
        print(f"  初始資金：   {r['initial_capital']:>15,.0f}")
        print(f"  最終總值：   {r['final_value']:>15,.0f}")
        print(f"  {'─'*40}")
        print(f"  AI 策略報酬：   {r['ai_return_pct']:>+.2f}%")
        print(f"  買入持有報酬：  {r['buy_hold_return_pct']:>+.2f}%")
        print(f"  超額報酬 Alpha：{alpha_sign}{r['alpha_pct']:.2f}%")
        print(f"  {'─'*40}")
        print(f"  總交易次數：{r['total_trades']}")
        print(f"  勝率：      {r['win_rate_pct']:.1f}%")
        print(f"  最大回撤：  {r['max_drawdown_pct']:.2f}%")
        print(f"{'═'*55}")

    def _save_report(self, report: dict) -> str:
        code     = self.yf_code.replace(".", "_")
        ts       = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"backtest_{code}_{ts}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=4)
        return filename


# ─────────────────────────────────────────────
#  參數組合掃描（Sweep 模式）
# ─────────────────────────────────────────────

def run_sweep(args):
    """測試不同 lookback 與 temperature 組合，找出最佳參數"""

    lookback_options    = [5, 10, 17]
    temperature_options = [0.1, 0.2, 0.4]

    results = []

    print(f"\n🔬 參數掃描模式：{len(lookback_options) * len(temperature_options)} 種組合\n")

    for lb in lookback_options:
        for temp in temperature_options:
            print(f"\n▶ lookback={lb}  temperature={temp}")
            try:
                engine = BacktestEngine(
                    stock_code=args.stock,
                    market=args.market,
                    period=args.period,
                    initial_capital=args.capital,
                    lookback=lb,
                    temperature=temp,
                    provider=args.provider,
                    gemini_key=args.gemini_key,
                )
                report = engine.run(stock_name=args.name)
                results.append({
                    "lookback":    lb,
                    "temperature": temp,
                    "ai_return":   report["ai_return_pct"],
                    "alpha":       report["alpha_pct"],
                    "win_rate":    report["win_rate_pct"],
                    "max_dd":      report["max_drawdown_pct"],
                })
            except Exception as e:
                print(f"  ⚠️ 此組合失敗：{e}")

    if not results:
        print("所有組合均失敗，請確認設定。")
        return

    # 排行榜
    results.sort(key=lambda x: x["alpha"], reverse=True)
    print(f"\n{'═'*65}")
    print(f"  🏆 參數掃描排行榜（依 Alpha 排序）")
    print(f"{'═'*65}")
    print(f"  {'Lookback':>8}  {'Temp':>5}  {'AI報酬':>8}  {'Alpha':>8}  {'勝率':>6}  {'最大回撤':>8}")
    print(f"  {'─'*55}")
    for r in results:
        print(f"  {r['lookback']:>8}  {r['temperature']:>5}  {r['ai_return']:>+7.2f}%  {r['alpha']:>+7.2f}%  {r['win_rate']:>5.1f}%  {r['max_dd']:>7.2f}%")
    print(f"{'═'*65}")

    best = results[0]
    print(f"\n  ✅ 最佳參數：lookback={best['lookback']}  temperature={best['temperature']}")

    # 儲存掃描結果
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    sweep_file = f"sweep_{args.stock}_{ts}.json"
    with open(sweep_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    print(f"  📁 掃描結果已儲存：{sweep_file}\n")


# ─────────────────────────────────────────────
#  CLI 入口
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 股票策略回測引擎")
    parser.add_argument("--stock",      default="2330",   help="股票代號（台股不加 .TW）")
    parser.add_argument("--name",       default="台積電", help="股票名稱（給 AI 看的）")
    parser.add_argument("--market",     default="台股",   choices=["台股", "美股"])
    parser.add_argument("--period",     default="6mo",    help="回測期間：3mo / 6mo / 1y / 2y")
    parser.add_argument("--capital",    type=int, default=1_000_000, help="初始資金（元）")
    parser.add_argument("--lookback",   type=int, default=17,        help="每次餵 AI 的歷史天數")
    parser.add_argument("--temp",       type=float, default=0.2,     help="AI temperature")
    parser.add_argument("--provider",   default="local",  choices=["local", "gemini"])
    parser.add_argument("--gemini-key", default=None,     dest="gemini_key", help="Gemini API Key")
    parser.add_argument("--sweep",      action="store_true", help="啟動參數組合掃描模式")

    args = parser.parse_args()

    if args.sweep:
        run_sweep(args)
    else:
        engine = BacktestEngine(
            stock_code=args.stock,
            market=args.market,
            period=args.period,
            initial_capital=args.capital,
            lookback=args.lookback,
            temperature=args.temp,
            provider=args.provider,
            gemini_key=args.gemini_key,
        )
        engine.run(stock_name=args.name)