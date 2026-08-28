from datetime import datetime
import streamlit as st
import yfinance as yf
import pandas as pd
from pttcrawler import PTTStockCrawler
import plotly.express as px
from yahoo import YahooNewsCrawler  
from analyzer import StockAI
import plotly.graph_objects as go
import os
import re
import json
from wallet import VirtualWallet
st.set_page_config(page_title="AI 投資委員會觀測站", page_icon="📈", layout="wide")

st.title("🏛️ AI 投資委員會觀測站")
st.markdown("結合 **技術線型 (Agent A)**、**PTT 散戶情緒 (Agent B)**、**Yahoo 新聞 (Agent C)** 的多代理人決策系統。")

with st.sidebar:
    st.header("⚙️ 參數設定")
    market = st.radio("選擇市場", ["台股 (TWSE)", "美股 (US)"])

    st.markdown("---")
    st.header("🧠 AI 引擎設定")
    ai_engine = st.radio("選擇運算大腦", ["Local Model (本地免費)", "Gemini API (雲端極速)"])
    
    gemini_key = ""
    gemini_model_choice = "gemini-3-flash-preview" # 預設值
    
    if ai_engine == "Gemini API (雲端極速)":
        gemini_key = st.text_input("輸入 Gemini API Key", type="password")
        st.caption("[點此獲取免費 API Key](https://aistudio.google.com/app/apikey)")
        
        # 💡 新增：讓你可以自己挑選要用哪一個 Gemini 模型
        gemini_model_choice = st.selectbox(
            "選擇 Gemini 模型版本", 
            ["gemini-3-flash-preview (推薦：極速分析)", 
             "gemini-3.1-pro-preview (推薦：深度推理)"]
        )
        # 把選項字串切乾淨，只留下模型代號
        gemini_model_choice = gemini_model_choice.split(" ")[0]
    tw_stocks = {
        "台積電 (2330)": "2330",
        "鴻海 (2317)": "2317",
        "聯發科 (2454)": "2454",
        "廣達 (2382)": "2382",
        "富邦金 (2881)": "2881",
        "長榮 (2603)": "2603"
    }
    
    us_stocks = {
        "NVIDIA 輝達 (NVDA)": "NVDA",
        "Apple 蘋果 (AAPL)": "AAPL",
        "Microsoft 微軟 (MSFT)": "MSFT",
        "Tesla 特斯拉 (TSLA)": "TSLA",
        "AMD 超微 (AMD)": "AMD",
        "Google (GOOGL)": "GOOGL"
    }

    if market == "台股 (TWSE)":
        selected_option = st.selectbox("請選擇觀測標的", ["（自行輸入）"] + list(tw_stocks.keys()))
        if selected_option == "（自行輸入）":
            custom_code = st.text_input("輸入股票代號", placeholder="例如：2881")
            stock_code  = custom_code.strip()
            stock_name  = stock_code  # 先用代號當名稱，抓到資料後再更新
        else:
            stock_code  = tw_stocks[selected_option]
            stock_name  = selected_option.split(" ")[0]

    else:
        selected_option = st.selectbox("請選擇觀測標的", ["（自行輸入）"] + list(us_stocks.keys()))
        if selected_option == "（自行輸入）":
            custom_code = st.text_input("輸入股票代號", placeholder="例如：META")
            stock_code  = custom_code.strip().upper()
            stock_name  = stock_code
        else:
            stock_code  = us_stocks[selected_option]
            stock_name  = selected_option.split(" ")[0]

    st.markdown("---")
    run_btn = st.button("🚀 召開投資委員會", type="primary",width='stretch')

MEMORY_FILE = "manager_memory.json"

def load_memory():

    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_memory(memory_dict):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory_dict, f, ensure_ascii=False, indent=4)


