"""Automated quarterly donor report from programme monitoring data.

Monitoring data generated with a fixed seed for modelled households, districts and programmes.
Produces an HTML report with indicators, confidence intervals and a significance test.
"""
from pathlib import Path
import base64
import io
import json
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SEED = 5


def generate(seed: int = SEED, n: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    districts = ["District A", "District B", "District C", "District D", "District E", "District F"]
    follow_rate = dict(zip(districts, [0.85, 0.80, 0.75, 0.30, 0.25, 0.20]))   # follow-up support coverage
    d = rng.choice(districts, n)
    prog = rng.choice(["Agriculture training", "Livelihoods", "Health & hygiene"], n, p=[.45, .3, .25])
    follow = rng.random(n) < np.vectorize(follow_rate.get)(d)
    p_success = 0.38 + 0.30 * follow + np.where(prog == "Health & hygiene", 0.05, 0)
    success = rng.random(n) < p_success
    q = rng.choice(["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"], n)
    income_gain = np.where(success, rng.lognormal(np.log(90), 0.5, n), rng.lognormal(np.log(25), 0.6, n))
    return pd.DataFrame({"household_id": np.arange(1, n + 1), "district": d, "programme": prog, "quarter": q,
                         "follow_up_support": follow, "outcome_success": success,
                         "monthly_income_gain_usd": income_gain.round(1)})


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p = k / n; den = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / den; h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return c - h, c + h


def analyse(df: pd.DataFrame) -> dict:
    by_d = df.groupby("district").agg(households=("household_id", "size"), successes=("outcome_success", "sum"),
                                      follow_up_pct=("follow_up_support", "mean"))
    by_d["success_pct"] = 100 * by_d["successes"] / by_d["households"]
    ci = [wilson(int(k), int(n)) for k, n in zip(by_d["successes"], by_d["households"])]
    by_d["ci_low"] = [100 * a for a, _ in ci]; by_d["ci_high"] = [100 * b for _, b in ci]
    by_d["follow_up_pct"] *= 100
    table = pd.crosstab(df["follow_up_support"], df["outcome_success"])
    chi2, p, dof, _ = stats.chi2_contingency(table)
    rates = df.groupby("follow_up_support")["outcome_success"].mean()
    n1, n0 = table.loc[True].sum(), table.loc[False].sum()
    diff = rates[True] - rates[False]
    se = np.sqrt(rates[True] * (1 - rates[True]) / n1 + rates[False] * (1 - rates[False]) / n0)
    return {
        "by_district": by_d.round(1),
        "households": len(df),
        "overall_success_pct": round(100 * df["outcome_success"].mean(), 1),
        "success_with_follow_up_pct": round(100 * rates[True], 1),
        "success_without_follow_up_pct": round(100 * rates[False], 1),
        "difference_pct_points": round(100 * diff, 1),
        "difference_95ci": [round(100 * (diff - 1.96 * se), 1), round(100 * (diff + 1.96 * se), 1)],
        "chi2": round(chi2, 1), "p_value": float(p),
        "median_income_gain_usd": round(df["monthly_income_gain_usd"].median(), 1),
        "by_quarter": df.groupby("quarter")["outcome_success"].mean().mul(100).round(1).to_dict(),
    }


def build_report(df: pd.DataFrame, res: dict, out: Path) -> None:
    bd = res["by_district"].sort_values("success_pct")
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.6))
    ax[0].barh(bd.index, bd["success_pct"], xerr=[bd["success_pct"] - bd["ci_low"], bd["ci_high"] - bd["success_pct"]],
               color="#2E6F95", capsize=3)
    ax[0].set_xlabel("% households with successful outcome (95% CI)"); ax[0].set_title("Outcome success by district")
    ax[1].scatter(bd["follow_up_pct"], bd["success_pct"], s=bd["households"] / 4, color="#BC4749")
    for name, r in bd.iterrows():
        ax[1].annotate(name, (r["follow_up_pct"], r["success_pct"]), fontsize=8, xytext=(4, 4), textcoords="offset points")
    ax[1].set_xlabel("% households receiving follow-up support"); ax[1].set_ylabel("success %")
    ax[1].set_title("Follow-up support coverage vs success")
    fig.suptitle("Programme monitoring", fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.92]); fig.savefig(out / "report_chart.png", dpi=130)
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=100); plt.close(fig)
    img = base64.b64encode(buf.getvalue()).decode()
    p = res["p_value"]; ptxt = "< 0.001" if p < 0.001 else f"= {p:.3f}"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Quarterly donor report</title>
<style>body{{font-family:system-ui,Arial;max-width:980px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px;text-align:right}}
.note{{background:#fff4e5;border-left:4px solid #e9a23b;padding:8px 12px}}</style></head><body>
<h1>Quarterly Programme Report - 2025</h1>
<p class="note"><b>Note.</b> Auto-generated from seeded monitoring data.</p>
<h2>Headline indicators</h2><ul>
<li>Households reached: {res['households']:,}</li>
<li>Successful outcomes: {res['overall_success_pct']}%</li>
<li>With follow-up support: {res['success_with_follow_up_pct']}% vs without: {res['success_without_follow_up_pct']}%
 (difference {res['difference_pct_points']} pp, 95% CI {res['difference_95ci'][0]} to {res['difference_95ci'][1]}; chi-square {res['chi2']}, p {ptxt})</li>
<li>Median monthly income gain: USD {res['median_income_gain_usd']}</li></ul>
<img src="data:image/png;base64,{img}" style="width:100%">
<h2>By district</h2>{res['by_district'].to_html()}
<h2>Recommendation</h2><p>Districts with low follow-up coverage underperform. Extending follow-up support is the main lever;
this association is observational, so a staggered roll-out would let the effect be tested causally.</p></body></html>"""
    (out / "quarterly_report.html").write_text(html)


def main() -> dict:
    t0 = time.perf_counter()
    df = generate(); df.to_csv(ROOT / "data" / "monitoring.csv", index=False)
    res = analyse(df); build_report(df, res, ROOT / "outputs")
    res["report_generation_seconds"] = round(time.perf_counter() - t0, 2)
    out = {k: v for k, v in res.items() if k != "by_district"}
    (ROOT / "outputs" / "summary.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
