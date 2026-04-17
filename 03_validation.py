# ============================================================
# TRADECLEANSE — NOTEBOOK 03 : Validation du Dataset Nettoye
# DCLE821 — QuantAxis Capital
# Etudiant(s) : ___________________________________
# Date        : ___________________________________
# ============================================================
#
# Approche choisie : tests pandas + assertions Python (approche B).
# Chaque test retourne [PASS] ou [FAIL] avec le detail.
# ============================================================

import re

import numpy as np
import pandas as pd

VALID_ASSET_CLASS = {"equity", "bond", "derivative", "fx"}
ISIN_REGEX = r"^[A-Z]{2}[A-Z0-9]{10}$"


def test_result(test_id: int, name: str, condition: bool, detail: str) -> dict:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {test_id:02d} - {name} | {detail}")
    return {"test_id": test_id, "name": name, "status": status, "detail": detail}


def run_suite(df: pd.DataFrame) -> pd.DataFrame:
    results = []

    results.append(
        test_result(1, "unicite_trade_id", df["trade_id"].duplicated().sum() == 0, f"doublons={int(df['trade_id'].duplicated().sum())}")
    )

    mandatory = ["trade_id", "counterparty_id_hash", "isin", "trade_date", "asset_class", "price", "quantity", "default_flag"]
    missing_total = int(sum(df[c].isna().sum() for c in mandatory if c in df.columns))
    results.append(test_result(2, "non_null_colonnes_obligatoires", missing_total == 0, f"null_total={missing_total}"))

    settle_bad = ((df["settlement_date"] < df["trade_date"]) & df["settlement_date"].notna() & df["trade_date"].notna()).sum()
    results.append(test_result(3, "settlement_ge_trade", int(settle_bad) == 0, f"violations={int(settle_bad)}"))

    bidask_bad = ((df["bid"] >= df["ask"]) & df["bid"].notna() & df["ask"].notna()).sum()
    results.append(test_result(4, "bid_lt_ask", int(bidask_bad) == 0, f"violations={int(bidask_bad)}"))

    pbad = ((df["price"] < df["bid"] * 0.995) | (df["price"] > df["ask"] * 1.005)).fillna(False).sum()
    results.append(test_result(5, "price_dans_spread", int(pbad) == 0, f"violations={int(pbad)}"))

    mid = (df["bid"] + df["ask"]) / 2
    mbad = (((df["mid_price"] - mid).abs() / mid) > 0.01).fillna(False).sum()
    results.append(test_result(6, "mid_price_coherent", int(mbad) == 0, f"violations={int(mbad)}"))

    ac_bad_values = set(df["asset_class"].dropna().str.lower().unique()) - VALID_ASSET_CLASS
    results.append(test_result(7, "asset_class_valide", len(ac_bad_values) == 0, f"invalides={sorted(ac_bad_values)}"))

    contradiction = ((df["credit_rating"].isin(["AAA", "AA", "A"])) & (df["default_flag"] == 1)).sum()
    results.append(test_result(8, "rating_default_coherent", int(contradiction) == 0, f"violations={int(contradiction)}"))

    notional_bad = (df["notional_eur"] <= 0).sum()
    results.append(test_result(9, "notional_strictement_positif", int(notional_bad) == 0, f"violations={int(notional_bad)}"))

    risk_bad = ((df["country_risk"] < 0) | (df["country_risk"] > 100)).fillna(False).sum()
    results.append(test_result(10, "country_risk_range", int(risk_bad) == 0, f"violations={int(risk_bad)}"))

    isin_bad = (~df["isin"].astype(str).str.match(ISIN_REGEX, na=False)).sum()
    results.append(test_result(11, "format_isin", int(isin_bad) == 0, f"violations={int(isin_bad)}"))

    vol_bad = ((df["volatility_30d"] < 0.1) | (df["volatility_30d"] > 200)).fillna(False).sum()
    results.append(test_result(12, "volatility_range", int(vol_bad) == 0, f"violations={int(vol_bad)}"))

    completeness = (1 - (df.isna().sum().sum() / (df.shape[0] * df.shape[1]))) * 100
    results.append(test_result(13, "completude_globale_sup_90", completeness > 90, f"completude={completeness:.2f}%"))

    pii_in_clear = [c for c in ["counterparty_name", "counterparty_id", "trader_id"] if c in df.columns]
    results.append(test_result(14, "pas_de_pii_en_clair", len(pii_in_clear) == 0, f"colonnes_pii={pii_in_clear}"))

    return pd.DataFrame(results)


def main() -> None:
    df = pd.read_csv("data/tradecleanse_clean.csv", low_memory=False)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["settlement_date"] = pd.to_datetime(df["settlement_date"], errors="coerce")
    for col in ["bid", "ask", "mid_price", "price", "notional_eur", "country_risk", "volatility_30d", "default_flag"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["credit_rating"] = df["credit_rating"].astype(str).str.upper()

    print(f"Validation sur {len(df)} lignes, {df.shape[1]} colonnes")
    report = run_suite(df)
    passed = int((report["status"] == "PASS").sum())
    total = len(report)
    print("\n" + "=" * 60)
    print(f"SCORE FINAL: {passed}/{total}")
    print("=" * 60)
    if passed != total:
        print("Tests en echec:")
        for _, row in report[report["status"] == "FAIL"].iterrows():
            print(f"- {row['test_id']:02d} {row['name']} -> {row['detail']}")

    report.to_csv("ge_validation_report.csv", index=False)
    print("Rapport enregistre: ge_validation_report.csv")


if __name__ == "__main__":
    main()