def get_stock_data(yf_code, market):
    ticker = yf.Ticker(yf_code)
    # 嘗試抓正式名稱
    try:
        real_name = ticker.info.get("shortName") or ticker.info.get("longName")
    except Exception:
        real_name = None
    # MACD 需要較長的天數來計算 EMA26，所以我們把歷史資料拉長到 6 個月確保準確度
    hist = ticker.history(period="6mo") 
    
    if hist.empty:
        return None, [], None, None, None

    # 1. 計算 MA5, MA20
    hist['MA5'] = hist['Close'].rolling(window=5).mean()
    hist['MA20'] = hist['Close'].rolling(window=20).mean()
    
    # 2. 計算 RSI (14天)
    delta = hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    hist['RSI'] = 100 - (100 / (1 + rs))

    # 3. 🔥 新增：計算 MACD
    # EMA12 和 EMA26
    exp1 = hist['Close'].ewm(span=12, adjust=False).mean()
    exp2 = hist['Close'].ewm(span=26, adjust=False).mean()
    hist['MACD'] = exp1 - exp2
    # MACD Signal (9天)
    hist['MACD_Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
    # MACD 柱狀圖 (OSC) = MACD - Signal
    hist['MACD_Hist'] = hist['MACD'] - hist['MACD_Signal']

    # 4. 只取最後 17 天給 AI
    recent_17 = hist.dropna().tail(17).reset_index()
    records = []
    for _, row in recent_17.iterrows():
        records.append({
            'Date': row['Date'].strftime('%Y-%m-%d'),
            'ClosingPrice': round(row['Close'], 2),
            'TradeVolume': int(row['Volume'] / 1000) if market == "台股 (TWSE)" else int(row['Volume']),
            'MA5': round(row['MA5'], 2),
            'MA20': round(row['MA20'], 2),
            'RSI': round(row['RSI'], 2),
            'MACD_Hist': round(row['MACD_Hist'], 2) # 🔥 把 MACD 柱狀圖數值加進去
        })
    # 💡 算出「上帝視角」大局觀 (抓近 90 個交易日，約 3 個月)
    recent_60 = hist.tail(90)
    period_high = round(recent_60['High'].max(), 2)
    period_low = round(recent_60['Low'].min(), 2)
    return hist.dropna(), records, period_high, period_low, real_name

if run_btn:

    if not stock_code:
        st.error("⚠️ 請輸入股票代號")
        st.stop()    
    # 🛑 安全防護：如果選了 Gemini 卻沒填 Key，直接中斷並警告
    if ai_engine == "Gemini API (雲端極速)" and not gemini_key:
        st.error("⚠️ 請在左側輸入 Gemini API Key 才能啟動雲端引擎！")
        st.stop() # 停止執行後續程式碼
    yf_code = f"{stock_code}.TW" if market == "台股 (TWSE)" else stock_code
    
    with st.spinner("🔄 正在下載歷史數據與計算技術指標..."):
        full_df, history_records, period_high, period_low, real_name = get_stock_data(yf_code, market)
        if real_name:
            stock_name = real_name  # 用正式名稱蓋掉代號
    if full_df is None:
        st.error(f"❌ 找不到代碼 {yf_code} 的歷史資料，請確認代碼是否正確。")
    else:
        st.subheader(f"📊 {stock_name} ({yf_code}) 近六個月 K 線走勢")
        
        # 💡 專業細節：判斷市場，設定正確的漲跌顏色
        if market == "台股 (TWSE)":
            color_up = '#ff3333'   # 台股紅漲
            color_down = '#00b300' # 台股綠跌
        else:
            color_up = '#00b300'   # 美股綠漲
            color_down = '#ff3333' # 美股紅跌
            
        # 建立 Plotly 畫布
        fig = go.Figure()

        # 1. 鋪上底層：K 線圖 (Candlestick)
        fig.add_trace(go.Candlestick(
            x=full_df.index,
            open=full_df['Open'],
            high=full_df['High'],
            low=full_df['Low'],
            close=full_df['Close'],
            name='K線',
            increasing_line_color=color_up,
            decreasing_line_color=color_down
        ))

        # 2. 疊加上層：MA5 (5日均線)
        fig.add_trace(go.Scatter(
            x=full_df.index,
            y=full_df['MA5'],
            mode='lines',
            name='MA5 (周線)',
            line=dict(color='orange', width=1.5)
        ))

        # 3. 疊加上層：MA20 (20日均線)
        fig.add_trace(go.Scatter(
            x=full_df.index,
            y=full_df['MA20'],
            mode='lines',
            name='MA20 (月線)',
            line=dict(color='blue', width=1.5)
        ))

        # 版面微調：隱藏底部佔空間的拉桿，讓圖表更簡潔
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            margin=dict(l=0, r=0, t=10, b=0),
            hovermode="x unified"
        )

        # 渲染圖表
        st.plotly_chart(fig, use_container_width=True)
        
        # 根據選擇動態啟動大腦
        provider_choice = "gemini" if "Gemini" in ai_engine else "local"
        # 這裡多傳一個 model_name 參數進去
        local_model_name = None  # 讓 analyzer.py 自動偵測或用預設值
        if ai_engine == "Gemini API (雲端極速)":
            ai = StockAI(provider="gemini", model_name=gemini_model_choice, gemini_api_key=gemini_key)
        else:
            ai = StockAI(provider="local")  # model_name 用 __init__ 裡的預設值

        crawler_ptt  = PTTStockCrawler()
        crawler_news = YahooNewsCrawler()
        
        st.markdown("---")
        
        # BUG FIX 5：改成四欄，加入 Yahoo 新聞 Agent C
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.subheader("📈 Agent A: 技術分析")
            with st.spinner("分析線型中..."):
                # 把大局觀的最高/最低價一起傳給 Agent A
                tech_report = ai.analyze_trend(stock_name, history_records, period_high, period_low)
                st.info(tech_report)

        with col2:
            st.subheader("🔥 Agent B: PTT 情緒")
            with st.spinner("潛入 PTT 中..."):
                try:
                    ptt_articles = crawler_ptt.get_stock_discussions(stock_code, limit=15)
                    ptt_titles = [a.title for a in ptt_articles]
                    ptt_report = ai.analyze_sentiment(
                        stock_name, ptt_titles,
                        source_hint="以下是 PTT 股版的散戶討論標題，請分析散戶情緒與市場氛圍"
                    )
                except Exception as e:
                    ptt_articles = []
                    ptt_report = f"⚠️ PTT 爬蟲發生錯誤：{e}"

                st.warning(ptt_report)
                if ptt_articles:
                    with st.expander("🔗 檢視 PTT 原始討論串"):
                        for a in ptt_articles:
                            st.markdown(f"- [{a.title}]({a.url})")

        with col3:
            st.subheader("📰 Agent C: Yahoo 新聞")
            with st.spinner("掃描財經新聞中..."):
                try:
                    news_articles = crawler_news.get_stock_news(yf_code, limit=15)
                    news_titles = [a.title for a in news_articles]
                    news_report = ai.analyze_sentiment(
                        stock_name, news_titles,
                        source_hint="以下是 Yahoo Finance 的財經新聞標題，請分析媒體報導基調與機構觀點"
                    )
                except Exception as e:
                    news_articles = []
                    news_report = f"⚠️ Yahoo 新聞爬蟲發生錯誤：{e}"

                st.warning(news_report)
                if news_articles:
                    with st.expander("🔗 檢視 Yahoo 原始新聞"):
                        for a in news_articles:
                            st.markdown(f"- [{a.title}]({a.url})")

        with col4:
            st.subheader("🧠 Agent D: 總經理決策")
            with st.spinner("權衡決策與回想記憶中..."):
                # 1. 讀取總經理昨天的記憶
                memory = load_memory()
                prev = memory.get(stock_code, None)
                if isinstance(prev, dict):
                    prev_decision = prev["decision"]
                    prev_time     = prev["time"]
                elif isinstance(prev, str):
                    prev_decision = prev
                    prev_time     = "未知"
                else:
                    prev_decision = None
                    prev_time     = None
                if prev_decision:
                    st.caption(f"💭 **總經理的記憶**：上次對此標的決策為 **[{prev_decision}]**，時間：{prev_time}")
                else:
                    st.caption("💭 **總經理的記憶**：這是一檔全新的標的，沒有歷史包袱。")

                # 2. 呼叫大腦，把前次決策一起傳進去
                final_decision = ai.manager_decision(
                    stock_name, tech_report,
                    ptt_report=ptt_report,
                    news_report=news_report,
                    previous_decision=prev_decision
                )

                #3. 顯示決策報告
                st.info(final_decision)
                
                # 4. 捕捉最終決策 (終極防呆版)
                # 使用 re.findall 找出所有符合的標籤，並支援各種變形的括號與空白
                matches = re.findall(r'[\[【［]\s*(買入|賣出|觀望)\s*[\]】］]', final_decision)

                # 補抓比例
                ratio_matches = re.findall(r'比例：[\[【［]\s*(\d+)%\s*[\]】］]', final_decision)
                trade_percentage = int(ratio_matches[-1]) if ratio_matches else 100
                
                if matches:
                    current_decision = matches[-1]
                else:
                    ending_text = final_decision[-100:]
                    if "賣出" in ending_text:
                        current_decision = "賣出"
                    elif "買入" in ending_text and "不" not in ending_text:
                        current_decision = "買入"
                    else:
                        current_decision = "觀望"

                # 寫入大腦記憶庫
                memory[stock_code] = {
                    "decision": current_decision,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                save_memory(memory)
                
                # 💡 新增：啟動虛擬錢包並執行交易
                wallet = VirtualWallet()
                
                # 從 Agent A 的數據中，抓取最後一天的收盤價作為交易價格
                latest_price = history_records[-1]['ClosingPrice']
                
                # 呼叫你寫的錢包引擎！
                trade_msg = wallet.execute_trade(
                    stock_id=yf_code,
                    stock_name=stock_name,
                    action=current_decision,
                    current_price=latest_price,
                    market=market,
                    percentage=trade_percentage  # ← 補上交易比例參數
                )
                
                # 顯示 UI 標籤與 💰 交易結果
                if current_decision == "買入":
                    st.success("✅ 最終決策：買入")
                elif current_decision == "賣出":
                    st.error("🚨 最終決策：賣出")
                else:
                    st.warning("⏸️ 最終決策：觀望")
                    
                # 把錢包回傳的扣款/入帳明細，印在決策卡片最下方
                st.info(trade_msg)