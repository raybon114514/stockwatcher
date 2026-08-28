import yfinance as yf
import pandas as pd
import json
import os
import time
import re
from datetime import datetime

# 引入你的最強大腦與手腳
from pttcrawler import PTTStockCrawler
from yahoo import YahooNewsCrawler
from analyzer import StockAI
from wallet import VirtualWallet

# ==========================================
# ⚙️ 系統設定與觀察清單
# ==========================================
WATCHLIST_TW = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科"
}

WATCHLIST_US = {
    "NVDA": "NVIDIA",
    "AMD": "AMD 超微",
    "MSFT": "微軟",
    "TSLA": "特斯拉"
}

AI_PROVIDER = "gemini"
GEMINI_API_KEY = ""  # ⚠️ 記得替換成你的 Key

MEMORY_FILE = "manager_memory_auto.json"

# ==========================================
# 🛠️ 核心運算函數
# ==========================================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_memory(memory_dict):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory_dict, f, ensure_ascii=False, indent=4)

def get_memory_decision(memory, stock_code):
    """從 memory 取出決策字串，相容新（dict）與舊（str）格式"""
    prev = memory.get(stock_code, None)
    if isinstance(prev, dict):
        return prev.get("decision", None)
    elif isinstance(prev, str):
        return prev
    return None

