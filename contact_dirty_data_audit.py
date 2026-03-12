"""
contact_dirty_data_audit.py
--------------------------------------------------------------------------------
A.D.A.M. – Contact Dirty Data Audit
Solo Admin Contact Purge Helper

PURPOSE
-------
Pulls all Contacts from Salesforce and classifies them into buckets of
"dirty data" (junk names, missing fields, uncontactable, etc.) that are
safe candidates for discussion/deletion.

IMPORTANT: This script is READ-ONLY. It only ever queries Salesforce.
It never deletes or modifies any records. All output is CSVs for human review.

PROTECTED PERSONAS
------------------
Contacts matching any of the following criteria are EXCLUDED from ALL
output CSVs, regardless of data quality:
  • Title contains a protected keyword (VP, SVP, Director, COO, CHRO, etc.)
  • Job_Level__c is C-Level, VP, Director, or Manager
  • Responsibility_Automation__c contains Human Resources, Learning &
    Development, Health & Safety, or Operations

[WARN]  BEFORE RUNNING: Verify the two custom field API names below.
    Go to Setup -> Object Manager -> Contact -> Fields & Relationships and
    confirm the exact "Field Name" (API Name) for:
      - "Responsibility Automation"  (likely: Responsibility_Automation__c)
      - "Job Level"                  (likely: Job_Level__c)
    Update the CUSTOM_FIELD_* constants if different.

HOW TO RUN
----------
Place this file in the same folder as sf_query_tool.py (so it can find
the .sf_token_cache.json auth token). Then run:

    python contact_dirty_data_audit.py

Output CSVs are written to a sub-folder: contact_audit_output/
Each CSV is a separate "purge bucket" for discussion.

REQUIREMENTS
------------
  pip install simple-salesforce pandas
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from simple_salesforce import Salesforce

# -----------------------------------------------------------------------------
# [WARN]  CONFIRM THESE CUSTOM FIELD API NAMES BEFORE RUNNING
#     Setup -> Object Manager -> Contact -> Fields & Relationships
# -----------------------------------------------------------------------------
CUSTOM_FIELD_JOB_LEVEL         = "Job_Level__c"
CUSTOM_FIELD_RESPONSIBILITY    = "Responsibility_Automation__c"

# -----------------------------------------------------------------------------
# Protected Job Levels (exact picklist values — case-insensitive match)
# -----------------------------------------------------------------------------
PROTECTED_JOB_LEVELS = {
    "c-level", "vp", "director", "manager",
}

# -----------------------------------------------------------------------------
# Protected Responsibility values (substring match — case-insensitive)
# -----------------------------------------------------------------------------
PROTECTED_RESPONSIBILITY_KEYWORDS = [
    "human resources",
    "learning & development",
    "learning and development",
    "health & safety",
    "health and safety",
    "operations",
]

# -----------------------------------------------------------------------------
# Protected Title keywords (substring match — case-insensitive)
# Covers all Tier 1 / Tier 2 / Tier 3 titles from the marketing brief
# -----------------------------------------------------------------------------
PROTECTED_TITLE_KEYWORDS = [
    "vp ", "svp ", "vice president",
    "director",
    "coo", "chro", "cpo",
    "c-level",
    # Manager-level keywords
    "district manager", "area manager", "regional director",
    # Functional areas that map to protected personas even without VP/Dir
    "operations excellence", "field enablement", "operational readiness",
    "store excellence", "restaurant excellence",
    "ehs", "health, safety",
    "operations analytics", "business intelligence",
    "learning & development", "learning and development",
    "training & development", "training and development",
    "people & culture", "people and culture",
]

# -----------------------------------------------------------------------------
# Junk name patterns
# -----------------------------------------------------------------------------
# Names that are purely numeric  e.g. "64935", "1"
PATTERN_NUMERIC     = re.compile(r"^\d+$")

# Names that are 1 or 2 characters (single letters, initials used as full names)
PATTERN_SHORT       = re.compile(r"^.{1,2}$")

# Known junk keywords in names (case-insensitive)
JUNK_NAME_KEYWORDS = [
    "test", "sample", "demo", "fake", "dummy", "xxx", "yyy", "zzz",
    "n/a", "na", "null", "none", "unknown", "tbd", "placeholder",
    "delete", "do not use", "donotuse", "admin", "import",
]

# -----------------------------------------------------------------------------
# Activity / Bizible lookback window
# Contacts with ANY activity or Bizible touchpoint within this window
# are protected — even if their name looks like junk data.
# -----------------------------------------------------------------------------
ACTIVITY_LOOKBACK_MONTHS = 24

# Bizible touchpoint object and field API names (standard Bizible 2 package).
# If your org uses a different package namespace, update these.
BIZIBLE_TOUCHPOINT_OBJECT   = "bizible2__Bizible_Touchpoint__c"
BIZIBLE_CONTACT_FIELD       = "bizible2__Contact__c"
BIZIBLE_DATE_FIELD          = "bizible2__Touchpoint_Date__c"

# -----------------------------------------------------------------------------
# Token cache — same file A.D.A.M. uses
# -----------------------------------------------------------------------------
TOKEN_CACHE_FILE = ".sf_token_cache.json"
OUTPUT_DIR       = Path("contact_audit_output")


# ==============================================================================
# AUTH
# ==============================================================================

def connect_from_cache() -> Salesforce:
    """
    Reads the OAuth token saved by A.D.A.M. and creates a live SF connection.
    Make sure you have logged in to A.D.A.M. at least once so the cache exists.
    """
    cache_path = Path(__file__).parent / TOKEN_CACHE_FILE
    if not cache_path.exists():
        sys.exit(
            f"\n[ERROR]  Token cache not found at: {cache_path}\n"
            "    Please open A.D.A.M. in your browser, log in to Salesforce,\n"
            "    then re-run this script.\n"
        )
    with open(cache_path) as f:
        data = json.load(f)
    instance_url = data["instance_url"]
    access_token = data["access_token"]

    sf = Salesforce(instance_url=instance_url, session_id=access_token)
    # Lightweight ping to confirm token is still alive
    try:
        sf.query("SELECT Id FROM User LIMIT 1")
    except Exception:
        sys.exit(
            "\n[ERROR]  Salesforce token has expired.\n"
            "    Open A.D.A.M., log in again, then re-run this script.\n"
        )
    print(f"[OK]  Connected to Salesforce: {instance_url}")
    return sf


# ==============================================================================
# DATA FETCH
# ==============================================================================

def fetch_all_contacts(sf: Salesforce) -> pd.DataFrame:
    """
    Pulls every Contact (not deleted) with the fields we need for dirty-data
    classification. Includes both standard and the two custom persona fields.

    Note: query_all() handles Salesforce pagination automatically — it will
    fetch ALL records even if there are more than 2,000.
    """
    print("[...]  Fetching all Contacts from Salesforce (this may take a moment)...")

    soql = f"""
        SELECT
            Id,
            FirstName,
            LastName,
            Name,
            Email,
            Phone,
            MobilePhone,
            Title,
            Department,
            AccountId,
            Account.Name,
            OwnerId,
            Owner.Name,
            CreatedDate,
            LastModifiedDate,
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
        # Friendly error if the custom field names are wrong
        if "INVALID_FIELD" in str(e):
            print(
                f"\n[ERROR]  One of the custom fields was not found on Contact.\n"
                f"    Error: {e}\n\n"
                f"    Fix: Open Setup -> Object Manager -> Contact ->\n"
                f"         Fields & Relationships and update these constants\n"
                f"         at the top of this script:\n"
                f"           CUSTOM_FIELD_JOB_LEVEL      = '{CUSTOM_FIELD_JOB_LEVEL}'\n"
                f"           CUSTOM_FIELD_RESPONSIBILITY = '{CUSTOM_FIELD_RESPONSIBILITY}'\n"
            )
            sys.exit(1)
        raise

    if not records:
        print("[WARN]  No Contact records returned.")
        return pd.DataFrame()

    df = pd.DataFrame(records).drop(columns=["attributes"], errors="ignore")

    # Flatten nested relationship fields (e.g. Account -> Account.Name)
    for rel_field, sub_key, flat_name in [
        ("Account", "Name", "Account.Name"),
        ("Owner",   "Name", "Owner.Name"),
    ]:
        if rel_field in df.columns:
            df[flat_name] = df[rel_field].apply(
                lambda x: x.get(sub_key, "") if isinstance(x, dict) else ""
            )
            df.drop(columns=[rel_field], inplace=True)

    # Normalise nulls to empty strings for string operations
    for col in df.columns:
        df[col] = df[col].fillna("")

    print(f"[OK]  Fetched {len(df):,} Contacts.")
    return df


