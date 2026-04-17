# ============================================================
# TRADECLEANSE — NOTEBOOK 02 : Pipeline de Nettoyage Complet
# DCLE821 — QuantAxis Capital
# Etudiant(s) : ___________________________________
# Date        : ___________________________________
# ============================================================
#
# CONTRAINTES OBLIGATOIRES :
#   - Ne jamais modifier tradecleanse_raw.csv
#   - Toujours travailler sur une copie : df = pd.read_csv(...).copy()
#   - Chaque etape doit etre loggee : nb lignes avant / apres / supprimees
#   - Chaque decision doit etre justifiee en commentaire (raison METIER)
#   - Le dataset final doit etre sauvegarde dans : tradecleanse_clean.csv
# ============================================================

import hashlib
import logging
import os

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("tradecleanse_pipeline.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

SENTINELS = ["#N/A", "N/A", "#VALUE!", "-", "nd", "null", "None", "na", "NaN", "missing", "n/a", "#NA"]
VALID_ASSET_CLASS = {"equity", "bond", "derivative", "fx"}
VALID_RATING = {"AAA", "AA", "A", "BBB", "BB", "B", "CCC", "D"}
NUMERIC_COLS = ["bid", "ask", "mid_price", "price", "notional_eur", "quantity", "volume_j", "volatility_30d", "country_risk"]


def log_step(label: str, before_rows: int, after_rows: int) -> None:
    logger.info("[%s] lignes: %s -> %s (%s)", label, before_rows, after_rows, after_rows - before_rows)


def replace_sentinels(df: pd.DataFrame) -> pd.DataFrame:
    before_nan = int(df.isna().sum().sum())
    df = df.copy()
    df.replace(SENTINELS, np.nan, inplace=True)
    df["country_risk"] = df["country_risk"].replace([99999, 99999.0, "99999"], np.nan)
    after_nan = int(df.isna().sum().sum())
    logger.info("[sentinelles] NaN: %s -> %s", before_nan, after_nan)
    return df


def drop_trade_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(subset="trade_id", keep="first").reset_index(drop=True)
    log_step("doublons_trade_id", before, len(df))
    return df


def cast_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["settlement_date"] = pd.to_datetime(df["settlement_date"], errors="coerce")
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["asset_class"] = df["asset_class"].astype(str).str.strip().str.lower().replace("nan", np.nan)
    df["credit_rating"] = df["credit_rating"].astype(str).str.strip().str.upper().replace("NAN", np.nan)
    df["sector"] = df["sector"].astype(str).str.strip().str.lower().replace("nan", np.nan)
    return df


def normalize_referentials(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    map_asset = {
        "equity": "equity",
        "equities": "equity",
        "eq": "equity",
        "bond": "bond",
        "fixed income": "bond",
        "fi": "bond",
        "derivative": "derivative",
        "derivatives": "derivative",
        "deriv": "derivative",
        "opt": "derivative",
        "fx": "fx",
        "forex": "fx",
        "foreign exchange": "fx",
    }
    df["asset_class"] = df["asset_class"].map(map_asset)
    df.loc[~df["credit_rating"].isin(VALID_RATING), "credit_rating"] = np.nan
    return df


def apply_business_rules(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    before = len(df)

    mask_bad_settle = (df["settlement_date"] < df["trade_date"]) & df["trade_date"].notna()
    df.loc[mask_bad_settle, "settlement_date"] = df.loc[mask_bad_settle, "trade_date"] + pd.offsets.BDay(2)
    logger.info("[regle] settlement < trade corrige: %s", int(mask_bad_settle.sum()))

    mask_bidask = (df["bid"] >= df["ask"]) & df["bid"].notna() & df["ask"].notna()
    df.loc[mask_bidask, ["bid", "ask"]] = df.loc[mask_bidask, ["ask", "bid"]].values
    logger.info("[regle] swap bid/ask: %s", int(mask_bidask.sum()))

    mid = (df["bid"] + df["ask"]) / 2
    bad_mid = ((df["mid_price"] - mid).abs() / mid > 0.01).fillna(False)
    df.loc[bad_mid, "mid_price"] = mid[bad_mid]
    logger.info("[regle] mid_price recalcule: %s", int(bad_mid.sum()))

    bad_price = ((df["price"] < df["bid"] * 0.995) | (df["price"] > df["ask"] * 1.005)).fillna(False)
    df.loc[bad_price, "price"] = df.loc[bad_price, "mid_price"]
    logger.info("[regle] price hors borne corrige: %s", int(bad_price.sum()))

    neg_notional = (df["notional_eur"] <= 0).fillna(False)
    df.loc[neg_notional, "notional_eur"] = df.loc[neg_notional, "notional_eur"].abs()
    logger.info("[regle] notionnel corrige: %s", int(neg_notional.sum()))

    wrong_rating_default = df["credit_rating"].isin(["AAA", "AA", "A"]) & (df["default_flag"] == 1)
    df.loc[wrong_rating_default, "credit_rating"] = "BBB"
    logger.info("[regle] rating contradictoire corrige: %s", int(wrong_rating_default.sum()))

    log_step("business_rules", before, len(df))
    return df


def enforce_ranges(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    range_rules = {
        "country_risk": (0, 100),
        "volatility_30d": (0.1, 200),
    }
    for col, (low, high) in range_rules.items():
        mask = (df[col] < low) | (df[col] > high)
        logger.info("[range] %s hors bornes -> NaN: %s", col, int(mask.fillna(False).sum()))
        df.loc[mask, col] = np.nan
    invalid_default = ~df["default_flag"].isin([0, 1])
    df.loc[invalid_default, "default_flag"] = np.nan
    return df


def impute_missing(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    before = len(df)

    n_trade_id_missing = int(df["trade_id"].isna().sum())
    if n_trade_id_missing:
        df = df.dropna(subset=["trade_id"]).copy()
        logger.info("[impute] lignes supprimees trade_id manquant: %s", n_trade_id_missing)

    too_sparse = (df.isna().mean() > 0.7)
    drop_cols = too_sparse[too_sparse].index.tolist()
    if drop_cols:
        logger.info("[impute] colonnes supprimees >70%% NaN: %s", drop_cols)
        df = df.drop(columns=drop_cols)

    miss_settle = df["settlement_date"].isna() & df["trade_date"].notna()
    df.loc[miss_settle, "settlement_date"] = df.loc[miss_settle, "trade_date"] + pd.offsets.BDay(2)

    num_cols = df.select_dtypes(include=[np.number]).columns
    cat_cols = df.select_dtypes(include=["object"]).columns
    for col in df.columns:
        n_missing = int(df[col].isna().sum())
        if n_missing == 0:
            continue
        df[f"{col}_was_missing"] = df[col].isna().astype(int)
        if col in num_cols:
            df[col] = df[col].fillna(df[col].median())
        elif col in cat_cols:
            mode_vals = df[col].mode(dropna=True)
            if not mode_vals.empty:
                df[col] = df[col].fillna(mode_vals.iloc[0])
        else:
            df[col] = df[col].ffill().bfill()
        logger.info("[impute] %s valeurs remplacees: %s", col, n_missing)

    log_step("imputation", before, len(df))
    return df


def pseudonymize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    salt = os.environ.get("CLEANSE_SALT", "default_salt_dev")

    def to_hash(value: object) -> str:
        if pd.isna(value):
            return np.nan
        return hashlib.sha256(f"{salt}{value}".encode("utf-8")).hexdigest()

    for col in ["counterparty_name", "counterparty_id", "trader_id"]:
        if col in df.columns:
            df[f"{col}_hash"] = df[col].apply(to_hash)
            df.drop(columns=[col], inplace=True)
            logger.info("[pii] colonne pseudonymisee: %s", col)
    return df


def quality_report(df_raw: pd.DataFrame, df_clean: pd.DataFrame) -> None:
    raw_nan = df_raw.isna().sum().sum()
    clean_nan = df_clean.isna().sum().sum()
    raw_dups = int(df_raw["trade_id"].duplicated().sum())
    clean_dups = int(df_clean["trade_id"].duplicated().sum())
    completeness = 1 - (clean_nan / (df_clean.shape[0] * df_clean.shape[1]))
    uniqueness = 1 - (clean_dups / max(df_clean.shape[0], 1))
    dqs = (0.6 * completeness + 0.4 * uniqueness) * 100

    print("\n" + "=" * 68)
    print("RAPPORT QUALITE FINAL")
    print("=" * 68)
    print(f"Lignes: {df_raw.shape[0]} -> {df_clean.shape[0]}")
    print(f"Colonnes: {df_raw.shape[1]} -> {df_clean.shape[1]}")
    print(f"NaN total: {raw_nan} -> {clean_nan}")
    print(f"Doublons trade_id: {raw_dups} -> {clean_dups}")
    print(f"Completude: {completeness:.4f}")
    print(f"Unicite: {uniqueness:.4f}")
    print(f"Data Quality Score: {dqs:.2f}%")
    print("=" * 68)


def main() -> None:
    df_raw = pd.read_csv("data/tradecleanse_raw.csv", low_memory=False).copy()
    logger.info("Dataset charge: %s lignes, %s colonnes", df_raw.shape[0], df_raw.shape[1])

    df = replace_sentinels(df_raw)
    df = drop_trade_duplicates(df)
    df = cast_columns(df)
    df = normalize_referentials(df)
    df = apply_business_rules(df)
    df = enforce_ranges(df)
    df = impute_missing(df)
    df = pseudonymize(df)

    df.to_csv("data/tradecleanse_clean.csv", index=False)
    logger.info("Fichier genere: data/tradecleanse_clean.csv")
    quality_report(df_raw, df)


if __name__ == "__main__":
    main()
