"""Curated European index constituents (Yahoo tickers).

US indices have clean constituent feeds (see index_components.py). Europe has no
equivalent free CSV, so these are hand-maintained lists of the largest members by
index weight — the ~30 names that drive most of each index's movement. The screener
caps to MAX_SCREENED_SIZE anyway, so full 100-name lists add little; a wrong ticker
degrades gracefully (no OHLCV -> the name is dropped, never a crash).

UPDATE CADENCE: European index membership is stable — a review once or twice a year
is plenty. FTSE reviews quarterly but the top names rarely change; DAX/CAC change ~1-2
names a year. Last curated: 2026-06.
"""

from __future__ import annotations

FTSE_100 = [
    "AZN.L", "SHEL.L", "HSBA.L", "ULVR.L", "BP.L", "RIO.L", "GSK.L", "REL.L",
    "DGE.L", "BATS.L", "GLEN.L", "LSEG.L", "NG.L", "AAL.L", "CPG.L", "RKT.L",
    "VOD.L", "BARC.L", "LLOY.L", "NWG.L", "STAN.L", "PRU.L", "TSCO.L", "IMB.L",
    "HLN.L", "FLTR.L", "EXPN.L", "AHT.L", "SSE.L", "RR.L", "BA.L",
]

DAX_40 = [
    "SAP.DE", "SIE.DE", "ALV.DE", "DTE.DE", "AIR.DE", "MBG.DE", "MUV2.DE",
    "BAS.DE", "BMW.DE", "IFX.DE", "DB1.DE", "ADS.DE", "DHL.DE", "VOW3.DE",
    "RWE.DE", "BAYN.DE", "MRK.DE", "EOAN.DE", "DBK.DE", "HEN3.DE", "VNA.DE",
    "CON.DE", "FRE.DE", "SHL.DE", "HNR1.DE", "SY1.DE", "ZAL.DE", "RHM.DE",
    "P911.DE", "QIA.DE",
]

CAC_40 = [
    "MC.PA", "OR.PA", "TTE.PA", "SAN.PA", "SU.PA", "AI.PA", "EL.PA", "BNP.PA",
    "RMS.PA", "CS.PA", "SAF.PA", "DG.PA", "KER.PA", "BN.PA", "GLE.PA", "ACA.PA",
    "STLAP.PA", "ENGI.PA", "CAP.PA", "DSY.PA", "LR.PA", "PUB.PA", "VIE.PA",
    "ORA.PA", "RI.PA", "HO.PA", "ML.PA", "STMPA.PA", "SGO.PA", "AIR.PA",
]

# Euro Stoxx 50 — largest eurozone names (blend of DE/FR/NL/IT/ES leaders).
EURO_STOXX_50 = [
    "ASML.AS", "MC.PA", "SAP.DE", "TTE.PA", "SIE.DE", "OR.PA", "SU.PA", "AIR.PA",
    "ALV.DE", "SAN.PA", "AI.PA", "IBE.MC", "ENEL.MI", "DTE.DE", "BNP.PA",
    "RMS.PA", "ISP.MI", "BBVA.MC", "SAN.MC", "ITX.MC", "ENI.MI", "UCG.MI",
    "MBG.DE", "BAS.DE", "BMW.DE", "ADYEN.AS", "PRX.AS", "INGA.AS", "NOKIA.HE",
    "STLAP.PA", "CS.PA", "DB1.DE", "MUV2.DE", "EL.PA", "BN.PA",
]

_LISTS = {
    "ftse 100": FTSE_100, "ftse100": FTSE_100, "ftse": FTSE_100, "uk": FTSE_100,
    "dax": DAX_40, "germany": DAX_40,
    "cac 40": CAC_40, "cac": CAC_40, "france": CAC_40,
    "euro stoxx 50": EURO_STOXX_50, "euro stoxx": EURO_STOXX_50,
    "stoxx 50": EURO_STOXX_50, "stoxx": EURO_STOXX_50,
}


def _dedupe(seq):
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s); out.append(s)
    return out


def constituents_for(directive: str) -> list[str] | None:
    """Return the European constituent tickers for a directive, or None if not a
    known European index. 'europe' returns a blended top set across FTSE/DAX/CAC."""
    low = (directive or "").lower().strip()
    if not low:
        return None
    if low in ("europe", "european indices", "european"):
        return _dedupe(FTSE_100[:12] + DAX_40[:12] + CAC_40[:12])
    if low in _LISTS:
        return list(_LISTS[low])
    for k in sorted(_LISTS, key=len, reverse=True):   # longest-key substring match
        if k in low:
            return list(_LISTS[k])
    return None