# ==============================================================================
# ACTIVITY & BIZIBLE LOOKBACK QUERIES
# ==============================================================================

def _cutoff_date_str() -> str:
    """
    Returns the 24-month lookback as a SOQL Date string (no time).
    Used for Task/Event ActivityDate fields, which are Date type.
    e.g. '2023-03-10'
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=ACTIVITY_LOOKBACK_MONTHS * 30)
    return cutoff.strftime("%Y-%m-%d")


def _cutoff_datetime_str() -> str:
    """
    Returns the 24-month lookback as a SOQL DateTime string.
    Used for Bizible touchpoint date fields, which are DateTime type.
    SOQL DateTime literals must include time and timezone: 2023-03-10T00:00:00Z
    Without the T/Z suffix Salesforce returns: 'value must be of type dateTime'
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=ACTIVITY_LOOKBACK_MONTHS * 30)
    return cutoff.strftime("%Y-%m-%dT00:00:00Z")


def fetch_recently_active_contact_ids(sf: Salesforce) -> set:
    """
    Returns a set of Contact IDs that have had at least one Task or Event
    with an ActivityDate in the last 24 months.

    WHY TWO QUERIES: Task and Event are separate objects in Salesforce.
    Both use WhoId to link back to a Contact (or Lead). We filter to
    Contact IDs only by checking that the ID starts with '003' (Salesforce's
    Contact key prefix).

    IMPORTANT: This protects contacts even if they look like junk data --
    recent engagement means they are real and active in the pipeline.
    """
    cutoff = _cutoff_date_str()
    protected = set()

    for obj, date_field in [
        ("Task",  "ActivityDate"),
        ("Event", "ActivityDate"),
    ]:
        print(f"[...]  Fetching recent {obj} records since {cutoff}...")
        soql = (
            f"SELECT WhoId FROM {obj} "
            f"WHERE {date_field} >= {cutoff} "
            f"AND WhoId != null "
            f"AND IsDeleted = false"
        )
        try:
            result = sf.query_all(soql)
            for rec in result.get("records", []):
                who_id = rec.get("WhoId", "")
                # WhoId can point to a Contact (003) or a Lead (00Q).
                # We only want Contacts here.
                if who_id and who_id.startswith("003"):
                    protected.add(who_id)
        except Exception as e:
            print(f"[WARN]  Could not query {obj}: {e}")

    print(f"[OK]  {len(protected):,} contacts protected by recent activity (last {ACTIVITY_LOOKBACK_MONTHS} months).")
    return protected


