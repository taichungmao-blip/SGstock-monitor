import yfinance as yf
import pandas as pd
import requests
import os
import datetime
import io
import matplotlib.pyplot as plt

# ==========================================
# 1. 設定與清單
# ==========================================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
YIELD_THRESHOLD = 6.0 

# 設定 Matplotlib 後端 (避免在伺服器跳出視窗)
plt.switch_backend('Agg')

# 新加坡 87 檔活躍股清單
sg_tickers_raw = [
    "D05", "O39", "U11", "A17U", "AJBU", "M44U", "ME8U", "BUOU", "O5RU", "AXB", 
    "J91U", "M1GU", "C38U", "N2IU", "T82U", "J69U", "K71U", "AU8U", "HMN", "J85", 
    "UD2", "JYEU", "TS0U", "C2PU", "H19", "Q5T", "ACV", "XZL", "BTOU", "AW9U", 
    "DHLU", "Z74", "A7RU", "CJLU", "S58", "S68", "U96", "BS6", "S63", "S51", 
    "C6L", "BN4", "C09", "U14", "F99", "C07", "H78", "J36", "E8Z", "9CI", 
    "502", "T39", "BQC", "Y92", "G13", "F34", "V03", "OV8", "EB5", "P8Z", 
    "579", "Q01", "AWX", "558", "E28", "CC3", "BTE", "5WF", "M04", "KUH", 
    "1D0", "S61", "H12", "D01", "O08", "40V", "S20", "539", "UV1", "BKZ", 
    "BEI", "F1E", "AFC", "P40U", "PJX", "RE4", "5GID"
]

# 加上 .SI 後綴
tickers_formatted = [f"{t}.SI" for t in sg_tickers_raw]

# ==========================================
# 2. Discord 發送功能
# ==========================================
def send_discord_text(msg_content):
    if not DISCORD_WEBHOOK_URL: 
        print("❌ 未設定 Webhook URL")
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg_content})
    except Exception as e:
        print(f"文字發送失敗: {e}")

def send_discord_with_chart(ticker_raw, row_data, chart_buffer):
    if not DISCORD_WEBHOOK_URL or not chart_buffer: return
    filename = f"{ticker_raw}_chart.png"
    
    embed = {
        "title": f"📈 {ticker_raw} - {row_data['Name']}",
        "color": 65280, # Green
        "fields": [
            {"name": "Dividend Yield", "value": f"**{row_data['Yield']}%**", "inline": True},
            {"name": "Current Price", "value": f"S${row_data['Price']}", "inline": True}
        ],
        "image": {"url": f"attachment://{filename}"}
    }
    
    try:
        import json
        files = {'file': (filename, chart_buffer, 'image/png')}
        requests.post(DISCORD_WEBHOOK_URL, data={'payload_json': json.dumps({"embeds": [embed]})}, files=files)
    except Exception as e:
        print(f"圖表發送失敗: {e}")

def generate_chart_buffer(hist_data, ticker_raw):
    """從已下載的歷史資料繪圖"""
    try:
        df = hist_data
        if df.empty: return None

        plt.figure(figsize=(8, 4))
        plt.plot(df.index, df['Close'], label='Close', color='#00a8ff')
        plt.title(f"{ticker_raw} - 1 Year Trend")
        plt.grid(True, linestyle='--', alpha=0.3)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        return buf
    except:
        return None

# ==========================================
# 3. 主程式 (改用 Batch Download)
# ==========================================
def main():
    print(f"🚀 啟動批量掃描 ({len(tickers_formatted)} 檔)...")
    
    # [關鍵修改] 使用 yf.download 批量下載 (自動處理重試與多線程)
    # group_by='ticker' 讓資料結構更好處理
    try:
        print("正在向 Yahoo 請求數據 (這可能需要 10-20 秒)...")
        data = yf.download(tickers_formatted, period="1y", group_by='ticker', progress=False)
        
        if data.empty:
            print("❌ Yahoo 回傳空資料 (可能被 IP 封鎖或網路問題)。")
            # 嘗試發送一個錯誤通知到 Discord，讓你知道程式掛了
            send_discord_text("⚠️ **警報**：GitHub Actions 無法抓取 Yahoo 數據，可能 IP 被鎖。")
            return
            
    except Exception as e:
        print(f"❌ 下載過程發生嚴重錯誤: {e}")
        return

    print("數據下載完成，開始分析殖利率...")
    results = []
    
    # 遍歷所有下載到的股票
    for ticker_raw in sg_tickers_raw:
        ticker_si = f"{ticker_raw}.SI"
        
        try:
            # 從批量資料中提取該股資料
            # 注意：如果某檔股票下載失敗，這裡會報錯，我們用 try 接住
            if ticker_si not in data.columns.levels[0]:
                continue
                
            df_stock = data[ticker_si]
            if df_stock.empty: continue

            # 取得最新價格
            price = df_stock['Close'].iloc[-1]
            if pd.isna(price): continue

            # 抓取殖利率 (這是唯一需要單獨 call 的地方，但我們加強容錯)
            # 為了避免這裡卡住，我們只對「有價格」的股票做檢查
            try:
                t_obj = yf.Ticker(ticker_si)
                # 這裡可能比較慢，但因為只跑一次 info，相對穩定
                # 若 info 抓不到，預設給 0
                div_yield = t_obj.info.get('dividendYield', 0)
            except:
                div_yield = 0

            if div_yield and div_yield > 0:
                results.append({
                    "Code": ticker_raw,
                    "Name": ticker_raw, # 批量下載較難拿到中文名，先用代碼代替
                    "Price": round(price, 2),
                    "Yield": round(div_yield * 100, 2),
                    "History": df_stock # 暫存歷史資料給繪圖用
                })
                
        except Exception as e:
            continue # 跳過這檔壞掉的

    # 轉為 DataFrame
    if not results:
        print("⚠️ 分析後無資料 (所有股票皆無殖利率資訊 或 抓取失敗)")
        return

    df_res = pd.DataFrame(results)
    
    # 篩選
    high_yield = df_res[df_res['Yield'] >= YIELD_THRESHOLD].sort_values(by="Yield", ascending=False)
    
    print(f"篩選結果：共發現 {len(high_yield)} 檔符合條件")

    # 發送通知
    if not high_yield.empty:
        # 1. 發送總表
        msg = f"**📊 SGX 高殖利率快報**\n門檻: > {YIELD_THRESHOLD}%\n```ini\n Code   Yield    Price\n"
        msg += "-"*25 + "\n"
        for _, row in high_yield.iterrows():
             msg += f"{row['Code']:<5} {row['Yield']:>5}%   ${row['Price']:<7}\n"
        msg += "```"
        send_discord_text(msg)
        
        # 2. 發送個別圖表
        for _, row in high_yield.iterrows():
            chart_buf = generate_chart_buffer(row['History'], row['Code'])
            if chart_buf:
                send_discord_with_chart(row['Code'], row, chart_buf)
    else:
        print("今日無符合條件個股。")

if __name__ == "__main__":
    main()
