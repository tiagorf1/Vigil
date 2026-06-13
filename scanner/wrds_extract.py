"""WRDS extractor — survivorship-free CRSP + IBES, written to local parquet.

The lab/production split: WRDS data is pulled HERE, once, into local files the
lab reads. The live system never touches WRDS (academic license + it expires at
graduation). Run this with YOUR WRDS login; nothing here ships to production.

Setup (one time):
    pip install wrds pyarrow
    python -m scanner.wrds_extract crsp     # first run prompts for WRDS user/pass,
                                            # offers to save a ~/.pgpass so future
                                            # runs are passwordless
    python -m scanner.wrds_extract ibes     # for the PEAD (H-001) SUE inputs

Outputs (gitignored):
    data/crsp_monthly.parquet   permno, date, ret (delisting-adjusted), mktcap,
                                price, shrcd, exchcd, ticker, comnam
    data/ibes_eps.parquet       ticker, anndate, actual, median_est, num_est, fpedats

Why these two: CRSP gives a survivorship-free universe with delisting returns
(the thing free data gets wrong); IBES gives point-in-time estimates so SUE is
real, not reconstructed. Both are the documented difference-makers for small-cap
equity signals; EDGAR (insiders) needs no WRDS.
"""

from __future__ import annotations

import argparse
import pathlib

OUT = pathlib.Path("data")


def _conn():
    import wrds
    return wrds.Connection()


def crsp_monthly(start: str = "2005-01-01") -> None:
    """Monthly common-stock returns, delisting-adjusted, survivorship-free."""
    db = _conn()
    # msf = monthly stock file; msenames = names/codes valid by date range;
    # msedelist = delisting returns. Common stocks only (shrcd 10,11).
    sql = f"""
        select a.permno, a.date, a.ret, a.prc, a.shrout, a.vol,
               b.shrcd, b.exchcd, b.ticker, b.comnam,
               d.dlret, d.dlstcd
        from crsp.msf a
        inner join crsp.msenames b
            on a.permno = b.permno and b.namedt <= a.date and a.date <= b.nameendt
        left join crsp.msedelist d
            on a.permno = d.permno and date_trunc('month', a.date) = date_trunc('month', d.dlstdt)
        where a.date >= '{start}' and b.shrcd in (10, 11)
    """
    df = db.raw_sql(sql, date_cols=["date"])
    db.close()
    # Delisting-adjusted return: use dlret where the month delisted, else ret.
    df["ret_adj"] = df["ret"].fillna(0.0)
    mask = df["dlret"].notna()
    df.loc[mask, "ret_adj"] = (1 + df.loc[mask, "ret"].fillna(0.0)) * (1 + df.loc[mask, "dlret"]) - 1
    df["mktcap"] = (df["prc"].abs() * df["shrout"]).where(df["shrout"] > 0)
    OUT.mkdir(exist_ok=True)
    cols = ["permno", "date", "ret_adj", "prc", "mktcap", "vol",
            "shrcd", "exchcd", "ticker", "comnam"]
    df[cols].to_parquet(OUT / "crsp_monthly.parquet", index=False)
    print(f"wrote data/crsp_monthly.parquet  rows={len(df):,}  "
          f"names={df['permno'].nunique():,}  span={df['date'].min().date()}..{df['date'].max().date()}")


def ibes_eps(start: str = "2005-01-01") -> None:
    """Point-in-time EPS estimates + actuals, for SUE (the PEAD signal)."""
    db = _conn()
    # statsum_epsus = summary statistics (median, n) by statpers; actu_epsus = actuals.
    est = db.raw_sql(f"""
        select ticker, statpers, fpedats, meanest, medest, numest, stdev, fpi
        from ibes.statsum_epsus
        where fpi = '1' and statpers >= '{start}'
    """, date_cols=["statpers", "fpedats"])
    act = db.raw_sql(f"""
        select ticker, anndats, pends, value as actual
        from ibes.actu_epsus
        where measure = 'EPS' and pdicity = 'QTR' and anndats >= '{start}'
    """, date_cols=["anndats", "pends"])
    db.close()
    OUT.mkdir(exist_ok=True)
    est.to_parquet(OUT / "ibes_estimates.parquet", index=False)
    act.to_parquet(OUT / "ibes_actuals.parquet", index=False)
    print(f"wrote data/ibes_estimates.parquet ({len(est):,}) + ibes_actuals.parquet ({len(act):,})")
    print("SUE = (actual - median_est) / stdev_est, joined on ticker + nearest pre-announcement statpers.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="scanner.wrds_extract")
    ap.add_argument("dataset", choices=["crsp", "ibes"])
    ap.add_argument("--start", default="2005-01-01")
    args = ap.parse_args()
    if args.dataset == "crsp":
        crsp_monthly(args.start)
    else:
        ibes_eps(args.start)


if __name__ == "__main__":
    main()