def fetch_recent_bizible_contact_ids(sf: Salesforce) -> set:
    """
    Returns a set of Contact IDs that have at least one Bizible Touchpoint
    record dated within the last 24 months.

    Bizible (Adobe Marketo Measure) stores buyer-journey touchpoints in
    bizible2__Bizible_Touchpoint__c. Each touchpoint has a Contact lookup
    (bizible2__Contact__c) and a date (bizible2__Touchpoint_Date__c).

    NOTE: bizible2__Touchpoint_Date__c is a DateTime field in Salesforce,
    so the SOQL filter must use the full ISO-8601 format: 2023-03-10T00:00:00Z
    Using a plain date (2023-03-10) causes: 'value must be of type dateTime'.

    If Bizible is not installed in your org, this function prints a notice
    and returns an empty set -- it will NOT crash the script.

    If your Bizible package uses a different namespace prefix, update
    BIZIBLE_TOUCHPOINT_OBJECT, BIZIBLE_CONTACT_FIELD, and BIZIBLE_DATE_FIELD
    at the top of this script.
    """
    cutoff = _cutoff_datetime_str()   # DateTime field -- needs T00:00:00Z suffix
    protected = set()

    print(f"[...]  Fetching Bizible touchpoints since {cutoff}...")
    soql = (
        f"SELECT {BIZIBLE_CONTACT_FIELD} FROM {BIZIBLE_TOUCHPOINT_OBJECT} "
        f"WHERE {BIZIBLE_DATE_FIELD} >= {cutoff} "
        f"AND {BIZIBLE_CONTACT_FIELD} != null "
        f"AND IsDeleted = false"
    )
    try:
        result = sf.query_all(soql)
        for rec in result.get("records", []):
            contact_id = rec.get(BIZIBLE_CONTACT_FIELD, "")
            if contact_id:
                protected.add(contact_id)
        print(f"[OK]  {len(protected):,} contacts protected by recent Bizible touchpoints (last {ACTIVITY_LOOKBACK_MONTHS} months).")
    except Exception as e:
        err_str = str(e)
        if "INVALID_TYPE" in err_str or "sObject type" in err_str.lower() or "does not exist" in err_str.lower():
            print(f"[SKIP]  Bizible object '{BIZIBLE_TOUCHPOINT_OBJECT}' not found -- touchpoint check skipped.")
        else:
            print(f"[WARN]  Bizible query failed: {e}")
            print(f"        If Bizible uses a different namespace, update BIZIBLE_TOUCHPOINT_OBJECT at the top of this script.")

    return protected


