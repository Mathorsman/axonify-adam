"""
digest_scheduler.py
═══════════════════
Standalone Salesforce Org Digest — runs without the browser tool.

Pulls data from your Salesforce org, generates an AI briefing via the
Anthropic API, and posts a formatted summary to Slack. Designed to be
run on a schedule (Windows Task Scheduler, macOS launchd, or cron).

REQUIREMENTS
────────────
Install dependencies (same as the main tool):
    pip install simple-salesforce anthropic python-dotenv pandas

AUTHENTICATION
──────────────
This script reuses the OAuth token written by sf_query_tool.py.
Run the main tool once in your browser to log in — the token is saved
to .sf_token_cache.json in the same folder. This script reads that file
automatically. Tokens typically last 2–8 hours; if it expires, open the
main tool again to refresh it.

CONFIGURATION
─────────────
All settings live in your existing .env file. Add this one new line:

    SF_SLACK_BOT_TOKEN=xoxb-your-token-here

(See Slack setup instructions in the Org Digest tab of the main tool.)

SCHEDULING
──────────
Windows Task Scheduler:
    Action → Start a program
    Program:  C:\\path\\to\\python.exe
    Arguments: C:\\path\\to\\digest_scheduler.py --days 7
    Trigger:  Weekly, Monday 8:00 AM

macOS / Linux cron (open with: crontab -e):
    # Every Monday at 8am
    0 8 * * 1 /usr/bin/python3 /path/to/digest_scheduler.py --days 7

USAGE
─────
    python digest_scheduler.py              # last 7 days, posts to Slack
    python digest_scheduler.py --days 14   # last 14 days
    python digest_scheduler.py --dry-run   # print output, do NOT post to Slack
    python digest_scheduler.py --no-ai     # skip AI summary, just post raw stats
"""

import os
import sys
import json
import argparse
import datetime
import urllib.parse
import urllib.request
import urllib.error

# ── Third-party (same deps as main tool) ──────────────────────────────────────
try:
    import pandas as pd
    from simple_salesforce import Salesforce
    import anthropic
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("   Run:  pip install simple-salesforce anthropic pandas python-dotenv")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env not required if vars are already in environment


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

# Slack channel to post to — #salesforce-slack-notification-testing
# Override by setting SF_SLACK_CHANNEL_ID in your .env file.
SLACK_CHANNEL_ID = os.environ.get("SF_SLACK_CHANNEL_ID", "C07SHCATU0H")

# All config files live in the same folder as this script and sf_query_tool.py
_HERE                = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE     = os.path.join(_HERE, ".sf_token_cache.json")
SCHEDULE_CONFIG_FILE = os.path.join(_HERE, "digest_schedule.json")

# Claude model used for the AI briefing
AI_MODEL = "claude-sonnet-4-6"


def _utcnow() -> datetime.datetime:
    """Current time in UTC (timezone-aware)."""
    return datetime.datetime.now(datetime.timezone.utc)


def load_schedule_config() -> dict:
    """
    Loads scheduler preferences from digest_schedule.json.

    This file is written by the Scheduler Configuration panel in the
    Org Digest tab of sf_query_tool.py. If the file does not exist,
    sensible defaults are returned so the script still runs.

    Keys in the file:
      frequency     — "Daily" | "Weekly" | "Monthly"
      weekday       — "Monday" … "Sunday"  (Weekly only)
      month_day     — 1–28  (Monthly only)
      hour          — 0–23
      minute        — 0–59
      lookback_days — 7 | 14 | 30
      include_ai    — true | false
    """
    defaults = {
        "frequency":     "Weekly",
        "weekday":       "Monday",
        "month_day":     1,
        "hour":          8,
        "minute":        0,
        "lookback_days": 7,
        "include_ai":    True,
    }
    if not os.path.exists(SCHEDULE_CONFIG_FILE):
        print(f"   ℹ️  No schedule config found at {SCHEDULE_CONFIG_FILE}")
        print("      Open sf_query_tool.py → Org Digest tab → Scheduler Configuration to set preferences.")
        print("      Using defaults for this run.")
        return defaults
    try:
        with open(SCHEDULE_CONFIG_FILE) as f:
            saved = json.load(f)
        defaults.update(saved)
        return defaults
    except Exception as e:
        print(f"   ⚠️  Could not read {SCHEDULE_CONFIG_FILE}: {e} — using defaults")
        return defaults


