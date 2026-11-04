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
from datetime import timedelta

# ── 設定 ────────────────────────────────────────────────────────
START_DATE  = '2015-01-01'
END_DATE    = None   # None = 今日
RETRY_WAITS = (3, 10, 30)
TW_CLOSE_UTC = timedelta(hours=6, minutes=30)   # 台股 14:30 後視為收盤資料完整
US_CLOSE_UTC = timedelta(hours=21, minutes=30)  # 美股收盤（涵蓋夏令與冬令）

ETF_LIST = {
    '0050':   '0050.TW',
    '0052':   '0052.TW',
    '0053':   '0053.TW',
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
    """下載單一標的；Yahoo 常暫時回空，退避重試，絕不改抓較短區間。"""
    df = pd.DataFrame()
    for wait in RETRY_WAITS:
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         auto_adjust=False, progress=False)
        if not df.empty:
            break
        time.sleep(wait)
    if df.empty:
        raise ValueError('無資料')

    if hasattr(df.columns, 'get_level_values'):
        df.columns = df.columns.get_level_values(0)

    cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
            if c in df.columns]
    df = df[cols].reset_index()

    if 'Adj Close' not in df.columns:
        raise ValueError(f'缺少 Adj Close，欄位：{list(df.columns)}')

    return df.dropna(subset=['Close', 'Adj Close']).reset_index(drop=True)


def drop_unfinished(df: pd.DataFrame, close_utc: timedelta) -> pd.DataFrame:
    """移除尚未收盤的當日資料（盤中價不是收盤價）。"""
    dates = pd.to_datetime(df['Date'])
    now = pd.Timestamp.now(tz='UTC').tz_localize(None)
    return df[dates + close_utc <= now].reset_index(drop=True)


def check_not_truncated(df: pd.DataFrame, out: Path) -> None:
    """新資料若比既有 CSV 短，視為 Yahoo 異常，保留舊檔。"""
    if not out.exists():
        return
    old = pd.read_csv(out, usecols=['Date'], parse_dates=['Date'])['Date']
    new = pd.to_datetime(df['Date'])
    if new.min() > old.min() + timedelta(days=7):
        raise ValueError(f'起始日倒退 {old.min().date()}→{new.min().date()}，保留舊檔')
    if new.max() < old.max() - timedelta(days=7):
        raise ValueError(f'結束日倒退 {old.max().date()}→{new.max().date()}，保留舊檔')


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
            df = drop_unfinished(download_one(ticker), TW_CLOSE_UTC)
            check_not_truncated(df, out)
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
            fail.extend(US_STOCKS)
        time.sleep(1.2)

        if fx is not None:
            for etf_id, ticker in US_STOCKS.items():
                out = OUTPUT_DIR / f'{etf_id}_data.csv'
                print(f'下載 {etf_id} ({ticker}, USD→TWD) …', end=' ')
                try:
                    df = drop_unfinished(download_one(ticker), US_CLOSE_UTC)
                    check_not_truncated(df, out)
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
        sys.exit(1)
    else:
        print('\n所有 CSV 已更新，請執行：python -X utf8 generate_html.py')