# ==============================================================================
# PROTECTED PERSONA FILTER
# ==============================================================================

def is_protected_persona(row: pd.Series) -> bool:
    """
    Returns True if a Contact should be EXCLUDED from all purge lists because
    they match the personas Marketing wants to keep or target.

    Checks three independent signals — any one of them is enough to protect:
      1. Title contains a protected keyword
      2. Job Level picklist value is in the protected set
      3. Responsibility Automation field contains a protected keyword
    """
    title        = str(row.get("Title",                         "")).lower()
    job_level    = str(row.get(CUSTOM_FIELD_JOB_LEVEL,          "")).lower().strip()
    resp         = str(row.get(CUSTOM_FIELD_RESPONSIBILITY,      "")).lower()

    # 1. Title check
    for kw in PROTECTED_TITLE_KEYWORDS:
        if kw in title:
            return True

    # 2. Job Level check
    if job_level in PROTECTED_JOB_LEVELS:
        return True

    # 3. Responsibility check
    for kw in PROTECTED_RESPONSIBILITY_KEYWORDS:
        if kw in resp:
            return True

    return False


# ==============================================================================
# DIRTY DATA CLASSIFIERS
# ==============================================================================

def _is_numeric_name(value: str) -> bool:
    """True if the name is entirely numbers (e.g. '64935', '1')."""
    return bool(PATTERN_NUMERIC.match(value.strip())) if value.strip() else False


def _is_short_name(value: str) -> bool:
    """True if the name is 1–2 characters (e.g. 'A', 'JJ')."""
    return bool(PATTERN_SHORT.match(value.strip())) if value.strip() else False


def _has_junk_keyword(value: str) -> bool:
    """True if the name contains a known junk keyword."""
    lower = value.lower().strip()
    return any(kw in lower for kw in JUNK_NAME_KEYWORDS)


def _is_all_caps_name(value: str) -> bool:
    """
    True if the full name is suspiciously ALL-CAPS and more than 3 chars.
    Single all-caps words (e.g. 'SMITH') may be legit data entry; we only
    flag when the full Name (first + last combined) is fully uppercased and
    at least one space is present (i.e. two words, both shouting).
    """
    v = value.strip()
    return (
        len(v) > 3
        and " " in v
        and v == v.upper()
        and v.replace(" ", "").isalpha()   # pure letters, no numbers
    )


def _is_missing_last_name(row: pd.Series) -> bool:
    return not str(row.get("LastName", "")).strip()


