# ============================================================
# TRADECLEANSE — NOTEBOOK 04 : Bonus Expert
# DCLE821 — QuantAxis Capital
# Etudiant(s) : ___________________________________
# Date        : ___________________________________
# ============================================================
#
# Ce notebook contient 3 bonus independants.
# Chaque bonus vaut +1 point au-dela de 20.
# ============================================================

import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split


def detect_wash_trading(df_clean: pd.DataFrame) -> pd.DataFrame:
    grouped = df_clean.groupby(["isin", "trader_id_hash", "trade_date"], dropna=False)
    pairs = []
    for (isin, trader, dte), grp in grouped:
        if len(grp) < 2:
            continue
        tmp = grp[["trade_id", "price", "quantity"]].dropna().reset_index(drop=True)
        for i in range(len(tmp)):
            for j in range(i + 1, len(tmp)):
                p1, p2 = tmp.loc[i, "price"], tmp.loc[j, "price"]
                q1, q2 = tmp.loc[i, "quantity"], tmp.loc[j, "quantity"]
                if (p1 + p2) == 0 or (q1 + q2) == 0:
                    continue
                delta_p = abs(p1 - p2) / ((p1 + p2) / 2) * 100
                delta_q = abs(q1 - q2) / ((q1 + q2) / 2) * 100
                if delta_p <= 0.10 and delta_q <= 5.0:
                    pairs.append(
                        {
                            "trade_id_1": tmp.loc[i, "trade_id"],
                            "trade_id_2": tmp.loc[j, "trade_id"],
                            "isin": isin,
                            "trader_hash": trader,
                            "trade_date": dte,
                            "delta_price_pct": round(delta_p, 4),
                            "delta_qty_pct": round(delta_q, 4),
                        }
                    )
    return pd.DataFrame(pairs)


def run_drift_analysis(df_clean: pd.DataFrame) -> pd.DataFrame:
    features = ["price", "volatility_30d", "notional_eur", "volume_j", "country_risk"]
    early_cut = df_clean["trade_date"].min() + pd.Timedelta(days=90)
    late_cut = df_clean["trade_date"].max() - pd.Timedelta(days=90)
    early = df_clean[df_clean["trade_date"] <= early_cut]
    late = df_clean[df_clean["trade_date"] >= late_cut]

    rows = []
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    axes = axes.flatten()

    for idx, col in enumerate(features):
        e = early[col].dropna()
        l = late[col].dropna()
        ks, pval = ks_2samp(e, l)
        rows.append({"variable": col, "ks_stat": round(float(ks), 4), "p_value": round(float(pval), 6), "drift": pval < 0.05})

        axes[idx].hist(e, bins=40, alpha=0.6, density=True, label="early")
        axes[idx].hist(l, bins=40, alpha=0.6, density=True, label="late")
        axes[idx].set_title(f"{col} | KS={ks:.3f} p={pval:.4f}")
        axes[idx].legend()

    axes[-1].axis("off")
    plt.tight_layout()
    plt.savefig("04_drift_monitor.png", dpi=150, bbox_inches="tight")
    plt.close()
    return pd.DataFrame(rows)


def train_compare_model(df_raw: pd.DataFrame, df_clean: pd.DataFrame) -> pd.DataFrame:
    predictors = ["price", "quantity", "bid", "ask", "mid_price", "volume_j", "volatility_30d", "country_risk"]

    def run_once(df: pd.DataFrame, label: str) -> tuple:
        local = df.copy()
        for c in predictors + ["default_flag"]:
            local[c] = pd.to_numeric(local[c], errors="coerce")
        local = local.dropna(subset=["default_flag"])
        X = local[predictors].fillna(local[predictors].median())
        y = local["default_flag"].astype(int)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
        clf = RandomForestClassifier(n_estimators=160, max_depth=7, random_state=42)
        clf.fit(X_train, y_train)
        pred = clf.predict(X_test)
        prob = clf.predict_proba(X_test)[:, 1]
        fpr, tpr, _ = roc_curve(y_test, prob)
        row = {
            "dataset": label,
            "auc_roc": round(float(roc_auc_score(y_test, prob)), 4),
            "precision": round(float(precision_score(y_test, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_test, pred, zero_division=0)), 4),
        }
        return row, fpr, tpr

    raw_res, raw_fpr, raw_tpr = run_once(df_raw, "raw")
    clean_res, clean_fpr, clean_tpr = run_once(df_clean, "clean")

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(raw_fpr, raw_tpr, label=f"raw (AUC={raw_res['auc_roc']})")
    ax.plot(clean_fpr, clean_tpr, label=f"clean (AUC={clean_res['auc_roc']})")
    ax.plot([0, 1], [0, 1], "--", color="grey", linewidth=1)
    ax.set_xlabel("FPR")
    ax.set_ylabel("TPR")
    ax.set_title("ROC - raw vs clean")
    ax.legend()
    plt.tight_layout()
    plt.savefig("04_roc_comparison.png", dpi=150, bbox_inches="tight")
    plt.close()

    return pd.DataFrame([raw_res, clean_res])


def main() -> None:
    raw = pd.read_csv("data/tradecleanse_raw.csv", low_memory=False).copy()
    clean = pd.read_csv("data/tradecleanse_clean.csv", low_memory=False).copy()
    clean["trade_date"] = pd.to_datetime(clean["trade_date"], errors="coerce")

    print("=" * 60)
    print("BONUS 1 - WASH TRADING")
    print("=" * 60)
    wash = detect_wash_trading(clean)
    wash.to_csv("wash_trading_suspects.csv", index=False)
    print(f"Paires suspectes: {len(wash)}")

    print("\n" + "=" * 60)
    print("BONUS 2 - DRIFT")
    print("=" * 60)
    drift = run_drift_analysis(clean)
    drift.to_csv("drift_report.csv", index=False)
    print(drift.to_string(index=False))
    print("Graphique: 04_drift_monitor.png")

    print("\n" + "=" * 60)
    print("BONUS 3 - IMPACT ML")
    print("=" * 60)
    comp = train_compare_model(raw, clean)
    comp.to_csv("model_comparison.csv", index=False)
    print(comp.to_string(index=False))
    print("Graphique: 04_roc_comparison.png")


if __name__ == "__main__":
    main()