# ══════════════════════════════════════════════════════════════════════════════
# SALESFORCE CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

def get_sf_connection() -> Salesforce:
    """
    Loads a Salesforce connection from the token cache written by sf_query_tool.py.

    If the cache is missing or the token has expired, the script exits with a
    clear message telling you to open the main tool and log in again.
    """
    if not os.path.exists(TOKEN_CACHE_FILE):
        print("❌ No Salesforce token found.")
        print(f"   Expected: {TOKEN_CACHE_FILE}")
        print("   Fix: Open sf_query_tool.py in your browser and log in once.")
        sys.exit(1)

    try:
        with open(TOKEN_CACHE_FILE) as f:
            data = json.load(f)
        instance_url = data["instance_url"]
        access_token = data["access_token"]
    except (json.JSONDecodeError, KeyError):
        print("❌ Token cache file is corrupt. Delete it and log in via the main tool.")
        sys.exit(1)

    # Verify the token is still valid
    try:
        sf = Salesforce(instance_url=instance_url, session_id=access_token)
        sf.query("SELECT Id FROM User LIMIT 1")
        return sf
    except Exception:
        print("❌ Salesforce token has expired.")
        print("   Fix: Open sf_query_tool.py in your browser and log in again.")
        print(f"   (The expired cache file at {TOKEN_CACHE_FILE} will be refreshed automatically.)")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT TRAIL NOISE FILTER
# Mirrors the constants in sf_query_tool.py — keep both in sync when extending.
# ══════════════════════════════════════════════════════════════════════════════

_AUDIT_SIGNAL_SECTIONS: set[str] = {
    "Custom Objects", "Custom Fields", "Record Types", "Page Layouts",
    "Compact Layouts", "Lightning Pages", "Custom Metadata Types",
    "Custom Settings", "Custom Tabs", "Global Actions", "Publisher Layouts",
    "Search Layouts", "Related Lists",
    "Flows", "Workflow Rules", "Process Builder", "Approval Processes",
    "Escalation Rules", "Assignment Rules", "Auto-Response Rules",
    "Matching Rules", "Duplicate Rules",
    "Apex Classes", "Apex Triggers", "Visualforce Pages",
    "Visualforce Components", "Lightning Components", "Static Resources",
    "Platform Cache",
    "Profiles", "Permission Sets", "Permission Set Groups", "Roles",
    "Sharing Rules", "Organization-Wide Defaults", "Security Controls",
    "Session Settings", "Login Access Policies",
    "Certificate and Key Management", "Named Credentials",
    "Auth. Providers", "CORS",
    "Manage Users",
    "Connected Apps", "Installed Packages", "AppExchange",
    "Remote Access", "OAuth",
    "Validation Rules", "Picklists",
    "Report Types", "Custom Report Types", "Dashboard",
    "Territory", "Territory Models", "Queues", "Groups", "Lead Settings",
    "Email Templates", "Email Deliverability", "Organization Email Addresses",
    "Company Information", "Business Hours", "Holidays", "Data Management",
    "Sandbox", "Change Sets", "Deploy",
}

_AUDIT_NOISE_PATTERNS: list[str] = [
    "logged in", "logged out", "login-as", "login as",
    "password reset", "changed their password", "verified their identity",
    "granted login access", "has granted login access",
    "session activated", "session deactivated",
    "exported report", "ran a report", "viewed dashboard",
    "refreshed dashboard", "subscribed to report", "unsubscribed from report",
    "scheduled data export", "data export completed",
    "posted to chatter", "posted a comment", "liked a post",
    "adjusted forecast", "submitted forecast",
]