def _is_uncontactable(row: pd.Series) -> bool:
    """No email AND no phone AND no mobile phone."""
    return (
        not str(row.get("Email",       "")).strip()
        and not str(row.get("Phone",       "")).strip()
        and not str(row.get("MobilePhone", "")).strip()
    )


def _is_orphaned(row: pd.Series) -> bool:
    """No Account AND uncontactable — truly floating in the void."""
    return not str(row.get("AccountId", "")).strip() and _is_uncontactable(row)


# ==============================================================================
# CLASSIFICATION ENGINE
# ==============================================================================

DISPLAY_COLUMNS = [
    "Id", "FirstName", "LastName", "Name", "Title",
    CUSTOM_FIELD_JOB_LEVEL, CUSTOM_FIELD_RESPONSIBILITY,
    "Email", "Phone", "MobilePhone",
    "Account.Name", "Department",
    "Owner.Name", "CreatedDate", "LastActivityDate",
    "dirty_flags",      # populated below — explains WHY flagged
]


def classify_contacts(
    df: pd.DataFrame,
    active_ids: set,
    bizible_ids: set,
) -> dict:
    """
    Runs every contact through all exclusion filters, then through the
    dirty-data classifiers. Returns a dict of { category_name: dataframe }.

    Exclusion layers (any one is enough to protect a contact):
      1. Protected persona  — title / job level / responsibility keywords
      2. Recent activity    — Task or Event in the last 24 months
      3. Bizible touchpoint — any touchpoint in the last 24 months

    A contact can appear in MORE than one category bucket (e.g. numeric name
    AND no email). The separate CSVs let you work through issues in waves.
    """

    buckets: dict[str, list[pd.Series]] = {
        "01_numeric_names":         [],
        "02_junk_keyword_names":    [],
        "03_short_names":           [],
        "04_missing_last_name":     [],
        "05_all_caps_names":        [],
        "06_no_email_no_phone":     [],
        "07_orphaned_no_account":   [],
        "08_uncontactable_no_title":[],
    }

    protected_persona_count = 0
    protected_activity_count = 0
    protected_bizible_count  = 0
    flagged_ids = set()   # tracks contacts that land in at least one bucket

    for _, row in df.iterrows():

        # -- Layer 1: Skip protected personas ---------------------------------
        if is_protected_persona(row):
            protected_persona_count += 1
            continue

        contact_id = str(row.get("Id", ""))

        # -- Layer 2: Skip contacts with recent activity (Task or Event) -------
        if contact_id in active_ids:
            protected_activity_count += 1
            continue

        # -- Layer 3: Skip contacts with recent Bizible touchpoints ------------
        if contact_id in bizible_ids:
            protected_bizible_count += 1
            continue

        first  = str(row.get("FirstName", "")).strip()
        last   = str(row.get("LastName",  "")).strip()
        name   = str(row.get("Name",      "")).strip()

        flags: list[str] = []

        # Cat 1: Numeric names
        if _is_numeric_name(first) or _is_numeric_name(last):
            flags.append("NUMERIC_NAME")
            buckets["01_numeric_names"].append(row)

        # Cat 2: Junk keyword names
        if _has_junk_keyword(first) or _has_junk_keyword(last):
            flags.append("JUNK_KEYWORD")
            buckets["02_junk_keyword_names"].append(row)

        # Cat 3: Suspiciously short names
        if _is_short_name(first) or _is_short_name(last):
            flags.append("SHORT_NAME")
            buckets["03_short_names"].append(row)

        # Cat 4: Missing last name entirely
        if _is_missing_last_name(row):
            flags.append("NO_LAST_NAME")
            buckets["04_missing_last_name"].append(row)

        # Cat 5: All-caps full name
        if _is_all_caps_name(name):
            flags.append("ALL_CAPS")
            buckets["05_all_caps_names"].append(row)

        # Cat 6: No email + no phone at all
        if _is_uncontactable(row):
            flags.append("UNCONTACTABLE")
            buckets["06_no_email_no_phone"].append(row)
            # Cat 7: No account on top of that
            if not str(row.get("AccountId", "")).strip():
                flags.append("ORPHANED")
                buckets["07_orphaned_no_account"].append(row)

        # Cat 8: No email, no phone, and no title/job level either
        if (
            _is_uncontactable(row)
            and not str(row.get("Title", "")).strip()
            and not str(row.get(CUSTOM_FIELD_JOB_LEVEL, "")).strip()
        ):
            if "UNCONTACTABLE" not in flags:   # avoid double-counting in summary
                flags.append("UNCONTACTABLE_NO_TITLE")
            buckets["08_uncontactable_no_title"].append(row)

        if flags:
            flagged_ids.add(str(row.get("Id", "")))

    print(f"\n[SUMMARY]  Classification summary:")
    print(f"    Protected: persona match        : {protected_persona_count:,}")
    print(f"    Protected: recent activity      : {protected_activity_count:,}")
    print(f"    Protected: Bizible touchpoint   : {protected_bizible_count:,}")
    total_protected = protected_persona_count + protected_activity_count + protected_bizible_count
    print(f"    ----------------------------------------")
    print(f"    Total contacts excluded (safe)  : {total_protected:,}")
    print(f"    Unique contacts flagged         : {len(flagged_ids):,}")
    print(f"    (A contact can appear in multiple buckets)\n")

    # Convert lists of Series -> DataFrames with a 'dirty_flags' column
    result: dict[str, pd.DataFrame] = {}
    for bucket_name, rows in buckets.items():
        if not rows:
            continue
        bucket_df = pd.DataFrame(rows)
        # Add flag column showing why flagged (may be inherited from classifier above)
        # Re-derive flags for display column
        flag_series = bucket_df.apply(
            lambda r: _derive_flags_for_row(r), axis=1
        )
        bucket_df["dirty_flags"] = flag_series

        # Keep only display columns that actually exist
        cols = [c for c in DISPLAY_COLUMNS if c in bucket_df.columns]
        result[bucket_name] = bucket_df[cols].copy()

    return result


