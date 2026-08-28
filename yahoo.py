"""
Yahoo Finance 新聞爬蟲 (yfinance API 穩定版)
直接呼叫 yfinance 底層 API，免去 HTML 解析被擋或改版的困擾。
"""

import yfinance as yf
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Article:
    title: str
    url: str
    author: str
    date: str
    push_count: str

class YahooNewsCrawler:
    def __init__(self):
        # 使用 yfinance 不需要複雜的 Headers 與 Session 偽裝
        pass

    def get_stock_news(self, stock_code: str, limit: int = 15) -> list[Article]:
        """
        使用 yfinance 內建的新聞 API 抓取。
        台股代號請帶 .TW 後綴，例如 "2330.TW"。美股直接填代號，例如 "NVDA"。
        """
        try:
            ticker = yf.Ticker(stock_code)
            # 呼叫 yfinance 內建的 news 屬性，直接取得 JSON 格式的新聞陣列
            news_list = ticker.news
            
            if not news_list:
                return []

            results = []
            for item in news_list[:limit]:
                # 🛑 防彈衣 1：如果這筆資料連字典都不是，直接跳過
                if not isinstance(item, dict):
                    continue
                
                # 🛑 防彈衣 2：安全地抓取 content，如果它是 None（例如廣告），就退回用 item 本身
                content = item.get("content")
                if not isinstance(content, dict):
                    content = item
                
                # 1. 解析標題 (雙重保險：如果真的找不到標題，就當作廢文跳過)
                title = content.get("title") or item.get("title")
                if not title:
                    continue
                
                # 2. 解析網址
                url_dict = content.get("clickThroughUrl")
                if not isinstance(url_dict, dict):
                    url_dict = {}
                url = url_dict.get("url") or content.get("link") or item.get("link") or ""
                
                # 3. 解析來源
                provider = content.get("provider")
                if not isinstance(provider, dict):
                    provider = {}
                author = provider.get("displayName") or content.get("publisher") or item.get("publisher") or "Yahoo"
                
                # 4. 解析時間
                pub_time = content.get("pubDate") or item.get("providerPublishTime")
                if isinstance(pub_time, str):
                    date_str = pub_time[:16].replace("T", " ")
                elif isinstance(pub_time, (int, float)):
                    date_str = datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d %H:%M')
                else:
                    date_str = "未知時間"

                # 組裝完成，送入陣列
                results.append(Article(
                    title=title,
                    url=url,
                    author=author,
                    date=date_str,
                    push_count="0"
                ))
            return results



        except Exception as e:
            print(f"Yahoo 新聞抓取失敗: {e}")
            return []

# ------------------------------------------------------------------ #
#  使用範例
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    crawler = YahooNewsCrawler()
    
    # 測試台股 (記得加 .TW)
    stock = "2330.TW" 
    print(f"\n=== Yahoo Finance 新聞 [{stock}] ===\n")
    
    articles = crawler.get_stock_news(stock, limit=5)
    
    if not articles:
        print("查無新聞，請確認代碼。")
    else:
        for i, a in enumerate(articles, 1):
            print(f"{i:>2}. {a.title}")
            print(f"      來源：{a.author}  時間：{a.date}")
            print(f"      {a.url}\n")
