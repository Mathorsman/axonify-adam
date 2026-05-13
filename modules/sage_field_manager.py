"""
modules/sage_field_manager.py — SAGE Salesforce Field Manager page.

A.D.A.M. tab that manages which Salesforce fields the SAGE pipeline lands in
BigQuery.  Reads/writes the manifest tables in the same Supabase project that
A.D.A.M. already uses; the salesforce-pipeline Cloud Run Job reads the same
tables on startup when ``MANIFEST_SOURCE=supabase``.

Design: https://github.com/Mathorsman/sage/blob/master/salesforce-field-manager-scope.md

Required Streamlit secrets (re-uses existing A.D.A.M. SUPABASE_*):
    SUPABASE_URL              already set by A.D.A.M.
    SUPABASE_KEY              already set by A.D.A.M. (anon ok while RLS is off)

For the "Trigger sync" button, additionally:
    GCP_PROJECT_ID            "gong-transcripts-490013"
    CLOUD_RUN_JOB_NAME        "salesforce-indexer"
    CLOUD_RUN_JOB_REGION      "us-central1"
    GCP_SERVICE_ACCOUNT_JSON  full service-account key JSON, granted roles/run.invoker
                              on the job
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests
import streamlit as st


BQ_TYPES = ["STRING", "FLOAT64", "INTEGER", "BOOL", "DATE", "TIMESTAMP"]
BQ_MODES = ["NULLABLE", "REQUIRED"]
CAST_STRATEGIES = [
    "auto",
    "float_or_null",
    "int_or_null",
    "bool_passthrough",
    "sf_ts",
]
DEFAULT_CAST_FOR_TYPE = {
    "STRING": "auto",
    "FLOAT64": "float_or_null",
    "INTEGER": "int_or_null",
    "BOOL": "bool_passthrough",
    "DATE": "auto",
    "TIMESTAMP": "sf_ts",
}


# ---------------------------------------------------------------------------
# Secrets — defer to A.D.A.M.'s helper if present, else st.secrets directly.
# ---------------------------------------------------------------------------


def _secret(name: str, default: str = "") -> str:
    """Read a value from ``st.secrets`` first, then default.

    A.D.A.M.'s top-level ``_get_secret`` wraps the same pattern but it's
    private to the module, so duplicate the minimal version here to keep
    this file importable on its own.
    """
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return default


# ---------------------------------------------------------------------------
# Supabase access — uses A.D.A.M.'s existing client when available.
# ---------------------------------------------------------------------------


def _supabase_client():
    """Return A.D.A.M.'s cached Supabase client, or build one ad hoc."""
    try:
        # When this module is imported under sf_query_tool, _get_db_connection
        # is defined in the parent namespace.  Pull it out by walking up the
        # module's globals.
        import importlib

        host = importlib.import_module("sf_query_tool")
        client = host._get_db_connection()
        if client is not None:
            return client
    except Exception:
        pass

    from supabase import create_client

    url = _secret("SUPABASE_URL")
    key = _secret("SUPABASE_KEY") or _secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        st.error(
            "SUPABASE_URL and SUPABASE_KEY must be set in Streamlit secrets."
        )
        st.stop()
    return create_client(url, key)


def _fetch_objects(client) -> list[dict[str, Any]]:
    return (
        client.table("sage_sf_object_manifest")
        .select("*")
        .order("position")
        .execute()
        .data
    )


def _fetch_fields(client, object_name: str) -> list[dict[str, Any]]:
    return (
        client.table("sage_sf_field_manifest")
        .select("*")
        .eq("object_name", object_name)
        .order("position")
        .execute()
        .data
    )


