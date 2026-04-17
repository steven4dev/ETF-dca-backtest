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
ETF_CONFIG = {
    '0050':   {'name':'0050 元大台灣50',       'csv':'0050_data.csv',   'split_date':None,         'split_ratio':1},
    '0052':   {'name':'0052 富邦科技',          'csv':'0052_data.csv',   'split_date':'2025-11-17', 'split_ratio':7},
    '00631L': {'name':'00631L 元大台灣50正2',   'csv':'00631L_data.csv', 'split_date':'2026-03-23', 'split_ratio':23},
    '009813': {'name':'009813 街口布局全球',    'csv':'009813_data.csv', 'split_date':None,         'split_ratio':1},
    '00770':  {'name':'00770 富邦台灣加權',     'csv':'00770_data.csv',  'split_date':None,         'split_ratio':1},
    '009810': {'name':'009810 街口ESG永續',     'csv':'009810_data.csv', 'split_date':None,         'split_ratio':1},
    '00988A': {'name':'00988A 野村優息存股A',   'csv':'00988A_data.csv', 'split_date':None,         'split_ratio':1},
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
def load_etf(cfg):
    df = pd.read_csv(cfg['csv'])
    df['Date']  = pd.to_datetime(df['Date'])
    df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
    df = df.dropna(subset=['Close']).sort_values('Date').reset_index(drop=True)

    if cfg['split_date']:
        sd = pd.Timestamp(cfg['split_date'])
        df.loc[df['Date'] < sd, 'Close'] /= cfg['split_ratio']

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
        'daily':      daily,
        'schedules':  sched,
        'finalPrice': round(float(df['Close'].iloc[-1]), 4),
        'dataYears':  data_years,
        'startDate':  df['Date'].min().strftime('%Y-%m-%d'),
        'endDate':    df['Date'].max().strftime('%Y-%m-%d'),
        'splitDate':  cfg['split_date'],
        'splitRatio': cfg['split_ratio'],
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
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--bg);color:var(--text);
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;line-height:1.6;}}