def _filter_audit_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove noise rows from a SetupAuditTrail DataFrame.

    Expects columns: Section, Detail (the Display text in digest_scheduler).
    Mirrors filter_audit_trail() in sf_query_tool.py.
    """
    if df.empty:
        return df

    result = df[df["Section"].astype(str).isin(_AUDIT_SIGNAL_SECTIONS)].copy()

    if not result.empty and "Detail" in result.columns:
        lower = result["Detail"].astype(str).str.lower()
        noise = pd.Series(False, index=result.index)
        for pat in _AUDIT_NOISE_PATTERNS:
            noise |= lower.str.contains(pat, na=False)
        result = result[~noise]

    # Belt-and-suspenders: strip self-Login-As
    if not result.empty and "Detail" in result.columns and "User" in result.columns:
        self_login = result.apply(
            lambda r: "login-as" in str(r["Detail"]).lower()
            and str(r["User"]) in str(r["Detail"]),
            axis=1,
        )
        result = result[~self_login]

    return result.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ══════════════════════════════════════════════════════════════════════════════

def get_setup_audit_trail(sf: Salesforce, days: int) -> pd.DataFrame:
    """
    Returns Setup Audit Trail entries for the last N days.

    Every configuration change made in Salesforce Setup is logged here —
    users created, fields added, flows activated, permissions changed.
    Returns columns: Date, User, Action, Section, Detail.
    """
    since = (_utcnow() - datetime.timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    soql = (
        "SELECT CreatedDate, CreatedBy.Name, Action, Section, Display "
        "FROM SetupAuditTrail "
        f"WHERE CreatedDate >= {since} "
        "ORDER BY CreatedDate DESC LIMIT 1000"
    )
    try:
        records = sf.query_all(soql).get("records", [])
        rows = []
        for r in records:
            rows.append({
                "Date":    r.get("CreatedDate", "")[:16].replace("T", " "),
                "User":    (r.get("CreatedBy") or {}).get("Name", ""),
                "Action":  r.get("Action", ""),
                "Section": r.get("Section", ""),
                "Detail":  r.get("Display", ""),
            })
        df = pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["Date", "User", "Action", "Section", "Detail"]
        )
        print(f"   ✓ Audit trail: {len(df):,} entries")
        return df
    except Exception as e:
        print(f"   ⚠️  Audit trail query failed: {e}")
        return pd.DataFrame(columns=["Date", "User", "Action", "Section", "Detail"])


def get_org_limits(sf: Salesforce) -> dict:
    """
    Returns current API and storage limit consumption.

    Uses the Salesforce Limits API endpoint. Returns a dict of
    {limit_name: {used, max, pct}} for the key limits we monitor.
    """
    key_limits = [
        "DailyApiRequests", "DataStorageMB", "FileStorageMB",
        "DailyBulkApiRequests", "DailyWorkflowEmails",
    ]
    try:
        raw    = sf.limits()
        parsed = {}
        for key in key_limits:
            if key in raw:
                max_  = raw[key].get("Max", 1)
                rem   = raw[key].get("Remaining", 0)
                used  = max_ - rem
                pct   = round(used / max_ * 100, 1) if max_ > 0 else 0
                parsed[key] = {"used": used, "max": max_, "pct": pct}
        print(f"   ✓ Limits: {len(parsed)} metrics fetched")
        return parsed
    except Exception as e:
        print(f"   ⚠️  Limits API failed: {e}")
        return {}


def get_user_changes(sf: Salesforce, days: int) -> dict:
    """
    Returns new and recently-deactivated users for the lookback period.
    Returns {"new": DataFrame, "deactivated": DataFrame}.
    """
    since = (_utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    soql  = (
        "SELECT Id, Name, Email, IsActive, Profile.Name, CreatedDate "
        "FROM User "
        f"WHERE CreatedDate >= {since}T00:00:00Z "
        "ORDER BY CreatedDate DESC LIMIT 200"
    )
    try:
        records = sf.query_all(soql).get("records", [])
        rows = []
        for r in records:
            rows.append({
                "Name":    r.get("Name", ""),
                "Email":   r.get("Email", ""),
                "Active":  r.get("IsActive", False),
                "Profile": (r.get("Profile") or {}).get("Name", ""),
                "Created": (r.get("CreatedDate") or "")[:10],
            })
        df       = pd.DataFrame(rows) if rows else pd.DataFrame()
        new_u    = df[df["Active"] == True].copy()  if not df.empty else pd.DataFrame()
        inactive = df[df["Active"] == False].copy() if not df.empty else pd.DataFrame()
        print(f"   ✓ Users: {len(new_u)} new, {len(inactive)} deactivated")
        return {"new": new_u, "deactivated": inactive}
    except Exception as e:
        print(f"   ⚠️  User query failed: {e}")
        return {"new": pd.DataFrame(), "deactivated": pd.DataFrame()}


def get_failed_flows(sf: Salesforce, days: int) -> pd.DataFrame:
    """
    Returns Flow interview error log entries for the last N days.

    Requires Flow error logging to be enabled in your org:
    Setup → Process Automation Settings → Enable Flow Interview Error Logging.
    Returns an empty DataFrame if the object is unavailable.
    """
    since = (_utcnow() - datetime.timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    try:
        # FlowInterviewLog field names vary by org/API version.
        # We query only the safe universal fields: Id and CreatedDate.
        # FlowInterviewLog requires "Enable Flow Interview Error Logging" in
        # Setup → Process Automation Settings to contain any records.
        soql = (
            "SELECT Id, CreatedDate "
            "FROM FlowInterviewLog "
            f"WHERE CreatedDate >= {since} "
            "ORDER BY CreatedDate DESC LIMIT 200"
        )
        records = sf.query_all(soql).get("records", [])
        rows = []
        for r in records:
            rows.append({
                "Date": r.get("CreatedDate", "")[:16].replace("T", " "),
                "Id":   r.get("Id", ""),
            })
        df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Date", "Id"])
        print(f"   ✓ Flow errors: {len(df):,} logged")
        return df
    except Exception as e:
        # FlowInterviewLog is not available in all orgs — treat as non-fatal
        print(f"   ℹ️  Flow error log unavailable (may not be enabled in org): {e}")
        return pd.DataFrame(columns=["Date", "Id"])


# ══════════════════════════════════════════════════════════════════════════════
# AI BRIEFING
# ══════════════════════════════════════════════════════════════════════════════

def generate_ai_briefing(
    days: int,
    audit_df: pd.DataFrame,
    limits: dict,
    user_changes: dict,
    flows_df: pd.DataFrame,
) -> str:
    """
    Calls the Anthropic API to generate a plain-English org health briefing.

    Summarises the raw data from all four sources into a 5–8 sentence
    briefing suitable for pasting into a Slack message or a stakeholder update.

    Returns the briefing text, or an error message string if the call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return (
            "AI briefing unavailable — ANTHROPIC_API_KEY not set in .env. "
            "Raw stats are included in the fields below."
        )

    # Build a compact data summary for the prompt
    high_limits = []
    for k, v in limits.items():
        if isinstance(v, dict) and v.get("pct", 0) > 70:
            label = k.replace("Daily","").replace("MB"," MB").strip()
            high_limits.append(f"{label} at {v['pct']}%")

    top_sections = ""
    if not audit_df.empty and "Section" in audit_df.columns:
        top = audit_df["Section"].value_counts().head(5).to_dict()
        top_sections = ", ".join(f"{k} ({v})" for k, v in top.items())

    new_u  = user_changes.get("new", pd.DataFrame())
    dead_u = user_changes.get("deactivated", pd.DataFrame())

    prompt = (
        f"You are a Salesforce administrator writing a weekly org health briefing.\n\n"
        f"Org: Axonify (Sales Cloud)\n"
        f"Period: last {days} days\n\n"
        f"DATA:\n"
        f"- Setup changes: {len(audit_df)} total. "
        f"Most active areas: {top_sections or 'none'}\n"
        f"- New users: {len(new_u)}\n"
        f"- Deactivated users: {len(dead_u)}\n"
        f"- Flow errors logged: {len(flows_df)}\n"
        f"- Limits at >70% usage: {', '.join(high_limits) if high_limits else 'None'}\n\n"
        "Write a concise 5–8 sentence briefing in plain English. Cover:\n"
        "1. Overall org health (one verdict sentence)\n"
        "2. Notable changes or events this period\n"
        "3. Risks or items needing attention — be specific if the data supports it\n"
        "4. One recommended action if anything warrants it\n\n"
        "Write in paragraphs. Professional but plain tone. "
        "Do not invent specific details beyond what the data shows."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp   = client.messages.create(
            model      = AI_MODEL,
            max_tokens = 500,
            messages   = [{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as e:
        return f"AI briefing failed: {e}. Raw stats are included below."


# ══════════════════════════════════════════════════════════════════════════════
# SLACK POSTING
# ══════════════════════════════════════════════════════════════════════════════

def generate_adam_narrative(days: int) -> str:
    """
    Generate a plain-language 'This Week in A.D.A.M.' narrative from
    operation_logs stored in Supabase. Returns empty string if Supabase
    is not configured or no logs exist.
    """
    sb_url = os.environ.get("SUPABASE_URL", "").strip()
    sb_key = os.environ.get("SUPABASE_KEY", "").strip()
    if not sb_url or not sb_key:
        return ""

    try:
        from supabase import create_client as _sb
        sb = _sb(sb_url, sb_key)
        cutoff = (_utcnow() - datetime.timedelta(days=days)).isoformat()
        logs = (sb.table("operation_logs")
                .select("operation,object_name,record_count,succeeded,failed,created_at")
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(200)
                .execute()).data or []
    except Exception:
        return ""

    if not logs:
        return ""

    # Build a compact summary for the AI
    from collections import Counter
    op_counts = Counter()
    total_records = 0
    total_failed = 0
    for log in logs:
        op_counts[log.get("operation", "Unknown")] += 1
        total_records += log.get("record_count", 0) or 0
        total_failed += log.get("failed", 0) or 0

    ops_summary = ", ".join(f"{op}: {ct}" for op, ct in op_counts.most_common())

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return ""

    prompt = (
        f"You are A.D.A.M., the Axonify Data & Administration Manager.\n\n"
        f"Operations in the last {days} days:\n"
        f"- Total operations: {len(logs)}\n"
        f"- Operations by type: {ops_summary}\n"
        f"- Total records affected: {total_records:,}\n"
        f"- Failed operations: {total_failed}\n\n"
        f"Write a 3-sentence paragraph summarizing this week's admin activity, "
        f"suitable for a Revenue Ops manager. Be specific about what happened. "
        f"Start with 'This Week in A.D.A.M.' as the opening."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return ""


def build_slack_blocks(
    days: int,
    summary: str,
    audit_df: pd.DataFrame,
    limits: dict,
    user_changes: dict,
    flows_df: pd.DataFrame,
    adam_narrative: str = "",
) -> list:
    """
    Builds a Slack Block Kit message from the digest data.

    Block Kit gives us formatted sections, a stats grid, and a limits summary
    that renders cleanly in both desktop and mobile Slack clients.
    """
    new_u  = user_changes.get("new", pd.DataFrame())
    dead_u = user_changes.get("deactivated", pd.DataFrame())

    # Limits summary lines
    limit_lines = []
    for k, v in list(limits.items())[:5]:
        if not isinstance(v, dict):
            continue
        pct   = v.get("pct", 0)
        emoji = "🔴" if pct > 85 else ("🟡" if pct > 60 else "🟢")
        label = k.replace("Daily","").replace("MB"," MB").strip()
        limit_lines.append(f"{emoji} *{label}:* {pct}% ({v['used']:,} / {v['max']:,})")

    today   = _utcnow().strftime("%b %d, %Y")
    ts_str  = _utcnow().strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        # Header
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"⚡ Axonify Salesforce Org Digest — {today}",
            },
        },
        {"type": "divider"},
    ]

    # Plain Language Summary — AI-generated from operation_logs (F5 Component 3)
    if adam_narrative:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*This Week in A.D.A.M. — Auto-generated summary*\n\n{adam_narrative[:2800]}",
            },
        })
        blocks.append({"type": "divider"})

    blocks += [
        # AI summary
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                # Slack block text has a 3,000 char limit — truncate safely
                "text": summary[:2900] if len(summary) > 2900 else summary,
            },
        },
        {"type": "divider"},

        # Key stats grid
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Period:* Last {days} days"},
                {"type": "mrkdwn", "text": f"*Setup changes:* {len(audit_df):,}"},
                {"type": "mrkdwn", "text": f"*New users:* {len(new_u)}"},
                {"type": "mrkdwn", "text": f"*Deactivated users:* {len(dead_u)}"},
                {"type": "mrkdwn", "text": f"*Flow errors logged:* {len(flows_df)}"},
            ],
        },
    ]

    # Limits section (only if we have data)
    if limit_lines:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*API & Storage Limits:*\n" + "\n".join(limit_lines),
            },
        })

    # Top audit sections (if there were changes)
    if not audit_df.empty and "Section" in audit_df.columns:
        top = audit_df["Section"].value_counts().head(5)
        if not top.empty:
            lines = [f"• {section}: {count}" for section, count in top.items()]
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Most active Setup areas:*\n" + "\n".join(lines),
                },
            })

    # Footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Generated by digest_scheduler.py · {ts_str}",
            }
        ],
    })

    return blocks


