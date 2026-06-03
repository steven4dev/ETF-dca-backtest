"""
下載所有 ETF 歷史資料（含 Adj Close）
來源：Yahoo Finance（透過 yfinance）
用法：python -X utf8 download_data.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import time
import yfinance as yf
from pathlib import Path
from datetime import date, timedelta

# ── 設定 ────────────────────────────────────────────────────────
# 優先用固定起始日（10 年以上）；若 Yahoo 拒絕則 fallback 到動態 10 年前
START_DATE  = '2015-01-01'
START_10Y   = (date.today() - timedelta(days=10 * 366)).strftime('%Y-%m-%d')
END_DATE   = None   # None = 今日

ETF_LIST = {
    '0050':   '0050.TW',
    '0052':   '0052.TW',
    '00631L': '00631L.TW',
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

OUTPUT_DIR = Path('.')


def download_one(ticker: str) -> 'pd.DataFrame':
    """下載單一標的，固定日期失敗時自動 fallback 至動態 10 年前。"""
    import pandas as pd

    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     auto_adjust=False, progress=False)
    if df.empty:
        df = yf.download(ticker, start=START_10Y, end=END_DATE,
                         auto_adjust=False, progress=False)
    if df.empty:
        raise ValueError('無資料')

    # 展平 MultiIndex columns
    if hasattr(df.columns, 'get_level_values'):
        df.columns = df.columns.get_level_values(0)

    cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
            if c in df.columns]
    df = df[cols].reset_index()

    if 'Adj Close' not in df.columns:
        raise ValueError(f'缺少 Adj Close，欄位：{list(df.columns)}')

    return df


# ── 主流程 ───────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'開始下載 {len(ETF_LIST)} 支 ETF（Adj Close）…\n')
    ok, fail = 0, []

    for etf_id, ticker in ETF_LIST.items():
        out = OUTPUT_DIR / f'{etf_id}_data.csv'
        print(f'下載 {etf_id} ({ticker}) …', end=' ')
        try:
            df = download_one(ticker)
            df.to_csv(out, index=False, encoding='utf-8-sig')
            rows  = len(df)
            start = str(df['Date'].iloc[0])[:10]
            end   = str(df['Date'].iloc[-1])[:10]
            print(f'{rows} 筆  {start}~{end}')
            ok += 1
        except Exception as e:
            print(f'✗ 失敗：{e}')
            fail.append(etf_id)
        time.sleep(1.2)

    print(f'\n完成：{ok} 成功 / {len(fail)} 失敗')
    if fail:
        print(f'失敗清單：{fail}')
        print('提示：請到 https://hk.finance.yahoo.com/quote/{標的}.TW/history/ 手動下載 CSV')
    else:
        print('\n所有 CSV 已更新，請執行：python -X utf8 generate_html.py')
