"""
下載所有 ETF 歷史資料（含 Adj Close）
來源：Yahoo Finance（透過 yfinance）
用法：python -X utf8 download_data.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import yfinance as yf
from pathlib import Path

# ── 設定 ────────────────────────────────────────────────────────
START_DATE = '2021-01-01'   # 起始日期
END_DATE   = None            # None = 今日

ETF_LIST = {
    '0050':   '0050.TW',
    '0052':   '0052.TW',
    '00631L': '00631L.TW',
    '009813': '009813.TW',
    '00770':  '00770.TW',
    '009810': '009810.TW',
    '00981A': '00981A.TW',
    '00988A': '00988A.TW',
    '00992A': '00992A.TW',
}

OUTPUT_DIR = Path('.')

# ── 主流程 ───────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'開始下載 {len(ETF_LIST)} 支 ETF（Adj Close）…\n')
    ok, fail = 0, []

    for etf_id, ticker in ETF_LIST.items():
        out = OUTPUT_DIR / f'{etf_id}_data.csv'
        print(f'下載 {etf_id} ({ticker}) …', end=' ')
        try:
            df = yf.download(
                ticker,
                start=START_DATE,
                end=END_DATE,
                auto_adjust=False,   # 保留 Adj Close 欄位
                progress=False,
            )
            if df.empty:
                raise ValueError('無資料')

            # yfinance 回傳 MultiIndex columns 時展平
            if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, 'get_level_values'):
                df.columns = df.columns.get_level_values(0)

            # 保留需要的欄位並重設索引
            cols = [c for c in ['Open','High','Low','Close','Adj Close','Volume'] if c in df.columns]
            df = df[cols].reset_index()
            df.rename(columns={'index': 'Date'}, inplace=True)

            # 確認 Adj Close 存在
            if 'Adj Close' not in df.columns:
                raise ValueError(f'下載結果無 Adj Close，欄位：{list(df.columns)}')

            df.to_csv(out, index=False, encoding='utf-8-sig')

            rows = len(df)
            start = str(df['Date'].iloc[0])[:10]
            end   = str(df['Date'].iloc[-1])[:10]
            print(f'{rows} 筆  {start}~{end}')
            ok += 1

        except Exception as e:
            print(f'✗ 失敗：{e}')
            fail.append(etf_id)

    print(f'\n完成：{ok} 成功 / {len(fail)} 失敗')
    if fail:
        print(f'失敗清單：{fail}')
        print('提示：請到 https://hk.finance.yahoo.com/quote/{{標的}}.TW/history/ 手動下載 CSV')
        print('      手動下載後確認第一行包含 "Adj Close" 欄位')
    else:
        print('\n所有 CSV 已更新，請重新執行：')
        print('  python -X utf8 generate_html.py')
