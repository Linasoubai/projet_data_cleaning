import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

SENTINELS = [
    "#N/A",
    "N/A",
    "#VALUE!",
    "-",
    "nd",
    "null",
    "None",
    "na",
    "NaN",
    "missing",
    "99999",
]

VALID_ASSET_CLASS = {"equity", "bond", "derivative", "fx"}
VALID_RATINGS = {"AAA", "AA", "A", "BBB", "BB", "B", "CCC", "D"}


def load_raw_dataset(path: str = "data/tradecleanse_raw.csv") -> pd.DataFrame:
    df_raw = pd.read_csv(path, low_memory=False, na_values=SENTINELS, keep_default_na=True).copy()
    print(f"Dataset charge: {df_raw.shape[0]} lignes x {df_raw.shape[1]} colonnes")
    return df_raw


def basic_profile(df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("PROFILING DE BASE")
    print("=" * 72)
    print(df.dtypes.to_string())

    missing = (
        pd.DataFrame(
            {
                "nb_missing": df.isna().sum(),
                "pct_missing": (df.isna().sum() / len(df) * 100).round(2),
            }
        )
        .sort_values("pct_missing", ascending=False)
    )
    print("\nTop colonnes avec valeurs manquantes:")
    print(missing[missing["nb_missing"] > 0].head(15).to_string())

    print("\nStatistiques numeriques:")
    print(df.describe(include=[np.number]).round(2).to_string())

    print("\nCardinalite de colonnes categorielles:")
    for col in df.select_dtypes(include="object").columns:
        print(f"- {col}: {df[col].nunique(dropna=True)} valeurs uniques")


def detect_rule_violations(df: pd.DataFrame) -> pd.DataFrame:
    audit = df.copy()
    audit["trade_date"] = pd.to_datetime(audit["trade_date"], errors="coerce")
    audit["settlement_date"] = pd.to_datetime(audit["settlement_date"], errors="coerce")

    for col in ["bid", "ask", "mid_price", "price", "notional_eur", "country_risk", "volatility_30d"]:
        audit[col] = pd.to_numeric(audit[col], errors="coerce")

    rating = audit["credit_rating"].astype(str).str.strip().str.upper()
    asset = audit["asset_class"].astype(str).str.strip().str.lower()
    mid_theo = (audit["bid"] + audit["ask"]) / 2

    checks = [
        ("trade_id_duplique", audit["trade_id"].duplicated(keep=False)),
        ("settlement_avant_trade", audit["settlement_date"] < audit["trade_date"]),
        ("bid_superieur_ou_egal_ask", audit["bid"] >= audit["ask"]),
        ("mid_price_incoherent_1pct", ((audit["mid_price"] - mid_theo).abs() / mid_theo).fillna(0) > 0.01),
        (
            "price_hors_borne_bid_ask",
            (audit["price"] < audit["bid"] * 0.995) | (audit["price"] > audit["ask"] * 1.005),
        ),
        ("notional_non_positif", audit["notional_eur"] <= 0),
        ("asset_class_hors_referentiel", ~asset.isin(VALID_ASSET_CLASS)),
        ("credit_rating_hors_referentiel", ~rating.isin(VALID_RATINGS)),
        ("country_risk_hors_plage", (audit["country_risk"] < 0) | (audit["country_risk"] > 100)),
        ("volatility_hors_plage", (audit["volatility_30d"] < 0.1) | (audit["volatility_30d"] > 200)),
        ("default_flag_invalide", ~audit["default_flag"].isin([0, 1])),
        ("rating_ig_en_default", rating.isin(["AAA", "AA", "A"]) & (audit["default_flag"] == 1)),
    ]

    rows = []
    for rule_name, mask in checks:
        count = int(mask.fillna(False).sum())
        if count > 0:
            rows.append({"regle": rule_name, "nb_lignes": count, "pct_lignes": round(100 * count / len(audit), 2)})

    report = pd.DataFrame(rows).sort_values("nb_lignes", ascending=False)
    print("\n" + "=" * 72)
    print("ANOMALIES SELON REGLES METIER")
    print("=" * 72)
    if report.empty:
        print("Aucune anomalie detectee.")
    else:
        print(report.to_string(index=False))
    return report


def build_visuals(df: pd.DataFrame) -> None:
    viz = df.copy()
    viz["trade_date"] = pd.to_datetime(viz["trade_date"], errors="coerce")
    viz["settlement_date"] = pd.to_datetime(viz["settlement_date"], errors="coerce")
    for col in ["bid", "ask", "price", "notional_eur"]:
        viz[col] = pd.to_numeric(viz[col], errors="coerce")

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.suptitle("TradeCleanse - Profiling", fontsize=14, fontweight="bold")

    missing_pct = (viz.isna().sum() / len(viz) * 100).sort_values()
    axes[0, 0].barh(missing_pct.index, missing_pct.values, color="#4c78a8")
    axes[0, 0].set_title("% valeurs manquantes")
    axes[0, 0].set_xlabel("Pourcentage")

    asset_dist = viz["asset_class"].astype(str).str.lower().str.strip().value_counts().head(12)
    axes[0, 1].bar(asset_dist.index, asset_dist.values, color="#f58518")
    axes[0, 1].set_title("Distribution asset_class")
    axes[0, 1].tick_params(axis="x", rotation=45)

    mask_valid_bidask = viz["bid"].notna() & viz["ask"].notna()
    axes[1, 0].scatter(viz.loc[mask_valid_bidask, "bid"], viz.loc[mask_valid_bidask, "ask"], s=8, alpha=0.25)
    axes[1, 0].set_title("Nuage bid vs ask")
    axes[1, 0].set_xlabel("bid")
    axes[1, 0].set_ylabel("ask")

    delay = (viz["settlement_date"] - viz["trade_date"]).dt.days.dropna()
    axes[1, 1].hist(delay, bins=25, color="#54a24b", alpha=0.8, edgecolor="black")
    axes[1, 1].axvline(0, color="red", linestyle="--", linewidth=1)
    axes[1, 1].axvline(2, color="black", linestyle=":", linewidth=1)
    axes[1, 1].set_title("Distribution du delai de settlement")
    axes[1, 1].set_xlabel("Jours")

    plt.tight_layout()
    plt.savefig("01_profiling_report.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("\nGraphique enregistre: 01_profiling_report.png")


def main() -> None:
    df = load_raw_dataset()
    basic_profile(df)
    anomalies = detect_rule_violations(df)
    anomalies.to_csv("01_anomaly_report.csv", index=False)
    print("Rapport enregistre: 01_anomaly_report.csv")
    build_visuals(df)


if __name__ == "__main__":
    main()