def _derive_flags_for_row(row: pd.Series) -> str:
    """Rebuilds the dirty flag string for the display column."""
    first = str(row.get("FirstName", "")).strip()
    last  = str(row.get("LastName",  "")).strip()
    name  = str(row.get("Name",      "")).strip()
    flags = []
    if _is_numeric_name(first) or _is_numeric_name(last):
        flags.append("NUMERIC_NAME")
    if _has_junk_keyword(first) or _has_junk_keyword(last):
        flags.append("JUNK_KEYWORD")
    if _is_short_name(first) or _is_short_name(last):
        flags.append("SHORT_NAME")
    if _is_missing_last_name(row):
        flags.append("NO_LAST_NAME")
    if _is_all_caps_name(name):
        flags.append("ALL_CAPS")
    if _is_uncontactable(row):
        flags.append("UNCONTACTABLE")
        if not str(row.get("AccountId", "")).strip():
            flags.append("ORPHANED")
    return " | ".join(flags) if flags else ""


# ==============================================================================
# CSV EXPORT
# ==============================================================================

BUCKET_DESCRIPTIONS = {
    "01_numeric_names":          "First or Last name is entirely numbers (e.g. '64935', '1')",
    "02_junk_keyword_names":     "Name contains a known junk keyword (test, sample, dummy, etc.)",
    "03_short_names":            "First or Last name is 1–2 characters only",
    "04_missing_last_name":      "Last Name field is blank / null",
    "05_all_caps_names":         "Full name is ALL CAPS (two-word, letters only)",
    "06_no_email_no_phone":      "No Email, no Phone, and no Mobile Phone",
    "07_orphaned_no_account":    "No Account AND no email/phone (completely floating records)",
    "08_uncontactable_no_title": "No email/phone AND no Title or Job Level populated",
}


