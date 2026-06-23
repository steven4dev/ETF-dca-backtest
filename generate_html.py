"""
多標的 ETF 定期定額回測分析 HTML 產生器
Python：讀取各 ETF CSV → 拆分還原 → 輸出交易日程 + 每日收盤 JSON
JS：多選勾選、年份、金額全部即時重算
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
import json
from pathlib import Path

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        return super().default(obj)

# ── ETF 設定表 ────────────────────────────────────────────────────
# split_date / split_ratio 已移除：由 load_etf() 自動偵測並補正
ETF_CONFIG = {
    '0050':   {'name':'0050 元大台灣50',          'csv':'0050_data.csv',   'type':'etf'},
    '0052':   {'name':'0052 富邦科技',             'csv':'0052_data.csv',   'type':'etf'},
    '00631L': {'name':'00631L 元大台灣50正2',      'csv':'00631L_data.csv', 'type':'leveraged'},
    '00663L': {'name':'00663L 國泰臺灣加權正2',    'csv':'00663L_data.csv', 'type':'leveraged'},
    '00675L': {'name':'00675L 富邦臺灣加權正2',    'csv':'00675L_data.csv', 'type':'leveraged'},
    '00685L': {'name':'00685L 群益臺灣加權正2',    'csv':'00685L_data.csv', 'type':'leveraged'},
    '009813': {'name':'009813 街口布局全球',       'csv':'009813_data.csv', 'type':'etf'},
    '00735':  {'name':'00735 國泰臺韓科技',        'csv':'00735_data.csv',  'type':'etf'},
    '00830':  {'name':'00830 國泰費城半導體',      'csv':'00830_data.csv',  'type':'etf'},
    '00770':  {'name':'00770 富邦台灣加權',        'csv':'00770_data.csv',  'type':'etf'},
    '009810': {'name':'009810 街口ESG永續',        'csv':'009810_data.csv', 'type':'etf'},
    '00935':  {'name':'00935 野村臺灣新科技50',    'csv':'00935_data.csv',  'type':'etf'},
    '00981A': {'name':'00981A 國泰優選收益',       'csv':'00981A_data.csv', 'type':'etf'},
    '00988A': {'name':'00988A 野村優息存股A',      'csv':'00988A_data.csv', 'type':'etf'},
    '00992A': {'name':'00992A 群益台灣科技創新',   'csv':'00992A_data.csv', 'type':'etf'},
    '2330':   {'name':'2330 台積電',              'csv':'2330_data.csv',   'type':'stock'},
    '2308':   {'name':'2308 台達電',              'csv':'2308_data.csv',   'type':'stock'},
    '2454':   {'name':'2454 聯發科',              'csv':'2454_data.csv',   'type':'stock'},
}

GROUPS = {
    '組合一': [1, 6, 11, 16, 21, 26, 31],
    '組合二': [2, 7, 12, 17, 22, 27],
    '組合三': [3, 8, 13, 18, 23, 28],
    '組合四': [4, 9, 14, 19, 24, 29],
    '組合五': [5, 10, 15, 20, 25, 30],
}
DAYS_LABEL = {
    '組合一': '1/6/11/16/21/26/31',
    '組合二': '2/7/12/17/22/27',
    '組合三': '3/8/13/18/23/28',
    '組合四': '4/9/14/19/24/29',
    '組合五': '5/10/15/20/25/30',
}

# ── 各 ETF 資料處理 ───────────────────────────────────────────────
def auto_fix_splits(prices: np.ndarray) -> np.ndarray:
    """
    自動偵測股票分割並向前修正，使價格序列連續。
    偵測條件：單日跌幅 >40%，且跌幅接近 1/N（N≥2 整數，誤差<12%）。
    每次偵測到分割後重新掃描（支援多次分割）。
    """
    p = prices.copy().astype(float)
    changed = True
    while changed:
        changed = False
        for i in range(len(p) - 1):
            if p[i] <= 0:
                continue
            ratio = p[i + 1] / p[i]
            if ratio >= 0.6:
                continue
            n = round(1.0 / ratio)
            if n >= 2 and abs(ratio - 1.0 / n) / (1.0 / n) < 0.12:
                p[:i + 1] /= n   # 分割日前全部除以 N
                changed = True
                break             # 重新掃描
    return p


def load_etf(cfg):
    df = pd.read_csv(cfg['csv'])
    df['Date'] = pd.to_datetime(df['Date'])

    # 優先使用 Adj Close（含配息還原），否則用 Close
    col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
    df['Close'] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['Close']).sort_values('Date').reset_index(drop=True)

    # 自動偵測並補正股票分割（Yahoo Finance Adj Close 僅含配息，分割不連續需補正）
    df['Close'] = auto_fix_splits(df['Close'].values)

    return df

def build_schedules(df):
    trading_dates = pd.DatetimeIndex(df['Date'].values)
    close_map     = dict(zip(df['Date'].dt.strftime('%Y-%m-%d'), df['Close'].round(4)))
    latest        = df['Date'].max()
    earliest      = df['Date'].min()

    all_sched = {}
    for gname, days in GROUPS.items():
        trades = {}
        cur = earliest.replace(day=1)
        while cur <= latest:
            for day in days:
                try:    target = cur.replace(day=day)
                except: continue
                if target < earliest or target > latest: continue
                idx = trading_dates.searchsorted(target)
                if idx >= len(trading_dates): continue
                actual = trading_dates[idx]
                dstr   = actual.strftime('%Y-%m-%d')
                price  = round(float(close_map[dstr]), 4)
                if dstr in trades: trades[dstr]['n'] += 1
                else:              trades[dstr] = {'d': dstr, 'p': price, 'n': 1}
            cur = cur.replace(month=cur.month % 12 + 1,
                              year=cur.year + (1 if cur.month == 12 else 0))
        all_sched[gname] = sorted(trades.values(), key=lambda x: x['d'])
    return all_sched

# ── 載入所有 ETF ──────────────────────────────────────────────────
etf_js = {}   # 輸出給 JS 的大 dict

for etf_id, cfg in ETF_CONFIG.items():
    print(f'處理 {etf_id} ...', end=' ')
    df    = load_etf(cfg)
    sched = build_schedules(df)
    daily = [{'d': row['Date'].strftime('%Y-%m-%d'),
              'p': round(float(row['Close']), 4)} for _, row in df.iterrows()]
    data_days  = (df['Date'].max() - df['Date'].min()).days
    data_years = round(data_days / 365.25, 2)

    etf_js[etf_id] = {
        'id':         etf_id,
        'name':       cfg['name'],
        'type':       cfg.get('type', 'etf'),
        'daily':      daily,
        'schedules':  sched,
        'finalPrice': round(float(df['Close'].iloc[-1]), 4),
        'dataYears':  data_years,
        'startDate':  df['Date'].min().strftime('%Y-%m-%d'),
        'endDate':    df['Date'].max().strftime('%Y-%m-%d'),
    }
    print(f'{len(daily)} 筆  {daily[0]["d"]}~{daily[-1]["d"]}  {data_years:.1f}年')

etf_json     = json.dumps(etf_js,      ensure_ascii=False, cls=NpEncoder)
days_lbl_json = json.dumps(DAYS_LABEL, ensure_ascii=False)
gnames_json  = json.dumps(list(GROUPS.keys()), ensure_ascii=False)

# ═════════════════════════════════════════════════════════════════
# HTML
# ═════════════════════════════════════════════════════════════════
HTML = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ETF 定期定額回測分析</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{
  --bg:#0f1117; --card:#1a1d27; --border:#2a2d3e;
  --accent:#4f8ef7; --green:#22c55e; --red:#ef4444;
  --yellow:#f59e0b; --purple:#a78bfa; --orange:#fb923c;
  --text:#e2e8f0; --muted:#94a3b8;
}}
body.light{{
  --bg:#f1f5f9; --card:#ffffff; --border:#cbd5e1;
  --text:#1e293b; --muted:#64748b;
}}
body.light header{{background:linear-gradient(135deg,#1e3a8a 0%,#1e40af 100%);}}
body.light .year-btn:hover:not(.active),
body.light .sel-all-btn:hover:not(.active){{background:#e2e8f0;color:var(--text);}}
body.light .amt-wrap{{background:#f8fafc;}}
body.light tbody tr:hover{{background:#f1f5f9;}}
/* Toast */
#kb-toast{{
  position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;
  background:var(--card);color:var(--text);
  border:1px solid var(--border);border-radius:8px;
  padding:.45rem 1rem;font-size:.82rem;font-weight:600;
  pointer-events:none;opacity:0;transition:opacity .25s;
  box-shadow:0 4px 12px rgba(0,0,0,.3);
}}
#kb-toast.show{{opacity:1;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--bg);color:var(--text);
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;line-height:1.6;}}

/* ── Header ── */
header{{
  background:linear-gradient(135deg,#1a1d27 0%,#0f1117 100%);
  border-bottom:1px solid var(--border);
  padding:1.1rem 1.2rem .8rem;text-align:center;
}}
header h1{{font-size:1.4rem;font-weight:700;color:#fff;letter-spacing:-.5px;}}
header p{{color:var(--muted);margin-top:.1rem;font-size:.82rem;}}

/* ── Control bar ── */
.ctrl-bar{{
  background:var(--card);border-bottom:1px solid var(--border);
  padding:.6rem 0;
}}
.ctrl-bar-inner{{
  max-width:1280px;margin:0 auto;padding:0 1.2rem;
  display:flex;flex-wrap:wrap;align-items:center;gap:.7rem;
}}
.ctrl-group{{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;}}
.ctrl-label{{color:var(--muted);font-size:.78rem;font-weight:600;white-space:nowrap;}}
.sep{{width:1px;height:18px;background:var(--border);}}

/* ETF 多選 */
.etf-checks{{display:flex;flex-wrap:wrap;gap:.35rem;}}
.etf-check-item{{
  display:flex;align-items:center;gap:.28rem;
  background:#1e2133;border:1px solid var(--border);
  border-radius:5px;padding:.2rem .55rem;cursor:pointer;
  transition:all .15s;user-select:none;
}}
.etf-check-item:hover{{border-color:var(--accent);}}
.etf-check-item.checked{{border-color:var(--accent);background:rgba(79,142,247,.12);}}
.etf-check-item input{{accent-color:var(--accent);width:12px;height:12px;cursor:pointer;}}
.etf-check-item label{{font-size:.76rem;font-weight:600;cursor:pointer;color:var(--muted);}}
.etf-check-item.checked label{{color:var(--text);}}

/* 年份按鈕 */
.year-btns{{display:flex;gap:.3rem;}}
.sel-all-btn{{
  background:var(--border);color:var(--muted);border:none;
  padding:.2rem .6rem;border-radius:5px;cursor:pointer;
  font-size:.76rem;font-weight:600;transition:all .15s;
}}
.sel-all-btn.active{{background:var(--accent);color:#fff;}}
.sel-all-btn:hover:not(.active){{background:#3a3d50;color:var(--text);}}
.year-btn{{
  background:var(--border);color:var(--muted);border:none;
  padding:.2rem .6rem;border-radius:5px;cursor:pointer;
  font-size:.76rem;font-weight:600;transition:all .15s;
}}
.year-btn.active{{background:var(--accent);color:#fff;}}
.year-btn:hover:not(.active){{background:#3a3d50;color:var(--text);}}

/* 投資策略切換 */
.invest-toggle{{
  display:flex;background:var(--border);
  border-radius:6px;padding:2px;gap:2px;
}}
.toggle-opt{{
  padding:.18rem .7rem;border-radius:4px;
  font-size:.76rem;font-weight:600;color:var(--muted);
  cursor:pointer;user-select:none;white-space:nowrap;
  transition:background .18s,color .18s;
}}
.toggle-opt.active{{background:var(--accent);color:#fff;}}
.toggle-opt:not(.active):hover{{color:var(--text);}}

/* 金額輸入 */
.amt-wrap{{
  display:flex;align-items:center;gap:.3rem;
  background:#0f1117;border:1px solid var(--border);
  border-radius:5px;padding:.2rem .6rem;transition:border-color .2s;
}}
.amt-wrap:focus-within{{border-color:var(--accent);}}
.amt-wrap span{{color:var(--muted);font-size:.78rem;}}
.amt-wrap input{{
  background:transparent;border:none;outline:none;
  color:#fff;font-size:.88rem;font-weight:700;
  width:100px;text-align:right;
}}
.amt-wrap input::-webkit-outer-spin-button,
.amt-wrap input::-webkit-inner-spin-button{{-webkit-appearance:none;}}
.amt-wrap input[type=number]{{-moz-appearance:textfield;}}

/* ── Container ── */
.container{{max-width:1280px;margin:0 auto;padding:1.2rem 1.2rem;}}
.section-title{{
  font-size:.95rem;font-weight:600;color:#fff;
  margin-bottom:.6rem;padding-bottom:.3rem;
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:.5rem;
  cursor:pointer;user-select:none;
}}
.section-title:hover{{color:var(--accent);border-color:var(--accent);}}
.section-title .chev{{
  margin-left:auto;font-size:.7rem;color:var(--muted);
  transition:transform .25s;
}}
.section-title.collapsed .chev{{transform:rotate(-90deg);}}
.sec-body{{
  overflow:hidden;
  max-height:9999px;
  transition:max-height .35s ease, opacity .25s;
  opacity:1;
}}
.sec-body.collapsed{{max-height:0 !important;opacity:0;}}

/* ── KPI grid ── */
.kpi-grid{{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
  gap:.65rem;margin-bottom:1.4rem;
}}
.kpi{{
  background:var(--card);border:1px solid var(--border);
  border-radius:8px;padding:.7rem;text-align:center;transition:border-color .2s;
}}
.kpi:hover{{border-color:var(--accent);}}
.kpi-stock-red{{border:2.5px solid var(--red)   !important;box-shadow:0 0 8px rgba(239,68,68,.3);}}
.kpi-stock-blue{{border:2.5px solid var(--accent) !important;box-shadow:0 0 8px rgba(79,142,247,.3);}}
.kpi-stock-green{{border:2.5px solid var(--green) !important;box-shadow:0 0 8px rgba(34,197,94,.3);}}
.kpi .val{{font-size:1.1rem;font-weight:700;}}
.kpi .lbl{{font-size:.67rem;color:var(--muted);margin-top:.1rem;}}
.pos{{color:var(--green);}} .neg{{color:var(--red);}} .neu{{color:var(--accent);}}

/* ── Table ── */
.table-wrap{{overflow-x:auto;margin-bottom:1.4rem;}}
table{{width:100%;border-collapse:collapse;font-size:.8rem;}}
thead tr{{background:#232636;}}
thead th{{
  padding:.45rem .75rem;text-align:right;color:var(--muted);
  font-weight:600;white-space:nowrap;border-bottom:1px solid var(--border);
}}
thead th:first-child,thead th:nth-child(2){{text-align:left;}}
tbody tr{{border-bottom:1px solid var(--border);transition:background .12s;}}
tbody tr:hover{{background:#1e2133;}}
tbody td{{padding:.45rem .75rem;text-align:right;white-space:nowrap;}}
tbody td:first-child,tbody td:nth-child(2){{text-align:left;font-weight:600;}}
.etf-badge{{
  display:inline-block;font-size:.61rem;font-weight:700;
  padding:.07rem .35rem;border-radius:4px;margin-right:.28rem;
}}
.tag{{
  display:inline-block;font-size:.58rem;padding:.06rem .3rem;
  border-radius:4px;margin-left:.2rem;font-weight:600;vertical-align:middle;
}}
.tag-best{{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3);}}
.tag-second{{background:rgba(234,179,8,.15);color:#fde047;border:1px solid rgba(234,179,8,.3);}}
.tag-safe{{background:rgba(79,142,247,.15);color:var(--accent);border:1px solid rgba(79,142,247,.3);}}
.tag-worst{{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3);}}

/* ── Charts ── */
.charts-grid{{
  display:grid;grid-template-columns:1fr 1fr;
  gap:1rem;margin-bottom:1.4rem;
}}
@media(max-width:768px){{.charts-grid{{grid-template-columns:1fr;}}}}
.chart-card{{
  background:var(--card);border:1px solid var(--border);
  border-radius:8px;padding:.8rem;
}}
.chart-card.full{{grid-column:1/-1;}}
.chart-title{{
  font-size:.74rem;font-weight:600;color:var(--muted);
  margin-bottom:.6rem;text-transform:uppercase;letter-spacing:.05em;
}}
.chart-wrap{{position:relative;height:195px;}}
.chart-wrap.tall{{height:255px;}}
.tab-row{{display:flex;gap:.25rem;margin-bottom:.45rem;flex-wrap:wrap;}}
.tab-btn{{
  background:var(--border);color:var(--muted);border:none;
  padding:.18rem .6rem;border-radius:4px;cursor:pointer;
  font-size:.71rem;font-weight:600;transition:all .15s;
}}
.tab-btn.active{{background:var(--accent);color:#fff;}}

/* ── Conclusion ── */
.conclusion-grid{{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));
  gap:.65rem;margin-bottom:1.4rem;
}}
.c-card{{
  background:var(--card);border:1px solid var(--border);
  border-radius:8px;padding:.8rem;
}}
.c-card h3{{
  font-size:.74rem;font-weight:700;color:var(--accent);
  text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem;
}}
.c-card p,.c-card li{{font-size:.81rem;color:var(--muted);}}
.c-card ul{{padding-left:.85rem;}}
.c-card li{{margin-bottom:.18rem;}}
.hl{{color:var(--text)!important;font-weight:600;}}
.gr{{color:var(--green)!important;}} .rd{{color:var(--red)!important;}}

/* ── No data notice ── */
.no-data{{
  text-align:center;padding:1.8rem;color:var(--muted);
  background:var(--card);border-radius:8px;border:1px dashed var(--border);
  margin-bottom:1.4rem;
}}

footer{{
  text-align:center;padding:1rem;color:var(--muted);
  font-size:.76rem;border-top:1px solid var(--border);
}}
</style>
</head>
<body>

<header>
  <h1>🇹🇼 台灣 ETF 定期定額回測分析</h1>
  <p>支援多標的比較・五組扣款日・自訂投入金額・可調回測年數 &nbsp;|&nbsp; 資料來源：Yahoo Finance（調整後收盤價）</p>
</header>

<!-- 控制列 -->
<div class="ctrl-bar">
<div class="ctrl-bar-inner">
  <div class="ctrl-group">
    <span class="ctrl-label">選擇標的</span>
    <button class="sel-all-btn" id="btn-select-all">全選</button>
    <button class="sel-all-btn" id="btn-select-etf">ETF</button>
    <button class="sel-all-btn" id="btn-select-leveraged">正二</button>
    <button class="sel-all-btn" id="btn-select-stock">個股</button>
    <div class="etf-checks" id="etf-checks"></div>
  </div>
  <div class="sep"></div>
  <div class="ctrl-group">
    <span class="ctrl-label">回測期間</span>
    <div class="year-btns" id="year-btns">
      <button class="year-btn active" data-y="0.0833">1 月</button>
      <button class="year-btn" data-y="0.1667">2 月</button>
      <button class="year-btn" data-y="0.25">3 月</button>
      <button class="year-btn" data-y="0.5">6 月</button>
      <button class="year-btn" data-y="1">1 年</button>
      <button class="year-btn" data-y="2">2 年</button>
      <button class="year-btn" data-y="3">3 年</button>
      <button class="year-btn" data-y="5">5 年</button>
      <button class="year-btn" data-y="10">10 年</button>
    </div>
  </div>
  <div class="sep"></div>
  <div class="ctrl-group">
    <div class="invest-toggle" id="mode-toggle"><span class="toggle-opt active" data-mode="dca">定期定額</span><span class="toggle-opt" data-mode="lump">單筆投入</span></div>
    <span class="ctrl-label" id="invest-input-lbl">總投入資金</span>
    <div class="amt-wrap">
      <span>NT$</span>
      <input type="number" id="invest-total" value="1000000" min="1" step="10000">
    </div>
    <span class="ctrl-label" id="derived-lbl">≈ 每次投入 <span id="per-trade-lbl" style="color:var(--text);font-weight:700">NT$ 10,000</span></span>
  </div>
</div>
</div>

<div class="container">
  <div class="section-title" data-sec="sec-kpi">📊 整體績效 KPI <span class="chev">▼</span></div>
  <div class="sec-body" id="sec-kpi">
    <div class="kpi-grid" id="kpi-grid"></div>
  </div>

  <div class="section-title" data-sec="sec-conclusion">💡 結論分析 <span class="chev">▼</span></div>
  <div class="sec-body" id="sec-conclusion">
    <div class="conclusion-grid" id="conclusion"></div>
  </div>

  <div class="section-title collapsed" data-sec="sec-table">🏆 五組扣款日績效對照表 <span class="chev">▼</span></div>
  <div class="sec-body collapsed" id="sec-table">
    <div class="table-wrap"><table>
      <thead><tr>
        <th>標的</th><th>組合</th><th>扣款日</th><th>交易次數</th>
        <th>總投入</th><th>持股數</th><th>平均成本</th>
        <th>最終市值</th><th>報酬率</th><th>年化報酬</th><th>最大回撤</th>
      </tr></thead>
      <tbody id="table-body"></tbody>
    </table></div>
  </div>

  <div class="section-title collapsed" data-sec="sec-charts">📈 視覺化比較 <span class="chev">▼</span></div>
  <div class="sec-body collapsed" id="sec-charts">
    <div class="charts-grid">
      <div class="chart-card">
        <div class="chart-title">各標的最佳組合 總報酬率</div>
        <div class="chart-wrap"><canvas id="chart-best-return"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">各標的最佳組合 年化報酬率（CAGR）</div>
        <div class="chart-wrap"><canvas id="chart-best-cagr"></canvas></div>
      </div>
      <div class="chart-card full">
        <div class="chart-title">各標的最佳組合 資產成長曲線</div>
        <div class="tab-row" id="best-curve-tabs"></div>
        <div class="chart-wrap tall"><canvas id="chart-curve-best"></canvas></div>
      </div>
      <div class="chart-card full">
        <div class="chart-title">單一標的 · 五組扣款日曲線比較</div>
        <div class="tab-row" id="etf-curve-tabs"></div>
        <div class="tab-row" id="group-curve-tabs"></div>
        <div class="chart-wrap tall"><canvas id="chart-curve-groups"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">各標的最佳組合 最大回撤</div>
        <div class="chart-wrap"><canvas id="chart-best-dd"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">各標的 五組扣款日報酬率分布</div>
        <div class="chart-wrap"><canvas id="chart-group-dist"></canvas></div>
      </div>
    </div>
  </div>

  <div class="section-title collapsed" data-sec="sec-layout">📊 2026 Q2-Q3 加速佈局配置表（8月完成版）<span class="chev">▼</span></div>
  <div class="sec-body collapsed" id="sec-layout">
    <div id="layout-wrap"></div>
  </div>
</div>

<div id="kb-toast"></div>


<script>
// ════════════════════════════════════════════════════════════════
//  靜態資料
// ════════════════════════════════════════════════════════════════
const ETF_DB     = {etf_json};
const DAYS_LABEL = {days_lbl_json};
const GNAMES     = {gnames_json};

// ETF 顯示顏色
const ETF_COLORS = {{
  '0050':   '#4f8ef7',
  '0052':   '#22c55e',
  '00631L': '#ef4444',
  '00685L': '#f97316',
  '009813': '#f59e0b',
  '00735':  '#06b6d4',
  '00830':  '#818cf8',
  '00770':  '#e879f9',
  '009810': '#fb923c',
  '00935':  '#f43f5e',
  '00981A': '#a78bfa',
  '00988A': '#38bdf8',
  '00992A': '#34d399',
  '2330':   '#60a5fa',
  '2308':   '#4ade80',
  '2454':   '#c084fc',
}};
const GROUP_COLORS = ['#4f8ef7','#22c55e','#f59e0b','#e879f9','#fb923c'];

const FMT  = n => Math.round(n).toLocaleString('zh-TW');
const FMTP = n => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const WFMT = v => Math.abs(v) >= 1e8 ? (v/1e8).toFixed(2)+'億' : (v/1e4).toFixed(1)+'萬';

// ── 狀態 ──────────────────────────────────────────────────────────
let selectedETFs  = Object.keys(ETF_DB);
let currentYears  = 0.0833;
let currentTotal  = 1000000;
let currentAmt    = 10000;
let investMode     = 'dca';   // 'dca'=定期定額  |  'lump'=單筆投入
let lastResults    = {{}};
let lastBestPerETF = {{}};

function calcPerTrade() {{
  const months = Math.max(1, Math.round(currentYears * 12));
  currentAmt = Math.round(currentTotal / (months * 6));
  const wrap = document.getElementById('derived-lbl');
  if (wrap) wrap.style.display = investMode === 'lump' ? 'none' : '';
  const lbl = document.getElementById('per-trade-lbl');
  if (lbl) lbl.textContent = 'NT$ ' + currentAmt.toLocaleString('zh-TW');
}}

// ── 單筆投入計算（在選定期間第一天買入，與 DCA 同期比較）─────
function calcLumpSum(daily, finalPrice, totalAmount, actualYears) {{
  if (!daily.length || totalAmount <= 0) return null;
  // 期間起點（第一個交易日）
  const buyPrice   = daily[0].p;
  const buyDate    = daily[0].d;
  const shares     = totalAmount / buyPrice;
  const finalValue = shares * finalPrice;
  const returnPct  = (finalValue - totalAmount) / totalAmount * 100;
  const cagr       = actualYears > 0.1
    ? (Math.pow(finalValue / totalAmount, 1 / actualYears) - 1) * 100 : 0;
  // 持有期間最大回撤
  let peakMV = totalAmount, maxDD = 0;
  for (let i = 0; i < daily.length; i++) {{
    const mv = shares * daily[i].p;
    if (mv > peakMV) peakMV = mv;
    const peakRet = (peakMV - totalAmount) / totalAmount * 100;
    const ret     = (mv     - totalAmount) / totalAmount * 100;
    const dd = peakRet > -100 ? (ret - peakRet) / (1 + peakRet / 100) : 0;
    if (dd < maxDD) maxDD = dd;
  }}
  return {{ buyDate, buyPrice, shares, finalValue, returnPct, cagr, maxDrawdown: maxDD, totalCost: totalAmount }};
}}

// ── 切換投資策略 ─────────────────────────────────────────────────
function syncToggleUI() {{
  document.querySelectorAll('#mode-toggle .toggle-opt').forEach(o => {{
    o.classList.toggle('active', o.dataset.mode === investMode);
  }});
  const wrap = document.getElementById('derived-lbl');
  if (wrap) wrap.style.display = investMode === 'lump' ? 'none' : '';
}}

function toggleInvestMode() {{
  investMode = investMode === 'dca' ? 'lump' : 'dca';
  syncToggleUI();
  showToast(investMode === 'lump' ? '📍 單筆投入' : '📈 定期定額模式');
  render();
}}

let focusETF      = '0050';   // 五組曲線聚焦標的
let focusGroup    = null;     // null = 全部組合

// ════════════════════════════════════════════════════════════════
//  ETF 勾選方塊
// ════════════════════════════════════════════════════════════════
const etfChecksEl = document.getElementById('etf-checks');
Object.values(ETF_DB)
  .sort((a, b) => b.dataYears - a.dataYears || a.id.localeCompare(b.id))
  .forEach(etf => {{
  const item = document.createElement('div');
  item.className = 'etf-check-item' + (selectedETFs.includes(etf.id) ? ' checked' : '');
  item.dataset.id = etf.id;

  const cb  = document.createElement('input');
  cb.type   = 'checkbox';
  cb.id     = 'cb-' + etf.id;
  cb.checked = selectedETFs.includes(etf.id);

  const lbl  = document.createElement('label');
  lbl.htmlFor = 'cb-' + etf.id;
  // 顯示 id + 可用年數
  const yrs = etf.dataYears < 1
    ? `${{(etf.dataYears*12).toFixed(0)}}月`
    : `${{etf.dataYears.toFixed(1).replace(/\\.0$/, '')}}年`;
  lbl.textContent = `${{etf.id}} (${{yrs}})`;
  lbl.title = etf.name;

  // 色點
  const dot = document.createElement('span');
  dot.style.cssText = `display:inline-block;width:8px;height:8px;border-radius:50%;
    background:${{ETF_COLORS[etf.id] || '#888'}};margin-right:2px;`;

  item.appendChild(dot);
  item.appendChild(cb);
  item.appendChild(lbl);
  etfChecksEl.appendChild(item);

  item.addEventListener('click', e => {{
    if (e.target !== cb) cb.checked = !cb.checked;
    const id = item.dataset.id;
    if (cb.checked) {{
      if (!selectedETFs.includes(id)) selectedETFs.push(id);
      item.classList.add('checked');
    }} else {{
      if (selectedETFs.length <= 1) {{ cb.checked = true; return; }} // 至少保留1個
      selectedETFs = selectedETFs.filter(x => x !== id);
      item.classList.remove('checked');
    }}
    if (!selectedETFs.includes(focusETF)) focusETF = selectedETFs[0];
    syncSelectAllBtn();
    render();
  }});
}});

// ── 全選 / 全取消 ─────────────────────────────────────────────────
const allETFIds = Object.keys(ETF_DB);
const btnSelectAll = document.getElementById('btn-select-all');

function syncSelectAllBtn() {{
  const allChecked = allETFIds.every(id => selectedETFs.includes(id));
  btnSelectAll.textContent = allChecked ? '全取消' : '全選';
  btnSelectAll.classList.toggle('active', allChecked);
}}

btnSelectAll.addEventListener('click', () => {{
  const allChecked = allETFIds.every(id => selectedETFs.includes(id));
  if (allChecked) {{
    // 全取消 → 只保留 0050
    selectedETFs = ['0050'];
  }} else {{
    // 全選
    selectedETFs = [...allETFIds];
  }}
  // 同步 checkbox UI
  document.querySelectorAll('.etf-check-item').forEach(item => {{
    const id = item.dataset.id;
    const cb = item.querySelector('input');
    const checked = selectedETFs.includes(id);
    cb.checked = checked;
    item.classList.toggle('checked', checked);
  }});
  if (!selectedETFs.includes(focusETF)) focusETF = selectedETFs[0];
  syncSelectAllBtn();
  render();
}});
syncSelectAllBtn();

// ── ETF / 個股 快速篩選 ────────────────────────────────────────
function applyTypeFilter(type) {{
  const ids = allETFIds.filter(id => ETF_DB[id].type === type);
  if (!ids.length) return;
  selectedETFs = [...ids];
  if (!selectedETFs.includes(focusETF)) focusETF = selectedETFs[0];
  document.querySelectorAll('.etf-check-item').forEach(item => {{
    const id = item.dataset.id;
    const cb = item.querySelector('input');
    const checked = selectedETFs.includes(id);
    cb.checked = checked;
    item.classList.toggle('checked', checked);
  }});
  syncSelectAllBtn();
  render();
}}

document.getElementById('btn-select-etf').addEventListener('click', () => applyTypeFilter('etf'));
document.getElementById('btn-select-leveraged').addEventListener('click', () => applyTypeFilter('leveraged'));
document.getElementById('btn-select-stock').addEventListener('click', () => applyTypeFilter('stock'));

// ════════════════════════════════════════════════════════════════
//  資料篩選（依年數）
// ════════════════════════════════════════════════════════════════
function sliceETF(etfId, years) {{
  const etf     = ETF_DB[etfId];
  const latestD = etf.daily[etf.daily.length - 1].d;
  const cutTs   = new Date(latestD).getTime() - years * 365.25 * 86400 * 1000;
  const cutD    = new Date(cutTs).toISOString().slice(0,10);
  const daily   = etf.daily.filter(d => d.d >= cutD);
  const sched   = {{}};
  for (const g of GNAMES) {{
    sched[g] = (etf.schedules[g] || []).filter(t => t.d >= cutD);
  }}
  const actualYears = (new Date(latestD) - new Date(daily[0].d)) / (365.25*86400*1000);
  return {{ daily, sched, actualYears, latestD, startD: daily[0].d }};
}}

// ════════════════════════════════════════════════════════════════
//  DCA 計算
// ════════════════════════════════════════════════════════════════
function runDCA(schedule, daily, finalPrice, amtPerTrade, actualYears) {{
  const tradeMap = {{}};
  for (const t of schedule) tradeMap[t.d] = {{ p: t.p, n: t.n }};

  let cumShares=0, cumCost=0;
  const mv=[], cc=[];
  for (const day of daily) {{
    if (tradeMap[day.d]) {{
      const t = tradeMap[day.d];
      cumShares += (amtPerTrade * t.n) / t.p;
      cumCost   += amtPerTrade * t.n;
    }}
    mv.push(cumShares * day.p);
    cc.push(cumCost);
  }}
  const totalCost  = cumCost;
  const finalValue = cumShares * finalPrice;
  const returnPct  = (finalValue - totalCost) / totalCost * 100;
  const cagr       = actualYears > 0.1
    ? (Math.pow(finalValue/totalCost, 1/actualYears)-1)*100 : 0;
  // 最大回撤：基於「累積報酬率」的回撤，避免 DCA 注資掩蓋真實跌幅
  let peakRet=-Infinity, maxDD=0;
  for (let i=0; i<mv.length; i++) {{
    const ret = cc[i] > 0 ? (mv[i] - cc[i]) / cc[i] * 100 : 0;
    if (ret > peakRet) peakRet = ret;
    const dd = peakRet > -100 ? (ret - peakRet) / (1 + peakRet/100) : 0;
    if (dd < maxDD) maxDD = dd;
  }}
  const trades = schedule.reduce((s,t)=>s+t.n, 0);
  const avgCost = cumShares > 0 ? totalCost/cumShares : 0;
  return {{ trades, totalCost, shares: cumShares, avgCost, finalValue,
            returnPct, cagr, maxDrawdown: maxDD, mv, cc }};
}}

// ════════════════════════════════════════════════════════════════
//  Chart 工廠
// ════════════════════════════════════════════════════════════════
function makeBar(id, labels, datasets, fmtFn) {{
  return new Chart(document.getElementById(id), {{
    type:'bar',
    data:{{labels, datasets}},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{
        legend:{{display:false}},
        tooltip:{{callbacks:{{label:c=>' '+fmtFn(c.raw)}}}},
      }},
      scales:{{
        x:{{ticks:{{color:'#94a3b8',font:{{size:11}}}},grid:{{color:'#1e2133'}}}},
        y:{{ticks:{{color:'#94a3b8',callback:fmtFn}},grid:{{color:'#1e2133'}}}},
      }},
    }},
  }});
}}

function makeLine(id, datasets) {{
  return new Chart(document.getElementById(id), {{
    type:'line',
    data:{{labels:[], datasets}},
    options:{{
      responsive:true, maintainAspectRatio:false,
      interaction:{{mode:'index',intersect:false}},
      plugins:{{
        legend:{{labels:{{color:'#94a3b8',boxWidth:10,font:{{size:11}}}}}},
        tooltip:{{
          itemSort: (a, b) => (b.raw ?? -Infinity) - (a.raw ?? -Infinity),
          callbacks:{{label:c=>` ${{c.dataset.label}}: ${{WFMT(c.raw)}}`}},
        }},
      }},
      scales:{{
        x:{{ticks:{{color:'#64748b',maxTicksLimit:10}},grid:{{color:'#1e2133'}}}},
        y:{{ticks:{{color:'#64748b',callback:WFMT}},grid:{{color:'#1e2133'}}}},
      }},
    }},
  }});
}}

// 初始化圖表
const chartBestReturn = makeBar('chart-best-return',[],[],v=>v.toFixed(2)+'%');
const chartBestCagr   = makeBar('chart-best-cagr',  [],[],v=>v.toFixed(2)+'%');
const chartBestDD     = makeBar('chart-best-dd',    [],[],v=>v.toFixed(2)+'%');
const chartGroupDist  = makeBar('chart-group-dist', [],[],v=>v.toFixed(2)+'%');

const chartCurveBest   = makeLine('chart-curve-best',   []);
const chartCurveGroups = makeLine('chart-curve-groups', []);

// ════════════════════════════════════════════════════════════════
//  Tabs：ETF 選擇 + 組合選擇（for 五組曲線圖）
// ════════════════════════════════════════════════════════════════
function rebuildGroupCurveTabs(results) {{
  // ETF tabs
  const etfTabRow = document.getElementById('etf-curve-tabs');
  etfTabRow.innerHTML = '';
  selectedETFs.forEach(id => {{
    const btn = document.createElement('button');
    btn.className = 'tab-btn' + (id===focusETF?' active':'');
    btn.textContent = id;
    btn.style.borderLeft = `3px solid ${{ETF_COLORS[id]||'#888'}}`;
    btn.onclick = () => {{
      focusETF = id;
      document.querySelectorAll('#etf-curve-tabs .tab-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      updateGroupCurveChart(results);
    }};
    etfTabRow.appendChild(btn);
  }});

  // Group tabs
  const grpTabRow = document.getElementById('group-curve-tabs');
  grpTabRow.innerHTML = '';
  ['全部', ...GNAMES].forEach((name, ni) => {{
    const btn = document.createElement('button');
    btn.className = 'tab-btn' + (!focusGroup && name==='全部' ? ' active' : focusGroup===name ? ' active' : '');
    btn.textContent = name;
    btn.onclick = () => {{
      focusGroup = name==='全部' ? null : name;
      document.querySelectorAll('#group-curve-tabs .tab-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      updateGroupCurveChart(results);
    }};
    grpTabRow.appendChild(btn);
  }});
}}

function updateGroupCurveChart(results) {{
  const etfRes = results[focusETF];
  if (!etfRes) return;
  const {{ daily }} = sliceETF(focusETF, currentYears);
  const labels = daily.map(d=>d.d);
  const datasets = [
    ...GNAMES.map((g,i) => ({{
      label: g,
      data:  etfRes[g].mv,
      borderColor: GROUP_COLORS[i],
      backgroundColor:'transparent',
      borderWidth:2, pointRadius:0, tension:.2,
      hidden: focusGroup && focusGroup!==g,
    }})),
    {{
      label:'累積投入成本',
      data: etfRes[GNAMES[0]].cc,
      borderColor:'#475569',backgroundColor:'transparent',
      borderDash:[5,5],borderWidth:1.5,pointRadius:0,
    }},
  ];
  chartCurveGroups.data.labels   = labels;
  chartCurveGroups.data.datasets = datasets;
  chartCurveGroups.update('none');
}}

// ════════════════════════════════════════════════════════════════
//  主 render
// ════════════════════════════════════════════════════════════════
function renderLumpTableCharts(lumpRes, activeIds, dcaResults, dcaBestPerETF) {{
  const lumpIds = [...activeIds].sort((a,b) => (lumpRes[b]?.returnPct??-999) - (lumpRes[a]?.returnPct??-999));
  if (!lumpIds.length) return;

  // 績效表
  const tbody = document.getElementById('table-body');
  const thEls = document.querySelectorAll('thead th');
  if (thEls.length >= 3) {{ thEls[1].textContent='進場日期（起點）'; thEls[2].textContent='進場價格'; }}

  tbody.innerHTML = lumpIds.map(id => {{
    const r   = lumpRes[id];
    const etf = ETF_DB[id];
    const col = ETF_COLORS[id] || '#888';
    const rc  = r.returnPct >= 0 ? 'color:var(--green)' : 'color:var(--red)';
    const cc  = r.cagr >= 0 ? 'color:var(--green)' : 'color:var(--red)';
    const dcaBest = dcaResults[id] && dcaBestPerETF[id]
      ? dcaResults[id][dcaBestPerETF[id]].returnPct : null;
    const vs = dcaBest !== null
      ? '<span style="font-size:.68rem;color:var(--muted)"> vs DCA最佳 ' + FMTP(dcaBest) + '</span>'
      : '';
    return '<tr>' +
      '<td><span class="etf-badge" style="background:' + col + '22;color:' + col + ';border:1px solid ' + col + '44">' + id + '</span>' +
      '<span style="font-size:.72rem;color:var(--muted)"> ' + etf.name.split(' ').slice(1).join(' ') + '</span></td>' +
      '<td style="font-size:.78rem">' + r.buyDate + '</td>' +
      '<td style="text-align:right">NT$ ' + r.buyPrice.toFixed(2) + '</td>' +
      '<td style="text-align:right">1</td>' +
      '<td style="text-align:right">NT$ ' + FMT(r.totalCost) + '</td>' +
      '<td style="text-align:right">' + r.shares.toFixed(2) + '</td>' +
      '<td style="text-align:right">NT$ ' + r.buyPrice.toFixed(2) + '</td>' +
      '<td style="text-align:right">NT$ ' + FMT(r.finalValue) + '</td>' +
      '<td style="' + rc + ';font-weight:700">' + FMTP(r.returnPct) + vs + '</td>' +
      '<td style="' + cc + '">' + FMTP(r.cagr) + '</td>' +
      '<td style="color:var(--red)">' + r.maxDrawdown.toFixed(2) + '%</td>' +
      '</tr>';
  }}).join('');

  // Bar charts
  const barBg = lumpIds.map(id => ETF_COLORS[id] || '#888');
  function updateBarL(chart, data, fmtFn, colors) {{
    chart.data.labels   = lumpIds;
    chart.data.datasets = [{{ data, backgroundColor: colors || barBg, borderRadius:6, borderSkipped:false }}];
    chart.options.scales.y.ticks.callback = fmtFn;
    chart.options.plugins.tooltip.callbacks.label = c => ' ' + fmtFn(c.raw);
    chart.update('none');
  }}
  updateBarL(chartBestReturn, lumpIds.map(id=>lumpRes[id].returnPct), v=>v.toFixed(2)+'%');
  updateBarL(chartBestCagr,   lumpIds.map(id=>lumpRes[id].cagr),      v=>v.toFixed(2)+'%');
  updateBarL(chartBestDD,     lumpIds.map(id=>lumpRes[id].maxDrawdown),v=>v.toFixed(2)+'%',
    lumpIds.map(id=>{{ const dd=lumpRes[id].maxDrawdown; return dd>-15?'#22c55e':dd>-30?'#f59e0b':'#ef4444'; }}));
  chartGroupDist.data.datasets  = []; chartGroupDist.update('none');
  chartCurveBest.data.datasets  = []; chartCurveBest.update('none');
  chartCurveGroups.data.datasets= []; chartCurveGroups.update('none');

  // 結論
  const best = lumpIds[0];
  const br   = lumpRes[best];
  const dcaBestRet = dcaResults[best] && dcaBestPerETF[best]
    ? dcaResults[best][dcaBestPerETF[best]].returnPct : null;

  const detailRows = lumpIds.map(id => {{
    const r   = lumpRes[id];
    const col = ETF_COLORS[id] || '#888';
    const rc  = r.returnPct >= 0 ? 'var(--green)' : 'var(--red)';
    const cc  = r.cagr >= 0 ? 'var(--green)' : 'var(--red)';
    const profit = r.finalValue - r.totalCost;
    return `<div style="border:1px solid var(--border);border-radius:8px;padding:.6rem .9rem;margin-bottom:.5rem">
      <div style="font-weight:700;margin-bottom:.35rem">
        <span class="etf-badge" style="background:${{col}}22;color:${{col}};border:1px solid ${{col}}44">${{id}}</span>
        <span style="font-size:.8rem;color:var(--muted);margin-left:.3rem">${{ETF_DB[id].name.split(' ').slice(1).join(' ')}}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:.2rem .8rem;font-size:.82rem">
        <span>總報酬：<b style="color:${{rc}}">${{FMTP(r.returnPct)}}</b></span>
        <span>年化報酬：<b style="color:${{cc}}">${{FMTP(r.cagr)}}</b></span>
        <span>總投入：<b>NT$ ${{FMT(r.totalCost)}}</b></span>
        <span>總獲益：<b style="color:${{rc}}">NT$ ${{FMT(profit)}}</b></span>
        <span>最終市值：<b>NT$ ${{FMT(r.finalValue)}}</b></span>
      </div>
    </div>`;
  }}).join('');

  document.getElementById('conclusion').innerHTML =
    '<div class="c-card"><h3>📍 單筆買入持有</h3>' +
    '<p style="margin-bottom:.6rem">進場時機：各標的<span class="hl">回測起點第一個交易日</span>買入，持有至今</p>' +
    detailRows +
    (dcaBestRet !== null ? '<p style="margin-top:.5rem;font-size:.8rem;color:var(--muted)">同期 DCA 最佳：' + FMTP(dcaBestRet) + ' — ' +
      (br.returnPct > dcaBestRet ? '<span class="gr">單筆勝出</span>' : '<span class="rd">DCA 較優</span>') + '</p>' : '') +
    '</div>';
}}


function render() {{
  // ── 計算 DCA 結果 ────────────────────────────────────────────
  const results = {{}};
  const bestPerETF = {{}};

  for (const id of selectedETFs) {{
    const etf = ETF_DB[id];
    const maxYrs = Math.min(currentYears, etf.dataYears);
    if (maxYrs < 0.08) continue;
    const {{ daily, sched, actualYears }} = sliceETF(id, maxYrs);
    if (daily.length < 5) continue;
    results[id] = {{}};
    for (const g of GNAMES) {{
      results[id][g] = runDCA(sched[g], daily, etf.finalPrice, currentAmt, actualYears);
    }}
    bestPerETF[id] = GNAMES.reduce((a,b) => results[id][a].returnPct > results[id][b].returnPct ? a : b);
  }}

  const activeIds = Object.keys(results);
  if (!activeIds.includes(focusETF)) focusETF = activeIds[0] || selectedETFs[0];

  // ── 計算 單筆投入 結果（回測起點一次性買入）────────────────────
  const lumpRes = {{}};
  for (const id of activeIds) {{
    const etf = ETF_DB[id];
    const maxYrs = Math.min(currentYears, etf.dataYears);
    const {{ daily, actualYears }} = sliceETF(id, maxYrs);
    const r = calcLumpSum(daily, etf.finalPrice, currentTotal, actualYears);
    if (r) lumpRes[id] = r;
  }}

  // ── KPI：兩種模式都顯示，排序依目前切換的模式 ──────────────────
  const kpiEl = document.getElementById('kpi-grid');
  const sortedIds = [...activeIds].sort((a, b) => {{
    const sa = investMode === 'dca'
      ? results[a][bestPerETF[a]].returnPct
      : (lumpRes[a]?.returnPct ?? -999);
    const sb = investMode === 'dca'
      ? results[b][bestPerETF[b]].returnPct
      : (lumpRes[b]?.returnPct ?? -999);
    return sb - sa;
  }});
  kpiEl.innerHTML = sortedIds.map(id => {{
    const dcaR  = results[id][bestPerETF[id]];
    const lumpR = lumpRes[id];
    const isDca = investMode === 'dca';
    const primRet  = isDca ? dcaR.returnPct  : (lumpR?.returnPct ?? 0);
    const secRet   = isDca ? (lumpR?.returnPct ?? 0) : dcaR.returnPct;
    const primC    = primRet  >= 0 ? 'pos' : 'neg';
    const secC     = secRet   >= 0 ? 'pos' : 'neg';
    const primLbl  = isDca ? '📈 定期定額' : '📍 單筆投入';
    const secLbl   = isDca ? '📍 單筆投入' : '📈 定期定額';
    const stockClass = id==='2330' ? ' kpi-stock-red' : id==='2454' ? ' kpi-stock-blue' : id==='2308' ? ' kpi-stock-green' : '';
    return '<div class="kpi' + stockClass + '">' +
      '<div class="val ' + primC + '">' + FMTP(primRet) + '</div>' +
      '<div class="lbl">' + id + ' ' + primLbl + '</div>' +
      '<div style="margin-top:.22rem;padding-top:.22rem;border-top:1px solid var(--border)">' +
      '<div class="val ' + secC + '" style="font-size:.92rem">' + FMTP(secRet) + '</div>' +
      '<div class="lbl">' + secLbl + '</div>' +
      '</div></div>';
  }}).join('');

  // ── 若為單筆模式，只更新表格、圖表、結論後返回 ─────────────────
  if (investMode === 'lump') {{
    renderLumpTableCharts(lumpRes, activeIds, results, bestPerETF);
    lastResults = results; lastBestPerETF = bestPerETF;
    renderLayoutTable();
    return;
  }}

  // ── 績效表 ──────────────────────────────────────────────────
  const tbody = document.getElementById('table-body');
  let rows = [];
  for (const id of activeIds) {{
    const etf    = ETF_DB[id];
    const bestG   = bestPerETF[id];
    const sortedG = [...GNAMES].sort((a,b)=>results[id][b].returnPct-results[id][a].returnPct);
    const secondG = sortedG[1];
    const worstG  = GNAMES.reduce((a,b)=>results[id][a].returnPct<results[id][b].returnPct?a:b);
    const safeG   = GNAMES.reduce((a,b)=>results[id][a].maxDrawdown>results[id][b].maxDrawdown?a:b);
    const color  = ETF_COLORS[id] || '#888';

    GNAMES.forEach(g => {{
      const r   = results[id][g];
      const isBest   = g===bestG, isSecond = g===secondG, isWorst = g===worstG, isSafe = g===safeG;
      let tag = '';
      if(isBest)              tag += '<span class="tag tag-best">最佳</span>';
      if(isSecond && !isBest) tag += '<span class="tag tag-second">次優</span>';
      if(isSafe && !isBest)   tag += '<span class="tag tag-safe">最穩</span>';
      if(isWorst && !isBest)  tag += '<span class="tag tag-worst">最差</span>';
      const rc = r.returnPct>=0?'color:var(--green)':'color:var(--red)';
      const cc = r.cagr>=0?'color:var(--green)':'color:var(--red)';
      rows.push(`<tr>
        <td><span class="etf-badge" style="background:${{color}}22;color:${{color}};border:1px solid ${{color}}44">${{id}}</span></td>
        <td>${{g}}${{tag}}</td>
        <td>${{DAYS_LABEL[g]}}</td>
        <td>${{r.trades}}</td>
        <td>NT$ ${{FMT(r.totalCost)}}</td>
        <td>${{r.shares.toFixed(2)}}</td>
        <td>NT$ ${{r.avgCost.toFixed(2)}}</td>
        <td>NT$ ${{FMT(r.finalValue)}}</td>
        <td style="${{rc}};font-weight:700">${{FMTP(r.returnPct)}}</td>
        <td style="${{cc}}">${{FMTP(r.cagr)}}</td>
        <td style="color:var(--red)">${{r.maxDrawdown.toFixed(2)}}%</td>
      </tr>`);
    }});
  }}
  // 恢復 DCA 表頭
  const thEls = document.querySelectorAll('thead th');
  if (thEls.length >= 3) {{ thEls[1].textContent='組合'; thEls[2].textContent='扣款日'; }}
  tbody.innerHTML = rows.join('');

  // ── 最佳組合 Bar charts ──────────────────────────────────────
  const barLabels = activeIds.map(id => id);
  const barBgBest = activeIds.map(id => ETF_COLORS[id]||'#888');

  function updateBar(chart, data, fmtFn, highlight) {{
    chart.data.labels = barLabels;
    chart.data.datasets = [{{
      data,
      backgroundColor: highlight || barBgBest,
      borderRadius:6, borderSkipped:false,
    }}];
    chart.options.scales.y.ticks.callback = fmtFn;
    chart.options.plugins.tooltip.callbacks.label = c=>' '+fmtFn(c.raw);
    chart.update('none');
  }}

  updateBar(chartBestReturn,
    activeIds.map(id=>results[id][bestPerETF[id]].returnPct),
    v=>v.toFixed(2)+'%');
  updateBar(chartBestCagr,
    activeIds.map(id=>results[id][bestPerETF[id]].cagr),
    v=>v.toFixed(2)+'%');
  updateBar(chartBestDD,
    activeIds.map(id=>results[id][bestPerETF[id]].maxDrawdown),
    v=>v.toFixed(2)+'%',
    activeIds.map(id=>{{
      const dd = results[id][bestPerETF[id]].maxDrawdown;
      return dd > -15 ? '#22c55e' : dd > -30 ? '#f59e0b' : '#ef4444';
    }}));

  // 五組分布（grouped bar）
  chartGroupDist.data.labels = activeIds;
  chartGroupDist.data.datasets = GNAMES.map((g,i) => ({{
    label: g,
    data: activeIds.map(id => results[id]?.[g]?.returnPct ?? 0),
    backgroundColor: GROUP_COLORS[i]+'bb',
    borderRadius:4, borderSkipped:false,
  }}));
  chartGroupDist.options.scales.y.ticks.callback = v=>v.toFixed(1)+'%';
  chartGroupDist.update('none');

  // ── 最佳組合成長曲線（可複選）────────────────────────────────
  {{
    // 取最長 ETF 作 x 軸基準
    const refId = activeIds.reduce((a,b) => {{
      const al = sliceETF(a, Math.min(currentYears, ETF_DB[a].dataYears)).daily.length;
      const bl = sliceETF(b, Math.min(currentYears, ETF_DB[b].dataYears)).daily.length;
      return al >= bl ? a : b;
    }});
    const {{ daily:refDaily }} = sliceETF(refId, Math.min(currentYears, ETF_DB[refId].dataYears));

    chartCurveBest.data.labels = refDaily.map(d => d.d);
    chartCurveBest.data.datasets = activeIds.map(id => {{
      const {{ daily }} = sliceETF(id, Math.min(currentYears, ETF_DB[id].dataYears));
      const bg  = bestPerETF[id];
      const pad = refDaily.length - daily.length;
      return {{
        label: id + ' (' + bg + ')',
        data:  [...Array(pad).fill(null), ...results[id][bg].mv],
        borderColor: ETF_COLORS[id] || '#888',
        backgroundColor: 'transparent',
        borderWidth: 2.2, pointRadius: 0, tension: .2,
        spanGaps: false,
        hidden: false,
      }};
    }});
    chartCurveBest.update('none');

    // 複選 toggle 按鈕（每次 render 重建）
    const bestTabRow = document.getElementById('best-curve-tabs');
    bestTabRow.innerHTML = '';

    // 全選 / 全消
    const allBtn = document.createElement('button');
    allBtn.className = 'tab-btn active';
    allBtn.textContent = '全部';
    allBtn.onclick = () => {{
      const anyHidden = chartCurveBest.data.datasets.some(ds => ds.hidden);
      chartCurveBest.data.datasets.forEach(ds => ds.hidden = !anyHidden);
      chartCurveBest.update('none');
      // 同步各 ETF 按鈕狀態
      bestTabRow.querySelectorAll('.tab-btn[data-etf]').forEach(b => {{
        b.classList.toggle('active', !anyHidden);
      }});
      allBtn.classList.toggle('active', !anyHidden);
    }};
    bestTabRow.appendChild(allBtn);

    // 各 ETF 按鈕
    activeIds.forEach((id, i) => {{
      const color = ETF_COLORS[id] || '#888';
      const btn   = document.createElement('button');
      btn.className   = 'tab-btn active';
      btn.dataset.etf = id;
      btn.style.borderLeft = `3px solid ${{color}}`;
      btn.textContent = id;
      btn.onclick = () => {{
        const ds = chartCurveBest.data.datasets[i];
        ds.hidden = !ds.hidden;
        btn.classList.toggle('active', !ds.hidden);
        // 全部顯示時同步全選按鈕
        const allVisible = chartCurveBest.data.datasets.every(d => !d.hidden);
        allBtn.classList.toggle('active', allVisible);
        chartCurveBest.update('none');
      }};
      bestTabRow.appendChild(btn);
    }});
  }}

  // ── 單一 ETF 五組曲線 ────────────────────────────────────────
  rebuildGroupCurveTabs(results);
  updateGroupCurveChart(results);

  // ── 結論 ────────────────────────────────────────────────────
  const best = activeIds.reduce((a,b)=>
    results[a][bestPerETF[a]].returnPct > results[b][bestPerETF[b]].returnPct ? a : b);
  const safe = activeIds.reduce((a,b)=>
    results[a][bestPerETF[a]].maxDrawdown > results[b][bestPerETF[b]].maxDrawdown ? a : b);
  const bestR = results[best][bestPerETF[best]];
  const safeR = results[safe][bestPerETF[safe]];

  document.getElementById('conclusion').innerHTML = [
    {{
      t:'🏆 最佳報酬標的',
      h:`<p>標的：<span class="hl">${{ETF_DB[best].name}}</span></p>
         <p style="margin-top:.3rem">最佳扣款組合：<span class="hl">${{bestPerETF[best]}}（${{DAYS_LABEL[bestPerETF[best]]}}）</span></p>
         <ul style="margin-top:.5rem">
           <li>總報酬：<span class="${{bestR.returnPct>=0?'gr':'rd'}} hl">${{FMTP(bestR.returnPct)}}</span></li>
           <li>年化報酬：<span class="${{bestR.cagr>=0?'gr':'rd'}} hl">${{FMTP(bestR.cagr)}}</span></li>
           <li>總投入：NT$ ${{FMT(bestR.totalCost)}}</li>
           <li>總獲益：NT$ ${{FMT(bestR.finalValue - bestR.totalCost)}}</li>
           <li>最終市值：NT$ ${{FMT(bestR.finalValue)}}</li>
         </ul>`
    }},
    {{
      t:'🛡️ 最低回撤標的',
      h:`<p>標的：<span class="hl">${{ETF_DB[safe].name}}</span></p>
         <p style="margin-top:.3rem">最佳扣款組合：<span class="hl">${{bestPerETF[safe]}}（${{DAYS_LABEL[bestPerETF[safe]]}}）</span></p>
         <ul style="margin-top:.5rem">
           <li>最大回撤：<span class="hl">${{safeR.maxDrawdown.toFixed(2)}}%</span></li>
           <li>年化報酬：${{FMTP(safeR.cagr)}}</li>
         </ul>`
    }},
    {{
      t:'📅 扣款日效應',
      h:`<ul>
           <li>各組扣款日報酬差距普遍 <span class="hl">< 2%</span>，時機影響有限</li>
           <li>定期定額透過時間分散已大幅降低進場時機風險</li>
           <li>月中偏前（4/9…）在多數標的略優，可能反映台股<span class="hl">月初換手效應</span></li>
         </ul>`
    }},
    {{
      t:'💡 實務建議',
      h:`<ul>
           <li>資料期間較短（< 1年）的標的 CAGR 參考性較低</li>
           <li>建議以 <span class="hl">3年以上</span> 回測結果作為主要參考</li>
           <li>多標的分散持有可進一步降低單一 ETF 風險</li>
           <li>歷史績效不代表未來；建議長期持有、定期再平衡</li>
         </ul>`
    }},
  ].map(c=>`<div class="c-card"><h3>${{c.t}}</h3>${{c.h}}</div>`).join('');

  // 儲存結果供佈局配置表使用，並重繪
  lastResults    = results;
  lastBestPerETF = bestPerETF;
  renderLayoutTable();
}}

// ════════════════════════════════════════════════════════════════
//  事件監聽
// ════════════════════════════════════════════════════════════════
document.querySelectorAll('.year-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.year-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    currentYears = parseFloat(btn.dataset.y);
    calcPerTrade();
    render();
  }});
}});

let debounce;
document.getElementById('invest-total').addEventListener('input', e => {{
  clearTimeout(debounce);
  debounce = setTimeout(() => {{
    const v = parseInt(e.target.value, 10);
    if (v >= 1000) {{ currentTotal = v; calcPerTrade(); render(); }}
  }}, 300);
}});

document.querySelectorAll('#mode-toggle .toggle-opt').forEach(opt => {{
  opt.addEventListener('click', () => {{
    if (opt.dataset.mode === investMode) return;
    investMode = opt.dataset.mode;
    syncToggleUI();
    showToast(investMode === 'lump' ? '📍 單筆投入' : '📈 定期定額模式');
    render();
  }});
}});

// ── 收摺區塊 ────────────────────────────────────────────────────
document.querySelectorAll('.section-title[data-sec]').forEach(title => {{
  title.addEventListener('click', () => {{
    const body = document.getElementById(title.dataset.sec);
    const closing = !title.classList.contains('collapsed');
    title.classList.toggle('collapsed', closing);
    body.classList.toggle('collapsed', closing);
  }});
}});

// ── 鍵盤快捷鍵 ──────────────────────────────────────────────────
const kbToast = document.getElementById('kb-toast');
let kbTimer;
function showToast(msg) {{
  kbToast.textContent = msg;
  kbToast.classList.add('show');
  clearTimeout(kbTimer);
  kbTimer = setTimeout(() => kbToast.classList.remove('show'), 1600);
}}

function applyChartTheme(isLight) {{
  const tc = isLight ? '#475569' : '#94a3b8';
  const gc = isLight ? '#e2e8f0' : '#2a2d3e';
  const allCharts = [chartBestReturn, chartBestCagr, chartBestDD,
                     chartGroupDist, chartCurveBest, chartCurveGroups];
  allCharts.forEach(ch => {{
    Object.values(ch.options.scales || {{}}).forEach(sc => {{
      if (sc.ticks) sc.ticks.color = tc;
      if (sc.grid)  sc.grid.color  = gc;
    }});
    if (ch.options.plugins?.legend?.labels) ch.options.plugins.legend.labels.color = tc;
    ch.update('none');
  }});
}}

document.addEventListener('keydown', e => {{
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'l' || e.key === 'L') {{
    const isLight = document.body.classList.toggle('light');
    applyChartTheme(isLight);
    showToast(isLight ? '☀️ 亮色模式' : '🌙 暗色模式');
  }}
  if (e.key === 'f' || e.key === 'F') {{
    if (!document.fullscreenElement) {{
      document.documentElement.requestFullscreen().catch(()=>{{}});
      showToast('⛶ 全螢幕');
    }} else {{
      document.exitFullscreen();
      showToast('✕ 結束全螢幕');
    }}
  }}
}});

// ════════════════════════════════════════════════════════════════
//  佈局配置表（依績效比例配權重）
// ════════════════════════════════════════════════════════════════
function renderLayoutTable() {{
  const PLAN = [
    {{month:'2026/04', ratio:83,  label:'佈局啟動期'}},
    {{month:'2026/05', ratio:108, label:'五窮（分批加碼）'}},
    {{month:'2026/06', ratio:133, label:'六絕（配置最高峰）'}},
    {{month:'2026/07', ratio:108, label:'七上吊（持盈保泰）'}},
    {{month:'2026/08', ratio:68,  label:'提前佈局完成'}},
  ];

  // 取有效結果的標的（依 selectedETFs 順序，最多顯示 6 支）
  const ETFS = selectedETFs.filter(id => lastResults[id] && lastBestPerETF[id]).slice(0, 6);
  if (ETFS.length === 0) {{
    document.getElementById('layout-wrap').innerHTML =
      '<p style="color:var(--muted);font-size:.82rem;padding:.5rem 0">請至少選擇一個有效標的</p>';
    return;
  }}

  // ── 依各標的最佳報酬率計算配重 ──────────────────────────────
  // 直接以報酬率本身為比例，設 floor=1 防止負報酬標的權重歸零
  const rets    = ETFS.map(id => lastResults[id][lastBestPerETF[id]].returnPct);
  const floored = rets.map(r => Math.max(r, 1));
  const floorSum = floored.reduce((s,v) => s + v, 0);
  const weights = {{}};
  ETFS.forEach((id, i) => {{ weights[id] = floored[i] / floorSum; }});

  const total    = currentTotal;
  const ratioSum = PLAN.reduce((s,r) => s + r.ratio, 0);
  const peakRatio = Math.max.apply(null, PLAN.map(r => r.ratio));

  const TH = 'padding:.45rem .75rem;font-weight:600;border-bottom:1px solid var(--border);white-space:nowrap;color:var(--muted)';

  // ── 表頭 ────────────────────────────────────────────────────
  let html = '<div style="overflow-x:auto;margin-bottom:1.4rem">';
  html += '<table style="width:100%;border-collapse:collapse;font-size:.8rem">';
  html += '<thead>';

  // 第一行：欄位名稱
  html += '<tr style="background:#232636">';
  html += '<th style="' + TH + ';text-align:left">月份</th>';
  html += '<th style="' + TH + ';text-align:left">市場邏輯</th>';
  html += '<th style="' + TH + ';text-align:right">投入占比</th>';
  html += '<th style="' + TH + ';text-align:right">月投入總額</th>';
  for (const etf of ETFS) {{
    const col = ETF_COLORS[etf] || '#888';
    html += '<th style="' + TH + ';text-align:right;border-left:2px solid ' + col + '44">' + etf + '</th>';
  }}
  html += '</tr>';

  // 第二行：績效配重
  html += '<tr style="background:#1a1d27">';
  html += '<td style="padding:.2rem .75rem;font-size:.7rem;color:var(--muted)" colspan="4">績效配重</td>';
  for (const etf of ETFS) {{
    const col  = ETF_COLORS[etf] || '#888';
    const wPct = (weights[etf] * 100).toFixed(1);
    const ret  = lastResults[etf][lastBestPerETF[etf]].returnPct;
    const retStr = (ret >= 0 ? '+' : '') + ret.toFixed(2) + '%';
    html += '<td style="padding:.2rem .75rem;text-align:right;font-size:.7rem;color:' + col + ';border-left:2px solid ' + col + '44">';
    html += wPct + '% <span style="color:var(--muted)">(' + retStr + ')</span></td>';
  }}
  html += '</tr>';
  html += '</thead><tbody>';

  // ── 資料列 ──────────────────────────────────────────────────
  let grandTotal = 0;
  const etfTotals = {{}};
  for (const etf of ETFS) {{ etfTotals[etf] = 0; }}

  for (const row of PLAN) {{
    const monthly = Math.round(total * row.ratio / ratioSum);
    const pct     = (row.ratio / ratioSum * 100).toFixed(1);
    grandTotal   += monthly;
    const rowBg   = row.ratio === peakRatio ? 'background:rgba(79,142,247,.08);' : '';
    html += '<tr style="border-bottom:1px solid var(--border);' + rowBg + '">';
    html += '<td style="padding:.45rem .75rem;font-weight:600;white-space:nowrap">' + row.month + '</td>';
    html += '<td style="padding:.45rem .75rem;color:var(--muted)">' + row.label + '</td>';
    html += '<td style="padding:.45rem .75rem;text-align:right;color:var(--accent)">' + pct + '%</td>';
    html += '<td style="padding:.45rem .75rem;text-align:right;font-weight:700">NT$ ' + monthly.toLocaleString('zh-TW') + '</td>';
    for (const etf of ETFS) {{
      const amt      = Math.round(monthly * weights[etf]);
      const perTrade = Math.round(amt / 6);
      etfTotals[etf] += amt;
      const col = ETF_COLORS[etf] || '#888';
      html += '<td style="padding:.45rem .75rem;text-align:right;border-left:2px solid ' + col + '22">';
      html += '<span style="font-weight:700">NT$ ' + amt.toLocaleString('zh-TW') + '</span>';
      html += '<br><span style="font-size:.68rem;color:var(--muted)">6筆 × NT$ ' + perTrade.toLocaleString('zh-TW') + '</span>';
      html += '</td>';
    }}
    html += '</tr>';
  }}

  // ── 合計列 ──────────────────────────────────────────────────
  html += '<tr style="background:#232636;font-weight:700;border-top:2px solid var(--border)">';
  html += '<td style="padding:.45rem .75rem">合計</td>';
  html += '<td style="padding:.45rem .75rem;color:var(--muted)">5個月完成佈局</td>';
  html += '<td style="padding:.45rem .75rem;text-align:right;color:var(--accent)">100%</td>';
  html += '<td style="padding:.45rem .75rem;text-align:right;color:var(--green)">NT$ ' + grandTotal.toLocaleString('zh-TW') + '</td>';
  for (const etf of ETFS) {{
    const col = ETF_COLORS[etf] || '#888';
    html += '<td style="padding:.45rem .75rem;text-align:right;color:var(--green);border-left:2px solid ' + col + '44">NT$ ' + etfTotals[etf].toLocaleString('zh-TW') + '</td>';
  }}
  html += '</tr></tbody></table></div>';

  // ── 說明 ─────────────────────────────────────────────────────
  const wDesc = ETFS.map(id => id + ' ' + (weights[id]*100).toFixed(1) + '%').join('、');
  html += '<p style="font-size:.76rem;color:var(--muted);margin-bottom:1rem">';
  html += '＊ 倒金字塔配置比例（83/108/133/108/68）；各標的依回測最佳報酬率加權分配：' + wDesc + '。總計 = 總投入資金。</p>';

  document.getElementById('layout-wrap').innerHTML = html;
}}

// 首次渲染
calcPerTrade();
render(); // render() 末尾會呼叫 renderLayoutTable()
</script>
</body>
</html>"""

out = Path('index.html')
out.write_text(HTML, encoding='utf-8')
print(f'HTML 產生完成：{out}  ({out.stat().st_size//1024} KB)')
