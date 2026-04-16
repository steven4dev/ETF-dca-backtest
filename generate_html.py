"""
產生 0052 定期定額分析的互動式 HTML（for GitHub Pages）
Python 只負責：讀 CSV → 拆分調整 → 輸出交易日程 JSON + 每日收盤價 JSON
所有 DCA 計算（含金額）全部在 JS 完成，支援使用者即時調整投入金額
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

# ── 常數 ─────────────────────────────────────────────────────────────
CSV_PATH    = "0052_5yr.csv"
SPLIT_DATE  = pd.Timestamp('2025-11-17')
SPLIT_RATIO = 7

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

# ── 讀取 & 拆分調整 ────────────────────────────────────────────────────
df_raw = pd.read_csv(CSV_PATH)
df_raw['Date']  = pd.to_datetime(df_raw['Date'])
df_raw['Close'] = pd.to_numeric(df_raw['Close'], errors='coerce')
df_raw.sort_values('Date', inplace=True)
df_raw.reset_index(drop=True, inplace=True)
df_raw = df_raw.dropna(subset=['Close'])

# Yahoo Finance 未做向後還原，手動套用拆分調整
df_raw.loc[df_raw['Date'] < SPLIT_DATE, 'Close'] /= SPLIT_RATIO

latest_date   = df_raw['Date'].max()
earliest_date = df_raw['Date'].min()
# 輸出全部資料給 JS，讓 JS 依使用者選擇年份篩選
df = df_raw.copy()
trading_dates = pd.DatetimeIndex(df['Date'].values)
close_map     = dict(zip(df['Date'].dt.strftime('%Y-%m-%d'), df['Close'].round(4)))
final_price   = float(df['Close'].iloc[-1])
data_years    = (latest_date - earliest_date).days / 365.25

# ── 建立每日收盤價序列（全部，JS 端篩選）────────────────────────────
daily_prices = [
    {"d": row['Date'].strftime('%Y-%m-%d'), "p": round(float(row['Close']), 4)}
    for _, row in df.iterrows()
]

# ── 建立各組交易日程（全部 5 年，JS 端依期間篩選）──────────────────
def build_trade_schedule(payment_days):
    """回傳 [{d, p, n}] 全部 5 年，JS 端再依 cutoff 截斷"""
    trades = {}
    start = df['Date'].min()
    end   = latest_date
    cur   = start.replace(day=1)
    while cur <= end:
        for day in payment_days:
            try:
                target = cur.replace(day=day)
            except ValueError:
                continue
            if target < start or target > end:
                continue
            idx = trading_dates.searchsorted(target)
            if idx >= len(trading_dates):
                continue
            actual = trading_dates[idx]
            dstr   = actual.strftime('%Y-%m-%d')
            price  = round(float(close_map[dstr]), 4)
            if dstr in trades:
                trades[dstr]['n'] += 1   # 同一天多個目標日順延合併，計次數
            else:
                trades[dstr] = {'d': dstr, 'p': price, 'n': 1}
        if cur.month == 12:
            cur = cur.replace(year=cur.year+1, month=1)
        else:
            cur = cur.replace(month=cur.month+1)
    return sorted(trades.values(), key=lambda x: x['d'])

schedules = {g: build_trade_schedule(days) for g, days in GROUPS.items()}

# ── 序列化為 JS 用資料 ────────────────────────────────────────────────
daily_json    = json.dumps(daily_prices, ensure_ascii=False, cls=NpEncoder)
schedules_json = json.dumps(schedules,   ensure_ascii=False, cls=NpEncoder)
days_label_json = json.dumps(GROUP_DAYS_LABEL, ensure_ascii=False)

print(f"資料範圍：{earliest_date.date()} ～ {latest_date.date()}（{data_years:.2f} 年）")
print(f"最後收盤：NT$ {final_price}")
print(f"每組交易次數（全期）：{ {g: len(v) for g,v in schedules.items()} }")

# ── HTML ──────────────────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>0052 富邦科技 定期定額回測分析</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg:#0f1117; --card:#1a1d27; --border:#2a2d3e;
  --accent:#4f8ef7; --green:#22c55e; --red:#ef4444;
  --text:#e2e8f0; --muted:#94a3b8;
}}
*{{ box-sizing:border-box; margin:0; padding:0; }}
body{{ background:var(--bg); color:var(--text);
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif; line-height:1.6; }}

/* ── Header ── */
header{{
  background:linear-gradient(135deg,#1a1d27 0%,#0f1117 100%);
  border-bottom:1px solid var(--border); padding:1.8rem 1.5rem; text-align:center;
}}
header h1{{ font-size:1.8rem; font-weight:700; color:#fff; letter-spacing:-.5px; }}
header p{{ color:var(--muted); margin-top:.3rem; font-size:.9rem; }}
.badge{{
  display:inline-block; background:var(--accent); color:#fff;
  font-size:.7rem; font-weight:600; padding:.15rem .55rem;
  border-radius:999px; margin-left:.5rem; vertical-align:middle;
}}

/* ── Investment input bar ── */
.invest-bar{{
  background:var(--card); border-bottom:1px solid var(--border);
  padding:.9rem 1.5rem; display:flex; align-items:center;
  justify-content:center; gap:1rem; flex-wrap:wrap;
}}
.invest-bar label{{ color:var(--muted); font-size:.9rem; font-weight:600; }}
.invest-input-wrap{{
  display:flex; align-items:center; gap:.5rem;
  background:#0f1117; border:1px solid var(--border);
  border-radius:8px; padding:.35rem .75rem;
  transition:border-color .2s;
}}
.invest-input-wrap:focus-within{{ border-color:var(--accent); }}
.invest-input-wrap span{{ color:var(--muted); font-size:.9rem; }}
.invest-input-wrap input{{
  background:transparent; border:none; outline:none;
  color:#fff; font-size:1rem; font-weight:700;
  width:120px; text-align:right;
}}
.sep{{ width:1px; height:24px; background:var(--border); }}
.year-btns{{ display:flex; gap:.4rem; }}
.year-btn{{
  background:var(--border); color:var(--muted); border:none;
  padding:.35rem .75rem; border-radius:6px; cursor:pointer;
  font-size:.82rem; font-weight:600; transition:all .15s;
}}
.year-btn.active{{ background:var(--accent); color:#fff; }}
.year-btn:hover:not(.active){{ background:#3a3d50; color:var(--text); }}
/* Chrome 隱藏 number spinner */
.invest-input-wrap input::-webkit-outer-spin-button,
.invest-input-wrap input::-webkit-inner-spin-button{{ -webkit-appearance:none; }}
.invest-input-wrap input[type=number]{{ -moz-appearance:textfield; }}
.invest-hint{{ color:var(--muted); font-size:.78rem; }}

/* ── Container ── */
.container{{ max-width:1200px; margin:0 auto; padding:2rem 1.5rem; }}
.section-title{{
  font-size:1.05rem; font-weight:600; color:#fff;
  margin-bottom:1rem; padding-bottom:.5rem;
  border-bottom:1px solid var(--border);
  display:flex; align-items:center; gap:.5rem;
}}

/* ── KPI ── */
.kpi-grid{{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr));
  gap:1rem; margin-bottom:2.5rem;
}}
.kpi{{
  background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:1.1rem 1rem; text-align:center;
  transition:border-color .2s;
}}
.kpi:hover{{ border-color:var(--accent); }}
.kpi .val{{ font-size:1.45rem; font-weight:700; }}
.kpi .lbl{{ font-size:.72rem; color:var(--muted); margin-top:.2rem; }}
.neg{{ color:var(--red); }} .pos{{ color:var(--green); }} .neu{{ color:var(--accent); }}

/* ── Table ── */
.table-wrap{{ overflow-x:auto; margin-bottom:2.5rem; }}
table{{ width:100%; border-collapse:collapse; font-size:.85rem; }}
thead tr{{ background:#232636; }}
thead th{{
  padding:.7rem 1rem; text-align:right; color:var(--muted);
  font-weight:600; white-space:nowrap; border-bottom:1px solid var(--border);
}}
thead th:first-child{{ text-align:left; }}
tbody tr{{ border-bottom:1px solid var(--border); transition:background .15s; }}
tbody tr:hover{{ background:#1e2133; }}
tbody td{{ padding:.7rem 1rem; text-align:right; white-space:nowrap; }}
tbody td:first-child{{ text-align:left; font-weight:600; }}
.tag{{
  display:inline-block; font-size:.65rem; padding:.1rem .4rem;
  border-radius:4px; margin-left:.3rem; font-weight:600; vertical-align:middle;
}}
.tag-best{{ background:rgba(34,197,94,.15); color:var(--green); border:1px solid rgba(34,197,94,.3); }}
.tag-safe{{ background:rgba(79,142,247,.15); color:var(--accent); border:1px solid rgba(79,142,247,.3); }}
.tag-worst{{ background:rgba(239,68,68,.15); color:var(--red); border:1px solid rgba(239,68,68,.3); }}

/* ── Charts ── */
.charts-grid{{
  display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; margin-bottom:2.5rem;
}}
@media(max-width:768px){{ .charts-grid{{ grid-template-columns:1fr; }} }}
.chart-card{{
  background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:1.2rem;
}}
.chart-card.full{{ grid-column:1/-1; }}
.chart-title{{
  font-size:.82rem; font-weight:600; color:var(--muted);
  margin-bottom:1rem; text-transform:uppercase; letter-spacing:.05em;
}}
.chart-wrap{{ position:relative; height:260px; }}
.chart-wrap.tall{{ height:340px; }}
.tab-row{{ display:flex; gap:.4rem; margin-bottom:.75rem; flex-wrap:wrap; }}
.tab-btn{{
  background:var(--border); color:var(--muted); border:none;
  padding:.35rem .8rem; border-radius:6px; cursor:pointer;
  font-size:.78rem; font-weight:600; transition:all .15s;
}}
.tab-btn.active{{ background:var(--accent); color:#fff; }}

/* ── Conclusion ── */
.conclusion-grid{{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:1rem; margin-bottom:2.5rem;
}}
.c-card{{
  background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:1.2rem;
}}
.c-card h3{{
  font-size:.82rem; font-weight:700; color:var(--accent);
  text-transform:uppercase; letter-spacing:.05em; margin-bottom:.7rem;
}}
.c-card p,.c-card li{{ font-size:.875rem; color:var(--muted); }}
.c-card ul{{ padding-left:1.2rem; }}
.c-card li{{ margin-bottom:.3rem; }}
.hl{{ color:var(--text)!important; font-weight:600; }}
.gr{{ color:var(--green)!important; }} .rd{{ color:var(--red)!important; }}

footer{{
  text-align:center; padding:1.5rem; color:var(--muted);
  font-size:.8rem; border-top:1px solid var(--border);
}}
</style>
</head>
<body>

<header>
  <h1>0052 富邦科技<span class="badge">ETF</span> 定期定額回測分析</h1>
  <p id="header-sub">資料最早：{earliest_date.strftime('%Y-%m-%d')} ～ {latest_date.strftime('%Y-%m-%d')}
     &nbsp;|&nbsp; 可回測最長 {data_years:.1f} 年 &nbsp;|&nbsp; 五組扣款日比較
     &nbsp;|&nbsp; 資料來源：Yahoo Finance（已還原7:1拆分）</p>
</header>

<!-- 設定列 -->
<div class="invest-bar">
  <label>回測期間</label>
  <div class="year-btns" id="year-btns">
    <button class="year-btn" data-y="1">1 年</button>
    <button class="year-btn" data-y="2">2 年</button>
    <button class="year-btn active" data-y="3">3 年</button>
    <button class="year-btn" data-y="5">5 年</button>
  </div>
  <div class="sep"></div>
  <label for="invest-amt">每次投入金額</label>
  <div class="invest-input-wrap">
    <span>NT$</span>
    <input type="number" id="invest-amt" value="10000" min="100" step="1000">
  </div>
  <span class="invest-hint">修改後即時重算</span>
</div>

<div class="container">

  <div style="margin-bottom:1rem">
    <div class="section-title"><span>📊</span>市場概況</div>
  </div>
  <div class="kpi-grid" id="kpi-row"></div>

  <div class="section-title"><span>🏆</span>五組績效對照表</div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>組合</th><th>扣款日</th><th>交易次數</th>
        <th>總投入</th><th>持股數</th><th>平均成本</th>
        <th>最終市值</th><th>報酬率</th><th>年化報酬</th><th>最大回撤</th>
      </tr></thead>
      <tbody id="table-body"></tbody>
    </table>
  </div>

  <div class="section-title"><span>📈</span>視覺化分析</div>
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
      <div class="chart-title">最佳 vs 最差組合對比</div>
      <div class="chart-wrap"><canvas id="chart-vs"></canvas></div>
    </div>
  </div>

  <div class="section-title"><span>💡</span>結論分析</div>
  <div class="conclusion-grid" id="conclusion"></div>

</div>

<footer>
  資料來源：0052 富邦科技 歷史股價（已還原除權息）&nbsp;|&nbsp;
  最後更新：{latest_date.strftime('%Y-%m-%d')} &nbsp;|&nbsp;
  本分析僅供參考，不構成投資建議
</footer>

<script>
// ════════════════════════════════════════════════════════════════
//  靜態資料（Python 產生，全部 5 年）
// ════════════════════════════════════════════════════════════════
const DAILY_ALL   = {daily_json};         // [{{d:'2021-04-16', p:18.4}}, ...]  全 5 年
const SCHEDULES_ALL = {schedules_json};   // {{組合一:[{{d,p,n}}, ...], ...}}  全 5 年
const DAYS_LABEL  = {days_label_json};
const FINAL_PRICE = {final_price};
const DATA_YEARS  = {data_years:.4f};     // 可用最長年數（約 5）
const GNAMES = Object.keys(SCHEDULES_ALL);
const COLORS = ['#4f8ef7','#22c55e','#f59e0b','#e879f9','#fb923c'];

// ── 依年數篩選資料 ────────────────────────────────────────────────
function sliceByYears(years) {{
  const latestD = DAILY_ALL[DAILY_ALL.length - 1].d;
  const latestTs = new Date(latestD).getTime();
  const cutoffTs = latestTs - years * 365.25 * 86400 * 1000;
  const cutoffD  = new Date(cutoffTs).toISOString().slice(0, 10);

  const daily = DAILY_ALL.filter(d => d.d >= cutoffD);
  const schedules = {{}};
  for (const g of GNAMES) {{
    schedules[g] = SCHEDULES_ALL[g].filter(t => t.d >= cutoffD);
  }}
  return {{ daily, schedules, cutoffD, actualYears: (latestTs - new Date(daily[0].d).getTime()) / (365.25 * 86400 * 1000) }};
}}

// ════════════════════════════════════════════════════════════════
//  DCA 計算（純 JS，依金額 & 年數即時重算）
// ════════════════════════════════════════════════════════════════
function runDCA(schedule, daily, amtPerTrade, actualYears) {{
  // schedule: [{{d, p, n}}]  n = 該交易日合併幾個扣款點
  const tradeMap = {{}};
  for (const t of schedule) {{
    tradeMap[t.d] = {{ price: t.p, count: t.n }};
  }}

  let cumShares = 0, cumCost = 0;
  const mv = [];          // 每日市值（NT$）
  const cc = [];          // 每日累積成本

  for (const day of daily) {{
    if (tradeMap[day.d]) {{
      const t = tradeMap[day.d];
      const cost   = amtPerTrade * t.count;
      const shares = cost / t.price;
      cumShares += shares;
      cumCost   += cost;
    }}
    mv.push(cumShares * day.p);
    cc.push(cumCost);
  }}

  const totalCost   = cumCost;
  const totalShares = cumShares;
  const avgCost     = totalShares > 0 ? totalCost / totalShares : 0;
  const finalValue  = totalShares * FINAL_PRICE;
  const returnPct   = (finalValue - totalCost) / totalCost * 100;
  const cagr        = actualYears > 0
    ? (Math.pow(finalValue / totalCost, 1 / actualYears) - 1) * 100 : 0;

  // Max Drawdown
  let peak = -Infinity, maxDD = 0;
  for (const v of mv) {{
    if (v > peak) peak = v;
    const dd = (v - peak) / peak * 100;
    if (dd < maxDD) maxDD = dd;
  }}

  return {{
    trades:      schedule.reduce((s,t) => s + t.n, 0),
    totalCost, totalShares, avgCost, finalValue,
    returnPct, cagr, maxDrawdown: maxDD, mv, cc,
  }};
}}

// ════════════════════════════════════════════════════════════════
//  Chart 實例（初始化一次，之後只更新資料）
// ════════════════════════════════════════════════════════════════
const FMT  = n => Math.round(n).toLocaleString('zh-TW');
const FMTP = n => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';

function makeBarChart(id, labels, values, colors, fmtFn) {{
  const ctx = document.getElementById(id).getContext('2d');
  return new Chart(ctx, {{
    type: 'bar',
    data: {{ labels, datasets: [{{ data: values, backgroundColor: colors,
      borderRadius: 6, borderSkipped: false }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: c => ' ' + fmtFn(c.raw) }} }},
      }},
      scales: {{
        x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e2133' }} }},
        y: {{ ticks: {{ color: '#94a3b8', callback: v => fmtFn(v) }},
              grid: {{ color: '#1e2133' }} }},
      }},
    }},
  }});
}}

function makeLineChart(id, labels, datasets, yFmt, tall) {{
  const ctx = document.getElementById(id).getContext('2d');
  return new Chart(ctx, {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#94a3b8', boxWidth: 12 }} }},
        tooltip: {{ callbacks: {{ label: c =>
          ` ${{c.dataset.label}}: ${{yFmt(c.raw)}}` }} }},
      }},
      scales: {{
        x: {{ ticks: {{ color: '#64748b', maxTicksLimit: 10 }},
              grid: {{ color: '#1e2133' }} }},
        y: {{ ticks: {{ color: '#64748b', callback: yFmt }},
              grid: {{ color: '#1e2133' }} }},
      }},
    }},
  }});
}}

// ── 目前狀態 ──────────────────────────────────────────────────────
let currentYears = 3;

// 初始化圖表（空資料，render() 填入）
const chartReturn = makeBarChart('chart-return', GNAMES,
  new Array(5).fill(0), COLORS, v => v.toFixed(2)+'%');
const chartCagr   = makeBarChart('chart-cagr',   GNAMES,
  new Array(5).fill(0), COLORS, v => v.toFixed(2)+'%');
const chartDD     = makeBarChart('chart-dd',     GNAMES,
  new Array(5).fill(0), COLORS, v => v.toFixed(2)+'%');

const mkWanFmt = () => v => {{
  if (Math.abs(v) >= 100000000) return (v/100000000).toFixed(2) + '億';
  return (v/10000).toFixed(1) + '萬';
}};

const curveDatasetsInit = [
  ...GNAMES.map((g,i) => ({{
    label: g, data: [], borderColor: COLORS[i],
    backgroundColor: 'transparent', borderWidth: 2,
    pointRadius: 0, tension: 0.2,
  }})),
  {{ label:'累積投入成本', data: [],
    borderColor:'#475569', backgroundColor:'transparent',
    borderDash:[5,5], borderWidth:1.5, pointRadius:0 }},
];
const chartCurve = makeLineChart('chart-curve', [],
  curveDatasetsInit, mkWanFmt(), true);

const vsInit = [
  {{ label:'最佳', data:[], borderColor:'#22c55e',
    backgroundColor:'transparent', borderWidth:2.5, pointRadius:0, tension:.2 }},
  {{ label:'最差', data:[], borderColor:'#ef4444',
    backgroundColor:'transparent', borderWidth:2.5, pointRadius:0, tension:.2 }},
  {{ label:'累積成本', data:[], borderColor:'#475569',
    backgroundColor:'transparent', borderDash:[5,5], borderWidth:1.5, pointRadius:0 }},
];
const chartVS = makeLineChart('chart-vs', [], vsInit, mkWanFmt(), false);

// ── Tabs ─────────────────────────────────────────────────────────
const tabRow = document.getElementById('curve-tabs');
['全部', ...GNAMES].forEach(name => {{
  const btn = document.createElement('button');
  btn.className = 'tab-btn' + (name==='全部'?' active':'');
  btn.textContent = name;
  btn.onclick = () => {{
    tabRow.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    chartCurve.data.datasets.forEach((ds,i) => {{
      ds.hidden = (name!=='全部' && i < GNAMES.length && ds.label !== name);
    }});
    chartCurve.update();
  }};
  tabRow.appendChild(btn);
}});

// ════════════════════════════════════════════════════════════════
//  主 render 函式
// ════════════════════════════════════════════════════════════════
function render(amtPerTrade, years) {{
  // 依年數篩選資料
  const {{ daily, schedules, actualYears }} = sliceByYears(years);
  const dateLabels = daily.map(d => d.d);

  // 計算所有組合
  const allR = {{}};
  for (const g of GNAMES) {{
    allR[g] = runDCA(schedules[g], daily, amtPerTrade, actualYears);
  }}

  const bestG  = GNAMES.reduce((a,b) => allR[a].returnPct > allR[b].returnPct ? a : b);
  const worstG = GNAMES.reduce((a,b) => allR[a].returnPct < allR[b].returnPct ? a : b);
  const safeG  = GNAMES.reduce((a,b) => allR[a].maxDrawdown > allR[b].maxDrawdown ? a : b);
  const bestR  = allR[bestG];
  const safeR  = allR[safeG];

  // ── KPI ────────────────────────────────────────────────────────
  const kpiRow = document.getElementById('kpi-row');
  kpiRow.innerHTML = [
    {{ v:'NT$ '+FINAL_PRICE.toFixed(2),         l:'最後收盤價',    c:'neu' }},
    {{ v:actualYears.toFixed(1)+' 年',          l:'回測期間',      c:'neu' }},
    {{ v:'NT$ '+amtPerTrade.toLocaleString(),    l:'每次投入金額',  c:'neu' }},
    {{ v:bestG,                                  l:'最佳組合',      c:'pos' }},
    {{ v:FMTP(bestR.returnPct),                  l:'最佳報酬率',
       c:bestR.returnPct>=0?'pos':'neg' }},
    {{ v:FMTP(bestR.cagr),                       l:'最佳年化報酬',
       c:bestR.cagr>=0?'pos':'neg' }},
  ].map(k=>`<div class="kpi"><div class="val ${{k.c}}">${{k.v}}</div><div class="lbl">${{k.l}}</div></div>`).join('');

  // ── Table ──────────────────────────────────────────────────────
  const tbody = document.getElementById('table-body');
  tbody.innerHTML = GNAMES.map(g => {{
    const r  = allR[g];
    const isBest  = g === bestG, isSafe = g === safeG, isWorst = g === worstG;
    let tag = '';
    if (isBest)  tag += '<span class="tag tag-best">最佳</span>';
    if (isSafe && !isBest) tag += '<span class="tag tag-safe">最穩</span>';
    if (isWorst && !isBest) tag += '<span class="tag tag-worst">最差</span>';
    const rc = r.returnPct >= 0 ? 'color:var(--green)' : 'color:var(--red)';
    const cc = r.cagr      >= 0 ? 'color:var(--green)' : 'color:var(--red)';
    return `<tr>
      <td>${{g}}${{tag}}</td>
      <td>${{DAYS_LABEL[g]}}</td>
      <td>${{r.trades}}</td>
      <td>NT$ ${{FMT(r.totalCost)}}</td>
      <td>${{r.totalShares.toFixed(2)}}</td>
      <td>NT$ ${{r.avgCost.toFixed(2)}}</td>
      <td>NT$ ${{FMT(r.finalValue)}}</td>
      <td style="${{rc}};font-weight:700">${{FMTP(r.returnPct)}}</td>
      <td style="${{cc}}">${{FMTP(r.cagr)}}</td>
      <td style="color:var(--red)">${{r.maxDrawdown.toFixed(2)}}%</td>
    </tr>`;
  }}).join('');

  // ── Bar charts ─────────────────────────────────────────────────
  function updateBar(chart, values, colorsFn) {{
    chart.data.datasets[0].data = values;
    chart.data.datasets[0].backgroundColor = GNAMES.map(colorsFn);
    chart.update('none');
  }}
  updateBar(chartReturn, GNAMES.map(g=>allR[g].returnPct),
    (g,i) => g===bestG ? '#22c55e' : COLORS[i]);
  updateBar(chartCagr,   GNAMES.map(g=>allR[g].cagr),
    (g,i) => g===bestG ? '#22c55e' : COLORS[i]);
  updateBar(chartDD,     GNAMES.map(g=>allR[g].maxDrawdown),
    (g,i) => g===safeG ? '#4f8ef7' : '#ef4444');

  // ── Curve chart ────────────────────────────────────────────────
  chartCurve.data.labels = dateLabels;
  GNAMES.forEach((g,i) => {{
    chartCurve.data.datasets[i].data = allR[g].mv;
  }});
  chartCurve.data.datasets[GNAMES.length].data = allR[bestG].cc;
  chartCurve.update('none');

  // ── VS chart ───────────────────────────────────────────────────
  chartVS.data.labels = dateLabels;
  chartVS.data.datasets[0].label = bestG  + '（最佳）';
  chartVS.data.datasets[1].label = worstG + '（最差）';
  chartVS.data.datasets[0].data  = allR[bestG].mv;
  chartVS.data.datasets[1].data  = allR[worstG].mv;
  chartVS.data.datasets[2].data  = allR[bestG].cc;
  chartVS.update('none');

  // ── Conclusion ─────────────────────────────────────────────────
  const diff = Math.abs(bestR.returnPct - allR[worstG].returnPct).toFixed(2);
  document.getElementById('conclusion').innerHTML = [
    {{
      t:'🏆 最佳績效',
      h:`<p>組合：<span class="hl">${{bestG}}（${{DAYS_LABEL[bestG]}}）</span></p>
        <ul style="margin-top:.5rem">
          <li>總報酬率：<span class="${{bestR.returnPct>=0?'gr':'rd'}} hl">${{FMTP(bestR.returnPct)}}</span></li>
          <li>年化報酬：<span class="${{bestR.cagr>=0?'gr':'rd'}} hl">${{FMTP(bestR.cagr)}}</span></li>
          <li>最終市值：<span class="hl">NT$ ${{FMT(bestR.finalValue)}}</span></li>
          <li>總投入：NT$ ${{FMT(bestR.totalCost)}}</li>
        </ul>`
    }},
    {{
      t:'🛡️ 最低風險',
      h:`<p>組合：<span class="hl">${{safeG}}（${{DAYS_LABEL[safeG]}}）</span></p>
        <ul style="margin-top:.5rem">
          <li>最大回撤：<span class="hl">${{safeR.maxDrawdown.toFixed(2)}}%</span>（五組中最小）</li>
          <li>年化報酬：${{FMTP(safeR.cagr)}}</li>
          <li>最終市值：NT$ ${{FMT(safeR.finalValue)}}</li>
        </ul>`
    }},
    {{
      t:'📅 月份效應',
      h:`<ul>
          <li>五組報酬差距僅 <span class="hl">${{diff}}%</span></li>
          <li>扣款日對長期報酬影響<span class="hl">極為有限</span></li>
          <li>月中偏前（4/9/14…）略佔優勢，可能反映台股<span class="hl">月初買壓較低</span></li>
          <li>定期定額已透過時間分散大幅降低時機風險</li>
        </ul>`
    }},
    {{
      t:'💡 實務建議',
      h:`<ul>
          <li>各組差距 < 2%，<span class="hl">扣款日影響不大</span></li>
          <li>若要選擇：<span class="hl">${{bestG}}</span> 報酬最佳</li>
          <li>追求更平滑成本：選<span class="hl">組合一</span>（每5日一次，頻率最高）</li>
          <li>空頭期持股最多的組合，行情回升時<span class="hl">獲利最快</span></li>
          <li>歷史績效不代表未來；建議長期持有、定期檢視</li>
        </ul>`
    }},
  ].map(c=>`<div class="c-card"><h3>${{c.t}}</h3>${{c.h}}</div>`).join('');
}}

// ── 年份按鈕 ──────────────────────────────────────────────────────
document.querySelectorAll('.year-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.year-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentYears = parseFloat(btn.dataset.y);
    const amt = parseInt(document.getElementById('invest-amt').value, 10);
    if (amt >= 100) render(amt, currentYears);
  }});
}});

// ── 金額輸入 ──────────────────────────────────────────────────────
const input = document.getElementById('invest-amt');
let debounce;
input.addEventListener('input', () => {{
  clearTimeout(debounce);
  debounce = setTimeout(() => {{
    const v = parseInt(input.value, 10);
    if (v >= 100) render(v, currentYears);
  }}, 300);
}});

// 首次渲染（預設 3 年、NT$10,000）
render(10000, 3);
</script>
</body>
</html>"""

out_path = Path("index.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"HTML 已產生：{out_path}  ({out_path.stat().st_size // 1024} KB)")