def post_to_slack(blocks: list, fallback_text: str) -> tuple:
    """
    Posts a Block Kit message to the configured Slack channel.

    Returns (success: bool, message: str).
    Requires SF_SLACK_BOT_TOKEN to be set in the .env file.
    """
    token = os.environ.get("SF_SLACK_BOT_TOKEN", "").strip()
    if not token:
        return False, (
            "SF_SLACK_BOT_TOKEN not set. "
            "See the Org Digest tab in sf_query_tool.py for setup instructions."
        )

    payload = json.dumps({
        "channel": SLACK_CHANNEL_ID,
        "text":    fallback_text,
        "blocks":  blocks,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data    = payload,
        headers = {
            "Content-Type":  "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method = "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ok"):
            return True, "Posted successfully"
        else:
            return False, f"Slack API error: {body.get('error', 'unknown')}"
    except urllib.error.URLError as e:
        return False, f"Network error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments.

    Command-line flags always override digest_schedule.json values,
    so you can do one-off runs with different settings without editing the file.
    """
    parser = argparse.ArgumentParser(
        description="Salesforce Org Digest — generate and post to Slack on a schedule.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help=(
            "How many days to look back. "
            "Overrides the lookback_days value in digest_schedule.json. "
            "Defaults to the saved config value, or 7 if no config exists."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the digest to the console but do NOT post to Slack",
    )
    parser.add_argument(
        "--no-ai", action="store_true",
        help=(
            "Skip the AI briefing step (faster, just posts raw stats). "
            "Overrides the include_ai value in digest_schedule.json."
        ),
    )
    parser.add_argument(
        "--show-config", action="store_true",
        help="Print the current digest_schedule.json config and exit",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Load schedule config ──────────────────────────────────────────────────
    # digest_schedule.json is written by the Org Digest tab in sf_query_tool.py.
    # CLI flags override config values when provided.
    cfg = load_schedule_config()

    # Resolve effective settings: CLI flag wins over config file
    effective_days  = args.days if args.days is not None else int(cfg.get("lookback_days", 7))
    effective_no_ai = args.no_ai or not bool(cfg.get("include_ai", True))

    # --show-config: print config and exit
    if args.show_config:
        print("\nCurrent schedule config (digest_schedule.json):")
        print("-" * 40)
        for k, v in cfg.items():
            print(f"  {k:<16} {v}")
        print(f"\nEffective for this run:")
        print(f"  lookback_days    {effective_days}")
        print(f"  include_ai       {not effective_no_ai}")
        return

    print(f"\n{'='*60}")
    print(f"  Axonify Org Digest — {_utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Lookback: last {effective_days} days")
    print(f"  Config: {SCHEDULE_CONFIG_FILE}")
    if args.dry_run:
        print("  Mode: DRY RUN (will not post to Slack)")
    print(f"{'='*60}\n")

    # ── Step 1: Connect ───────────────────────────────────────────────────────
    print("🔌 Connecting to Salesforce…")
    sf = get_sf_connection()
    print(f"   ✓ Connected ({sf.sf_instance})\n")

    # ── Step 2: Fetch data ────────────────────────────────────────────────────
    print(f"📥 Fetching data (last {effective_days} days)…")
    audit_df_raw = get_setup_audit_trail(sf, effective_days)
    audit_df     = _filter_audit_df(audit_df_raw)
    if len(audit_df_raw) > len(audit_df):
        print(
            f"   ✓ Audit trail: {len(audit_df):,} signal entries "
            f"({len(audit_df_raw) - len(audit_df):,} noise rows filtered)"
        )
    limits       = get_org_limits(sf)
    user_changes = get_user_changes(sf, effective_days)
    flows_df     = get_failed_flows(sf, effective_days)
    print()

    # ── Step 3: AI briefing ───────────────────────────────────────────────────
    if effective_no_ai:
        summary = (
            "AI briefing skipped. "
            "Raw statistics are included in the fields below."
        )
        print("⏩ Skipping AI briefing (include_ai=false or --no-ai flag)\n")
    else:
        print("🤖 Generating AI briefing…")
        summary = generate_ai_briefing(effective_days, audit_df, limits, user_changes, flows_df)
        print(f"   ✓ Briefing generated ({len(summary)} chars)\n")

    # ── Step 3b: A.D.A.M. narrative (from operation_logs in Supabase) ────────
    adam_narrative = ""
    if not effective_no_ai:
        print("📝 Generating A.D.A.M. activity narrative…")
        adam_narrative = generate_adam_narrative(effective_days)
        if adam_narrative:
            print(f"   ✓ Narrative generated ({len(adam_narrative)} chars)\n")
        else:
            print("   ℹ️  No operation logs found or Supabase not configured — skipping narrative\n")

    # ── Step 4: Print summary to console (always) ─────────────────────────────
    print("─" * 60)
    print("DIGEST SUMMARY")
    print("─" * 60)
    if adam_narrative:
        print("\n[This Week in A.D.A.M.]")
        print(adam_narrative)
        print()
    print(summary)
    print()

    # Print key stats
    new_u  = user_changes.get("new", pd.DataFrame())
    dead_u = user_changes.get("deactivated", pd.DataFrame())
    print(f"Setup changes : {len(audit_df):,}")
    print(f"New users     : {len(new_u)}")
    print(f"Deactivated   : {len(dead_u)}")
    print(f"Flow errors   : {len(flows_df)}")
    if limits:
        high = [(k, v["pct"]) for k, v in limits.items() if isinstance(v, dict) and v["pct"] > 70]
        if high:
            print(f"High limits   : {', '.join(f'{k} {p}%' for k, p in high)}")
        else:
            print("Limits        : all within normal range")
    print()

    # ── Step 5: Post to Slack ─────────────────────────────────────────────────
    if args.dry_run:
        print("🔍 Dry run — skipping Slack post.")
    else:
        print("📤 Posting to Slack…")
        today      = _utcnow().strftime("%b %d, %Y")
        fallback   = f"Axonify Salesforce Org Digest — {today}"
        blocks     = build_slack_blocks(
            effective_days, summary, audit_df, limits, user_changes, flows_df,
            adam_narrative=adam_narrative,
        )
        ok, msg = post_to_slack(blocks, fallback)

        if ok:
            print(f"   ✅ Posted to #salesforce-slack-notification-testing")
        else:
            print(f"   ❌ Slack post failed: {msg}")
            sys.exit(1)

    print(f"\n{'='*60}")
    print("  Done.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
