"""
產生 0052 定期定額分析的互動式 HTML（for GitHub Pages）
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
import json, base64

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        return super().default(obj)
from pathlib import Path

# ── 讀取資料（與主程式相同邏輯）────────────────────────────────────────
CSV_PATH      = "0052 ETF Stock Price History.csv"
INVEST_PER_TRADE = 10_000
SHARE_DECIMALS   = 4

GROUPS = {
    "組合一": [1, 6, 11, 16, 21, 26, 31],
    "組合二": [2, 7, 12, 17, 22, 27],
    "組合三": [3, 8, 13, 18, 23, 28],
    "組合四": [4, 9, 14, 19, 24, 29],
    "組合五": [5, 10, 15, 20, 25, 30],
}
GROUP_DAYS_LABEL = {
    "組合一": "1/6/11/16/21/26/31",
    "組合二": "2/7/12/17/22/27",
    "組合三": "3/8/13/18/23/28",
    "組合四": "4/9/14/19/24/29",
    "組合五": "5/10/15/20/25/30",
}

df_raw = pd.read_csv(CSV_PATH)
df_raw.columns = [c.strip().strip('"') for c in df_raw.columns]
df_raw.rename(columns={'Date':'Date','Price':'Close','Open':'Open',
                        'High':'High','Low':'Low','Vol.':'Volume','Change %':'Change'}, inplace=True)
df_raw['Date']  = pd.to_datetime(df_raw['Date'], format='%m/%d/%Y')
df_raw['Close'] = df_raw['Close'].astype(str).str.replace(',','').astype(float)
df_raw.sort_values('Date', inplace=True)
df_raw.reset_index(drop=True, inplace=True)

latest_date    = df_raw['Date'].max()
earliest_date  = df_raw['Date'].min()
target_start   = latest_date - pd.DateOffset(years=3)
backtest_start = earliest_date if earliest_date > target_start else target_start

df = df_raw[df_raw['Date'] >= backtest_start].copy().reset_index(drop=True)
trading_dates = pd.DatetimeIndex(df['Date'].values)
close_series  = df.set_index('Date')['Close']
final_price   = close_series.iloc[-1]
actual_years  = (latest_date - df['Date'].min()).days / 365.25

def next_trading_day(target_date, trading_dates):
    idx = trading_dates.searchsorted(target_date)
    return trading_dates[idx] if idx < len(trading_dates) else None

def run_backtest(payment_days):
    transactions = []
    start = df['Date'].min()
    end   = latest_date
    current = start.replace(day=1)
    while current <= end:
        for day in payment_days:
            try:
                target = current.replace(day=day)
            except ValueError:
                continue
            if target < start or target > end:
                continue
            actual = next_trading_day(target, trading_dates)
            if actual is None:
                continue
            price  = close_series.loc[actual]
            shares = round(INVEST_PER_TRADE / price, SHARE_DECIMALS)
            transactions.append({'trade_date': actual, 'price': price,
                                  'shares': shares, 'cost': INVEST_PER_TRADE})
        current = current.replace(month=current.month % 12 + 1,
                                   year=current.year + (1 if current.month == 12 else 0))

    txn_df = pd.DataFrame(transactions)
    txn_df = txn_df.groupby('trade_date', as_index=False).agg(
        shares=('shares','sum'), cost=('cost','sum'), price=('price','first'))
    txn_df.sort_values('trade_date', inplace=True)

    cum_shares = 0; cum_cost = 0
    daily_records = []
    txn_map = txn_df.set_index('trade_date')
    for _, row in df.iterrows():
        date  = row['Date']
        price = row['Close']
        if date in txn_map.index:
            cum_shares += txn_map.loc[date,'shares']
            cum_cost   += txn_map.loc[date,'cost']
        daily_records.append({'date': date.strftime('%Y-%m-%d'),
                               'market_value': round(cum_shares * price, 0),
                               'cum_cost':     cum_cost})
    return txn_df, daily_records

# ── 執行回測 ──────────────────────────────────────────────────────────
all_results = {}
all_curves  = {}

for gname, days in GROUPS.items():
    txn_df, daily = run_backtest(days)
    total_cost   = txn_df['cost'].sum()
    total_shares = txn_df['shares'].sum()
    avg_cost     = total_cost / total_shares if total_shares > 0 else 0
    final_value  = total_shares * final_price
    total_return = (final_value - total_cost) / total_cost * 100
    cagr         = ((final_value / total_cost) ** (1/actual_years) - 1) * 100 if actual_years > 0 else 0

    mv = pd.Series([d['market_value'] for d in daily])
    rolling_max  = mv.cummax()
    max_drawdown = ((mv - rolling_max) / rolling_max).min() * 100

    all_results[gname] = {
        'label':       gname,
        'days_label':  GROUP_DAYS_LABEL[gname],
        'trades':      len(txn_df),
        'total_cost':  int(total_cost),
        'total_shares':round(total_shares, 2),
        'avg_cost':    round(avg_cost, 2),
        'final_value': int(final_value),
        'return_pct':  round(total_return, 2),
        'cagr':        round(cagr, 2),
        'max_drawdown':round(max_drawdown, 2),
    }
    all_curves[gname] = daily

# ── 讀取圖片轉 base64 ─────────────────────────────────────────────────
img_b64 = ""
img_path = Path("0052_DCA_Analysis.png")
if img_path.exists():
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

# ── 準備 JS 資料 ──────────────────────────────────────────────────────
results_json = json.dumps(all_results, ensure_ascii=False, cls=NpEncoder)
curves_json  = json.dumps(all_curves,  ensure_ascii=False, cls=NpEncoder)
date_labels  = json.dumps([d['date'] for d in all_curves['組合一']])

best_group   = max(all_results, key=lambda g: all_results[g]['return_pct'])
safest_group = max(all_results, key=lambda g: all_results[g]['max_drawdown'])

# ── HTML 模板 ─────────────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>0052 富邦科技 定期定額回測分析</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d3e;
    --accent: #4f8ef7;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #f59e0b;
    --text: #e2e8f0;
    --muted: #94a3b8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    line-height: 1.6;
  }}
  header {{
    background: linear-gradient(135deg, #1a1d27 0%, #0f1117 100%);
    border-bottom: 1px solid var(--border);
    padding: 2rem 1.5rem;
    text-align: center;
  }}
  header h1 {{ font-size: 1.8rem; font-weight: 700; color: #fff; letter-spacing: -0.5px; }}
  header p  {{ color: var(--muted); margin-top: .4rem; font-size: .9rem; }}
  .badge {{
    display: inline-block;
    background: var(--accent);
    color: #fff;
    font-size: .7rem;
    font-weight: 600;
    padding: .15rem .55rem;
    border-radius: 999px;
    margin-left: .5rem;
    vertical-align: middle;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem; }}
  .section-title {{
    font-size: 1.1rem;
    font-weight: 600;
    color: #fff;
    margin-bottom: 1rem;
    padding-bottom: .5rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: .5rem;
  }}
  .section-title .icon {{ font-size: 1.1rem; }}

  /* KPI Cards */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem;
    margin-bottom: 2.5rem;
  }}
  .kpi {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem 1rem;
    text-align: center;
    transition: border-color .2s;
  }}
  .kpi:hover {{ border-color: var(--accent); }}
  .kpi .val  {{ font-size: 1.5rem; font-weight: 700; }}
  .kpi .lbl  {{ font-size: .75rem; color: var(--muted); margin-top: .25rem; }}
  .kpi .neg  {{ color: var(--red); }}
  .kpi .pos  {{ color: var(--green); }}
  .kpi .neu  {{ color: var(--accent); }}

  /* Table */
  .table-wrap {{ overflow-x: auto; margin-bottom: 2.5rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  thead tr {{ background: #232636; }}
  thead th {{
    padding: .75rem 1rem;
    text-align: right;
    color: var(--muted);
    font-weight: 600;
    white-space: nowrap;
    border-bottom: 1px solid var(--border);
  }}
  thead th:first-child {{ text-align: left; }}
  tbody tr {{ border-bottom: 1px solid var(--border); transition: background .15s; }}
  tbody tr:hover {{ background: #1e2133; }}
  tbody td {{
    padding: .75rem 1rem;
    text-align: right;
    white-space: nowrap;
  }}
  tbody td:first-child {{ text-align: left; font-weight: 600; }}
  .tag {{
    display: inline-block;
    font-size: .65rem;
    padding: .1rem .4rem;
    border-radius: 4px;
    margin-left: .3rem;
    font-weight: 600;
    vertical-align: middle;
  }}
  .tag-best   {{ background: rgba(34,197,94,.15); color: var(--green); border: 1px solid rgba(34,197,94,.3); }}
  .tag-safe   {{ background: rgba(79,142,247,.15); color: var(--accent); border: 1px solid rgba(79,142,247,.3); }}
  .tag-worst  {{ background: rgba(239,68,68,.15); color: var(--red);  border: 1px solid rgba(239,68,68,.3); }}

  /* Charts */
  .charts-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    margin-bottom: 2.5rem;
  }}
  @media (max-width: 768px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
  .chart-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem;
  }}
  .chart-card.full {{ grid-column: 1 / -1; }}
  .chart-title {{ font-size: .85rem; font-weight: 600; color: var(--muted); margin-bottom: 1rem; text-transform: uppercase; letter-spacing: .05em; }}
  .chart-wrap  {{ position: relative; height: 260px; }}
  .chart-wrap.tall {{ height: 340px; }}

  /* Conclusion */
  .conclusion-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 1rem;
    margin-bottom: 2.5rem;
  }}
  .c-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem;
  }}
  .c-card h3 {{
    font-size: .85rem;
    font-weight: 700;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: .05em;
    margin-bottom: .75rem;
  }}
  .c-card p, .c-card li {{ font-size: .875rem; color: var(--muted); }}
  .c-card ul {{ padding-left: 1.2rem; }}
  .c-card li {{ margin-bottom: .35rem; }}
  .highlight {{ color: var(--text) !important; font-weight: 600; }}
  .green {{ color: var(--green) !important; }}
  .red   {{ color: var(--red)   !important; }}

  /* Static chart image */
  .img-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem;
    margin-bottom: 2.5rem;
    text-align: center;
  }}
  .img-card img {{ max-width: 100%; border-radius: 8px; }}

  footer {{
    text-align: center;
    padding: 1.5rem;
    color: var(--muted);
    font-size: .8rem;
    border-top: 1px solid var(--border);
  }}

  /* Tab buttons */
  .tab-row {{ display: flex; gap: .5rem; margin-bottom: 1rem; flex-wrap: wrap; }}
  .tab-btn {{
    background: var(--border);
    color: var(--muted);
    border: none;
    padding: .4rem .9rem;
    border-radius: 6px;
    cursor: pointer;
    font-size: .8rem;
    font-weight: 600;
    transition: all .15s;
  }}
  .tab-btn.active {{ background: var(--accent); color: #fff; }}
</style>
</head>
<body>

<header>
  <h1>0052 富邦科技<span class="badge">ETF</span> 定期定額回測分析</h1>
  <p>回測期間：{df['Date'].min().strftime('%Y-%m-%d')} ～ {latest_date.strftime('%Y-%m-%d')}
     &nbsp;|&nbsp; {actual_years:.1f} 年 &nbsp;|&nbsp; 每次投入 NT$10,000 &nbsp;|&nbsp; 五組扣款日比較</p>
</header>

<div class="container">

  <!-- KPI -->
  <div style="margin-bottom:1rem">
    <div class="section-title"><span class="icon">📊</span>市場概況</div>
  </div>
  <div class="kpi-grid" id="kpi-row"></div>

  <!-- Table -->
  <div class="section-title"><span class="icon">🏆</span>五組績效對照表</div>
  <div class="table-wrap">
    <table id="perf-table">
      <thead><tr>
        <th>組合</th><th>扣款日</th><th>交易次數</th>
        <th>總投入</th><th>持股數</th><th>平均成本</th>
        <th>最終市值</th><th>報酬率</th><th>年化報酬</th><th>最大回撤</th>
      </tr></thead>
      <tbody id="table-body"></tbody>
    </table>
  </div>

  <!-- Charts -->
  <div class="section-title"><span class="icon">📈</span>視覺化分析</div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-title">總報酬率比較</div>
      <div class="chart-wrap"><canvas id="chart-return"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">年化報酬率（CAGR）</div>
      <div class="chart-wrap"><canvas id="chart-cagr"></canvas></div>
    </div>
    <div class="chart-card full">
      <div class="chart-title">資產市值成長曲線</div>
      <div class="tab-row" id="curve-tabs"></div>
      <div class="chart-wrap tall"><canvas id="chart-curve"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">最大回撤比較</div>
      <div class="chart-wrap"><canvas id="chart-dd"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">最佳 vs 最差 組合對比</div>
      <div class="chart-wrap"><canvas id="chart-vs"></canvas></div>
    </div>
  </div>

  <!-- Static chart -->
  {"" if not img_b64 else f'''
  <div class="section-title"><span class="icon">🖼️</span>完整分析圖表</div>
  <div class="img-card">
    <img src="data:image/png;base64,{img_b64}" alt="完整分析圖">
  </div>
  '''}

  <!-- Conclusion -->
  <div class="section-title"><span class="icon">💡</span>結論分析</div>
  <div class="conclusion-grid" id="conclusion"></div>

</div>

<footer>
  資料來源：0052 富邦科技 歷史股價 &nbsp;|&nbsp;
  分析日期：{latest_date.strftime('%Y-%m-%d')} &nbsp;|&nbsp;
  本分析僅供參考，不構成投資建議
</footer>

<script>
// ── 資料 ──────────────────────────────────────────────────────────────
const RESULTS     = {results_json};
const CURVES      = {curves_json};
const DATE_LABELS = {date_labels};
const BEST_GROUP  = "{best_group}";
const SAFE_GROUP  = "{safest_group}";
const FINAL_PRICE = {final_price};

const COLORS = ['#4f8ef7','#22c55e','#f59e0b','#e879f9','#fb923c'];
const GNAMES = Object.keys(RESULTS);
const FMT    = n => n.toLocaleString('zh-TW');
const FMTP   = n => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';

// ── KPI ──────────────────────────────────────────────────────────────
const kpiData = [
  {{ label:'最後收盤價',    val:'NT$ ' + FINAL_PRICE.toFixed(2),    cls:'neu' }},
  {{ label:'回測期間',      val:'{actual_years:.1f} 年',              cls:'neu' }},
  {{ label:'最佳組合',      val: BEST_GROUP,                          cls:'pos' }},
  {{ label:'最佳報酬率',    val: FMTP(RESULTS[BEST_GROUP].return_pct), cls: RESULTS[BEST_GROUP].return_pct>=0?'pos':'neg' }},
  {{ label:'最佳年化報酬',  val: FMTP(RESULTS[BEST_GROUP].cagr),      cls: RESULTS[BEST_GROUP].cagr>=0?'pos':'neg' }},
  {{ label:'最低風險組合',  val: SAFE_GROUP,                           cls:'neu' }},
];
const kpiRow = document.getElementById('kpi-row');
kpiData.forEach(k => {{
  kpiRow.innerHTML += `<div class="kpi"><div class="val ${{k.cls}}">${{k.val}}</div><div class="lbl">${{k.label}}</div></div>`;
}});

// ── Table ─────────────────────────────────────────────────────────────
const tbody = document.getElementById('table-body');
GNAMES.forEach(g => {{
  const r = RESULTS[g];
  const isBest  = g === BEST_GROUP;
  const isSafe  = g === SAFE_GROUP;
  const isWorst = r.return_pct === Math.min(...GNAMES.map(n=>RESULTS[n].return_pct));
  let tag = '';
  if(isBest)  tag += '<span class="tag tag-best">最佳</span>';
  if(isSafe && g!==BEST_GROUP) tag += '<span class="tag tag-safe">最穩</span>';
  if(isWorst && !isBest) tag += '<span class="tag tag-worst">最差</span>';

  const retCls  = r.return_pct  >= 0 ? 'color:var(--green)' : 'color:var(--red)';
  const cagrCls = r.cagr        >= 0 ? 'color:var(--green)' : 'color:var(--red)';

  tbody.innerHTML += `<tr>
    <td>${{g}}${{tag}}</td>
    <td>${{r.days_label}}</td>
    <td>${{r.trades}}</td>
    <td>NT$ ${{FMT(r.total_cost)}}</td>
    <td>${{r.total_shares.toFixed(2)}}</td>
    <td>NT$ ${{r.avg_cost.toFixed(2)}}</td>
    <td>NT$ ${{FMT(r.final_value)}}</td>
    <td style="${{retCls}};font-weight:700">${{FMTP(r.return_pct)}}</td>
    <td style="${{cagrCls}}">${{FMTP(r.cagr)}}</td>
    <td style="color:var(--red)">${{r.max_drawdown.toFixed(2)}}%</td>
  </tr>`;
}});

// ── Chart helpers ─────────────────────────────────────────────────────
const chartDefaults = {{
  color: '#94a3b8',
  plugins: {{ legend: {{ labels: {{ color:'#94a3b8', boxWidth:12 }} }} }},
  scales: {{
    x: {{ ticks:{{color:'#64748b',maxTicksLimit:8}}, grid:{{color:'#1e2133'}} }},
    y: {{ ticks:{{color:'#64748b'}}, grid:{{color:'#1e2133'}} }},
  }}
}};

// Bar chart helper
function barChart(canvasId, labels, values, colors, yLabel, formatFn) {{
  const ctx = document.getElementById(canvasId).getContext('2d');
  return new Chart(ctx, {{
    type: 'bar',
    data: {{ labels, datasets:[{{ data:values, backgroundColor:colors,
      borderRadius:6, borderSkipped:false }}] }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{
        legend: {{display:false}},
        tooltip: {{ callbacks: {{ label: c => ' ' + formatFn(c.raw) }} }}
      }},
      scales: {{
        x: {{ ticks:{{color:'#94a3b8'}}, grid:{{color:'#1e2133'}} }},
        y: {{
          ticks: {{ color:'#94a3b8', callback: v => formatFn(v) }},
          grid: {{color:'#1e2133'}}
        }}
      }}
    }}
  }});
}}

// ── 報酬率長條 ───────────────────────────────────────────────────────
barChart('chart-return', GNAMES,
  GNAMES.map(g => RESULTS[g].return_pct),
  GNAMES.map((g,i) => g===BEST_GROUP ? '#22c55e' : COLORS[i]),
  '報酬率', v => v.toFixed(2)+'%'
);

// ── CAGR 長條 ────────────────────────────────────────────────────────
barChart('chart-cagr', GNAMES,
  GNAMES.map(g => RESULTS[g].cagr),
  GNAMES.map((g,i) => g===BEST_GROUP ? '#22c55e' : COLORS[i]),
  '年化報酬率', v => v.toFixed(2)+'%'
);

// ── 最大回撤長條 ─────────────────────────────────────────────────────
barChart('chart-dd', GNAMES,
  GNAMES.map(g => RESULTS[g].max_drawdown),
  GNAMES.map((g,i) => g===SAFE_GROUP ? '#4f8ef7' : '#ef4444'),
  '最大回撤', v => v.toFixed(2)+'%'
);

// ── 資產成長曲線（全部 / 切換）────────────────────────────────────────
const curveCtx    = document.getElementById('chart-curve').getContext('2d');
const tabRow      = document.getElementById('curve-tabs');
let   activeMask  = new Set(GNAMES);   // 預設全顯示

// 投入成本曲線（共用）
const costData = CURVES[GNAMES[0]].map(d => d.cum_cost / 10000);

const curveDatasets = [
  ...GNAMES.map((g,i) => ({{
    label: g,
    data:  CURVES[g].map(d => d.market_value / 10000),
    borderColor: COLORS[i],
    backgroundColor: 'transparent',
    borderWidth: 2,
    pointRadius: 0,
    tension: 0.2,
  }})),
  {{
    label:'累積投入成本',
    data: costData,
    borderColor:'#475569',
    backgroundColor:'transparent',
    borderDash:[5,5],
    borderWidth:1.5,
    pointRadius:0,
    tension:0,
  }}
];

const curveChart = new Chart(curveCtx, {{
  type:'line',
  data:{{ labels: DATE_LABELS, datasets: curveDatasets }},
  options:{{
    responsive:true, maintainAspectRatio:false,
    interaction:{{ mode:'index', intersect:false }},
    plugins:{{
      legend:{{ labels:{{ color:'#94a3b8', boxWidth:12 }} }},
      tooltip:{{ callbacks:{{ label: c => ` ${{c.dataset.label}}: ${{c.raw.toFixed(1)}} 萬` }} }}
    }},
    scales:{{
      x:{{ ticks:{{color:'#64748b',maxTicksLimit:10}}, grid:{{color:'#1e2133'}} }},
      y:{{
        ticks:{{ color:'#64748b', callback: v => v.toFixed(0)+'萬' }},
        grid:{{color:'#1e2133'}}
      }}
    }}
  }}
}});

// Tab 按鈕
['全部', ...GNAMES].forEach(name => {{
  const btn = document.createElement('button');
  btn.className = 'tab-btn' + (name==='全部' ? ' active' : '');
  btn.textContent = name;
  btn.onclick = () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    if(name === '全部') {{
      curveChart.data.datasets.forEach(ds => {{ ds.hidden = false; }});
    }} else {{
      curveChart.data.datasets.forEach((ds,i) => {{
        if(i < GNAMES.length) ds.hidden = (ds.label !== name);
        else ds.hidden = false; // always show cost line
      }});
    }}
    curveChart.update();
  }};
  tabRow.appendChild(btn);
}});

// ── 最佳 vs 最差 ─────────────────────────────────────────────────────
const worstGroup = GNAMES.reduce((a,b) => RESULTS[a].return_pct < RESULTS[b].return_pct ? a : b);
const vsCtx = document.getElementById('chart-vs').getContext('2d');
new Chart(vsCtx, {{
  type:'line',
  data:{{
    labels: DATE_LABELS,
    datasets:[
      {{
        label: BEST_GROUP  + '（最佳）',
        data:  CURVES[BEST_GROUP ].map(d=>d.market_value/10000),
        borderColor:'#22c55e', backgroundColor:'transparent',
        borderWidth:2.5, pointRadius:0, tension:.2,
      }},
      {{
        label: worstGroup + '（最差）',
        data:  CURVES[worstGroup].map(d=>d.market_value/10000),
        borderColor:'#ef4444', backgroundColor:'transparent',
        borderWidth:2.5, pointRadius:0, tension:.2,
      }},
      {{
        label:'累積投入成本',
        data: costData,
        borderColor:'#475569',backgroundColor:'transparent',
        borderDash:[5,5],borderWidth:1.5,pointRadius:0,tension:0,
      }}
    ]
  }},
  options:{{
    responsive:true, maintainAspectRatio:false,
    interaction:{{ mode:'index', intersect:false }},
    plugins:{{ legend:{{ labels:{{ color:'#94a3b8',boxWidth:12 }} }},
      tooltip:{{ callbacks:{{ label:c=>` ${{c.dataset.label}}: ${{c.raw.toFixed(1)}}萬` }} }} }},
    scales:{{
      x:{{ ticks:{{color:'#64748b',maxTicksLimit:10}}, grid:{{color:'#1e2133'}} }},
      y:{{ ticks:{{color:'#64748b',callback:v=>v.toFixed(0)+'萬'}}, grid:{{color:'#1e2133'}} }}
    }}
  }}
}});

// ── 結論 ──────────────────────────────────────────────────────────────
const bestR  = RESULTS[BEST_GROUP];
const safeR  = RESULTS[SAFE_GROUP];
const worstR = RESULTS[worstGroup];
const diff   = Math.abs(bestR.return_pct - worstR.return_pct).toFixed(2);

const conclusions = [
  {{
    title:'🏆 最佳績效',
    html:`
      <p>組合：<span class="highlight">${{BEST_GROUP}}（${{bestR.days_label}}）</span></p>
      <ul style="margin-top:.5rem">
        <li>總報酬率：<span class="${{bestR.return_pct>=0?'green':'red'}} highlight">${{FMTP(bestR.return_pct)}}</span></li>
        <li>年化報酬：<span class="${{bestR.cagr>=0?'green':'red'}} highlight">${{FMTP(bestR.cagr)}}</span></li>
        <li>最終市值：<span class="highlight">NT$ ${{FMT(bestR.final_value)}}</span></li>
        <li>總投入：NT$ ${{FMT(bestR.total_cost)}}</li>
      </ul>`
  }},
  {{
    title:'🛡️ 最低風險',
    html:`
      <p>組合：<span class="highlight">${{SAFE_GROUP}}（${{safeR.days_label}}）</span></p>
      <ul style="margin-top:.5rem">
        <li>最大回撤：<span class="highlight">${{safeR.max_drawdown.toFixed(2)}}%</span>（五組中最小）</li>
        <li>年化報酬：${{FMTP(safeR.cagr)}}</li>
      </ul>`
  }},
  {{
    title:'📅 月份效應',
    html:`
      <ul>
        <li>五組報酬差距僅 <span class="highlight">${{diff}}%</span></li>
        <li>扣款日對長期報酬影響<span class="highlight">極為有限</span></li>
        <li>組合二（月初偏後）略佔優勢，可能反映台股<span class="highlight">月中買壓較低</span>的特性</li>
        <li>定期定額已透過時間分散大幅降低時機風險</li>
      </ul>`
  }},
  {{
    title:'💡 實務建議',
    html:`
      <ul>
        <li>各組差距 < 2%，<span class="highlight">扣款日影響不大</span></li>
        <li>若要選擇：<span class="highlight">${{BEST_GROUP}}</span> 報酬最佳且風險最低</li>
        <li>追求更平滑成本：選<span class="highlight">組合一</span>（每5日一次，頻率最高）</li>
        <li>空頭期持股最多的組合，行情回升時<span class="highlight">獲利最快</span></li>
        <li>歷史績效不代表未來；建議長期持有、定期檢視</li>
      </ul>`
  }},
];

const concDiv = document.getElementById('conclusion');
conclusions.forEach(c => {{
  concDiv.innerHTML += `<div class="c-card"><h3>${{c.title}}</h3>${{c.html}}</div>`;
}});
</script>
</body>
</html>"""

# 輸出 HTML
out_path = Path("index.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"HTML 已產生：{out_path}  ({out_path.stat().st_size // 1024} KB)")
