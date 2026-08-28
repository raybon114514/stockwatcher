from openai import OpenAI
import google.generativeai as genai
import requests
import subprocess
import time

class StockAI:
    def __init__(self, provider="local", model_name="gpt-oss-20b", gemini_api_key=None):
        self.provider = provider
        self.model_name = model_name
        self._server_ready = False  # ← 新增 flag
        # 根據選擇的引擎進行初始化
        if self.provider == "local":
            self.client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
        elif self.provider == "gemini":
            if not gemini_api_key:
                raise ValueError("使用 Gemini 引擎必須提供 API Key")
            genai.configure(api_key=gemini_api_key)
            # 預設使用速度快且極度聰明的 flash 模型
            self.gemini_model = genai.GenerativeModel(self.model_name)

    def _get_active_model(self, host="http://localhost:1234"):
        """自動抓取 LM Studio 目前載入的模型名稱"""
        try:
            response = requests.get(f"{host}/v1/models", timeout=2)
            models = response.json().get("data", [])
            if models:
                model_id = "openai/gpt-oss-20b"  # 預設 fallback
                print(f"🤖 自動偵測到模型：{model_id}")
                return model_id
        except Exception as e:
            print(f"⚠️ 無法取得模型清單：{e}")
        return None

    def _ensure_lm_studio_running(self, host="http://localhost:1234", timeout=30):
        """用 LM Studio CLI 確保 server 跟模型都就緒"""
        if self._server_ready:
            return True
        # 先確認是否已經在跑
        try:
            requests.get(f"{host}/v1/models", timeout=2)
            print("✅ LM Studio Server 已在運行")
            active_model = self._get_active_model(host)
            if active_model:
                self.model_name = active_model
            self._server_ready = True
            return True
        except requests.exceptions.ConnectionError:
            pass

        print("🚀 啟動 LM Studio Server...")
        try:
            # 啟動 server
            subprocess.Popen(
                ["lms", "server", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print("❌ 找不到 lms 指令，請確認 LM Studio CLI 有安裝並加入 PATH。")
            return False

        # 等 server 起來
        start = time.time()
        while time.time() - start < timeout:
            try:
                requests.get(f"{host}/v1/models", timeout=2)
                print("✅ Server 就緒，載入模型中...")
                break
            except requests.exceptions.ConnectionError:
                print("⏳ 等待 Server 啟動...")
                time.sleep(2)
        else:
            print("⚠️ Server 啟動超時")
            return False

        active_model = self._get_active_model(host)
        if active_model:
            print(f"✅ 已有模型在運行，略過載入步驟")
            self.model_name = active_model  # ← 自動更新
            self._server_ready = True
            return True
        if not self.model_name:
            print("⚠️ 沒有偵測到模型，且未指定 model_name，請手動載入模型。")
            return False
        # 載入指定模型
        try:
            result = subprocess.run(
                ["lms", "load", self.model_name],
                capture_output=True,
                text=True,
                timeout=60,  # 載入模型可能要一段時間
            )
            if result.returncode == 0:
                print(f"✅ 模型 {self.model_name} 載入成功")
                time.sleep(2)
                return True
            else:
                print(f"⚠️ 模型載入失敗: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            print("⚠️ 模型載入超時")
            return False
        
    def _call_ai(self, system_prompt, prompt, temperature):
        """共用的 AI 呼叫引擎，負責把任務派發給正確的大腦"""
        if self.provider == "local":
            self._ensure_lm_studio_running()
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                )
                return response.choices[0].message.content
            except Exception as e:
                self._server_ready = False
                return f"Local Model 呼叫失敗: {e}\n請確認 LM Studio 是否有開啟 Server。"
                
        elif self.provider == "gemini":
            try:
                # Gemini 的 Prompt 結構：將 System 角色與 User 問題合併給合
                full_prompt = f"【系統角色與指令】\n{system_prompt}\n\n【使用者提供之資料】\n{prompt}"
                response = self.gemini_model.generate_content(
                    full_prompt,
                    generation_config={"temperature": temperature}
                )
                return response.text
            except Exception as e:
                return f"Gemini API 呼叫失敗: {e}"

    # ---------------------------------------------------------
    # 以下的分析方法，全部改用 _call_ai 來發送請求
    # ---------------------------------------------------------
    def analyze_data(self, stock_data):
        """(舊版保留) 分析單日行情"""
        system_prompt = "你是一位專業的台股分析師。請務必使用繁體中文回答，語氣專業且客觀，直接給出分析，不要包含多餘的問候語。"
        
        prompt = f"""
        請分析以下今日個股行情並給予簡短評論：
        
        【個股資訊】
        - 股票：{stock_data.get('Name', '未知')} ({stock_data.get('Code', '未知')})
        - 收盤價：{stock_data.get('ClosingPrice', '未知')}
        - 漲跌：{stock_data.get('Change', '未知')}
        - 最高 / 最低：{stock_data.get('HighestPrice', '未知')} / {stock_data.get('LowestPrice', '未知')}
        - 成交量：{stock_data.get('TradeVolume', '未知')}
        
        【請依序回答】
        1. 今日走勢簡評：
        2. 價格區間觀察：
        3. 成交量分析：
        4. 投資建議：
        """
        
        # 魔法在這裡！直接把信交給 _call_ai 就結束了，超乾淨！
        return self._call_ai(system_prompt, prompt, temperature=0.3)
    
    def analyze_trend(self, stock_name, history_data, period_high=None, period_low=None):
        """傳入近五日資料、技術指標與三個月大局觀，讓 AI 做趨勢判斷"""
        
        history_text = ""
        for day in history_data:
            ma_rsi_info = f"MA5: {day.get('MA5', 'N/A')} | MA20: {day.get('MA20', 'N/A')} | RSI: {day.get('RSI', 'N/A')} | MACD柱狀圖: {day.get('MACD_Hist', 'N/A')}"
            # 🔥 明確把「成交量」與「5日均量」並列，讓 AI 可以直接比較
            history_text += f"- 日期: {day['Date']} | 收盤價: {day['ClosingPrice']} | 成交量: {day['TradeVolume']}張 (5日均量: {day.get('VMA5')}張) | {ma_rsi_info}\n"

        # 組裝大局觀提示詞
        big_picture_prompt = ""
        if period_high and period_low:
            big_picture_prompt = f"""
        【大局觀 (近三個月)】
        - 波段最高價：{period_high}
        - 波段最低價：{period_low}
        請判斷目前收盤價在這個區間的相對位階 (例如：創新高、高檔震盪、谷底反彈、破底危機等)。
            """

        system_prompt = "你是一位具備宏觀視野與微觀敏銳度的資深量化分析師。請務必使用繁體中文，並直接輸出分析結果，不需要開場白。"
        prompt = f"""
        請分析【{stock_name}】的技術面趨勢。
        {big_picture_prompt}
        
        【短線歷史數據 (近五日)】
        {history_text}
        
        【指標參考標準】
        - RSI > 70 代表超買，< 30 代表超賣。
        - MACD柱狀圖 > 0 代表多頭動能強勁；< 0 代表空頭動能發散。
        -  量價關係：若當日成交量 > 5日均量 (VMA5)，代表「出量」；上漲出量為多頭換手積極，下跌出量為賣壓沉重。若成交量 < 5日均量，代表「量縮觀望」。
        
        【請依照以下結構進行分析並以 Markdown 格式輸出】
        ### 1. 大局位階與均線走勢
        (結合近三個月最高/最低價，說明目前價格所處的相對位階，並判斷 MA5, MA20 的支撐或壓力狀況)
        
        ### 2. 量價與動能分析
        (請務必說明目前的上漲/下跌是否有成交量放大的支撐)
        (利用 RSI 與 MACD 柱狀圖，判斷目前上漲/下跌動能是否正在增強或衰退)
        
        ### 3. 短期觀測建議
        (給予精簡的技術面觀測重點，是否即將面臨波段前高壓力或前低支撐)
        
        ### 4. 投資建議
        (請簡短說明理由)
        """
        return self._call_ai(system_prompt, prompt, temperature=0.2)
        
    def analyze_sentiment(self, stock_name, news_titles, source_hint="請分析以下標題與市場氛圍"):
        if not news_titles:
            return "目前查無相關討論或新聞。"

        titles_text = "\n".join([f"- {t}" for t in news_titles])
        system_prompt = "你是一位精通行為金融學與市場心理學的分析師。請用繁體中文，根據提供的標題判斷市場情緒。"
        prompt = f"""
        {source_hint}：【{stock_name}】
        巴菲特曾說：「別人恐懼我貪婪，別人貪婪我恐懼」。請客觀評估目前的市場氛圍。
        
        【抓取到的標題】
        {titles_text}
        
        【請依照以下格式輸出並使用 Markdown】
        ### 1. 市場情緒總結
        ### 2. 恐懼與貪婪指數 (0-100) (0為極度恐懼，100為極度貪婪，50為中立。請務必只給出一個數字)
        ### 3. 關注焦點
        """
        return self._call_ai(system_prompt, prompt, temperature=0.4)
        
    def manager_decision(self, stock_name, technical_report, ptt_report="無", news_report="無", previous_decision=None):
        memory_prompt = ""
        if previous_decision:
            memory_prompt = f"【⚠️ 歷史決策紀錄】你上一次對這檔股票的決策是：[{previous_decision}]。若今天的決策發生翻盤，你必須在「綜合評估」中解釋原因。"

        system_prompt = "你是一位頂級避險基金的總經理。你需要綜合底下分析師的報告，做出冷靜的最終交易決策。請務必使用繁體中文。"
        prompt = f"""
        請綜合以下關於【{stock_name}】的報告，做出今天的最終交易決策。
        {memory_prompt}
        
        【Agent A：技術面分析報告】
        {technical_report}
        
        【Agent B：PTT 散戶情緒報告】
        {ptt_report}
        
        【Agent C：Yahoo 財經新聞報告】
        {news_report}
        
        【決策邏輯守則】
        1. 順勢突破 (積極進場)：當技術面 (Agent A) 呈現多頭排列、MACD 動能轉強，且新聞偏向正面或中性時，應果斷選擇 [買入] 順勢操作，不需等待極度恐慌才進場。
        2. 反轉訊號 (果斷停利/損)：當技術面出現高檔破線 (如跌破 MA5)、MACD 動能顯著轉弱，且散戶極度貪婪或出現「利多出盡」的新聞時，應立刻 [賣出] 以保全資金。
        3. 訊號衝突時的權重法則：不准輕易退縮為 [觀望]！當各方訊號衝突時，請以「技術面與動能 (Agent A)」為第一優先準則。只有在趨勢極度混沌、完全缺乏動能的橫盤死水期，才允許選擇 [觀望]。
        4. 部位管理：如果歷史決策已經是 [買入]，且目前趨勢尚未破敗，請繼續維持 [買入] (視為續抱或加碼)，直到出現明確的賣出訊號.
        
        【請依照以下格式輸出】
        ### 1. 綜合評估
        (說明你如何權衡這三份報告，以及你決定動用多少資金比例的理由)
        
        ### 2. 最終交易指示
        (請給出明確結論)
        
        【AI交易決策】：請務必在報告最後獨立輸出以下兩行標籤：
        決策：[買入]、[賣出] 或 [觀望]
        比例：[X%] (X為 10 到 100 的十的倍數數字。若為買入，代表使用「剩餘本金」的比例；若為賣出，代表賣出「現有庫存」的比例；觀望請填 [0%])
        """
        return self._call_ai(system_prompt, prompt, temperature=0.2)