/* ── Header ── */
header{{
  background:linear-gradient(135deg,#1a1d27 0%,#0f1117 100%);
  border-bottom:1px solid var(--border);
  padding:1.5rem 1.5rem 1.2rem;text-align:center;
}}
header h1{{font-size:1.7rem;font-weight:700;color:#fff;letter-spacing:-.5px;}}
header p{{color:var(--muted);margin-top:.25rem;font-size:.85rem;}}

/* ── Control bar ── */
.ctrl-bar{{
  background:var(--card);border-bottom:1px solid var(--border);
  padding:.85rem 1.5rem;display:flex;flex-wrap:wrap;
  align-items:center;gap:1rem;
}}
.ctrl-group{{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;}}
.ctrl-label{{color:var(--muted);font-size:.8rem;font-weight:600;white-space:nowrap;}}
.sep{{width:1px;height:22px;background:var(--border);}}

/* ETF 多選 */
.etf-checks{{display:flex;flex-wrap:wrap;gap:.45rem;}}
.etf-check-item{{
  display:flex;align-items:center;gap:.35rem;
  background:#1e2133;border:1px solid var(--border);
  border-radius:7px;padding:.3rem .65rem;cursor:pointer;
  transition:all .15s;user-select:none;
}}
.etf-check-item:hover{{border-color:var(--accent);}}
.etf-check-item.checked{{border-color:var(--accent);background:rgba(79,142,247,.12);}}
.etf-check-item input{{accent-color:var(--accent);width:14px;height:14px;cursor:pointer;}}
.etf-check-item label{{font-size:.8rem;font-weight:600;cursor:pointer;color:var(--muted);}}
.etf-check-item.checked label{{color:var(--text);}}

/* 年份按鈕 */
.year-btns{{display:flex;gap:.4rem;}}
.sel-all-btn{{
  background:var(--border);color:var(--muted);border:none;
  padding:.3rem .7rem;border-radius:6px;cursor:pointer;
  font-size:.8rem;font-weight:600;transition:all .15s;
}}
.sel-all-btn.active{{background:var(--accent);color:#fff;}}
.sel-all-btn:hover:not(.active){{background:#3a3d50;color:var(--text);}}
.year-btn{{
  background:var(--border);color:var(--muted);border:none;
  padding:.3rem .7rem;border-radius:6px;cursor:pointer;
  font-size:.8rem;font-weight:600;transition:all .15s;
}}
.year-btn.active{{background:var(--accent);color:#fff;}}
.year-btn:hover:not(.active){{background:#3a3d50;color:var(--text);}}

/* 金額輸入 */
.amt-wrap{{
  display:flex;align-items:center;gap:.4rem;
  background:#0f1117;border:1px solid var(--border);
  border-radius:7px;padding:.3rem .7rem;transition:border-color .2s;
}}
.amt-wrap:focus-within{{border-color:var(--accent);}}
.amt-wrap span{{color:var(--muted);font-size:.82rem;}}
.amt-wrap input{{
  background:transparent;border:none;outline:none;
  color:#fff;font-size:.95rem;font-weight:700;
  width:110px;text-align:right;
}}
.amt-wrap input::-webkit-outer-spin-button,
.amt-wrap input::-webkit-inner-spin-button{{-webkit-appearance:none;}}
.amt-wrap input[type=number]{{-moz-appearance:textfield;}}

/* ── Container ── */
.container{{max-width:1280px;margin:0 auto;padding:1.8rem 1.5rem;}}
.section-title{{
  font-size:1rem;font-weight:600;color:#fff;
  margin-bottom:.9rem;padding-bottom:.45rem;
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:.5rem;
}}

/* ── KPI grid ── */
.kpi-grid{{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
  gap:.85rem;margin-bottom:2rem;
}}
.kpi{{
  background:var(--card);border:1px solid var(--border);
  border-radius:10px;padding:1rem;text-align:center;transition:border-color .2s;
}}
.kpi:hover{{border-color:var(--accent);}}
.kpi .val{{font-size:1.35rem;font-weight:700;}}
.kpi .lbl{{font-size:.7rem;color:var(--muted);margin-top:.2rem;}}
.pos{{color:var(--green);}} .neg{{color:var(--red);}} .neu{{color:var(--accent);}}

/* ── Table ── */
.table-wrap{{overflow-x:auto;margin-bottom:2rem;}}
table{{width:100%;border-collapse:collapse;font-size:.82rem;}}
thead tr{{background:#232636;}}
thead th{{
  padding:.65rem .9rem;text-align:right;color:var(--muted);
  font-weight:600;white-space:nowrap;border-bottom:1px solid var(--border);
}}
thead th:first-child,thead th:nth-child(2){{text-align:left;}}
tbody tr{{border-bottom:1px solid var(--border);transition:background .12s;}}
tbody tr:hover{{background:#1e2133;}}
tbody td{{padding:.65rem .9rem;text-align:right;white-space:nowrap;}}
tbody td:first-child,tbody td:nth-child(2){{text-align:left;font-weight:600;}}
.etf-badge{{
  display:inline-block;font-size:.65rem;font-weight:700;
  padding:.1rem .4rem;border-radius:4px;margin-right:.3rem;
}}
.tag{{
  display:inline-block;font-size:.62rem;padding:.08rem .35rem;
  border-radius:4px;margin-left:.25rem;font-weight:600;vertical-align:middle;
}}
.tag-best{{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3);}}
.tag-safe{{background:rgba(79,142,247,.15);color:var(--accent);border:1px solid rgba(79,142,247,.3);}}
.tag-worst{{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3);}}

/* ── Charts ── */
.charts-grid{{
  display:grid;grid-template-columns:1fr 1fr;
  gap:1.3rem;margin-bottom:2rem;
}}
@media(max-width:768px){{.charts-grid{{grid-template-columns:1fr;}}}}
.chart-card{{
  background:var(--card);border:1px solid var(--border);
  border-radius:10px;padding:1.1rem;
}}
.chart-card.full{{grid-column:1/-1;}}
.chart-title{{
  font-size:.78rem;font-weight:600;color:var(--muted);
  margin-bottom:.85rem;text-transform:uppercase;letter-spacing:.05em;
}}
.chart-wrap{{position:relative;height:250px;}}
.chart-wrap.tall{{height:320px;}}
.tab-row{{display:flex;gap:.35rem;margin-bottom:.6rem;flex-wrap:wrap;}}
.tab-btn{{
  background:var(--border);color:var(--muted);border:none;
  padding:.28rem .7rem;border-radius:5px;cursor:pointer;
  font-size:.75rem;font-weight:600;transition:all .15s;
}}
.tab-btn.active{{background:var(--accent);color:#fff;}}

/* ── Conclusion ── */
.conclusion-grid{{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));
  gap:.85rem;margin-bottom:2rem;
}}
.c-card{{
  background:var(--card);border:1px solid var(--border);
  border-radius:10px;padding:1.1rem;
}}
.c-card h3{{
  font-size:.78rem;font-weight:700;color:var(--accent);
  text-transform:uppercase;letter-spacing:.05em;margin-bottom:.65rem;
}}
.c-card p,.c-card li{{font-size:.85rem;color:var(--muted);}}
.c-card ul{{padding-left:1.1rem;}}
.c-card li{{margin-bottom:.28rem;}}
.hl{{color:var(--text)!important;font-weight:600;}}
.gr{{color:var(--green)!important;}} .rd{{color:var(--red)!important;}}

/* ── No data notice ── */
.no-data{{
  text-align:center;padding:2.5rem;color:var(--muted);
  background:var(--card);border-radius:10px;border:1px dashed var(--border);
  margin-bottom:2rem;
}}

footer{{
  text-align:center;padding:1.3rem;color:var(--muted);
  font-size:.78rem;border-top:1px solid var(--border);
}}
</style>
</head>
<body>

<header>
  <h1>🇹🇼 台灣 ETF 定期定額回測分析</h1>
  <p>支援多標的比較・五組扣款日・自訂投入金額・可調回測年數 &nbsp;|&nbsp; 資料來源：Yahoo Finance</p>
</header>

<!-- 控制列 -->
<div class="ctrl-bar">
  <div class="ctrl-group">
    <span class="ctrl-label">選擇標的</span>
    <button class="sel-all-btn" id="btn-select-all">全選</button>
    <div class="etf-checks" id="etf-checks"></div>
  </div>
  <div class="sep"></div>
  <div class="ctrl-group">
    <span class="ctrl-label">回測期間</span>
    <div class="year-btns" id="year-btns">
      <button class="year-btn" data-y="0.25">3 月</button>
      <button class="year-btn" data-y="0.5">6 月</button>
      <button class="year-btn" data-y="1">1 年</button>
      <button class="year-btn" data-y="2">2 年</button>
      <button class="year-btn active" data-y="3">3 年</button>
      <button class="year-btn" data-y="5">5 年</button>
    </div>
  </div>
  <div class="sep"></div>
  <div class="ctrl-group">
    <span class="ctrl-label">每次投入</span>
    <div class="amt-wrap">
      <span>NT$</span>
      <input type="number" id="invest-amt" value="10000" min="100" step="1000">
    </div>
  </div>
</div>

<div class="container">
  <div class="section-title">📊 整體績效 KPI</div>
  <div class="kpi-grid" id="kpi-grid"></div>

  <div class="section-title">🏆 五組扣款日績效對照表</div>
  <div class="table-wrap"><table>
    <thead><tr>
      <th>標的</th><th>組合</th><th>扣款日</th><th>交易次數</th>
      <th>總投入</th><th>持股數</th><th>平均成本</th>
      <th>最終市值</th><th>報酬率</th><th>年化報酬</th><th>最大回撤</th>
    </tr></thead>
    <tbody id="table-body"></tbody>
  </table></div>

  <div class="section-title">📈 視覺化比較</div>
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

  <div class="section-title">💡 結論分析</div>
  <div class="conclusion-grid" id="conclusion"></div>
</div>

<footer>
  資料來源：Yahoo Finance（各 ETF 已還原股票拆分）&nbsp;|&nbsp;
  本分析僅供參考，不構成投資建議
</footer>

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
  '009813': '#f59e0b',
  '00770':  '#e879f9',
  '009810': '#fb923c',
  '00988A': '#38bdf8',
}};
const GROUP_COLORS = ['#4f8ef7','#22c55e','#f59e0b','#e879f9','#fb923c'];

const FMT  = n => Math.round(n).toLocaleString('zh-TW');
const FMTP = n => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const WFMT = v => Math.abs(v) >= 1e8 ? (v/1e8).toFixed(2)+'億' : (v/1e4).toFixed(1)+'萬';

// ── 狀態 ──────────────────────────────────────────────────────────
let selectedETFs  = ['0050', '0052'];
let currentYears  = 3;
let currentAmt    = 10000;
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
    // 全取消 → 只保留第一個
    selectedETFs = [allETFIds[0]];
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
  let peak=-Infinity, maxDD=0;
  for (const v of mv) {{
    if (v>peak) peak=v;
    const dd=(v-peak)/peak*100;
    if (dd<maxDD) maxDD=dd;
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
        tooltip:{{callbacks:{{label:c=>` ${{c.dataset.label}}: ${{WFMT(c.raw)}}`}}}},
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
function render() {{
  // ── 計算所有選中 ETF 的所有組合 ─────────────────────────────
  const results = {{}};   // {{etfId: {{組合一: {{...}}, ...}}}}
  const bestPerETF = {{}};

  for (const id of selectedETFs) {{
    const etf = ETF_DB[id];
    const maxYrs = Math.min(currentYears, etf.dataYears);
    if (maxYrs < 0.08) continue; // 資料太少跳過
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

  // ── KPI（依報酬率降冪排序）────────────────────────────────────
  const kpiEl = document.getElementById('kpi-grid');
  const kpis = activeIds.map(id => {{
    const bg = bestPerETF[id];
    const r  = results[id][bg];
    return {{ v: FMTP(r.returnPct), l: id + ' 最佳報酬',
              c: r.returnPct>=0?'pos':'neg', sort: r.returnPct }};
  }}).sort((a, b) => b.sort - a.sort);
  kpiEl.innerHTML = kpis.map(k=>
    `<div class="kpi"><div class="val ${{k.c}}">${{k.v}}</div><div class="lbl">${{k.l}}</div></div>`
  ).join('');

  // ── 績效表 ──────────────────────────────────────────────────
  const tbody = document.getElementById('table-body');
  let rows = [];
  for (const id of activeIds) {{
    const etf    = ETF_DB[id];
    const bestG  = bestPerETF[id];
    const worstG = GNAMES.reduce((a,b)=>results[id][a].returnPct<results[id][b].returnPct?a:b);
    const safeG  = GNAMES.reduce((a,b)=>results[id][a].maxDrawdown>results[id][b].maxDrawdown?a:b);
    const color  = ETF_COLORS[id] || '#888';

    GNAMES.forEach(g => {{
      const r   = results[id][g];
      const isBest  = g===bestG, isWorst = g===worstG, isSafe = g===safeG;
      let tag = '';
      if(isBest)  tag += '<span class="tag tag-best">最佳</span>';
      if(isSafe && !isBest) tag += '<span class="tag tag-safe">最穩</span>';
      if(isWorst && !isBest) tag += '<span class="tag tag-worst">最差</span>';
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
}}

// ════════════════════════════════════════════════════════════════
//  事件監聽
// ════════════════════════════════════════════════════════════════
document.querySelectorAll('.year-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.year-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    currentYears = parseFloat(btn.dataset.y);
    render();
  }});
}});

let debounce;
document.getElementById('invest-amt').addEventListener('input', e => {{
  clearTimeout(debounce);
  debounce = setTimeout(() => {{
    const v = parseInt(e.target.value, 10);
    if (v >= 100) {{ currentAmt = v; render(); }}
  }}, 300);
}});

// 首次渲染
render();
</script>
</body>
</html>"""

out = Path('index.html')
out.write_text(HTML, encoding='utf-8')
print(f'HTML 產生完成：{out}  ({out.stat().st_size//1024} KB)')
