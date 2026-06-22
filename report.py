"""
Generates a self-contained HTML backtest report with all charts embedded as
base64 PNGs. No external CDN, no internet required to open the report.
"""

from __future__ import annotations
import base64
import io
import math
from datetime import date
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")   # no display required
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.colors as mcolors
import numpy as np

from backtest import BacktestResult, Trade, monte_carlo

DARK  = "#0E1217"
PANEL = "#151B23"
LINE  = "#29333E"
TEXT  = "#E7E3D6"
MUTED = "#8C97A4"
TEAL  = "#45B69C"
AMBER = "#E0A24A"
RED   = "#D96A6A"
STEEL = "#6E7C8A"

plt.rcParams.update({
    "figure.facecolor": PANEL,
    "axes.facecolor": PANEL,
    "axes.edgecolor": LINE,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": TEXT,
    "grid.color": LINE,
    "grid.linewidth": 0.5,
    "font.family": "monospace",
})


def _b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=PANEL, edgecolor="none")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _img(b64: str, caption: str = "") -> str:
    html = f'<img src="data:image/png;base64,{b64}" style="max-width:100%;border-radius:10px">'
    if caption:
        html += f'<div class="cap">{caption}</div>'
    return f'<div class="chart">{html}</div>'


# ─── individual charts ────────────────────────────────────────────────────────

def chart_equity(res: BacktestResult, benchmark: Optional[List[Tuple[date, float]]] = None) -> str:
    fig, axes = plt.subplots(2, 1, figsize=(11, 6),
                              gridspec_kw={"height_ratios": [3, 1], "hspace": 0.05})
    ax, ax_dd = axes

    dates  = [pt.date for pt in res.equity_curve]
    equity = [pt.equity for pt in res.equity_curve]

    ax.plot(dates, equity, color=TEAL, linewidth=1.8, label="Strategy")
    ax.fill_between(dates, res.start_equity, equity,
                    where=[e >= res.start_equity for e in equity],
                    alpha=0.10, color=TEAL)
    ax.fill_between(dates, res.start_equity, equity,
                    where=[e < res.start_equity for e in equity],
                    alpha=0.12, color=RED)

    if benchmark:
        bd = [b[0] for b in benchmark]
        bv = [b[1] * res.start_equity for b in benchmark]
        ax.plot(bd, bv, color=STEEL, linewidth=1.0, linestyle="--", label="Buy-&-Hold SPY")

    ax.axhline(res.start_equity, color=LINE, linewidth=0.8, linestyle=":")
    ax.set_ylabel("Portfolio value ($)", fontsize=9)
    ax.legend(fontsize=8, facecolor=PANEL, edgecolor=LINE)
    ax.grid(True, alpha=0.3)
    ax.set_xticklabels([])

    # drawdown
    dd_vals = []
    peak = res.start_equity
    for e in equity:
        peak = max(peak, e)
        dd_vals.append(-(peak - e) / peak * 100)
    ax_dd.fill_between(dates, 0, dd_vals, color=RED, alpha=0.55)
    ax_dd.set_ylabel("Drawdown (%)", fontsize=9)
    ax_dd.set_ylim(top=0.5)
    ax_dd.grid(True, alpha=0.3)

    return _b64(fig)


def chart_monthly(res: BacktestResult) -> str:
    monthly = res.monthly_returns()
    if not monthly:
        return ""
    all_years  = sorted({y for y, m in monthly})
    months_lbl = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]
    mat = np.full((len(all_years), 12), np.nan)
    for (y, m), v in monthly.items():
        if y in all_years:
            mat[all_years.index(y), m - 1] = v

    fig, ax = plt.subplots(figsize=(11, max(3, len(all_years) * 0.55)))
    vmax = max(abs(np.nanmin(mat)), abs(np.nanmax(mat)), 1)
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rg", [RED, PANEL, TEAL])
    im = ax.imshow(mat, aspect="auto", cmap=cmap, vmin=-vmax, vmax=vmax)

    for i, yr in enumerate(all_years):
        for j in range(12):
            v = mat[i, j]
            if not np.isnan(v):
                txt = f"{v:+.1f}%"
                ax.text(j, i, txt, ha="center", va="center",
                        fontsize=7, color=TEXT if abs(v) < vmax * 0.7 else DARK,
                        fontweight="bold")

    ax.set_xticks(range(12)); ax.set_xticklabels(months_lbl, fontsize=8)
    ax.set_yticks(range(len(all_years))); ax.set_yticklabels(all_years, fontsize=8)
    ax.set_title("Monthly returns (%)", color=MUTED, fontsize=9, pad=8)
    plt.colorbar(im, ax=ax, fraction=0.02, pad=0.01)
    return _b64(fig)


