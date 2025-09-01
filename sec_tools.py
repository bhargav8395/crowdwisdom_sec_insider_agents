import os
import time
import json
import math
import gzip
import io
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

import requests
import pandas as pd
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt

SEC_BASE = "https://www.sec.gov"
HEADERS = {
    "User-Agent": "CrowdWisdomTrading-Assessment (contact@example.com)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}

def _http_get(url: str, sleep: float = 0.2) -> bytes:
    """GET with polite rate limiting and gzip support."""
    time.sleep(sleep)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.content

def _quarter_of(dt: datetime) -> int:
    return (dt.month - 1)//3 + 1

def _idx_url_for_date(dt: datetime) -> str:
    q = _quarter_of(dt)
    y = dt.year
    ds = dt.strftime("%Y%m%d")
    return f"{SEC_BASE}/Archives/edgar/daily-index/{y}/Q{q}/master.{ds}.idx"

def fetch_daily_master_idx(dt: datetime) -> pd.DataFrame:
    """
    Download and parse master.YYYYMMDD.idx into a DataFrame with columns:
    CIK | Company Name | Form Type | Date Filed | Filename
    """
    url = _idx_url_for_date(dt)
    raw = _http_get(url)
    text = raw.decode("latin-1", errors="ignore")
    # Find the header delimiter line and parse pipe-delimited body
    lines = text.splitlines()
    # Data starts after a line that begins with '-----'
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("-----"):
            start = i + 1
    data_lines = [ln for ln in lines[start:] if "|" in ln]
    rows = [ln.split("|") for ln in data_lines]
    if not rows:
        return pd.DataFrame(columns=["CIK","Company Name","Form Type","Date Filed","Filename"])
    df = pd.DataFrame(rows, columns=["CIK","Company Name","Form Type","Date Filed","Filename"])
    return df

def list_form4_filings_for_range(start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """
    Collect all Form 4/4A filings from daily master index for each date in [start_dt, end_dt].
    Dates are in US ET per SEC daily index; we use UTC dates as approximation.
    """
    dates = []
    cur = start_dt
    while cur.date() <= end_dt.date():
        dates.append(cur)
        cur += timedelta(days=1)

    frames = []
    for d in dates:
        try:
            df = fetch_daily_master_idx(d)
            if not df.empty:
                df = df[df["Form Type"].isin(["4","4/A"])].copy()
                df["date"] = d.strftime("%Y-%m-%d")
                frames.append(df)
        except requests.HTTPError:
            # Index may not exist yet for today; skip quietly
            continue
        except Exception:
            continue
    if frames:
        out = pd.concat(frames, ignore_index=True)
        # Normalize some fields
        out["CIK"] = out["CIK"].astype(str).str.zfill(10)
        return out
    return pd.DataFrame(columns=["CIK","Company Name","Form Type","Date Filed","Filename","date"])

def _dir_index_json_url(cik: str, accession_no_dashes: str) -> str:
    return f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{accession_no_dashes}/index.json"

def _extract_accession_and_dirpath(filename: str) -> Tuple[str,str]:
    # Example filename: edgar/data/320193/0000320193-25-000123.txt
    # dir URL uses accession with NO dashes: 000032019325000123
    m = re.search(r"edgar/data/(\d+)/(\d{10}-\d{2}-\d{6})\.txt", filename)
    if not m:
        # Fallback: try any accession-like
        m2 = re.search(r"edgar/data/(\d+)/([0-9-]+)\.txt", filename)
        if not m2:
            raise ValueError(f"Cannot parse filename: {filename}")
        cik = m2.group(1)
        accession = m2.group(2).replace("-", "")
        dirpath = f"{SEC_BASE}/Archives/edgar/data/{cik}/{accession}"
        return accession, dirpath
    cik = m.group(1)
    accession = m.group(2).replace("-", "")
    dirpath = f"{SEC_BASE}/Archives/edgar/data/{cik}/{accession}"
    return accession, dirpath

def find_form4_xml_url(cik: str, filename: str) -> Optional[str]:
    """
    Given CIK and index 'Filename' from master.idx, locate the form4.xml URL.
    """
    accession, dirpath = _extract_accession_and_dirpath(filename)
    idx_url = _dir_index_json_url(cik, accession)
    try:
        data = json.loads(_http_get(idx_url).decode("utf-8"))
    except Exception:
        return None
    # Look for typical names
    for f in data.get("directory", {}).get("item", []):
        name = f.get("name","").lower()
        if name == "form4.xml" or name.endswith("_form4.xml") or (name.endswith(".xml") and "form4" in name):
            return f"{dirpath}/{f['name']}"
    return None

def parse_form4_xml(xml_bytes: bytes) -> Dict:
    """
    Return structured insider transactions from a Form 4 XML.
    """
    root = ET.fromstring(xml_bytes)
    ns = {"ns": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    def gx(path):
        return root.findall(path, ns) if ns else root.findall(path)

    issuer_sym = (root.findtext(".//issuerTradingSymbol", default="") or "").strip()
    issuer_name = (root.findtext(".//issuerName", default="") or "").strip()

    # Collect non-derivative transactions
    tx_rows = []
    for tx in gx(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = (tx.findtext("./transactionCoding/transactionCode", default="") or "").strip()
        shares = tx.findtext("./transactionAmounts/transactionShares/value")
        price = tx.findtext("./transactionAmounts/transactionPricePerShare/value")
        date = tx.findtext("./transactionDate/value")
        direct = tx.findtext("./ownershipNature/directOrIndirectOwnership/value")
        try:
            shares = float(shares) if shares is not None else None
        except:
            shares = None
        try:
            price = float(price) if price is not None else None
        except:
            price = None
        tx_rows.append({
            "issuerSymbol": issuer_sym,
            "issuerName": issuer_name,
            "transactionCode": code,
            "shares": shares,
            "price": price,
            "date": date,
            "ownership": direct
        })

    return {
        "issuerSymbol": issuer_sym,
        "issuerName": issuer_name,
        "transactions": tx_rows
    }

def collect_last24h_and_week() -> Dict[str, pd.DataFrame]:
    """
    Fetch Form 4 filings for last 24h and previous 7 days.
    Returns dict of DataFrames.
    """
    now = datetime.now(timezone.utc)
    # SEC index is daily; approximate last 24h by using today's and yesterday's indexes
    today = now
    yesterday = now - timedelta(days=1)
    last_week_start = now - timedelta(days=8)  # inclusive
    last_week_end = now - timedelta(days=1)    # inclusive

    last24_df = list_form4_filings_for_range(yesterday, today)
    week_df = list_form4_filings_for_range(last_week_start, last_week_end)

    return {"last24": last24_df, "week": week_df}

def build_activity_summary(filings_df: pd.DataFrame, max_filings: int = 300) -> pd.DataFrame:
    """
    Download and parse up to max_filings Form 4 XMLs and return transactions table.
    """
    rows = []
    count = 0
    for _, r in filings_df.iterrows():
        if count >= max_filings:
            break
        cik = str(r["CIK"]).zfill(10)
        filename = r["Filename"]
        xml_url = find_form4_xml_url(cik, filename)
        if not xml_url:
            continue
        try:
            xml_bytes = _http_get(xml_url, sleep=0.15)
            parsed = parse_form4_xml(xml_bytes)
            for tx in parsed["transactions"]:
                rows.append(tx)
            count += 1
        except Exception:
            continue
    if rows:
        df = pd.DataFrame(rows)
        # Basic cleanup
        df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df
    return pd.DataFrame(columns=["issuerSymbol","issuerName","transactionCode","shares","price","date","ownership"])

def aggregate_by_issuer(transactions: pd.DataFrame) -> pd.DataFrame:
    if transactions.empty:
        return pd.DataFrame(columns=["issuerSymbol","nTransactions","totalShares","buys","sells"])
    buys = transactions[transactions["transactionCode"]=="P"].groupby("issuerSymbol")["shares"].sum(min_count=1)
    sells = transactions[transactions["transactionCode"]=="S"].groupby("issuerSymbol")["shares"].sum(min_count=1)
    total = transactions.groupby("issuerSymbol")["shares"].sum(min_count=1)
    n = transactions.groupby("issuerSymbol")["shares"].count()
    out = pd.concat([n.rename("nTransactions"), total.rename("totalShares"), buys.rename("buys"), sells.rename("sells")], axis=1).fillna(0).sort_values(["nTransactions","totalShares"], ascending=False)
    out = out.reset_index()
    return out

def weekly_baseline(transactions_week: pd.DataFrame) -> float:
    """Average number of transactions per day in prior 7 days."""
    if transactions_week.empty:
        return 0.0
    # The weekly df contains only filenames; we need count of filings per day as baseline proxy.
    # For a reasonable baseline, use count of Form 4 filings per day.
    counts = transactions_week.groupby("date")["Filename"].count()
    return float(counts.mean()) if not counts.empty else 0.0

def save_chart(top_issuers: pd.DataFrame, out_path: str):
    if top_issuers.empty:
        return
    plt.figure(figsize=(10,6))
    subset = top_issuers.head(15)
    plt.bar(subset["issuerSymbol"].astype(str), subset["nTransactions"])
    plt.title("Insider Transactions — Last 24h (count per issuer)")
    plt.xlabel("Issuer Symbol")
    plt.ylabel("Number of Transactions")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()

def run_pipeline(output_dir: str = "data", charts_dir: str = "charts", max_filings: int = 300) -> Dict:
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(charts_dir, exist_ok=True)

    spans = collect_last24h_and_week()
    last24_df = spans["last24"]
    week_df = spans["week"]

    # Parse Form4 XML for last 24h
    last24_tx = build_activity_summary(last24_df, max_filings=max_filings)
    summary = aggregate_by_issuer(last24_tx)

    # Weekly baseline by filings/day
    baseline = weekly_baseline(week_df)

    # Save artifacts
    last24_path = os.path.join(output_dir, "last24h_insider_summary.json")
    week_path = os.path.join(output_dir, "weekly_baseline.json")
    chart_path = os.path.join(charts_dir, "insider_activity_last24h.png")

    summary.to_json(last24_path, orient="records", indent=2)
    with open(week_path, "w") as f:
        json.dump({"avg_filings_per_day_prior_7d": baseline}, f, indent=2)

    save_chart(summary, chart_path)

    # Compose final report
    top_row = summary.head(1).to_dict(orient="records")[0] if not summary.empty else None
    report = {
        "generatedAtUTC": datetime.utcnow().isoformat()+"Z",
        "topIssuerToday": top_row,
        "avgFilingsPerDayPrior7d": baseline,
        "artifacts": {
            "last24h_json": last24_path,
            "weekly_json": week_path,
            "chart_png": chart_path,
        }
    }
    with open(os.path.join(output_dir, "final_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    return report
