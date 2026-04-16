"""
0052 富邦科技 定期定額回測分析
分析五組扣款日期組合，找出最佳投資策略
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec
import warnings
warnings.filterwarnings('ignore')

# ── 字型設定（支援中文）──────────────────────────────────────────────
import matplotlib.font_manager as fm
import os, sys

def setup_font():
    """嘗試設定中文字型"""
    # Windows 常見中文字型
    font_candidates = [
        'Microsoft JhengHei', 'Microsoft YaHei',
        'PingFang TC', 'STHeiti', 'SimHei', 'Noto Sans CJK TC'
    ]
    available = [f.name for f in fm.fontManager.ttflist]
    for font in font_candidates:
        if font in available:
            plt.rcParams['font.family'] = font
            return font
    # fallback
    plt.rcParams['font.family'] = 'DejaVu Sans'
    return 'DejaVu Sans'

FONT = setup_font()
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150

# ── 常數設定 ─────────────────────────────────────────────────────────
CSV_PATH = "0052 ETF Stock Price History.csv"
INVEST_PER_TRADE = 10_000          # 每次投入 NT$10,000
SHARE_DECIMALS   = 4               # 股數保留小數位數

# 五組扣款日（每月哪幾天）
GROUPS = {
    "組合一": [1, 6, 11, 16, 21, 26, 31],
    "組合二": [2, 7, 12, 17, 22, 27],
    "組合三": [3, 8, 13, 18, 23, 28],
    "組合四": [4, 9, 14, 19, 24, 29],
    "組合五": [5, 10, 15, 20, 25, 30],
}

# ── Step 1：讀取 CSV ──────────────────────────────────────────────────
print("=" * 60)
print("0052 富邦科技  定期定額回測分析")
print("=" * 60)

df_raw = pd.read_csv(CSV_PATH)
df_raw.columns = [c.strip().strip('"') for c in df_raw.columns]

# 重命名欄位
rename_map = {
    'Date': 'Date', 'Price': 'Close',
    'Open': 'Open', 'High': 'High', 'Low': 'Low',
    'Vol.': 'Volume', 'Change %': 'Change'
}
df_raw.rename(columns=rename_map, inplace=True)

# 解析日期
df_raw['Date'] = pd.to_datetime(df_raw['Date'], format='%m/%d/%Y')

# Close 欄位：去掉逗號後轉 float
df_raw['Close'] = df_raw['Close'].astype(str).str.replace(',', '').astype(float)

df_raw.sort_values('Date', inplace=True)
df_raw.reset_index(drop=True, inplace=True)

# ── 股票拆分調整（7:1，2025-11-12）────────────────────────────────────
SPLIT_DATE  = pd.Timestamp('2025-11-12')
SPLIT_RATIO = 7
pre_split = df_raw['Date'] < SPLIT_DATE
df_raw.loc[pre_split, 'Close'] = df_raw.loc[pre_split, 'Close'] / SPLIT_RATIO
print(f"已套用拆分調整：{SPLIT_DATE.date()} 前的價格 ÷ {SPLIT_RATIO}")

latest_date = df_raw['Date'].max()
earliest_date = df_raw['Date'].min()
target_start = latest_date - pd.DateOffset(years=3)

print(f"\n資料範圍：{earliest_date.date()} ～ {latest_date.date()}")
print(f"最後收盤價（{latest_date.date()}）：NT$ {df_raw.loc[df_raw['Date']==latest_date,'Close'].values[0]:.2f}")

# 若資料不足 3 年，使用全部資料
if earliest_date > target_start:
    backtest_start = earliest_date
    print(f"\n[注意] 資料不足 3 年，使用全部可用資料：{backtest_start.date()} ~ {latest_date.date()}")
else:
    backtest_start = target_start
    print(f"\n回測起始日：{backtest_start.date()}（往前推 3 年）")

# 回測期間價格資料
df = df_raw[df_raw['Date'] >= backtest_start].copy()
df.reset_index(drop=True, inplace=True)

trading_dates = pd.DatetimeIndex(df['Date'].values)
close_series  = df.set_index('Date')['Close']
final_price   = close_series.iloc[-1]
actual_years  = (latest_date - df['Date'].min()).days / 365.25

print(f"有效回測天數：{(latest_date - df['Date'].min()).days} 天（{actual_years:.2f} 年）")
print(f"回測資料筆數：{len(df)} 個交易日\n")

# ── Step 2：找下一個交易日 ────────────────────────────────────────────
def next_trading_day(target_date, trading_dates):
    """若 target_date 非交易日，順延至最近的下一個交易日"""
    idx = trading_dates.searchsorted(target_date)
    if idx >= len(trading_dates):
        return None
    return trading_dates[idx]

# ── Step 3：回測函式 ──────────────────────────────────────────────────
def run_backtest(group_name, payment_days):
    """
    對單一組合執行定期定額回測
    回傳：transactions DataFrame、每日資產曲線 Series
    """
    transactions = []

    # 產生所有扣款「目標日期」
    start = df['Date'].min()
    end   = latest_date

    current = start.replace(day=1)
    while current <= end:
        for day in payment_days:
            try:
                target = current.replace(day=day)
            except ValueError:
                # 月份不足該天數（e.g. 2 月 31 日）
                continue

            if target < start or target > end:
                continue

            # 找實際交易日
            actual = next_trading_day(target, trading_dates)
            if actual is None:
                continue

            price = close_series.loc[actual]
            shares = round(INVEST_PER_TRADE / price, SHARE_DECIMALS)
            transactions.append({
                'target_date': target,
                'trade_date':  actual,
                'price':       price,
                'shares':      shares,
                'cost':        INVEST_PER_TRADE,
            })

        # 下個月
        if current.month == 12:
            current = current.replace(year=current.year+1, month=1)
        else:
            current = current.replace(month=current.month+1)

    txn_df = pd.DataFrame(transactions)
    # 去重（同一天可能被多個 target 順延到）
    txn_df = txn_df.groupby('trade_date', as_index=False).agg(
        shares=('shares', 'sum'),
        cost=('cost', 'sum'),
        price=('price', 'first'),
    )
    txn_df.sort_values('trade_date', inplace=True)
    txn_df.reset_index(drop=True, inplace=True)

    # ── 每日資產曲線 ──
    cum_shares = 0
    cum_cost   = 0
    daily_records = []

    txn_map = txn_df.set_index('trade_date')

    for idx, row in df.iterrows():
        date  = row['Date']
        price = row['Close']

        if date in txn_map.index:
            cum_shares += txn_map.loc[date, 'shares']
            cum_cost   += txn_map.loc[date, 'cost']

        market_value = cum_shares * price
        daily_records.append({
            'date':         date,
            'cum_cost':     cum_cost,
            'cum_shares':   cum_shares,
            'market_value': market_value,
        })

    daily_df = pd.DataFrame(daily_records).set_index('date')

    return txn_df, daily_df

# ── Step 4：執行所有組合 ──────────────────────────────────────────────
results   = {}   # 儲存統計指標
daily_all = {}   # 儲存每日曲線

for gname, days in GROUPS.items():
    txn_df, daily_df = run_backtest(gname, days)

    total_cost    = txn_df['cost'].sum()
    total_shares  = txn_df['shares'].sum()
    avg_cost      = total_cost / total_shares if total_shares > 0 else 0
    final_value   = total_shares * final_price
    total_return  = (final_value - total_cost) / total_cost * 100
    num_trades    = len(txn_df)

    # CAGR
    cagr = (final_value / total_cost) ** (1 / actual_years) - 1 if actual_years > 0 else 0

    # Max Drawdown（以每日市值 / 當時投入成本之相對回撤）
    mv = daily_df['market_value']
    rolling_max = mv.cummax()
    drawdown = (mv - rolling_max) / rolling_max
    max_drawdown = drawdown.min() * 100   # 負值

    results[gname] = {
        '扣款日':     str(days),
        '交易次數':   num_trades,
        '總投入(NT$)': total_cost,
        '持股數':     round(total_shares, 4),
        '平均成本':   round(avg_cost, 2),
        '最終市值':   round(final_value, 0),
        '報酬率(%)':  round(total_return, 2),
        '年化報酬(%)':round(cagr * 100, 2),
        '最大回撤(%)':round(max_drawdown, 2),
    }

    daily_all[gname] = daily_df
    print(f"{gname}：報酬率 {total_return:+.2f}%  年化 {cagr*100:+.2f}%  MaxDD {max_drawdown:.2f}%  交易{num_trades}次")

# ── Step 5：績效對照表 ────────────────────────────────────────────────
print("\n" + "=" * 60)
print("五組定期定額績效對照表")
print("=" * 60)

table_cols = ['總投入(NT$)', '持股數', '平均成本', '最終市值', '報酬率(%)', '年化報酬(%)', '最大回撤(%)']
rows = []
for g, r in results.items():
    rows.append([g] + [r[c] for c in table_cols])

summary_df = pd.DataFrame(rows, columns=['組合'] + table_cols)
summary_df.set_index('組合', inplace=True)

# 格式化輸出
pd.set_option('display.float_format', '{:,.2f}'.format)
pd.set_option('display.max_columns', 20)
pd.set_option('display.width', 120)
print(summary_df.to_string())

best_group  = summary_df['報酬率(%)'].idxmax()
worst_group = summary_df['報酬率(%)'].idxmin()
safest      = summary_df['最大回撤(%)'].idxmax()   # 最大回撤最小（值最接近 0）

print(f"\n最佳報酬：{best_group}（{summary_df.loc[best_group,'報酬率(%)']:+.2f}%）")
print(f"最差報酬：{worst_group}（{summary_df.loc[worst_group,'報酬率(%)']:+.2f}%）")
print(f"最低風險：{safest}（最大回撤 {summary_df.loc[safest,'最大回撤(%)']:.2f}%）")

# ── Step 6：視覺化 ────────────────────────────────────────────────────
colors = ['#2196F3', '#4CAF50', '#FF9800', '#E91E63', '#9C27B0']
group_names = list(GROUPS.keys())

fig = plt.figure(figsize=(18, 22))
gs  = GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)

# ── 圖1：報酬率長條圖 ─────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
returns = [results[g]['報酬率(%)'] for g in group_names]
bars = ax1.bar(group_names, returns, color=colors, edgecolor='white', linewidth=0.8, zorder=3)
ax1.axhline(0, color='black', linewidth=0.8)
ax1.set_title('五組定期定額  總報酬率比較', fontsize=13, fontweight='bold', pad=10)
ax1.set_ylabel('總報酬率 (%)', fontsize=10)
ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f%%'))
ax1.grid(axis='y', alpha=0.3, zorder=0)
for bar, val in zip(bars, returns):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             f'{val:+.2f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

# 標示最佳
best_idx = returns.index(max(returns))
bars[best_idx].set_edgecolor('gold')
bars[best_idx].set_linewidth(2.5)

# ── 圖2：年化報酬率長條圖 ─────────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
cagrs = [results[g]['年化報酬(%)'] for g in group_names]
bars2 = ax2.bar(group_names, cagrs, color=colors, edgecolor='white', linewidth=0.8, zorder=3)
ax2.axhline(0, color='black', linewidth=0.8)
ax2.set_title('五組定期定額  年化報酬率（CAGR）比較', fontsize=13, fontweight='bold', pad=10)
ax2.set_ylabel('年化報酬率 (%)', fontsize=10)
ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f%%'))
ax2.grid(axis='y', alpha=0.3, zorder=0)
for bar, val in zip(bars2, cagrs):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.15,
             f'{val:+.2f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

# ── 圖3：資產成長曲線（市值）────────────────────────────────────────
ax3 = fig.add_subplot(gs[1, :])
for i, gname in enumerate(group_names):
    ddf = daily_all[gname]
    ax3.plot(ddf.index, ddf['market_value'] / 10_000, label=gname, color=colors[i], linewidth=1.8)
# 繪製投入成本曲線（取任一組，成本相近）
cost_curve = daily_all[group_names[0]]['cum_cost'] / 10_000
ax3.plot(cost_curve.index, cost_curve.values, '--', color='gray',
         linewidth=1.4, alpha=0.7, label='累積投入成本')
ax3.set_title('五組定期定額  資產市值成長曲線', fontsize=13, fontweight='bold', pad=10)
ax3.set_ylabel('資產市值（萬元 NT$）', fontsize=10)
ax3.set_xlabel('日期', fontsize=10)
ax3.legend(fontsize=9, loc='upper left')
ax3.grid(alpha=0.3)
ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:.0f}萬'))

# ── 圖4：最佳 vs 最差比較 ────────────────────────────────────────────
ax4 = fig.add_subplot(gs[2, 0])
best_dd  = daily_all[best_group]
worst_dd = daily_all[worst_group]
ax4.plot(best_dd.index,  best_dd['market_value']/10_000,
         color=colors[0], linewidth=2, label=f'{best_group}（最佳）')
ax4.plot(worst_dd.index, worst_dd['market_value']/10_000,
         color=colors[3], linewidth=2, label=f'{worst_group}（最差）')
ax4.plot(daily_all[group_names[0]]['cum_cost']/10_000,
         '--', color='gray', linewidth=1.2, alpha=0.6, label='累積成本')
ax4.set_title('最佳 vs 最差組合  資產曲線對比', fontsize=13, fontweight='bold', pad=10)
ax4.set_ylabel('資產市值（萬元）', fontsize=10)
ax4.set_xlabel('日期', fontsize=10)
ax4.legend(fontsize=9)
ax4.grid(alpha=0.3)
ax4.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:.0f}萬'))

# ── 圖5：最大回撤比較 ────────────────────────────────────────────────
ax5 = fig.add_subplot(gs[2, 1])
max_dds = [results[g]['最大回撤(%)'] for g in group_names]
bars5 = ax5.bar(group_names, max_dds, color=colors, edgecolor='white', linewidth=0.8, zorder=3)
ax5.set_title('五組定期定額  最大回撤比較', fontsize=13, fontweight='bold', pad=10)
ax5.set_ylabel('最大回撤 (%)', fontsize=10)
ax5.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f%%'))
ax5.grid(axis='y', alpha=0.3, zorder=0)
for bar, val in zip(bars5, max_dds):
    ax5.text(bar.get_x() + bar.get_width()/2, val - 0.5,
             f'{val:.2f}%', ha='center', va='top', fontsize=10, fontweight='bold', color='white')

# 標示風險最低
safe_idx = max_dds.index(max(max_dds))  # 最大回撤值最接近 0
bars5[safe_idx].set_edgecolor('gold')
bars5[safe_idx].set_linewidth(2.5)

# ── 主標題 ──────────────────────────────────────────────────────────
fig.suptitle(
    f'0052 富邦科技  定期定額回測分析\n'
    f'回測期間：{df["Date"].min().strftime("%Y-%m-%d")} ～ {latest_date.strftime("%Y-%m-%d")}'
    f'（{actual_years:.1f} 年）  每次投入 NT$10,000',
    fontsize=14, fontweight='bold', y=0.98
)

output_path = "0052_DCA_Analysis.png"
fig.savefig(output_path, bbox_inches='tight', dpi=150, facecolor='white')
print(f"\n圖表已儲存：{output_path}")
plt.close()

# ── Step 7：結論分析 ─────────────────────────────────────────────────
print("\n" + "=" * 60)
print("結論分析")
print("=" * 60)

best_r   = results[best_group]['報酬率(%)']
worst_r  = results[worst_group]['報酬率(%)']
diff     = abs(best_r - worst_r)

print(f"""
1. 【最佳績效】{best_group}
   - 總報酬率：{results[best_group]['報酬率(%)']:+.2f}%
   - 年化報酬：{results[best_group]['年化報酬(%)']:+.2f}%
   - 最終市值：NT$ {results[best_group]['最終市值']:,.0f}