def chart_trades(trades: List[Trade]) -> str:
    if not trades:
        return ""
    pcts = [t.pl_pct * 100 for t in trades]
    wins   = [p for p in pcts if p >  0]
    losses = [p for p in pcts if p <= 0]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"wspace": 0.3})

    # P&L histogram
    bins = 30
    if wins:   ax1.hist(wins,   bins=bins, color=TEAL, alpha=0.8, label=f"Wins ({len(wins)})")
    if losses: ax1.hist(losses, bins=bins, color=RED,  alpha=0.8, label=f"Losses ({len(losses)})")
    ax1.axvline(0, color=LINE, linewidth=1)
    ax1.set_xlabel("Trade P&L (%)", fontsize=9)
    ax1.set_ylabel("Count", fontsize=9)
    ax1.set_title("Trade distribution", color=MUTED, fontsize=9)
    ax1.legend(fontsize=7, facecolor=PANEL, edgecolor=LINE)
    ax1.grid(True, alpha=0.3)

    # Exit reason pie
    exit_counts: dict = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
    labels = list(exit_counts.keys())
    sizes  = list(exit_counts.values())
    colors = {
        "target": TEAL, "stop": RED, "signal": AMBER,
        "timeout": STEEL
    }
    clrs = [colors.get(l, MUTED) for l in labels]
    wedges, texts, autotexts = ax2.pie(
        sizes, labels=labels, colors=clrs, autopct="%1.0f%%",
        startangle=90, pctdistance=0.75,
        textprops={"color": TEXT, "fontsize": 8},
    )
    for at in autotexts:
        at.set_color(DARK); at.set_fontsize(8); at.set_fontweight("bold")
    ax2.set_title("How trades closed", color=MUTED, fontsize=9)
    return _b64(fig)


def chart_monte_carlo(mc: dict, start_equity: float) -> str:
    if not mc.get("pct50"):
        return ""
    x = list(range(len(mc["pct50"])))
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.fill_between(x, mc["pct5"], mc["pct95"], alpha=0.18, color=TEAL,
                    label="5th–95th pct")
    ax.fill_between(x, [min(mc["pct5"][i], mc["pct50"][i]) for i in x],
                    [max(mc["pct5"][i], mc["pct50"][i]) for i in x],
                    alpha=0.25, color=TEAL)
    ax.plot(x, mc["pct50"], color=TEAL, linewidth=2, label="Median sim")
    for c in mc["curves"][:40]:
        if len(c) == len(mc["pct50"]):
            ax.plot(c, color=STEEL, linewidth=0.3, alpha=0.35)
    ax.axhline(start_equity, color=LINE, linewidth=0.8, linestyle=":")
    ax.set_xlabel("Trade #", fontsize=9)
    ax.set_ylabel("Portfolio value ($)", fontsize=9)
    ax.set_title(
        f"Monte Carlo — 2000 shuffled trade sequences  "
        f"(strategies above start: {mc['win_pct']:.0f}%)",
        color=MUTED, fontsize=9)
    ax.legend(fontsize=8, facecolor=PANEL, edgecolor=LINE)
    ax.grid(True, alpha=0.3)
    return _b64(fig)


