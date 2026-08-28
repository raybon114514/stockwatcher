import yfinance as yf
from pttcrawler import PTTStockCrawler
from yahoo import YahooNewsCrawler
from analyzer import StockAI


def get_recent_5_days(stock_code):
    """抓取歷史資料並計算技術指標 (MA5, MA20, RSI)"""
    ticker = yf.Ticker(stock_code)
    hist = ticker.history(period="3mo")
    
    if hist.empty:
        return []

    hist['MA5'] = hist['Close'].rolling(window=5).mean()
    hist['MA20'] = hist['Close'].rolling(window=20).mean()
    # 🔥 新增：計算 5 日成交均量 (VMA5)
    hist['VMA5'] = hist['Volume'].rolling(window=5).mean()

    delta = hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    hist['RSI'] = 100 - (100 / (1 + rs))

    hist = hist.dropna().tail(5).reset_index()
    
    records = []
    for _, row in hist.iterrows():
        records.append({
            'Date': row['Date'].strftime('%Y-%m-%d'),
            'ClosingPrice': round(row['Close'], 2),
            'TradeVolume': int(row['Volume'] / 1000),
            'VMA5': int(row['VMA5'] / 1000),
            'MA5': round(row['MA5'], 2),
            'MA20': round(row['MA20'], 2),
            'RSI': round(row['RSI'], 2)
        })
    return records

def run_committee(stock_code="2330", stock_tw_code="2330.TW", stock_name="台積電"):
    print(f"🏛️ 啟動【{stock_name}】AI 投資委員會...\n")
    
    crawler_ptt  = PTTStockCrawler()
    crawler_news = YahooNewsCrawler()
    ai = StockAI(model_name="local-model")
    
    # ---------------------------------------------------------
    # Agent A：技術分析師
    # ---------------------------------------------------------
    print("📈 Agent A 正在解析近 5 日技術線型...")
    history_data = get_recent_5_days(stock_tw_code)
    tech_report = ai.analyze_trend(stock_name, history_data)
    print("✅ 技術面分析完成。\n")
    
    # ---------------------------------------------------------
    # Agent B：PTT 散戶情緒分析師
    # ---------------------------------------------------------
    print("🔥 Agent B 正在潛入 PTT 探查散戶情緒...")
    ptt_titles = crawler_ptt.get_stock_discussions(stock_code, limit=15)
    ptt_report = ai.analyze_sentiment(
        stock_name, ptt_titles,
        source_hint="以下是 PTT 股版的散戶討論標題，請分析散戶情緒與市場氛圍"
    )
    print("✅ PTT 情緒分析完成。\n")
    
    # ---------------------------------------------------------
    # Agent C：Yahoo 新聞媒體分析師
    # ---------------------------------------------------------
    print("📰 Agent C 正在掃描 Yahoo Finance 財經新聞...")
    news_articles = crawler_news.get_stock_news(stock_tw_code, limit=15)
    news_titles = [a.title for a in news_articles]
    news_report = ai.analyze_sentiment(
        stock_name, news_titles,
        source_hint="以下是 Yahoo Finance 的財經新聞標題，請分析媒體報導基調與機構觀點"
    )
    print("✅ 新聞媒體分析完成。\n")
    
    # ---------------------------------------------------------
    # Agent D：避險基金總經理（綜合三份報告做最終決策）
    # ---------------------------------------------------------
    print("🧠 Agent D 正在權衡三方情報，準備做出最終決策...")
    final_decision = ai.manager_decision(
        stock_name, tech_report,
        ptt_report=ptt_report,
        news_report=news_report
    )
    print("✅ 最終決策出爐。\n")
    
    # ---------------------------------------------------------
    # 輸出完整報告
    # ---------------------------------------------------------
    print("=" * 60)
    print(f"=== {stock_name} AI 投資委員會報告 ===")
    print("=" * 60)
    
    print("\n【技術分析 - Agent A】\n")
    print(tech_report)
    print("-" * 40)
    
    print("\n【PTT 散戶情緒 - Agent B】\n")
    print(ptt_report)
    print("-" * 40)
    
    print("\n【Yahoo 新聞媒體 - Agent C】\n")
    print(news_report)
    print("-" * 40)
    
    print("\n【總經理最終決策 - Agent D】\n")
    print(final_decision)
    print("=" * 60)

if __name__ == "__main__":
    run_committee(stock_code="2330", stock_tw_code="2330.TW", stock_name="台積電")