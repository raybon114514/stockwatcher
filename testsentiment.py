from datetime import datetime
import os
from pttcrawler import PTTStockCrawler
from analyzer import StockAI

def main():
    crawler = PTTStockCrawler()
    ai = StockAI(model_name="local-model")
    
    stock_code = "2330"
    stock_name = "台積電"
    
    print(f"🕵️‍♂️ 正在潛入 PTT 股版搜集【{stock_name}】的最新情報...\n")
    
    # 抓取最新 30 篇討論
    titles = crawler.get_stock_discussions(stock_code, limit=30)
    
    if titles:
        # 1. 準備要寫入檔案的基礎字串
        report_content = f"=== PTT 股版情緒分析報告 ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===\n"
        report_content += f"分析標的：{stock_name} ({stock_code})\n\n"
        
        report_content += "【抓取到的熱門標題】\n"
        print("【抓取到的熱門標題】")
        for title in titles:
            line = f"- {title}"
            print(line)
            report_content += line + "\n" # 同時把標題加進要存檔的字串中
            
        print("-" * 40)
        report_content += "-" * 40 + "\n\n"
        
        # 2. 呼叫 AI 進行分析
        print("🧠 AI 正在解讀鄉民情緒中...\n")
        sentiment_report = ai.analyze_sentiment(stock_name, titles)
        print(sentiment_report)
        
        # 把 AI 的回答也加進去
        report_content += "【AI 情緒解讀】\n"
        report_content += sentiment_report + "\n"
        
        # 3. 執行存檔邏輯 (獨立存放在 sentiment_reports 資料夾)
        report_dir = "sentiment_reports"
        if not os.path.exists(report_dir):
            os.makedirs(report_dir)
            
        today_str = datetime.now().strftime('%Y-%m-%d')
        filename = os.path.join(report_dir, f"ptt_{stock_code}_{today_str}.txt")
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(report_content)
            
        print(f"\n✨ 情緒分析報告已完整存至 {filename}")
        
    else:
        print("找不到相關討論。")

if __name__ == "__main__":
    main()