def chart_sensitivity(grid_data: dict) -> str:
    mat = np.array(grid_data["sharpe_grid"])
    fig, ax = plt.subplots(figsize=(8, 4.5))
    vmax = max(abs(mat.min()), abs(mat.max()), 0.1)
    cmap = mcolors.LinearSegmentedColormap.from_list("rg", [RED, PANEL, TEAL])
    im = ax.imshow(mat, aspect="auto", cmap=cmap, vmin=-vmax, vmax=vmax)
    for i, lb in enumerate(grid_data["lookbacks"]):
        for j, ms in enumerate(grid_data["min_scores"]):
            ax.text(j, i, f"{mat[i,j]:.2f}", ha="center", va="center",
                    fontsize=9, color=TEXT, fontweight="bold")
    ax.set_xticks(range(len(grid_data["min_scores"])))
    ax.set_xticklabels([str(x) for x in grid_data["min_scores"]], fontsize=9)
    ax.set_yticks(range(len(grid_data["lookbacks"])))
    ax.set_yticklabels([str(x) for x in grid_data["lookbacks"]], fontsize=9)
    ax.set_xlabel("Min score", fontsize=9)
    ax.set_ylabel("Lookback (days)", fontsize=9)
    ax.set_title("Sharpe ratio — lookback vs. min_score", color=MUTED, fontsize=9)
    plt.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    return _b64(fig)


def chart_walkforward(in_res: BacktestResult, out_res: BacktestResult) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(11, 4), gridspec_kw={"wspace": 0.35})
    pairs = [("CAGR (%)", in_res.cagr, out_res.cagr),
             ("Sharpe",   in_res.sharpe, out_res.sharpe),
             ("Max DD (%)", in_res.max_drawdown_pct, out_res.max_drawdown_pct)]
    for ax, (lbl, iv, ov) in zip(axes, pairs):
        bars = ax.bar(["In-sample", "Out-of-sample"], [iv, ov],
                      color=[TEAL, AMBER], width=0.5)
        ax.set_title(lbl, color=MUTED, fontsize=9)
        ax.grid(True, alpha=0.3, axis="y")
        ax.axhline(0, color=LINE, linewidth=0.8)
        for bar, v in zip(bars, [iv, ov]):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + (abs(iv) + abs(ov)) * 0.02,
                    f"{v:.2f}", ha="center", va="bottom",
                    fontsize=9, color=TEXT, fontweight="bold")
    return _b64(fig)


# ─── full report ──────────────────────────────────────────────────────────────

def metric_card(label: str, value: str, color: str = TEXT) -> str:
    return (f'<div class="metric">'
            f'<div class="mlabel">{label}</div>'
            f'<div class="mvalue" style="color:{color}">{value}</div>'
            f'</div>')


def sym_table(res: BacktestResult) -> str:
    bd = res.symbol_breakdown()
    if not bd:
        return "<p>No completed trades.</p>"
    rows = ""
    for sym, d in sorted(bd.items(), key=lambda x: -x[1]["total_pl"]):
        wr = d["win_rate"]
        pl = d["total_pl"]
        color = TEAL if pl >= 0 else RED
        rows += (f'<tr><td>{sym}</td><td>{d["trades"]}</td>'
                 f'<td style="color:{TEAL if wr>=50 else RED}">{wr:.0f}%</td>'
                 f'<td>{d["avg_pl_pct"]:+.2f}%</td>'
                 f'<td style="color:{color}">${pl:+,.0f}</td></tr>')
    return (f'<table><thead><tr>'
            f'<th>Symbol</th><th>Trades</th><th>Win rate</th>'
            f'<th>Avg P&L</th><th>Total P&L</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def generate_report(
    res: BacktestResult,
    wf: Optional[dict] = None,
    mc: Optional[dict] = None,
    sensitivity: Optional[dict] = None,
    title: str = "Range Bot — Backtest Report",
    note: str = "",
) -> str:
    # ── charts ──────────────────────────────────────────────────────────────
    eq_b64  = chart_equity(res)
    mo_b64  = chart_monthly(res)
    tr_b64  = chart_trades(res.trades)
    mc_b64  = chart_monte_carlo(mc, res.start_equity) if mc else ""
    wf_b64  = chart_walkforward(wf["in_sample"], wf["out_of_sample"]) if wf else ""
    sen_b64 = chart_sensitivity(sensitivity) if sensitivity else ""

    # ── metric values ────────────────────────────────────────────────────────
    c_cagr  = TEAL if res.cagr    > 0 else RED
    c_sharpe= TEAL if res.sharpe  > 0.5 else (AMBER if res.sharpe > 0 else RED)
    c_pf    = TEAL if res.profit_factor > 1.2 else (AMBER if res.profit_factor > 1 else RED)
    c_wr    = TEAL if res.win_rate > 50 else RED
    pf_str  = f"{res.profit_factor:.2f}" if res.profit_factor < 99 else "∞"

    mc_note = (f'<div class="mcnote">'
               f'Monte Carlo ({mc.get("win_pct",0):.0f}% of 2 000 shuffles beat starting equity) · '
               f'5th pct: ${mc.get("final_p5",0):,.0f} · '
               f'Median: ${mc.get("final_mean",0):,.0f} · '
               f'95th pct: ${mc.get("final_p95",0):,.0f}'
               f'</div>') if mc else ""

    wf_note = ""
    if wf:
        oor = wf["out_of_sample"]
        c = TEAL if oor.cagr > 0 else RED
        wf_note = (f'<div class="mcnote">'
                   f'Walk-forward out-of-sample — CAGR <span style="color:{c}">{oor.cagr:.1f}%</span> · '
                   f'Sharpe {oor.sharpe:.2f} · Max DD {oor.max_drawdown_pct:.1f}%</div>')

    settings = res.settings_used
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Space+Grotesk:wght@600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:{DARK};--panel:{PANEL};--line:{LINE};--text:{TEXT};--muted:{MUTED};
  --teal:{TEAL};--amber:{AMBER};--red:{RED};--steel:{STEEL};}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'IBM Plex Mono',monospace;
  font-size:14px;padding:24px 20px 60px;line-height:1.5}}
