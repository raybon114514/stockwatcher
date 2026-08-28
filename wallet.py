import json
import os
from datetime import datetime

class VirtualWallet:
    def __init__(self, filename="wallet.json", initial_balance=10000000):
        self.filename = filename
        self.state = self._load_state(initial_balance)

    def _load_state(self, initial_balance):
        if os.path.exists(self.filename):
            with open(self.filename, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"balance": initial_balance, "positions": {}, "trade_history": []}

    def _save_state(self):
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=4, ensure_ascii=False)

    # 💡 新增 market 參數，讓錢包知道現在是買哪國的股票
    def execute_trade(self, stock_id, stock_name, action, current_price, market="台股 (TWSE)", percentage=100):
        price = float(str(current_price).replace(',', ''))
        date_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        msg = ""
        
        # 防呆：確保百分比在 0 到 100 之間
        percentage = max(0, min(100, float(percentage)))

        if action == "買入":
            # 依據比例計算願意拿多少錢出來買
            budget = self.state["balance"] * (percentage / 100.0)
            
            if market == "台股 (TWSE)":
                # 台股買整張 (1000股為單位)，算出這筆預算最多能買幾「張」，再換回股數
                lots = int(budget // (price * 1000))
                shares = lots * 1000
            else:
                # 美股以 1 股為單位
                shares = int(budget // price)
                
            cost = price * shares

            if shares > 0 and self.state["balance"] >= cost:
                self.state["balance"] -= cost
                if stock_id not in self.state["positions"]:
                    self.state["positions"][stock_id] = {"name": stock_name, "shares": 0, "avg_cost": 0.0}
                
                pos = self.state["positions"][stock_id]
                total_cost = (pos["shares"] * pos["avg_cost"]) + cost
                pos["shares"] += shares
                pos["avg_cost"] = total_cost / pos["shares"]
                
                self.state["trade_history"].append({"date": date_str, "type": "BUY", "stock": stock_name, "price": price, "shares": shares})
                msg = f"💸 [買入成功] 動用 {percentage}% 資金，花費 {round(cost, 2)} 元買進 {shares} 股，剩餘本金: {round(self.state['balance'], 2)}"
            else:
                msg = f"⚠️ [資金不足] 欲動用 {percentage}% 資金，但不足以買入最低單位 (可能本金太少或股價太高)，目前餘額: {round(self.state['balance'], 2)}"

        elif action == "賣出":
            if stock_id in self.state["positions"] and self.state["positions"][stock_id]["shares"] > 0:
                current_shares = self.state["positions"][stock_id]["shares"]
                
                if market == "台股 (TWSE)":
                    # 台股賣出依據比例算出張數
                    lots_to_sell = int((current_shares / 1000) * (percentage / 100.0))
                    # 如果算出來是 0 張，但其實有庫存，就強制至少賣 1 張 (避免卡死)
                    if lots_to_sell == 0 and current_shares >= 1000:
                        lots_to_sell = 1
                    shares = lots_to_sell * 1000
                else:
                    shares = int(current_shares * (percentage / 100.0))
                    if shares == 0 and current_shares > 0:
                        shares = 1

                cost = price * shares
                
                if shares > 0:
                    profit = (price - self.state["positions"][stock_id]["avg_cost"]) * shares
                    self.state["balance"] += cost
                    self.state["positions"][stock_id]["shares"] -= shares
                    
                    if self.state["positions"][stock_id]["shares"] <= 0:
                        del self.state["positions"][stock_id]

                    self.state["trade_history"].append({"date": date_str, "type": "SELL", "stock": stock_name, "price": price, "shares": shares, "profit": profit})
                    msg = f"💰 [賣出成功] 出脫 {percentage}% 庫存 ({shares} 股)，獲得 {round(cost, 2)} 元，本次損益: {round(profit, 2)} 元，餘額: {round(self.state['balance'], 2)}"
                else:
                    msg = f"📉 [庫存異常] 計算後賣出股數為 0，無法執行賣出。"
            else:
                msg = f"📉 [無庫存] 手上沒有 {stock_name} 的股票，無法賣出。"
        
        else:
            msg = f"⏳ [持續觀望] {stock_name} 無動作，目前餘額: {round(self.state['balance'], 2)}"

        self._save_state()
        return msg