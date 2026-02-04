import yfinance as yf
import pandas as pd
import requests
import os
import io
import matplotlib.pyplot as plt

# ==========================================
# 1. 設定區域
# ==========================================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
YIELD_THRESHOLD = 7.0  # 設定為 5% (通常新加坡高息股在 5-8% 之間)

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
# 3. 主程式
# ==========================================
def main():
    print(f"🚀 啟動批量掃描 ({len(tickers_formatted)} 檔)...")
    
    try:
        # 下載數據
        data = yf.download(tickers_formatted, period="1y", group_by='ticker', progress=False)
        if data.empty:
            print("❌ Yahoo 回傳空資料")
            return
    except Exception as e:
        print(f"❌ 下載錯誤: {e}")
        return

    results = []
    
    for ticker_raw in sg_tickers_raw:
        ticker_si = f"{ticker_raw}.SI"
        
        try:
            if ticker_si not in data.columns.levels[0]: continue
            df_stock = data[ticker_si]
            if df_stock.empty: continue

            # 取得最新價格
            price = df_stock['Close'].iloc[-1]
            if pd.isna(price): continue

            # 抓取殖利率 (容錯處理)
            try:
                t_obj = yf.Ticker(ticker_si)
                # 這裡最關鍵：有的回傳 0.05，有的回傳 5.0
                raw_yield = t_obj.info.get('dividendYield', 0)
                
                # --- [修正邏輯] ---
                if raw_yield is None:
                    final_yield = 0.0
                elif raw_yield > 0.3: 
                    # 如果大於 0.3 (30%)，假設它已經是百分比 (例如 4.83)
                    final_yield = float(raw_yield)
                else:
                    # 如果小於 0.3，假設它是小數 (例如 0.0483)，需乘 100
                    final_yield = float(raw_yield) * 100
                
                # 二次檢查：如果算出來超過 100%，肯定是錯的 (除非是異常股)，強制修正
                if final_yield > 100:
                    final_yield = final_yield / 100
                # ------------------

            except:
                final_yield = 0.0

            if final_yield >= YIELD_THRESHOLD:
                results.append({
                    "Code": ticker_raw,
                    "Name": ticker_raw,
                    "Price": round(price, 2),
                    "Yield": round(final_yield, 2),
                    "History": df_stock
                })
                
        except Exception:
            continue

    # 發送通知
    if results:
        df_res = pd.DataFrame(results).sort_values(by="Yield", ascending=False)
        
        # 1. 發送總表
        msg = f"**📊 SGX 高殖利率快報 (修正版)**\n門檻: > {YIELD_THRESHOLD}%\n```ini\n Code   Yield    Price\n"
        msg += "-"*25 + "\n"
        for _, row in df_res.iterrows():
             msg += f"{row['Code']:<5} {row['Yield']:>5}%   ${row['Price']:<7}\n"
        msg += "```"
        send_discord_text(msg)
        
        # 2. 發送個別圖表 (這裡為了避免洗版，只發前 5 名，您可以自行調整)
        top_picks = df_res.head(10) 
        for _, row in top_picks.iterrows():
            chart_buf = generate_chart_buffer(row['History'], row['Code'])
            if chart_buf:
                send_discord_with_chart(row['Code'], row, chart_buf)
    else:
        print("今日無符合條件個股。")

if __name__ == "__main__":
    main()
