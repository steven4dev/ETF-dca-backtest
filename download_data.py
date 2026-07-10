"""
下載所有 ETF 歷史資料（含 Adj Close）
來源：Yahoo Finance（透過 yfinance）
用法：python -X utf8 download_data.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import time
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import date, timedelta

# ── 設定 ────────────────────────────────────────────────────────
START_DATE  = '2015-01-01'
START_10Y   = (date.today() - timedelta(days=10 * 366)).strftime('%Y-%m-%d')
END_DATE   = None   # None = 今日

ETF_LIST = {
    '0050':   '0050.TW',
    '0052':   '0052.TW',
    '00631L': '00631L.TW',
    '00647L': '00647L.TW',
    '00663L': '00663L.TW',
    '00670L': '00670L.TW',
    '00675L': '00675L.TW',
    '00685L': '00685L.TW',
    '009813': '009813.TW',
    '00735':  '00735.TW',
    '00830':  '00830.TW',
    '00770':  '00770.TW',
    '009810': '009810.TW',
    '00935':  '00935.TW',
    '00981A': '00981A.TW',
    '00988A': '00988A.TW',
    '00992A': '00992A.TW',
    '2330':   '2330.TW',
    '2308':   '2308.TW',
    '2454':   '2454.TW',
}

# 美股清單（價格以 USD 計，下載後乘上匯率換算為 TWD）
US_STOCKS = {
    'SSO': 'SSO',
    'QLD': 'QLD',
}

OUTPUT_DIR = Path('.')


def download_one(ticker: str) -> pd.DataFrame:
    """下載單一標的，固定日期失敗時自動 fallback 至動態 10 年前。"""
    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     auto_adjust=False, progress=False)
    if df.empty:
        df = yf.download(ticker, start=START_10Y, end=END_DATE,
                         auto_adjust=False, progress=False)
    if df.empty:
        raise ValueError('無資料')

    if hasattr(df.columns, 'get_level_values'):
        df.columns = df.columns.get_level_values(0)

    cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
            if c in df.columns]
    df = df[cols].reset_index()

    if 'Adj Close' not in df.columns:
        raise ValueError(f'缺少 Adj Close，欄位：{list(df.columns)}')

    return df


def download_usdtwd() -> pd.Series:
    """下載 USD/TWD 匯率，回傳以日期為 index 的 Series。"""
    df = yf.download('TWD=X', start=START_DATE, end=END_DATE,
                     auto_adjust=False, progress=False)
    if hasattr(df.columns, 'get_level_values'):
        df.columns = df.columns.get_level_values(0)
    # 用 Close 欄位作為當日匯率
    rate = df['Close'].copy()
    rate.index = pd.to_datetime(rate.index).normalize()
    # 前向填補假日缺口
    rate = rate.reindex(pd.date_range(rate.index.min(), rate.index.max(), freq='D')).ffill()
    return rate


# ── 主流程 ───────────────────────────────────────────────────────
if __name__ == '__main__':
    total = len(ETF_LIST) + len(US_STOCKS)
    print(f'開始下載 {total} 支標的（Adj Close）…\n')
    ok, fail = 0, []

    # ── 台灣 ETF ──────────────────────────────────────────────────
    for etf_id, ticker in ETF_LIST.items():
        out = OUTPUT_DIR / f'{etf_id}_data.csv'
        print(f'下載 {etf_id} ({ticker}) …', end=' ')
        try:
            df = download_one(ticker)
            df.to_csv(out, index=False, encoding='utf-8-sig')
            print(f'{len(df)} 筆  {str(df["Date"].iloc[0])[:10]}~{str(df["Date"].iloc[-1])[:10]}')
            ok += 1
        except Exception as e:
            print(f'✗ 失敗：{e}')
            fail.append(etf_id)
        time.sleep(1.2)

    # ── 美股（換算為台幣）────────────────────────────────────────
    if US_STOCKS:
        print('\n下載 USD/TWD 匯率…', end=' ')
        try:
            fx = download_usdtwd()
            print(f'{len(fx)} 筆  {str(fx.index[0])[:10]}~{str(fx.index[-1])[:10]}')
        except Exception as e:
            print(f'✗ 失敗：{e}，美股將跳過')
            fx = None
        time.sleep(1.2)

        if fx is not None:
            for etf_id, ticker in US_STOCKS.items():
                out = OUTPUT_DIR / f'{etf_id}_data.csv'
                print(f'下載 {etf_id} ({ticker}, USD→TWD) …', end=' ')
                try:
                    df = download_one(ticker)
                    df['Date'] = pd.to_datetime(df['Date']).dt.normalize()
                    # 對齊匯率
                    df['_fx'] = df['Date'].map(fx).ffill()
                    for col in ['Open', 'High', 'Low', 'Close', 'Adj Close']:
                        if col in df.columns:
                            df[col] = (df[col] * df['_fx']).round(4)
                    df.drop(columns=['_fx'], inplace=True)
                    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
                    df.to_csv(out, index=False, encoding='utf-8-sig')
                    print(f'{len(df)} 筆  {str(df["Date"].iloc[0])[:10]}~{str(df["Date"].iloc[-1])[:10]}  (TWD)')
                    ok += 1
                except Exception as e:
                    print(f'✗ 失敗：{e}')
                    fail.append(etf_id)
                time.sleep(1.2)

    print(f'\n完成：{ok} 成功 / {len(fail)} 失敗')
    if fail:
        print(f'失敗清單：{fail}')
    else:
        print('\n所有 CSV 已更新，請執行：python -X utf8 generate_html.py')
