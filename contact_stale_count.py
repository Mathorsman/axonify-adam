"""
contact_stale_count.py
--------------------------------------------------------------------------------
A.D.A.M. – Contact Stale Count Summary
Wave 2 Prep: How many contacts have gone dark, and for how long?

PURPOSE
-------
Gives you a fast count breakdown of contacts by inactivity band so you can
decide on a purge threshold before building full export CSVs.

This script is completely separate from contact_dirty_data_audit.py.
Running this will not affect, overwrite, or change anything that script produced.

HOW IT WORKS
------------
For each contact (excluding protected personas), it calculates their
"last signal date" — the most recent of:
  1. LastActivityDate  (Salesforce built-in: covers logged Tasks and Events)
  2. Most recent Bizible touchpoint date (queried separately)

It then buckets every non-protected contact into one of these bands:

  ACTIVE      — signal within the last 24 months  (would be protected)
  STALE_2YR   — last signal 24–36 months ago
  STALE_3YR   — last signal 36–48 months ago
  STALE_4YR+  — last signal more than 48 months ago
  NEVER       — no activity signal of any kind, ever

The output is:
  1. A summary printed to your console
  2. A single CSV with one row per contact, showing their band and last signal date
     — so you can spot-check the data before any decisions are made

IMPORTANT: READ-ONLY. This script never modifies Salesforce data.

HOW TO RUN
----------
Place in the same folder as sf_query_tool.py, then run:

    python contact_stale_count.py

Output goes to: contact_stale_output/

REQUIREMENTS
------------
  pip install simple-salesforce pandas
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from simple_salesforce import Salesforce

# -----------------------------------------------------------------------------
# [WARN]  CONFIRM THESE CUSTOM FIELD API NAMES BEFORE RUNNING
#     Must match what you set in contact_dirty_data_audit.py
# -----------------------------------------------------------------------------
CUSTOM_FIELD_JOB_LEVEL      = "Job_Level__c"
CUSTOM_FIELD_RESPONSIBILITY = "Responsibility_Automation__c"

# Bizible package API names — same as the dirty data script
BIZIBLE_TOUCHPOINT_OBJECT = "bizible2__Bizible_Touchpoint__c"
BIZIBLE_CONTACT_FIELD     = "bizible2__Contact__c"
BIZIBLE_DATE_FIELD        = "bizible2__Touchpoint_Date__c"

# -----------------------------------------------------------------------------
# Inactivity bands (in months). Edit these if you want different cut-offs.
# -----------------------------------------------------------------------------
BAND_DEFINITIONS = [
    ("ACTIVE",     0,   24),   # signal within last 24 months — shown for context only
    ("STALE_2YR",  24,  36),   # gone dark 2–3 years
    ("STALE_3YR",  36,  48),   # gone dark 3–4 years
    ("STALE_4YR+", 48, None),  # gone dark 4+ years (None = no upper limit)
]

# Minimum age of the Contact record before it can be flagged as stale.
# A contact created 6 months ago with no activity yet is not stale — it's new.
MIN_RECORD_AGE_MONTHS = 12

# -----------------------------------------------------------------------------
# Protected persona rules — identical to contact_dirty_data_audit.py
# -----------------------------------------------------------------------------
PROTECTED_JOB_LEVELS = {"c-level", "vp", "director", "manager"}

PROTECTED_RESPONSIBILITY_KEYWORDS = [
    "human resources",
    "learning & development", "learning and development",
    "health & safety", "health and safety",
    "operations",
]

PROTECTED_TITLE_KEYWORDS = [
    "vp ", "svp ", "vice president",
    "director",
    "coo", "chro", "cpo",
    "c-level",
    "district manager", "area manager", "regional director",
    "operations excellence", "field enablement", "operational readiness",
    "store excellence", "restaurant excellence",
    "ehs", "health, safety",
    "operations analytics", "business intelligence",
    "learning & development", "learning and development",
    "training & development", "training and development",
    "people & culture", "people and culture",
]

# Paths
TOKEN_CACHE_FILE = ".sf_token_cache.json"
OUTPUT_DIR       = Path("contact_stale_output")


# ==============================================================================
# AUTH  (same pattern as contact_dirty_data_audit.py)
# ==============================================================================

def connect_from_cache() -> Salesforce:
    """Loads the OAuth token A.D.A.M. saved and opens a Salesforce connection."""
    cache_path = Path(__file__).parent / TOKEN_CACHE_FILE
    if not cache_path.exists():
        sys.exit(
            f"\n[ERROR]  Token cache not found at: {cache_path}\n"
            "    Open A.D.A.M. in your browser, log in, then re-run.\n"
        )
    with open(cache_path) as f:
        data = json.load(f)
    sf = Salesforce(instance_url=data["instance_url"], session_id=data["access_token"])
    try:
        sf.query("SELECT Id FROM User LIMIT 1")
    except Exception:
        sys.exit(
            "\n[ERROR]  Salesforce token has expired.\n"
            "    Open A.D.A.M., log in again, then re-run.\n"
        )
    print(f"[OK]  Connected to Salesforce: {data['instance_url']}")
    return sf


# ==============================================================================
# DATA FETCH
# ==============================================================================

def fetch_contacts(sf: Salesforce) -> pd.DataFrame:
    """
    Pulls all contacts with the fields needed for staleness classification.
    LastActivityDate is a Salesforce system field that automatically updates
    whenever a Task or Event is logged against the contact — we use it as
    our primary activity signal so we don't have to query millions of activity
    records per contact.
    """
    print("[...]  Fetching contacts...")
    soql = f"""
        SELECT
            Id, FirstName, LastName, Name,
            Title, Department,
            AccountId, Account.Name,
            Owner.Name,
            CreatedDate,
            LastActivityDate,
            {CUSTOM_FIELD_JOB_LEVEL},
            {CUSTOM_FIELD_RESPONSIBILITY}
        FROM Contact
        WHERE IsDeleted = false
        ORDER BY LastName, FirstName
    """
    try:
        result  = sf.query_all(soql)
        records = result.get("records", [])
    except Exception as e:
        if "INVALID_FIELD" in str(e):
            sys.exit(
                f"\n[ERROR]  Custom field not found. Check these constants match your org:\n"
                f"    CUSTOM_FIELD_JOB_LEVEL      = '{CUSTOM_FIELD_JOB_LEVEL}'\n"
                f"    CUSTOM_FIELD_RESPONSIBILITY = '{CUSTOM_FIELD_RESPONSIBILITY}'\n"
                f"    Error detail: {e}\n"
            )
        raise

    df = pd.DataFrame(records).drop(columns=["attributes"], errors="ignore")

    # Flatten nested relationship fields
    for rel, key, flat in [("Account", "Name", "Account.Name"), ("Owner", "Name", "Owner.Name")]:
        if rel in df.columns:
            df[flat] = df[rel].apply(lambda x: x.get(key, "") if isinstance(x, dict) else "")
            df.drop(columns=[rel], inplace=True)

    df = df.fillna("")
    print(f"[OK]  Fetched {len(df):,} contacts.")
    return df


def fetch_latest_bizible_date_by_contact(sf: Salesforce) -> dict:
    """
    Returns a dict of { contact_id: most_recent_touchpoint_datetime } for
    every contact that has at least one Bizible touchpoint ever.

    Uses a SOQL aggregate query (GROUP BY + MAX) so we get one row per
    contact rather than fetching every individual touchpoint record.
    This is much faster and avoids hitting governor limits.

    Returns an empty dict if Bizible is not installed.
    """
    print("[...]  Fetching latest Bizible touchpoint date per contact...")
    soql = (
        f"SELECT {BIZIBLE_CONTACT_FIELD}, MAX({BIZIBLE_DATE_FIELD}) maxDate "
        f"FROM {BIZIBLE_TOUCHPOINT_OBJECT} "
        f"WHERE {BIZIBLE_CONTACT_FIELD} != null "
        f"GROUP BY {BIZIBLE_CONTACT_FIELD}"
    )
    result_map = {}
    try:
        result = sf.query_all(soql)
        for rec in result.get("records", []):
            cid      = rec.get(BIZIBLE_CONTACT_FIELD, "")
            raw_date = rec.get("maxDate", "") or rec.get("expr0", "")
            if cid and raw_date:
                try:
                    # Salesforce returns DateTime strings like: 2023-06-15T14:22:00.000+0000
                    dt = datetime.fromisoformat(raw_date.replace("+0000", "+00:00").replace("Z", "+00:00"))
                    result_map[cid] = dt
                except Exception:
                    pass
        print(f"[OK]  Got Bizible dates for {len(result_map):,} contacts.")
    except Exception as e:
        err = str(e)
        if "INVALID_TYPE" in err or "sObject type" in err.lower() or "does not exist" in err.lower():
            print(f"[SKIP]  Bizible not installed -- touchpoint signal skipped.")
        else:
            print(f"[WARN]  Bizible query failed: {e}")
    return result_map


# ==============================================================================
# PERSONA PROTECTION  (identical rules to contact_dirty_data_audit.py)
# ==============================================================================

def is_protected_persona(row: pd.Series) -> bool:
    """
    Returns True if the contact matches any protected persona rule.
    Exact same logic as contact_dirty_data_audit.py — these contacts
    are excluded from stale counts entirely.
    """
    title     = str(row.get("Title",                      "")).lower()
    job_level = str(row.get(CUSTOM_FIELD_JOB_LEVEL,       "")).lower().strip()
    resp      = str(row.get(CUSTOM_FIELD_RESPONSIBILITY,   "")).lower()

    for kw in PROTECTED_TITLE_KEYWORDS:
        if kw in title:
            return True
    if job_level in PROTECTED_JOB_LEVELS:
        return True
    for kw in PROTECTED_RESPONSIBILITY_KEYWORDS:
        if kw in resp:
            return True
    return False


# ==============================================================================
# STALENESS CLASSIFICATION
# ==============================================================================

def months_ago(dt: datetime) -> float:
    """Returns how many months ago a datetime was, relative to now."""
    now   = datetime.now(timezone.utc)
    delta = now - dt
    return delta.days / 30.0


def parse_sf_date(value: str) -> datetime | None:
    """
    Parses a Salesforce Date or DateTime string into a timezone-aware datetime.
    Returns None if the value is blank or unparseable.

    Salesforce Date format:     2023-06-15
    Salesforce DateTime format: 2023-06-15T14:22:00.000+0000
    """
    if not value or not str(value).strip():
        return None
    v = str(value).strip()
    try:
        if "T" in v:
            # DateTime — normalise the timezone offset for fromisoformat
            v = v.replace("+0000", "+00:00").replace("Z", "+00:00")
            return datetime.fromisoformat(v)
        else:
            # Date only — treat as midnight UTC
            return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def classify_contacts(
    df: pd.DataFrame,
    bizible_dates: dict,
) -> pd.DataFrame:
    """
    Applies persona protections, minimum record age filter, then assigns
    each remaining contact to an inactivity band based on their last signal.

    Adds these columns to the returned DataFrame:
      last_signal_date  -- most recent of LastActivityDate and Bizible date
      last_signal_source -- which signal was newer: 'activity', 'bizible', or 'none'
      inactivity_band   -- ACTIVE / STALE_2YR / STALE_3YR / STALE_4YR+ / NEVER
      excluded_reason   -- why a contact was excluded from stale counts (if applicable)
    """
    now = datetime.now(timezone.utc)
    min_age_cutoff = now - timedelta(days=MIN_RECORD_AGE_MONTHS * 30)

    rows = []
    for _, row in df.iterrows():
        contact_id  = str(row.get("Id", ""))
        created_str = str(row.get("CreatedDate", ""))
        created_dt  = parse_sf_date(created_str)

        # -- Exclude: protected persona ----------------------------------------
        if is_protected_persona(row):
            rows.append({**row, "last_signal_date": "", "last_signal_source": "",
                         "inactivity_band": "EXCLUDED", "excluded_reason": "protected_persona"})
            continue

        # -- Exclude: record too new (< 12 months old) -------------------------
        if created_dt and created_dt > min_age_cutoff:
            rows.append({**row, "last_signal_date": "", "last_signal_source": "",
                         "inactivity_band": "EXCLUDED", "excluded_reason": "record_too_new"})
            continue

        # -- Determine last signal date ----------------------------------------
        activity_dt = parse_sf_date(str(row.get("LastActivityDate", "")))
        bizible_dt  = bizible_dates.get(contact_id)

        # Pick the most recent of the two signals
        if activity_dt and bizible_dt:
            if activity_dt >= bizible_dt:
                last_signal = activity_dt
                source      = "activity"
            else:
                last_signal = bizible_dt
                source      = "bizible"
        elif activity_dt:
            last_signal = activity_dt
            source      = "activity"
        elif bizible_dt:
            last_signal = bizible_dt
            source      = "bizible"
        else:
            last_signal = None
            source      = "none"

        # -- Assign inactivity band --------------------------------------------
        if last_signal is None:
            band = "NEVER"
        else:
            age_months = months_ago(last_signal)
            band = "ACTIVE"   # default — overwritten below if stale
            for band_name, lower, upper in BAND_DEFINITIONS:
                if upper is None:
                    if age_months >= lower:
                        band = band_name
                        break
                else:
                    if lower <= age_months < upper:
                        band = band_name
                        break

        last_signal_str = last_signal.strftime("%Y-%m-%d") if last_signal else ""
        rows.append({
            **row,
            "last_signal_date":   last_signal_str,
            "last_signal_source": source,
            "inactivity_band":    band,
            "excluded_reason":    "",
        })

    return pd.DataFrame(rows)


# ==============================================================================
# SUMMARY & EXPORT
# ==============================================================================

BAND_LABELS = {
    "ACTIVE":     "Active (< 24 months)       -- shown for context, NOT a purge candidate",
    "STALE_2YR":  "Stale 2-3 years            -- no signal in 24-36 months",
    "STALE_3YR":  "Stale 3-4 years            -- no signal in 36-48 months",
    "STALE_4YR+": "Stale 4+ years             -- no signal in 48+ months",
    "NEVER":      "Never had any activity     -- no Task, Event, or Bizible ever",
}


def print_summary(df: pd.DataFrame) -> None:
    """Prints the count breakdown to the console."""
    total = len(df)

    excluded_persona  = len(df[df["excluded_reason"] == "protected_persona"])
    excluded_too_new  = len(df[df["excluded_reason"] == "record_too_new"])
    total_excluded    = excluded_persona + excluded_too_new
    total_evaluated   = total - total_excluded

    print("\n" + "=" * 65)
    print("  CONTACT STALE COUNT SUMMARY")
    print(f"  Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)
    print(f"\n  Total contacts in org              : {total:>8,}")
    print(f"  Excluded: protected persona        : {excluded_persona:>8,}")
    print(f"  Excluded: created < {MIN_RECORD_AGE_MONTHS} months ago    : {excluded_too_new:>8,}")
    print(f"  -----------------------------------------------")
    print(f"  Contacts evaluated for staleness   : {total_evaluated:>8,}")
    print()

    stale_df  = df[~df["excluded_reason"].isin(["protected_persona", "record_too_new"])]
    total_stale = len(stale_df[stale_df["inactivity_band"].isin(["STALE_2YR", "STALE_3YR", "STALE_4YR+", "NEVER"])])

    print(f"  {'Band':<30}  {'Count':>8}  {'% of evaluated':>15}")
    print(f"  {'-'*57}")
    for band, label in BAND_LABELS.items():
        count = len(stale_df[stale_df["inactivity_band"] == band])
        pct   = (count / total_evaluated * 100) if total_evaluated > 0 else 0
        marker = "  <-- purge candidate" if band != "ACTIVE" else ""
        print(f"  {band:<30}  {count:>8,}  {pct:>14.1f}%{marker}")

    print(f"  {'-'*57}")
    pct_stale = (total_stale / total_evaluated * 100) if total_evaluated > 0 else 0
    print(f"  {'TOTAL STALE (all bands)':<30}  {total_stale:>8,}  {pct_stale:>14.1f}%")
    print()


DISPLAY_COLUMNS = [
    "Id", "FirstName", "LastName", "Name", "Title",
    CUSTOM_FIELD_JOB_LEVEL, CUSTOM_FIELD_RESPONSIBILITY,
    "Account.Name", "Department", "Owner.Name",
    "CreatedDate", "LastActivityDate",
    "last_signal_date", "last_signal_source", "inactivity_band", "excluded_reason",
]


def export_csv(df: pd.DataFrame) -> None:
    """
    Writes a single CSV with every contact (excluding protected/too-new),
    showing their inactivity band and last signal date.

    This is your working document for the threshold discussion with your boss.
    Filter the 'inactivity_band' column in Excel to explore each band.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Only include contacts that were actually evaluated (not excluded)
    export_df = df[~df["excluded_reason"].isin(["protected_persona", "record_too_new"])].copy()

    cols      = [c for c in DISPLAY_COLUMNS if c in export_df.columns]
    out_path  = OUTPUT_DIR / f"contact_stale_bands_{date_str}.csv"
    export_df[cols].to_csv(out_path, index=False)
    print(f"[FILE]  Detail CSV written -> {out_path}")
    print(f"        Filter the 'inactivity_band' column in Excel to explore each band.")


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    print("\n" + "=" * 65)
    print("  A.D.A.M. – Contact Stale Count Summary")
    print("=" * 65 + "\n")

    # 1. Connect
    sf = connect_from_cache()

    # 2. Pull contacts
    df = fetch_contacts(sf)
    if df.empty:
        print("No contacts found. Exiting.")
        return

    # 3. Pull latest Bizible date per contact (single aggregate query)
    bizible_dates = fetch_latest_bizible_date_by_contact(sf)

    # 4. Classify every contact into a band
    print("[SCAN]  Classifying contacts into inactivity bands...")
    classified_df = classify_contacts(df, bizible_dates)

    # 5. Print summary to console
    print_summary(classified_df)

    # 6. Export detail CSV for review
    print("[SAVE]  Writing detail CSV...")
    export_csv(classified_df)

    print(
        f"\n[OK]  Done. Open '{OUTPUT_DIR}/contact_stale_bands_*.csv' in Excel.\n"
        f"      Filter the 'inactivity_band' column to review each band.\n"
        f"      Agree on a threshold with your boss, then we'll build the\n"
        f"      full per-band export CSVs for the purge wave.\n"
    )


if __name__ == "__main__":
    main()