def _fetch_history(client, limit: int = 50) -> list[dict[str, Any]]:
    return (
        client.table("sage_sf_field_manifest_history")
        .select("*")
        .order("changed_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )


def _insert_field(client, *, object_name, sf_field, bq_column, bq_type, bq_mode,
                  cast_strategy, is_derived, actor_email) -> None:
    existing = _fetch_fields(client, object_name)
    next_position = (max((f["position"] for f in existing), default=-1)) + 1

    client.table("sage_sf_field_manifest").insert({
        "object_name": object_name,
        "position": next_position,
        "sf_field": sf_field,
        "bq_column": bq_column,
        "bq_type": bq_type,
        "bq_mode": bq_mode,
        "cast_strategy": cast_strategy,
        "is_derived": is_derived,
        "enabled": True,
    }).execute()

    client.table("sage_sf_field_manifest_history").insert({
        "object_name": object_name,
        "bq_column": bq_column,
        "action": "create",
        "diff": {
            "sf_field": sf_field,
            "bq_type": bq_type,
            "bq_mode": bq_mode,
            "cast_strategy": cast_strategy,
            "is_derived": is_derived,
        },
        "actor_email": actor_email,
    }).execute()


def _insert_object(
    client,
    *,
    object_name: str,
    bq_table: str,
    primary_key_column: str,
    primary_key_sf_field: str,
    primary_key_bq_type: str,
    where_clause: str | None,
    incremental_field: str,
    source_label: str,
    extra_soql_fields: list[str],
    actor_email: str,
) -> None:
    """Create a new sObject row plus its primary-key FieldSpec.

    Every object needs at least one REQUIRED field (the PK) so the BQ table
    can be created — this helper inserts the object row and the PK field row
    in one logical operation, plus two history entries.
    """
    existing = _fetch_objects(client)
    next_position = (max((o["position"] for o in existing), default=-1)) + 1

    client.table("sage_sf_object_manifest").insert({
        "object_name": object_name,
        "bq_table": bq_table,
        "primary_key_column": primary_key_column,
        "where_clause": where_clause or None,
        "incremental_field": incremental_field,
        "source_label": source_label,
        "extra_soql_fields": extra_soql_fields,
        "position": next_position,
        "enabled": True,
    }).execute()

    client.table("sage_sf_field_manifest").insert({
        "object_name": object_name,
        "position": 0,
        "sf_field": primary_key_sf_field,
        "bq_column": primary_key_column,
        "bq_type": primary_key_bq_type,
        "bq_mode": "REQUIRED",
        "cast_strategy": "auto",
        "is_derived": False,
        "enabled": True,
    }).execute()

    client.table("sage_sf_field_manifest_history").insert({
        "object_name": object_name,
        "bq_column": None,
        "action": "create",
        "diff": {
            "scope": "object",
            "bq_table": bq_table,
            "primary_key_column": primary_key_column,
            "where_clause": where_clause,
            "incremental_field": incremental_field,
            "source_label": source_label,
            "extra_soql_fields": extra_soql_fields,
        },
        "actor_email": actor_email,
    }).execute()

    client.table("sage_sf_field_manifest_history").insert({
        "object_name": object_name,
        "bq_column": primary_key_column,
        "action": "create",
        "diff": {
            "sf_field": primary_key_sf_field,
            "bq_type": primary_key_bq_type,
            "bq_mode": "REQUIRED",
            "note": "auto-created primary key",
        },
        "actor_email": actor_email,
    }).execute()


def _set_field_enabled(client, *, field_row, enabled, actor_email) -> None:
    client.table("sage_sf_field_manifest").update(
        {"enabled": enabled}
    ).eq("id", field_row["id"]).execute()
    client.table("sage_sf_field_manifest_history").insert({
        "object_name": field_row["object_name"],
        "bq_column": field_row["bq_column"],
        "action": "enable" if enabled else "disable",
        "diff": {"enabled": [not enabled, enabled]},
        "actor_email": actor_email,
    }).execute()


def _delete_field(client, *, field_row, actor_email, bq_dropped: bool = False) -> None:
    """Remove a field from the manifest.

    Hard delete from ``sage_sf_field_manifest``.  Logs the full removed row
    to history so it can be reconstructed if needed.

    By default the BigQuery column is left intact — only the manifest
    mapping is removed.  Pass ``bq_dropped=True`` *after* a successful
    ``_drop_bq_column`` call so the history entry records both actions
    atomically.
    """
    client.table("sage_sf_field_manifest_history").insert({
        "object_name": field_row["object_name"],
        "bq_column": field_row["bq_column"],
        "action": "delete_with_bq_drop" if bq_dropped else "delete",
        "diff": {
            "removed_row": {
                k: field_row.get(k)
                for k in (
                    "position", "sf_field", "bq_column", "bq_type", "bq_mode",
                    "cast_strategy", "is_derived", "enabled",
                )
            },
            "bq_dropped": bq_dropped,
            "note": (
                "BigQuery column dropped via ALTER TABLE."
                if bq_dropped
                else "BQ column not dropped; remove manually if needed."
            ),
        },
        "actor_email": actor_email,
    }).execute()
    client.table("sage_sf_field_manifest").delete().eq("id", field_row["id"]).execute()


def _drop_bq_column(*, project: str, dataset: str, table: str, column: str) -> tuple[bool, str]:
    """Issue ``ALTER TABLE <dataset>.<table> DROP COLUMN <column>`` against BigQuery.

    Uses the synchronous ``jobs.query`` REST endpoint with a 30-second timeout
    — DDL on a single column completes in well under that on any table.

    Returns ``(success, message)``.  Success returns the job id; failure
    returns the BQ error text suitable for showing in the UI.
    """
    sa_json = _secret("GCP_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        return False, (
            "GCP_SERVICE_ACCOUNT_JSON secret is not set.  The service "
            "account needs `bigquery.tables.update` on "
            f"`{project}.{dataset}`."
        )

    try:
        sa_info = json.loads(sa_json) if isinstance(sa_json, str) else dict(sa_json)
    except json.JSONDecodeError as exc:
        return False, f"GCP_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}"

    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleAuthRequest
    except ImportError:
        return False, (
            "google-auth is not installed.  Add `google-auth>=2.0.0` to "
            "requirements.txt and redeploy."
        )

    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(GoogleAuthRequest())

    # Backtick-quoting protects against odd identifiers and stops SOQL-style
    # parsing surprises.  The column / dataset / table values come from the
    # manifest we control, but defence in depth is cheap.
    sql = (
        f"ALTER TABLE `{project}.{dataset}.{table}` "
        f"DROP COLUMN IF EXISTS `{column}`"
    )

    resp = requests.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries",
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        json={
            "query": sql,
            "useLegacySql": False,
            "timeoutMs": 30000,
        },
        timeout=45,
    )
    if resp.status_code >= 300:
        return False, f"HTTP {resp.status_code}: {resp.text[:500]}"

    body = resp.json()
    if body.get("jobComplete") is False:
        return False, (
            "BigQuery job did not complete inside 30 s.  The DROP may still "
            "succeed in the background — check the BQ console."
        )
    if "errors" in body:
        return False, f"BigQuery: {body['errors']}"

    job_ref = body.get("jobReference", {})
    return True, job_ref.get("jobId", "unknown")


# ---------------------------------------------------------------------------
# Salesforce describe — autocomplete + type inference
# ---------------------------------------------------------------------------

# Maps each SF describe field-type to (bq_type, cast_strategy).  Drives the
# auto-population of the BQ type + cast inputs when the admin picks a field
# from the dropdown.
_SF_TYPE_TO_BQ: dict[str, tuple[str, str]] = {
    "id": ("STRING", "auto"),
    "string": ("STRING", "auto"),
    "textarea": ("STRING", "auto"),
    "email": ("STRING", "auto"),
    "phone": ("STRING", "auto"),
    "url": ("STRING", "auto"),
    "picklist": ("STRING", "auto"),
    "multipicklist": ("STRING", "auto"),
    "reference": ("STRING", "auto"),
    "combobox": ("STRING", "auto"),
    "encryptedstring": ("STRING", "auto"),
    "address": ("STRING", "auto"),
    "location": ("STRING", "auto"),
    "anyType": ("STRING", "auto"),
    "double": ("FLOAT64", "float_or_null"),
    "currency": ("FLOAT64", "float_or_null"),
    "percent": ("FLOAT64", "float_or_null"),
    "int": ("INTEGER", "int_or_null"),
    "long": ("INTEGER", "int_or_null"),
    "boolean": ("BOOL", "bool_passthrough"),
    "date": ("DATE", "auto"),
    "datetime": ("TIMESTAMP", "sf_ts"),
    "time": ("STRING", "auto"),
}


def _sf_to_bq_defaults(sf_type: str) -> tuple[str, str]:
    """Suggest (bq_type, cast_strategy) from an SF describe field type."""
    return _SF_TYPE_TO_BQ.get(sf_type, ("STRING", "auto"))


@st.cache_data(ttl=300, show_spinner=False)
def _describe_fields(object_name: str) -> list[dict]:
    """Return the SF field catalogue for ``object_name``, via A.D.A.M.'s cache.

    Returns an empty list if A.D.A.M.'s describe helper is unavailable (e.g.
    the module is imported outside the host app) or if the SF API errors.
    The UI falls back to a free-form text input when this is empty.
    """
    try:
        import importlib

        host = importlib.import_module("sf_query_tool")
        fields = host.get_object_fields(object_name)
        return fields or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# SOQL preview — same logic as salesforce-pipeline/manifest.build_soql.
# ---------------------------------------------------------------------------


def _render_soql(obj, fields) -> str:
    direct = [f["sf_field"] for f in fields if not f["is_derived"] and f["enabled"]]
    extra = obj.get("extra_soql_fields") or []
    sql = f"SELECT {', '.join(direct + list(extra))} FROM {obj['object_name']}"
    if obj.get("where_clause"):
        sql += f" WHERE {obj['where_clause']}"
    return sql


# ---------------------------------------------------------------------------
# Cloud Run Job trigger via REST API (no gcloud needed on Streamlit Cloud).
# ---------------------------------------------------------------------------


def _trigger_cloud_run_job(*, project: str, region: str, job: str, mode: str) -> tuple[bool, str]:
    """POST to ``runJobs:run`` with a service-account-issued token.

    Returns ``(success, message)`` — never raises.  The caller renders the
    message; we wrap every step so a missing secret, malformed JSON,
    network blip, or API rejection produces a visible string rather than a
    page-crashing exception.
    """
    sa_json = _secret("GCP_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        return False, (
            "GCP_SERVICE_ACCOUNT_JSON secret is not set.  Add a service "
            "account key in Streamlit Cloud → app → Settings → Secrets, "
            "with `roles/run.developer` scoped to the salesforce-indexer job."
        )

    try:
        sa_info = json.loads(sa_json) if isinstance(sa_json, str) else dict(sa_json)
    except json.JSONDecodeError as exc:
        return False, f"GCP_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}"

    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleAuthRequest
    except ImportError:
        return False, (
            "google-auth is not installed.  Add `google-auth>=2.0.0` to "
            "requirements.txt and redeploy."
        )

    try:
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(GoogleAuthRequest())
    except Exception as exc:  # pylint: disable=broad-except
        return False, f"Failed to mint a GCP access token: {type(exc).__name__}: {exc}"

    url = (
        f"https://run.googleapis.com/v2/projects/{project}/locations/{region}"
        f"/jobs/{job}:run"
    )
    body = {
        "overrides": {
            "containerOverrides": [{"args": [f"--mode={mode}"]}]
        }
    }
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
    except requests.RequestException as exc:
        return False, f"Network error calling Cloud Run API: {exc}"

    if resp.status_code >= 300:
        return False, f"HTTP {resp.status_code}: {resp.text[:800]}"

    op = resp.json()
    op_name = op.get("name", "unknown")
    return True, op_name


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------


def _suggest_bq_column(sf_field: str) -> str:
    if not sf_field:
        return ""
    stripped = sf_field.replace("__c", "")
    parts = [p for p in re.split(r"[._]", stripped) if p]
    snake = "_".join(re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", p) for p in parts)
    return snake.lower()


def _suggest_bq_table(object_name: str) -> str:
    """`User` → `users`, `OpportunityLineItem` → `opportunity_line_items`."""
    if not object_name:
        return ""
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", object_name).lower()
    # Naive English pluralisation — covers the common SF objects.  Admins
    # can override the auto-suggestion in the form.
    if snake.endswith("y") and not snake.endswith(("ay", "ey", "oy", "uy")):
        return snake[:-1] + "ies"
    if snake.endswith(("s", "x", "ch", "sh")):
        return snake + "es"
    return snake + "s"


def _suggest_source_label(object_name: str) -> str:
    """`User` → `salesforce-user-sync`."""
    if not object_name:
        return ""
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", object_name).lower()
    return f"salesforce-{snake}-sync"


def _suggest_pk_column(object_name: str) -> str:
    """`User` → `user_id`, `OpportunityLineItem` → `opportunity_line_item_id`."""
    if not object_name:
        return ""
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", object_name).lower()
    return f"{snake}_id"


def _render_delete_popover(client, *, field, actor) -> None:
    """Two-tier delete UI inside the row popover.

    Tier 1 ("Remove from manifest"): pipeline stops populating the column on
    future runs.  Historic values stay in BigQuery — reversible by adding the
    field back.

    Tier 2 ("Also drop BigQuery column"): typed-confirmation gate; runs
    ``ALTER TABLE … DROP COLUMN IF EXISTS …`` via the BigQuery REST API.
    Destroys the historic data.  Not reversible.
    """
    bq_column = field["bq_column"]
    object_name = field["object_name"]
    fid = field["id"]

    st.markdown(f"**Delete `{bq_column}` from the manifest?**")

    if field["bq_mode"] == "REQUIRED":
        st.warning(
            "Primary keys can't be deleted — incremental upserts rely on them. "
            "Delete the whole object instead."
        )
        return

    st.caption(
        "By default the BigQuery column stays put with its historic values "
        "— the pipeline just stops populating it on future runs.  Reversible."
    )

    if st.button(
        "🗑️ Remove from manifest",
        key=f"sage_del_btn_{fid}",
        type="primary",
    ):
        _delete_field(client, field_row=field, actor_email=actor)
        st.toast(f"Removed `{bq_column}` from {object_name}", icon="🗑️")
        st.rerun()

    st.divider()

    # ── Tier 2 — also drop the BQ column ──────────────────────────────────
    project = _secret("GCP_PROJECT_ID", "gong-transcripts-490013")
    dataset = _secret("SAGE_BQ_DATASET", "salesforce_data")

    obj_row = _fetch_object_by_name(client, object_name)
    bq_table = (obj_row or {}).get("bq_table") or "<unknown>"

    st.markdown("**Also drop the BigQuery column** (destructive)")
    st.caption(
        f"Runs `ALTER TABLE {project}.{dataset}.{bq_table} "
        f"DROP COLUMN IF EXISTS {bq_column}`.  The column and its historic "
        f"values are gone for good — not reversible."
    )

    confirm_key = f"sage_drop_confirm_{fid}"
    confirm = st.text_input(
        f"Type `{bq_column}` to enable the drop button:",
        key=confirm_key,
    )

    if st.button(
        "💥 Remove from manifest AND drop BQ column",
        key=f"sage_drop_btn_{fid}",
        type="primary",
        disabled=(confirm != bq_column),
    ):
        ok, msg = _drop_bq_column(
            project=project, dataset=dataset, table=bq_table, column=bq_column,
        )
        if ok:
            _delete_field(client, field_row=field, actor_email=actor, bq_dropped=True)
            st.toast(
                f"Dropped `{bq_column}` from BQ + manifest (job {msg})",
                icon="💥",
            )
            st.rerun()
        else:
            st.error(f"Drop failed — manifest untouched. {msg}")


def _fetch_object_by_name(client, object_name: str) -> dict | None:
    """Look up one object row by name; returns None if missing."""
    rows = (
        client.table("sage_sf_object_manifest")
        .select("*")
        .eq("object_name", object_name)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _render_field_table(client, fields, actor) -> None:
    if not fields:
        st.info("No fields configured for this object yet.")
        return

    weights = [0.4, 2, 2, 0.9, 1, 1.3, 0.7, 0.8, 1.0]
    header_cols = st.columns(weights)
    for col, label in zip(
        header_cols,
        ["#", "SF field", "BQ column", "Type", "Mode", "Cast", "Derived", "Enabled", "Actions"],
    ):
        col.markdown(f"**{label}**")

    for field in fields:
        cols = st.columns(weights)
        cols[0].markdown(f"`{field['position']}`")
        cols[1].markdown(f"`{field['sf_field']}`")
        cols[2].markdown(f"`{field['bq_column']}`")
        cols[3].markdown(field["bq_type"])
        cols[4].markdown(field["bq_mode"])
        cols[5].markdown(f"`{field['cast_strategy']}`")
        cols[6].markdown("✓" if field["is_derived"] else "")
        toggle = cols[7].toggle(
            "on",
            value=field["enabled"],
            key=f"sage_enabled_{field['id']}",
            label_visibility="collapsed",
        )
        if toggle != field["enabled"]:
            _set_field_enabled(
                client, field_row=field, enabled=toggle, actor_email=actor
            )
            st.rerun()

        # Per-row delete in a popover so the action is intentional, not a
        # single mis-click.  Refuses to delete the primary key — that would
        # break upsert deletes on incremental syncs.
        with cols[8].popover("⋯", help="Row actions"):
            _render_delete_popover(client, field=field, actor=actor)


def _render_add_field_form(client, object_name, existing_columns, actor) -> None:
    """Inline form to add one new field.

    Two modes:
      - **Picker** (default): selectbox sourced from the SF describe API.
        Verifies the field exists, shows its label + SF type, and
        auto-populates BQ type + cast strategy from the SF type.
      - **Custom path**: free-form text input for dotted relationship
        traversals (``Owner.Name``, ``Product2.Family``) that don't appear
        in describe directly.

    Not wrapped in ``st.form`` so suggestions update live as the user types.
    """
    with st.expander("➕ Add field", expanded=False):
        all_fields = _describe_fields(object_name)
        existing_sf_fields = {
            f["sf_field"]
            for f in _fetch_fields(client, object_name)
            if not f["is_derived"]
        }

        if not all_fields:
            st.warning(
                f"Couldn't load the field catalogue for `{object_name}` from "
                f"Salesforce.  Falling back to free-form input — make sure "
                f"the field name is exactly right (case-sensitive)."
            )
            use_picker = False
        else:
            use_picker = not st.toggle(
                "Custom field path (relationship traversal)",
                value=False,
                key=f"sage_add_field_custom_{object_name}",
                help="Enable for dotted paths like `Owner.Name` or "
                     "`Product2.Family` — those don't appear in describe but "
                     "the pipeline resolves them at runtime.",
            )

        # ------------------------------------------------------------------
        # SF field — selectbox (picker) or text input (custom)
        # ------------------------------------------------------------------
        if use_picker:
            # Filter out fields that are already on this object so the admin
            # can't accidentally double-add.
            available = [
                f for f in all_fields if f["name"] not in existing_sf_fields
            ]
            if not available:
                st.info("Every Salesforce field on this object is already mapped.")
                return

            def _label(f):
                return f"{f['name']}  —  {f['label']}  ({f['type']})"

            choice = st.selectbox(
                f"Salesforce field on `{object_name}`",
                options=available,
                format_func=_label,
                key=f"sage_add_field_picker_{object_name}",
                help="Start typing to filter.  Showing only fields that are "
                     "not already in the manifest.",
            )
            sf_field = choice["name"]
            sf_type = choice["type"]
            sf_label = choice["label"]
            default_bq, default_cast = _sf_to_bq_defaults(sf_type)
            st.caption(
                f"**SF type:** `{sf_type}`   **Label:** {sf_label}   "
                f"**Default mapping:** `{default_bq}` / cast `{default_cast}`"
            )
        else:
            sf_field = st.text_input(
                "Salesforce field path",
                placeholder="e.g. Owner.Name, Product2.Family",
                key=f"sage_add_field_path_{object_name}",
                help="Dotted paths walk relationships at runtime.  Make sure "
                     "the target field exists on the referenced object.",
            ).strip()
            sf_type = None
            default_bq, default_cast = "STRING", "auto"

        # ------------------------------------------------------------------
        # BQ column + type + mode + cast — auto-filled from the SF choice
        # ------------------------------------------------------------------
        suggested_bq = _suggest_bq_column(sf_field) if sf_field else ""
        bq_column = st.text_input(
            "BigQuery column",
            value=suggested_bq,
            placeholder="auto-suggested from SF field",
            key=f"sage_add_field_bq_col_{object_name}__{suggested_bq}",
        )

        col1, col2, col3 = st.columns(3)
        bq_type = col1.selectbox(
            "Type",
            BQ_TYPES,
            index=BQ_TYPES.index(default_bq),
            key=f"sage_add_field_bq_type_{object_name}__{default_bq}",
        )
        bq_mode = col2.selectbox(
            "Mode",
            BQ_MODES,
            index=0,
            key=f"sage_add_field_bq_mode_{object_name}",
        )
        cast_strategy = col3.selectbox(
            "Cast strategy",
            CAST_STRATEGIES,
            index=CAST_STRATEGIES.index(default_cast),
            key=f"sage_add_field_cast_{object_name}__{default_cast}",
            help="`auto` is correct for almost everything except numerics, booleans, and datetimes.",
        )

        is_derived = st.checkbox(
            "Derived (Python builder)",
            value=False,
            key=f"sage_add_field_derived_{object_name}",
            help=(
                "Check if this column's value is computed in Python from other "
                "fields rather than coming directly from SOQL.  A builder must "
                "be registered in `main.DERIVED_BUILDERS`."
            ),
        )

        if st.button(
            "Add field",
            type="primary",
            key=f"sage_add_field_submit_{object_name}",
        ):
            if not sf_field or not bq_column.strip():
                st.error("Both Salesforce field and BigQuery column are required.")
            elif bq_column in existing_columns:
                st.error(f"BigQuery column `{bq_column}` already exists.")
            else:
                _insert_field(
                    client,
                    object_name=object_name,
                    sf_field=sf_field,
                    bq_column=bq_column.strip(),
                    bq_type=bq_type,
                    bq_mode=bq_mode,
                    cast_strategy=cast_strategy,
                    is_derived=is_derived,
                    actor_email=actor,
                )
                st.success(f"Added `{bq_column}` to {object_name}.")
                st.rerun()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def _page_object(client, obj, actor) -> None:
    fields = _fetch_fields(client, obj["object_name"])

    st.subheader(f"{obj['object_name']} → `{obj['bq_table']}`")

    summary = st.columns(4)
    summary[0].metric("Fields", len(fields))
    summary[1].metric("Enabled", sum(1 for f in fields if f["enabled"]))
    summary[2].markdown(f"**Primary key**\n\n`{obj['primary_key_column']}`")
    summary[3].markdown(f"**Incremental on**\n\n`{obj['incremental_field']}`")

    if obj.get("where_clause"):
        st.caption(f"WHERE clause: `{obj['where_clause']}`")
    extra = obj.get("extra_soql_fields") or []
    if extra:
        st.caption(f"Extra SOQL fields (not mapped to BQ): {', '.join(extra)}")

    st.markdown("### Fields")
    _render_field_table(client, fields, actor)

    _render_add_field_form(
        client,
        obj["object_name"],
        existing_columns={f["bq_column"] for f in fields},
        actor=actor,
    )

    with st.expander("🔍 SOQL preview", expanded=False):
        st.code(_render_soql(obj, fields), language="sql")

    # Trigger results live in session_state keyed by object so they survive
    # the rerun-induced expander collapse.  Without this, st.success() would
    # render inside the expander, then disappear when the expander snaps
    # closed on the next interaction — the user would see "nothing happened".
    trigger_state_key = f"sage_trigger_result_{obj['object_name']}"
    last = st.session_state.get(trigger_state_key)

    expander_open = bool(last)  # Keep the expander open if there's a result to show.
    with st.expander("⚙️ Trigger pipeline run", expanded=expander_open):
        st.markdown(
            "After changing the manifest, run the pipeline to materialise the "
            "additions/removals in BigQuery.  Incremental is fast and safe; "
            "backfill truncates and reloads everything."
        )
        project = _secret("GCP_PROJECT_ID", "gong-transcripts-490013")
        job = _secret("CLOUD_RUN_JOB_NAME", "salesforce-indexer")
        region = _secret("CLOUD_RUN_JOB_REGION", "us-central1")

        # Surface the most recent trigger result every render until the user
        # dismisses it.  Persists across reruns.
        if last:
            ok, msg, when = last
            if ok:
                st.success(
                    f"✅ Submitted at {when} — execution `{msg}`.  "
                    f"Track in GCP console → Cloud Run → Jobs → "
                    f"[{job}](https://console.cloud.google.com/run/jobs/"
                    f"details/{region}/{job}/executions?project={project})."
                )
            else:
                st.error(f"❌ Last trigger failed: {msg}")
            if st.button("Dismiss", key=f"sage_trigger_dismiss_{obj['object_name']}"):
                del st.session_state[trigger_state_key]
                st.rerun()

        col1, col2 = st.columns(2)
        if col1.button(
            "▶️ Trigger incremental sync",
            key=f"sage_trigger_inc_{obj['object_name']}",
            type="primary",
        ):
            with st.spinner("Submitting incremental sync…"):
                ok, msg = _trigger_cloud_run_job(
                    project=project, region=region, job=job, mode="incremental"
                )
            from datetime import datetime
            st.session_state[trigger_state_key] = (
                ok, msg, datetime.now().strftime("%H:%M:%S"),
            )
            # Toast survives the rerun even if the user navigates away.
            st.toast(
                "Sync submitted" if ok else f"Trigger failed: {msg[:80]}",
                icon="✅" if ok else "❌",
            )
            st.rerun()

        if col2.button("⚠️ Trigger backfill", key=f"sage_trigger_bf_{obj['object_name']}"):
            st.session_state[f"sage_bf_pending_{obj['object_name']}"] = True

        if st.session_state.get(f"sage_bf_pending_{obj['object_name']}"):
            confirm = st.text_input(
                "Backfill truncates and reloads every manifest-managed table. "
                "Type **BACKFILL** to confirm:",
                key=f"sage_bf_confirm_{obj['object_name']}",
            )
            if confirm == "BACKFILL":
                with st.spinner("Submitting backfill…"):
                    ok, msg = _trigger_cloud_run_job(
                        project=project, region=region, job=job, mode="backfill"
                    )
                from datetime import datetime
                st.session_state[trigger_state_key] = (
                    ok, msg, datetime.now().strftime("%H:%M:%S"),
                )
                st.session_state[f"sage_bf_pending_{obj['object_name']}"] = False
                st.toast(
                    "Backfill submitted" if ok else f"Backfill failed: {msg[:80]}",
                    icon="✅" if ok else "❌",
                )
                st.rerun()


def _render_add_object_form(client, existing_object_names: set[str], existing_tables: set[str], actor: str) -> None:
    """Form to create a new sObject entry in the manifest.

    A new entry needs at minimum: the SF object name, the BQ table name,
    and a primary key field.  Everything else is optional and can be edited
    later via the Field Manager tab for that object.
    """

    # No st.form wrapper — Streamlit's form widget batches all inputs and only
    # reruns on submit, which prevents the BQ table / PK column / source label
    # suggestions from updating live as the user types the object name.
    col1, col2 = st.columns(2)
    object_name = col1.text_input(
        "Salesforce object name",
        placeholder="e.g. User, Contact, Case, Lead",
        help="The exact SOQL object API name.  Case-sensitive.",
        key="sage_add_obj_name",
    )

    # Re-derive each suggestion from the live object_name; embed it into the
    # widget key so Streamlit treats a new suggestion as a new widget and
    # re-renders the input value (rather than preserving the stale value the
    # user hasn't touched).
    suggested_table = _suggest_bq_table(object_name)
    suggested_pk = _suggest_pk_column(object_name)
    suggested_source = _suggest_source_label(object_name)

    bq_table = col2.text_input(
        "BigQuery table name",
        value=suggested_table,
        placeholder="auto-suggested from object name",
        help="Will land under `gong-transcripts-490013.salesforce_data.<this>`.",
        key=f"sage_add_obj_bq_table__{suggested_table}",
    )

    st.markdown(
        "**Primary key** — the SF field that uniquely identifies a record. "
        "Almost always `Id`."
    )
    col3, col4, col5 = st.columns([2, 2, 1])
    primary_key_sf_field = col3.text_input(
        "SF primary-key field",
        value="Id",
        key="sage_add_obj_pk_sf",
    )
    primary_key_bq_column = col4.text_input(
        "BQ primary-key column",
        value=suggested_pk,
        placeholder="auto-suggested",
        key=f"sage_add_obj_pk_bq__{suggested_pk}",
    )
    primary_key_bq_type = col5.selectbox(
        "Type",
        BQ_TYPES,
        index=0,
        key="sage_add_obj_pk_type",
    )

    st.markdown("**Filters & sync behaviour**")
    col6, col7 = st.columns(2)
    where_clause = col6.text_input(
        "WHERE clause (optional)",
        placeholder="e.g. IsDeleted = false",
        help="SOQL WHERE body, no leading WHERE.  Applied in both backfill "
             "and incremental modes.",
        key="sage_add_obj_where",
    )
    incremental_field = col7.text_input(
        "Incremental field",
        value="LastModifiedDate",
        help="SF datetime field for incremental syncs.  Almost always "
             "LastModifiedDate.",
        key="sage_add_obj_inc",
    )

    source_label = st.text_input(
        "Audit source label",
        value=suggested_source,
        placeholder="auto-suggested",
        help="Written to the `source` column on every row this object "
             "produces, for traceability.",
        key=f"sage_add_obj_source__{suggested_source}",
    )

    extra_soql_raw = st.text_input(
        "Extra SOQL fields (optional, comma-separated)",
        placeholder="e.g. OwnerId, RecordTypeId",
        help="SF fields to include in the SELECT but **not** map to a BQ "
             "column.  Used for derived-column inputs or forward-compat.",
        key="sage_add_obj_extra",
    )

    if st.button("Create object", type="primary", key="sage_add_obj_submit"):
        errors = []
        object_name = object_name.strip()
        bq_table = bq_table.strip()
        primary_key_sf_field = primary_key_sf_field.strip()
        primary_key_bq_column = primary_key_bq_column.strip()
        where_clause_clean = (where_clause or "").strip() or None
        source_label = source_label.strip()
        extra_soql = [s.strip() for s in extra_soql_raw.split(",") if s.strip()]

        if not object_name:
            errors.append("Salesforce object name is required.")
        elif object_name in existing_object_names:
            errors.append(f"Object `{object_name}` already exists in the manifest.")
        if not bq_table:
            errors.append("BigQuery table name is required.")
        elif bq_table in existing_tables:
            errors.append(f"BigQuery table `{bq_table}` is already used.")
        if not primary_key_sf_field:
            errors.append("Primary-key SF field is required.")
        if not primary_key_bq_column:
            errors.append("Primary-key BQ column is required.")
        if not source_label:
            errors.append("Source label is required.")

        if errors:
            for err in errors:
                st.error(err)
        else:
            _insert_object(
                client,
                object_name=object_name,
                bq_table=bq_table,
                primary_key_column=primary_key_bq_column,
                primary_key_sf_field=primary_key_sf_field,
                primary_key_bq_type=primary_key_bq_type,
                where_clause=where_clause_clean,
                incremental_field=incremental_field.strip() or "LastModifiedDate",
                source_label=source_label,
                extra_soql_fields=extra_soql,
                actor_email=actor,
            )
            st.success(
                f"Created `{object_name}`.  Open Field Manager and pick "
                f"its tab to add fields, then trigger an incremental sync."
            )
            st.rerun()


def _page_history(client) -> None:
    rows = _fetch_history(client)
    if not rows:
        st.info("No manifest changes yet.")
        return
    st.markdown("### Recent manifest changes")
    for r in rows:
        diff = r.get("diff") or {}
        diff_str = ", ".join(f"`{k}`={v}" for k, v in diff.items()) if diff else ""
        st.markdown(
            f"- **{r['changed_at'][:19]}** — `{r['action']}` "
            f"on `{r['object_name']}.{r.get('bq_column') or '*'}` "
            f"by `{r.get('actor_email') or 'unknown'}`  \n"
            f"  {diff_str}"
        )


# ---------------------------------------------------------------------------
# Entry point — called from sf_query_tool.render_sage_field_manager_page.
# ---------------------------------------------------------------------------


def render_page(dry_run_mode: bool, auto_backup: bool) -> None:
    """A.D.A.M. page wrapper.  The dry_run/auto_backup args are accepted for
    signature symmetry with other render_*_page functions but unused — the
    manifest is itself a config layer, separate from A.D.A.M.'s SF write
    safety controls.
    """
    st.title("SAGE Salesforce Field Manager")
    st.caption(
        "Manage which Salesforce fields the SAGE pipeline lands in BigQuery. "
        "Changes take effect on the next pipeline run.  "
        "Backed by Supabase tables `sage_sf_object_manifest` / "
        "`sage_sf_field_manifest` / `sage_sf_field_manifest_history`."
    )

    client = _supabase_client()
    actor = (
        st.session_state.get("sf_user_info", {}).get("email")
        or _secret("DEFAULT_ACTOR_EMAIL")
        or "unknown@axonify.com"
    )

    objects = _fetch_objects(client)
    if not objects:
        st.error(
            "No objects in `sage_sf_object_manifest`.  Run "
            "`seed_supabase_manifest.py` from the salesforce-pipeline repo to "
            "bootstrap the tables, then refresh."
        )
        return

    tab_names = [o["object_name"] for o in objects] + ["📜 History"]
    tabs = st.tabs(tab_names)

    for tab, obj in zip(tabs[:-1], objects):
        with tab:
            _page_object(client, obj, actor)

    with tabs[-1]:
        _page_history(client)


# ---------------------------------------------------------------------------
# Object Manager — separate sidebar entry, focused on adding / overview.
# ---------------------------------------------------------------------------


def render_object_manager(dry_run_mode: bool, auto_backup: bool) -> None:
    """A.D.A.M. page: manage the *set* of synced sObjects.

    Field-level editing lives in the Field Manager page; this one is for
    structural changes: what's being synced at all, primary key, WHERE
    filter, audit label.  New objects are created here and their fields
    populated via the Field Manager.
    """
    st.title("Data Lake — Object Manager")
    st.caption(
        "Manage which Salesforce objects the SAGE pipeline syncs into "
        "BigQuery.  Each row maps one SF sObject to one BQ table in "
        "`gong-transcripts-490013.salesforce_data`.  Field-level mapping "
        "lives in Field Manager."
    )

    client = _supabase_client()
    actor = (
        st.session_state.get("sf_user_info", {}).get("email")
        or _secret("DEFAULT_ACTOR_EMAIL")
        or "unknown@axonify.com"
    )

    objects = _fetch_objects(client)

    st.markdown("### Synced objects")
    if not objects:
        st.info(
            "No objects in the manifest yet.  Use the form below to create one."
        )
    else:
        for obj in objects:
            fields = _fetch_fields(client, obj["object_name"])
            with st.container(border=True):
                top = st.columns([3, 2, 1, 1])
                top[0].markdown(
                    f"#### `{obj['object_name']}` → `{obj['bq_table']}`"
                )
                top[1].markdown(
                    f"**Source label**\n\n`{obj['source_label']}`"
                )
                top[2].metric("Fields", len(fields))
                top[3].metric("Enabled", sum(1 for f in fields if f["enabled"]))

                detail = st.columns(3)
                detail[0].markdown(
                    f"**Primary key**\n\n`{obj['primary_key_column']}`"
                )
                detail[1].markdown(
                    f"**Incremental field**\n\n`{obj['incremental_field']}`"
                )
                detail[2].markdown(
                    f"**WHERE clause**\n\n"
                    f"`{obj['where_clause'] or '(none)'}`"
                )

                extra = obj.get("extra_soql_fields") or []
                if extra:
                    st.caption(
                        f"Extra SOQL fields (not mapped to BQ): "
                        f"{', '.join(extra)}"
                    )

    st.markdown("### Add a new object")
    _render_add_object_form(
        client,
        existing_object_names={o["object_name"] for o in objects},
        existing_tables={o["bq_table"] for o in objects},
        actor=actor,
    )