def get_stock_data(yf_code, market="台股 (TWSE)"):
    ticker = yf.Ticker(yf_code)
    hist = ticker.history(period="6mo")

    if hist.empty:
        return None, [], 0, 0

    hist['MA5']  = hist['Close'].rolling(window=5).mean()
    hist['MA20'] = hist['Close'].rolling(window=20).mean()

    delta = hist['Close'].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs    = gain / loss
    hist['RSI'] = 100 - (100 / (1 + rs))

    exp1 = hist['Close'].ewm(span=12, adjust=False).mean()
    exp2 = hist['Close'].ewm(span=26, adjust=False).mean()
    hist['MACD']        = exp1 - exp2
    hist['MACD_Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
    hist['MACD_Hist']   = hist['MACD'] - hist['MACD_Signal']

    recent_5 = hist.dropna().tail(5).reset_index()
    records  = []
    for _, row in recent_5.iterrows():
        volume = int(row['Volume'] / 1000) if market == "台股 (TWSE)" else int(row['Volume'])
        records.append({
            'Date':         row['Date'].strftime('%Y-%m-%d'),
            'ClosingPrice': round(row['Close'], 2),
            'TradeVolume':  volume,
            'MA5':          round(row['MA5'],  2),
            'MA20':         round(row['MA20'], 2),
            'RSI':          round(row['RSI'],  2),
            'MACD_Hist':    round(row['MACD_Hist'], 2)
        })

    recent_60   = hist.tail(60)
    period_high = round(recent_60['High'].max(), 2)
    period_low  = round(recent_60['Low'].min(),  2)

    return hist.dropna(), records, period_high, period_low

# ==========================================
# 🚀 主程式：每日自動盤後批次執行
# ==========================================
def run_daily_batch():
    today_date = datetime.now().strftime('%Y-%m-%d')
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 啟動 AI 投資委員會自動巡邏機制...\n")
    print("-" * 50)

    ai           = StockAI(provider=AI_PROVIDER, model_name="gemini-3-flash-preview", gemini_api_key=GEMINI_API_KEY)
    crawler_ptt  = PTTStockCrawler()
    crawler_news = YahooNewsCrawler()
    wallet       = VirtualWallet(filename="wallet_auto.json")
    memory       = load_memory()

    daily_summary  = []
    report_content = f"# 🏛️ AI 投資委員會每日會議記錄\n"
    report_content += f"**會議日期：** {today_date}\n\n---\n\n"

    targets = []
    for code, name in WATCHLIST_TW.items():
        targets.append(("台股 (TWSE)", code, name, f"{code}.TW"))
    for code, name in WATCHLIST_US.items():
        targets.append(("美股 (US)", code, name, code))

    for market, stock_code, stock_name, yf_code in targets:
        print(f"🔍 正在分析 [{market}] {stock_name} ({stock_code})...")

        full_df, history_records, period_high, period_low = get_stock_data(yf_code, market)
        if not history_records:
            print(f"  ❌ 無法取得 {stock_name} 的數據，跳過。\n")
            continue

        latest_price = history_records[-1]['ClosingPrice']

        # ── Agent A：技術分析 ──
        try:
            tech_report = ai.analyze_trend(stock_name, history_records, period_high, period_low)
        except Exception as e:
            print(f"  ⚠️ 技術分析失敗：{e}，跳過此標的。\n")
            continue

        # ── Agent B：PTT 情緒（僅台股）──
        if market == "台股 (TWSE)":
            try:
                ptt_articles = crawler_ptt.get_stock_discussions(stock_code, limit=10)
                ptt_titles   = [a.title for a in ptt_articles]
                ptt_report   = ai.analyze_sentiment(
                    stock_name, ptt_titles,
                    f"以下是 PTT 對 {stock_name} 的討論"
                )
            except Exception as e:
                ptt_report = f"PTT 爬蟲失敗：{e}"
        else:
            ptt_report = "無（美股不適用 PTT）"

        # ── Agent C：Yahoo 新聞 ──
        try:
            news_articles = crawler_news.get_stock_news(yf_code, limit=10)
            news_titles   = [a.title for a in news_articles]
            news_report   = ai.analyze_sentiment(
                stock_name, news_titles,
                "以下是 Yahoo 財經新聞"
            )
        except Exception as e:
            news_report = f"Yahoo 新聞失敗：{e}"

        # ── Agent D：總經理決策 ──
        prev_decision = get_memory_decision(memory, stock_code)  # 只傳決策字串
        try:
            final_decision = ai.manager_decision(
                stock_name, tech_report, ptt_report, news_report, prev_decision
            )
        except Exception as e:
            print(f"  ⚠️ 總經理決策失敗：{e}，跳過此標的。\n")
            continue

        # ── 解析決策與比例 ──
        decision_matches = re.findall(r'[\[【［]\s*(買入|賣出|觀望)\s*[\]】］]', final_decision)
        current_decision = decision_matches[-1] if decision_matches else "觀望"

        percent_matches = re.findall(r'比例[：:]\s*[\[【［]\s*(\d+)%\s*[\]】］]', final_decision)
        if percent_matches:
            trade_percent = int(percent_matches[-1])
        else:
            trade_percent = 20 if current_decision == "買入" else (100 if current_decision == "賣出" else 0)

        # ── 寫入記憶（新格式，含時間）──
        memory[stock_code] = {
            "decision": current_decision,
            "time":     datetime.now().strftime("%Y-%m-%d %H:%M")
        }

        # ── 執行交易 ──
        trade_msg = wallet.execute_trade(
            stock_id=yf_code,
            stock_name=stock_name,
            action=current_decision,
            current_price=latest_price,
            market=market,
            percentage=trade_percent
        )

        print(f"  🧠 總經理決策：{current_decision} ({trade_percent}%)")
        print(f"  {trade_msg}\n")

        daily_summary.append(
            f"{stock_name}: {current_decision} ({trade_msg.split(']')[1].strip() if ']' in trade_msg else trade_msg})"
        )

        # ── 寫入會議記錄 ──
        report_content += f"## 📊 {stock_name} ({stock_code})\n"
        report_content += f"- **當時收盤價：** {latest_price}\n"
        report_content += f"- **系統執行結果：** {trade_msg}\n\n"
        report_content += f"### 📈 Agent A (技術分析)\n{tech_report}\n\n"
        report_content += f"### 🔥 Agent B (PTT情緒)\n{ptt_report}\n\n"
        report_content += f"### 📰 Agent C (新聞基本面)\n{news_report}\n\n"
        report_content += f"### 🧠 Agent D (總經理最終決策)\n{final_decision}\n\n"
        report_content += "---\n\n"

        time.sleep(5)

    save_memory(memory)

    # ── 儲存每日報告 ──
    if not os.path.exists("reports"):
        os.makedirs("reports")

    report_filename = f"reports/DailyReport_{today_date}.md"
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(report_content)

    print("-" * 50)
    print("📋 今日巡邏總結：")
    for summary in daily_summary:
        print(f"  - {summary}")
    print(f"\n📁 完整決策歷程已儲存至：{report_filename}")
    print(f"💼 庫存總表請查看 wallet_auto.json")
    print("✅ 任務完成！")


if __name__ == "__main__":
    run_daily_batch()