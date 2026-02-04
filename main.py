import yfinance as yf
import pandas as pd
import concurrent.futures
import requests
import os
import datetime
import io
import matplotlib.pyplot as plt

# ==========================================
# 1. 設定區域
# ==========================================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
YIELD_THRESHOLD = 6.0
MAX_WORKERS = 10

# 設定 matplotlib 不跳出視窗 (適合伺服器環境)
plt.switch_backend('Agg')

# 新加坡股市活躍 100 檔清單
sg_tickers_raw = [
    "D05", "O39", "U11", 
    "A17U", "AJBU", "M44U", "ME8U", "BUOU", "O5RU", "AXB", "J91U", "M1GU",
    "C38U", "N2IU", "T82U", "J69U", "K71U", "AU8U", "HMN", "J85", "UD2", "JYEU", "TS0U",
    "C2PU", "H19", "Q5T", "ACV", "XZL", "BTOU", "AW9U", "DHLU", 
    "Z74", "A7RU", "CJLU", "S58", "S68", "U96", "BS6", "S63", "S51", "C6L", "BN4",
    "C09", "U14", "F99", "C07", "H78", "J36", "E8Z", "9CI", "502", "T39", "BQC", 
    "Y92", "G13", "F34", "V03", "OV8", "EB5", "P8Z", "579", "Q01", 
    "AWX", "558", "E28", "CC3", "BTE", "5WF", "M04", "KUH", "1D0", 
    "S61", "H12", "D01", "O08", "40V", "S20", "539", "UV1", "BKZ", 
    "BEI", "F1E", "AFC", "P40U", "PJX", "RE4", "5GID"
]

# ==========================================
# 2. 功能函式：繪圖與通知
# ==========================================

def generate_chart_buffer(ticker_raw):
    """
    抓取一年歷史數據，繪製走勢圖，並儲存到記憶體 Buffer 中回傳。
    """
    ticker = f"{ticker_raw}.SI"
    try:
        print(f"正在繪製 {ticker_raw} 走勢圖...")
        # 抓取一年歷史數據
        df = yf.download(ticker, period="1y", progress=False)
        if df.empty:
            return None

        # 繪圖設定
        plt.figure(figsize=(8, 4)) # 設定圖片大小
        plt.plot(df.index, df['Close'], label='Close Price', color='#00a8ff', linewidth=1.5)
        
        # 圖表美化
        plt.title(f"{ticker_raw} - 1 Year Trend ({df.index[-1].strftime('%Y-%m-%d')})")
        plt.grid(True, which='both', linestyle='--', linewidth=0.5, color='gray', alpha=0.3)
        plt.ylabel("Price (SGD)")
        plt.xticks(rotation=30)
        plt.tight_layout()

        # 將圖片存入記憶體 Buffer (BytesIO)
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0) # 將指針重置到開頭
        plt.close() # 關閉圖表釋放記憶體
        return buf

    except Exception as e:
        print(f"繪圖失敗 {ticker_raw}: {e}")
        return None

def send_discord_text(msg_content):
    """發送純文字訊息 (用於總表)"""
    if not DISCORD_WEBHOOK_URL: return
    data = {"username": "SGX Yield Bot", "content": msg_content}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
    except Exception as e:
        print(f"文字發送異常: {e}")

def send_discord_with_chart(ticker_raw, row_data, chart_buffer):
    """
    發送帶有圖片附件的 Discord 訊息。
    使用 multipart/form-data 格式上傳圖片。
    """
    if not DISCORD_WEBHOOK_URL or not chart_buffer: return
    
    filename = f"{ticker_raw}_chart.png"
    
    # 準備 Embed 內容
    embed = {
        "title": f"📈 {ticker_raw} - {row_data['Name']}",
        "color": 65280, # 綠色
        "fields": [
            {"name": "Dividend Yield", "value": f"**{row_data['Yield']}%**", "inline": True},
            {"name": "Current Price", "value": f"S${row_data['Price']}", "inline": True}
        ],
        # 關鍵：透過 attachment:// 語法引用稍後要上傳的檔案
        "image": {"url": f"attachment://{filename}"}
    }

    # 準備 Payload (JSON 部分)
    payload = {
        "username": "SGX Chart Bot",
        "embeds": [embed]
    }

    # 準備檔案 (Multipart 部分)
    # files 格式: {'欄位名稱': (檔名, 檔案二進位資料, MIME類型)}
    files = {
        'file': (filename, chart_buffer, 'image/png')
    }

    try:
        # 注意：這裡不能用 json=payload，要用 data={'payload_json': ...} 配合 files
        import json
        r = requests.post(
            DISCORD_WEBHOOK_URL, 
            data={'payload_json': json.dumps(payload)}, 
            files=files
        )
        if r.status_code != 204:
             print(f"圖表發送失敗: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"圖表發送異常: {e}")

# ==========================================
# 3. 核心抓取邏輯 (維持不變)
# ==========================================
def fetch_stock_data(ticker_raw):
    ticker = f"{ticker_raw}.SI"
    try:
        stock = yf.Ticker(ticker)
        # 技巧：先抓 fast_info 確定有價格，再抓 info 拿殖利率，減少等待時間
        price = stock.fast_info.get('last_price')
        if not price: return None

        info = stock.info
        div_yield = info.get('dividendYield')
        name = info.get('shortName', ticker_raw)
        
        yield_pct = round(div_yield * 100, 2) if div_yield else 0.0
        price_clean = round(price, 2)
        
        return {"Code": ticker_raw, "Name": name, "Price": price_clean, "Yield": yield_pct}
    except:
        return None

# ==========================================
# 4. 主程式
# ==========================================
def main():
    print(f"啟動全市場掃描：目標 {len(sg_tickers_raw)} 檔...")
    results = []
    
    # 第一階段：多執行緒抓取基本資料
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ticker = {executor.submit(fetch_stock_data, t): t for t in sg_tickers_raw}
        for future in concurrent.futures.as_completed(future_to_ticker):
            data = future.result()
            if data:
                results.append(data)

    if not results: return

    # 轉為 DataFrame 並篩選
    df = pd.DataFrame(results)
    high_yield_stocks = df[df['Yield'] >= YIELD_THRESHOLD].sort_values(by="Yield", ascending=False)

    # 第二階段：發送通知與繪圖
    if not high_yield_stocks.empty:
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 1. 先發送一個總表 (純文字)
        msg = f"**📊 SGX 高殖利率快報 ({current_date})**\n"
        msg += f"篩選門檻: > **{YIELD_THRESHOLD}%** (共發現 {len(high_yield_stocks)} 檔)\n"
        msg += "```ini\n Code   Yield    Price     Name\n"
        msg += "-"*38 + "\n"
        for _, row in high_yield_stocks.iterrows():
             msg += f"{row['Code']:<5} {row['Yield']:>5}%   ${row['Price']:<7} {row['Name'][:15]}\n"
        msg += "```\n↓ 詳細走勢圖請見下方 ↓"
        send_discord_text(msg)
        
        # 2. 針對每一檔，繪製圖表並個別發送
        print("開始繪製走勢圖並發送...")
        for _, row in high_yield_stocks.iterrows():
            ticker_code = row['Code']
            # 生成圖表 Buffer
            chart_buf = generate_chart_buffer(ticker_code)
            if chart_buf:
                # 發送帶圖訊息
                send_discord_with_chart(ticker_code, row, chart_buf)
                # 重要：關閉 Buffer
                chart_buf.close()
        print("所有通知發送完成。")

    else:
        print(f"今日無殖利率 > {YIELD_THRESHOLD}% 的個股。")

if __name__ == "__main__":
    main()