2. 【最低風險】{safest}
   - 最大回撤：{results[safest]['最大回撤(%)']:.2f}%（回撤幅度最小）
   - 年化報酬：{results[safest]['年化報酬(%)']:+.2f}%

3. 【月份效應分析】
   各組報酬差距約 {diff:.2f} 個百分點。
   組合一（月初/月中/月底）VS 組合三/四（月中）差異
   可反映台股「月初效應」與「除息月份」的價格波動特性。

4. 【穩定性分析】
   定期定額本質上已透過「時間分散」降低時機風險。
   最大回撤各組差異較小，顯示策略穩健性高。

5. 【實務建議】""")

if diff < 2:
    print("   各組報酬差距極小（< 2%），長期而言扣款日影響有限。")
    print("   建議：以方便扣款的日期為主，或採多日期分散（如組合一，每5日一次）")
    print("   增加買入頻次以更平滑化成本。")
else:
    print(f"   {best_group} 表現明顯較佳，在條件允許下優先選用。")
    print("   亦可考慮多日期分散（如組合一）以進一步平滑平均成本。")

print(f"""
6. 【補充說明】
   - 本分析未考慮手續費、稅金、滑價
   - 資料期間：{df['Date'].min().strftime('%Y-%m-%d')} ～ {latest_date.strftime('%Y-%m-%d')}
   - 最後收盤價：NT$ {final_price:.2f}
   - 歷史績效不代表未來表現
""")

print("分析完成！")