.wrap{{max-width:1000px;margin:0 auto}}
header{{padding:24px 0 18px;border-bottom:1px solid var(--line);margin-bottom:24px}}
h1{{font-family:'Space Grotesk',sans-serif;font-size:clamp(22px,4vw,34px);
  font-weight:700;letter-spacing:-.02em;color:var(--teal)}}
.sub{{color:var(--muted);font-size:12px;margin-top:6px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:18px 0 24px}}
.metric{{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:14px 16px}}
.mlabel{{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}}
.mvalue{{font-size:22px;font-weight:600;margin-top:4px}}
.section{{margin:28px 0 12px;font-size:11px;letter-spacing:.2em;text-transform:uppercase;
  color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:6px}}
.chart{{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:16px;margin:12px 0}}
.cap{{font-size:11px;color:var(--muted);margin-top:8px;text-align:center}}
table{{width:100%;border-collapse:collapse;background:var(--panel);
  border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:12px 0}}
th{{background:rgba(255,255,255,.04);padding:10px 14px;text-align:left;
  font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  border-bottom:1px solid var(--line)}}
td{{padding:9px 14px;border-bottom:1px solid rgba(41,51,62,.6);font-size:12px}}
tr:last-child td{{border-bottom:none}}
.mcnote{{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:10px 14px;font-size:11px;color:var(--muted);margin:10px 0}}
.warn{{background:rgba(224,162,74,.08);border:1px solid rgba(224,162,74,.35);
  border-radius:8px;padding:12px 16px;font-size:12px;color:var(--amber);margin:20px 0}}
.params{{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:10px 16px;font-size:11px;color:var(--muted);margin:10px 0;display:flex;flex-wrap:wrap;gap:14px}}
.params b{{color:var(--text)}}
</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Range Bot · Backtest Report</h1>
<div class="sub">Strategy: <b>{settings.get('mode','range')}</b> &nbsp;·&nbsp;
 Lookback: <b>{settings.get('lookback',20)}d</b> &nbsp;·&nbsp;
 Min score: <b>{settings.get('min_score',60)}</b> &nbsp;·&nbsp;
 {len(res.trades)} trades &nbsp;·&nbsp; ${res.start_equity:,.0f} starting capital &nbsp;·&nbsp;
 {res.equity_curve[0].date if res.equity_curve else '—'} → {res.equity_curve[-1].date if res.equity_curve else '—'}</div>
</header>

<div class="warn">⚠  Past backtested performance does not guarantee future results.
Synthetic data is used when Yahoo Finance is unreachable (this sandbox). Run on
your own machine to get results against real historical bars. This is a research
tool, not investment advice.</div>

