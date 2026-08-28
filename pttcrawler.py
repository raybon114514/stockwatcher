"""
PTT 股版爬蟲 - 穩定版
策略：優先用 pttweb.cc API（JSON 回傳，最穩），失敗時 fallback 到直連 PTT
"""

import time
import random
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
#from typing import Optional


@dataclass
class Article:
    title: str
    url: str
    author: str
    date: str
    push_count: str  # 推文數，例如 "爆" / "XX" / 負數


class PTTStockCrawler:
    PTTWEB_API = "https://www.pttweb.cc/bbs/Stock/search"
    PTT_SEARCH  = "https://www.ptt.cc/bbs/Stock/search"
    PTT_INDEX   = "https://www.ptt.cc/bbs/Stock/index.html"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self._browser_headers())
        self.session.cookies.update({"over18": "1"})

        # 預熱：先訪問首頁，讓 PTT 給我們正確的 session cookie
        self._warmup()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def get_stock_discussions(self, stock_code, limit=15):
        articles = self._fetch_from_pttweb(stock_code, limit)  # 先試這個
        if not articles:
            print("[PTT] pttweb 無結果，切換到 ptt.cc...")
            articles = self._fetch_from_ptt(stock_code, limit)  # 再 fallback
        return articles

    # ------------------------------------------------------------------ #
    #  Strategy 1：pttweb.cc（JSON API，最穩定）
    # ------------------------------------------------------------------ #

    def _fetch_from_pttweb(self, stock_code: str, limit: int) -> list[Article]:
        url = f"{self.PTTWEB_API}?q={stock_code}"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select("div.b-ent")  # pttweb 的文章卡片 class

            results = []
            for item in items[:limit]:
                title_tag = item.select_one("div.title")
                meta_tag  = item.select_one("div.mata, div.meta")  # 不同版本 class 不同
                link_tag  = item.select_one("a")
                push_tag  = item.select_one("div.nrec span")

                if not title_tag or not link_tag:
                    continue

                results.append(Article(
                    title      = title_tag.get_text(strip=True),
                    url        = "https://www.pttweb.cc" + link_tag["href"],
                    author     = meta_tag.get_text(strip=True) if meta_tag else "",
                    date       = "",
                    push_count = push_tag.get_text(strip=True) if push_tag else "0",
                ))

            return results

        except Exception as e:
            print(f"[pttweb] 發生錯誤：{e}")
            return []

    # ------------------------------------------------------------------ #
    #  Strategy 2：直連 ptt.cc（HTML 解析，需預熱 cookie）
    # ------------------------------------------------------------------ #

    def _fetch_from_ptt(self, stock_code: str, limit: int) -> list[Article]:
        url = f"{self.PTT_SEARCH}?q={stock_code}"
        try:
            self._random_sleep()  # 避免觸發頻率限制
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("div.r-ent")

            results = []
            for row in rows[:limit]:
                title_tag  = row.select_one("div.title a")
                author_tag = row.select_one("div.meta div.author")
                date_tag   = row.select_one("div.meta div.date")
                push_tag   = row.select_one("div.nrec span")

                if not title_tag:
                    continue  # 已刪除文章

                results.append(Article(
                    title      = title_tag.get_text(strip=True),
                    url        = "https://www.ptt.cc" + title_tag["href"],
                    author     = author_tag.get_text(strip=True) if author_tag else "",
                    date       = date_tag.get_text(strip=True) if date_tag else "",
                    push_count = push_tag.get_text(strip=True) if push_tag else "0",
                ))

            return results

        except Exception as e:
            print(f"[ptt.cc] 發生錯誤：{e}")
            return []

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _warmup(self):
        """先訪問首頁，確保 over18 cookie 被接受、session 正常建立"""
        try:
            self.session.get(self.PTT_INDEX, timeout=8)
        except Exception:
            pass  # 預熱失敗不影響後續，只是可能略增被擋機率

    def _random_sleep(self, lo: float = 1.0, hi: float = 2.5):
        """隨機延遲，模擬真人瀏覽節奏，降低被限流的機率"""
        time.sleep(random.uniform(lo, hi))

    @staticmethod
    def _browser_headers() -> dict:
        return {
            "User-Agent"      : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36",
            "Accept"          : "text/html,application/xhtml+xml,application/xml;"
                                "q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language" : "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding" : "gzip, deflate, br",
            "Referer"         : "https://www.ptt.cc/bbs/Stock/index.html",
            "Connection"      : "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }


# ------------------------------------------------------------------ #
#  使用範例
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    crawler = PTTStockCrawler()

    stock = "2330"  # 台積電
    print(f"\n=== PTT 股版 [{stock}] 近期討論 ===\n")

    articles = crawler.get_stock_discussions(stock, limit=10)

    if not articles:
        print("查無結果，可能被擋或股票代號有誤。")
    else:
        for i, a in enumerate(articles, 1):
            push = f"[{a.push_count:>3}]" if a.push_count else "     "
            print(f"{i:>2}. {push} {a.title}")
            print(f"      作者：{a.author}  日期：{a.date}")
            print(f"      {a.url}\n")