def export_csvs(buckets: dict[str, pd.DataFrame]) -> None:
    """Writes each bucket to a dated CSV in the output directory."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Write a README summary file alongside the CSVs
    readme_lines = [
        "CONTACT DIRTY DATA AUDIT",
        f"Run date : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "-" * 60,
        "",
        "EXCLUSIONS — CONTACTS REMOVED FROM ALL CSVs",
        "  Persona match:",
        "  • Title keywords: VP, SVP, Director, COO, CHRO, CPO, Manager, etc.",
        f"  • Job Level ({CUSTOM_FIELD_JOB_LEVEL}) IN: C-Level, VP, Director, Manager",
        f"  • Responsibility ({CUSTOM_FIELD_RESPONSIBILITY}) contains:",
        "    Human Resources / Learning & Development / Health & Safety / Operations",
        "",
        "  Activity (last 24 months):",
        "  • Any Task with ActivityDate in last 24 months",
        "  • Any Event with ActivityDate in last 24 months",
        "",
        "  Bizible touchpoints (last 24 months):",
        f"  • Any record in {BIZIBLE_TOUCHPOINT_OBJECT} linked to the contact",
        "",
        "BUCKET DESCRIPTIONS",
    ]

    total_rows = 0
    for bucket, desc in BUCKET_DESCRIPTIONS.items():
        count = len(buckets.get(bucket, pd.DataFrame()))
        readme_lines.append(f"  {bucket}.csv  ({count:,} records)")
        readme_lines.append(f"    -> {desc}")
        total_rows += count

    readme_lines += [
        "",
        f"TOTAL ROWS ACROSS ALL CSVs: {total_rows:,}",
        "(Note: a single contact can appear in multiple CSVs.)",
        "",
        "NEXT STEPS",
        "  1. Review each CSV with your manager.",
        "  2. Mark any records that should NOT be deleted.",
        "  3. Agree on waves: start with 07_orphaned and 01_numeric (lowest risk).",
        "  4. Use Salesforce Data Loader or a Mass Delete flow to remove approved records.",
        "  5. Always export a backup before any bulk delete.",
    ]

    readme_path = OUTPUT_DIR / f"README_{date_str}.txt"
    readme_path.write_text("\n".join(readme_lines), encoding="utf-8")
    print(f"[FILE]  README written -> {readme_path}")

    # Write each bucket CSV
    for bucket_name, df in buckets.items():
        if df.empty:
            print(f"    [SKIP]   {bucket_name} — 0 records, skipped.")
            continue
        out_path = OUTPUT_DIR / f"{bucket_name}_{date_str}.csv"
        df.to_csv(out_path, index=False)
        print(f"    [OK]  {bucket_name}.csv — {len(df):,} records -> {out_path}")


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    print("\n" + "=" * 60)
    print("  A.D.A.M. — Contact Dirty Data Audit")
    print("=" * 60 + "\n")

    # 1. Connect
    sf = connect_from_cache()

    # 2. Pull all contacts
    df = fetch_all_contacts(sf)
    if df.empty:
        print("No contacts found. Exiting.")
        return

    # 3. Build exclusion sets from activity and Bizible lookbacks
    #    These run as separate SOQL queries so we don't miss any activity
    #    that isn't reflected on the Contact's LastActivityDate stamp.
    print(f"\n[SCAN]  Running 24-month activity lookback...")
    active_ids  = fetch_recently_active_contact_ids(sf)
    bizible_ids = fetch_recent_bizible_contact_ids(sf)

    # 4. Classify — apply all three exclusion layers then dirty-data rules
    print("\n[SCAN]  Classifying contacts...")
    buckets = classify_contacts(df, active_ids, bizible_ids)

    if not buckets:
        print("\n[DONE]  No dirty data contacts found outside all exclusion criteria.")
        return

    # 4. Print bucket summary table
    print(f"{'Bucket':<35} {'Count':>7}  Description")
    print("-" * 90)
    for name, desc in BUCKET_DESCRIPTIONS.items():
        count = len(buckets.get(name, pd.DataFrame()))
        print(f"  {name:<33} {count:>7,}  {desc}")

    # 5. Export CSVs
    print(f"\n[SAVE]  Writing CSVs to ./{OUTPUT_DIR}/")
    export_csvs(buckets)

    print(
        f"\n[OK]  Done.  Open the '{OUTPUT_DIR}' folder and review the CSVs.\n"
        f"    Start with 07_orphaned (safest to purge) then 01_numeric.\n"
        f"    Always get sign-off before any bulk deletion.\n"
    )


if __name__ == "__main__":
    main()