{'<div class="warn">⚡ Using SYNTHETIC data (internet not available here). Run run_backtest.py on your machine to use real Yahoo Finance data and get genuine historical results.</div>' if note else ''}

<div class="params">
  <span>Symbols: <b>{', '.join(settings.get('symbols',[]))}</b></span>
  <span>Mode: <b>{settings.get('mode')}</b></span>
  <span>Lookback: <b>{settings.get('lookback')}d</b></span>
  <span>Min score: <b>{settings.get('min_score')}</b></span>
  <span>Risk/trade: <b>{settings.get('risk_pct',0.01):.0%}</b></span>
</div>

<div class="section">Performance summary</div>
<div class="grid">
  {metric_card("Total return", f"{res.total_return_pct:+.1f}%", c_cagr)}
  {metric_card("CAGR", f"{res.cagr:+.1f}%", c_cagr)}
  {metric_card("Sharpe", f"{res.sharpe:.2f}", c_sharpe)}
  {metric_card("Sortino", f"{res.sortino:.2f}", c_sharpe)}
  {metric_card("Max drawdown", f"{res.max_drawdown_pct:.1f}%", RED if res.max_drawdown_pct > 20 else AMBER if res.max_drawdown_pct > 10 else TEAL)}
  {metric_card("Calmar", f"{res.calmar:.2f}", c_sharpe)}
  {metric_card("Win rate", f"{res.win_rate:.1f}%", c_wr)}
  {metric_card("Profit factor", pf_str, c_pf)}
  {metric_card("Avg win", f"{res.avg_win_pct:+.2f}%", TEAL)}
  {metric_card("Avg loss", f"{res.avg_loss_pct:+.2f}%", RED)}
  {metric_card("Expectancy", f"{res.expectancy_pct:+.3f}%", c_pf)}
  {metric_card("Avg hold", f"{res.avg_hold_days:.1f}d", TEXT)}
</div>

<div class="section">Equity curve & drawdown</div>
{_img(eq_b64)}

<div class="section">Monthly returns</div>
{_img(mo_b64, "Teal = positive month · Red = negative month")}

<div class="section">Trade analysis</div>
{_img(tr_b64)}

{'<div class="section">Walk-forward validation</div>' + _img(wf_b64) + wf_note if wf_b64 else ''}

{'<div class="section">Monte Carlo — 2 000 trade-sequence shuffles</div>' + _img(mc_b64) + mc_note if mc_b64 else ''}

{'<div class="section">Parameter sensitivity (Sharpe ratio)</div>' + _img(sen_b64, "Green = higher Sharpe · Red = lower or negative") if sen_b64 else ''}

<div class="section">Per-symbol breakdown</div>
{sym_table(res)}

<div class="section">Interpretation guide</div>
<table>
<thead><tr><th>Metric</th><th>Target</th><th>Yours</th><th>What it means</th></tr></thead>
<tbody>
<tr><td>Sharpe</td><td>&gt; 0.8</td><td style="color:{c_sharpe}">{res.sharpe:.2f}</td><td>Risk-adjusted return (annualised). &gt;1 is excellent.</td></tr>
<tr><td>Profit factor</td><td>&gt; 1.3</td><td style="color:{c_pf}">{pf_str}</td><td>Gross wins ÷ gross losses. 1.3+ = robust edge.</td></tr>
<tr><td>Win rate</td><td>varies</td><td style="color:{c_wr}">{res.win_rate:.1f}%</td><td>Matters less than the win/loss ratio. 45% win rate is fine if avg win >> avg loss.</td></tr>
<tr><td>Max drawdown</td><td>&lt; 20%</td><td style="color:{RED if res.max_drawdown_pct>20 else TEAL}">{res.max_drawdown_pct:.1f}%</td><td>Worst peak-to-trough. Your pain tolerance sets the limit.</td></tr>
<tr><td>Monte Carlo win %</td><td>&gt; 70%</td><td>{'—' if not mc else f"{mc.get('win_pct',0):.0f}%"}</td><td>% of shuffled simulations that beat starting equity. Tests if edge is structural, not sequencing luck.</td></tr>
</tbody></table>
</div></body></html>"""
    return html
