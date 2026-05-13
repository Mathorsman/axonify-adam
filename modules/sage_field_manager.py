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
    CLOUD_RUN_JOB_NAME        "salesforce-pipeline"
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
    """POST to runJobs:run with a service-account-issued token.

    Returns ``(success, message)``.  Sets ``--wait=false`` semantics by
    not polling — the job runs in Cloud Run; the caller can track it in
    the GCP console.
    """
    sa_json = _secret("GCP_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        return False, (
            "GCP_SERVICE_ACCOUNT_JSON secret is not set.  Add a service account "
            "key with the `roles/run.invoker` role on the salesforce-pipeline job, "
            "then redeploy."
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

    url = (
        f"https://run.googleapis.com/v2/projects/{project}/locations/{region}"
        f"/jobs/{job}:run"
    )
    body = {
        "overrides": {
            "containerOverrides": [{"args": [f"--mode={mode}"]}]
        }
    }
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    if resp.status_code >= 300:
        return False, f"HTTP {resp.status_code}: {resp.text[:500]}"

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


def _render_field_table(client, fields, actor) -> None:
    if not fields:
        st.info("No fields configured for this object yet.")
        return

    header_cols = st.columns([0.5, 2, 2, 1, 1, 1.5, 1, 1])
    for col, label in zip(
        header_cols,
        ["#", "SF field", "BQ column", "Type", "Mode", "Cast", "Derived", "Enabled"],
    ):
        col.markdown(f"**{label}**")

    for field in fields:
        cols = st.columns([0.5, 2, 2, 1, 1, 1.5, 1, 1])
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


def _render_add_field_form(client, object_name, existing_columns, actor) -> None:
    with st.expander("➕ Add field", expanded=False):
        with st.form(key=f"sage_add_field_{object_name}"):
            col1, col2 = st.columns(2)
            sf_field = col1.text_input(
                "Salesforce field name",
                placeholder="e.g. Website, Description, BillingPostalCode",
                help="Use dotted paths for relationships: Owner.Name, Product2.Family.",
                key=f"sage_sf_field_{object_name}",
            )
            bq_column = col2.text_input(
                "BigQuery column",
                value=_suggest_bq_column(sf_field) if sf_field else "",
                placeholder="auto-suggested from SF field",
                key=f"sage_bq_column_{object_name}",
            )
            col3, col4, col5 = st.columns(3)
            bq_type = col3.selectbox("Type", BQ_TYPES, index=0,
                key=f"sage_bq_type_{object_name}")
            bq_mode = col4.selectbox("Mode", BQ_MODES, index=0,
                key=f"sage_bq_mode_{object_name}")
            cast_strategy = col5.selectbox(
                "Cast strategy",
                CAST_STRATEGIES,
                index=CAST_STRATEGIES.index(DEFAULT_CAST_FOR_TYPE[bq_type]),
                key=f"sage_cast_{object_name}",
                help="`auto` is correct for almost everything except numerics, booleans, and datetimes.",
            )
            is_derived = st.checkbox(
                "Derived (Python builder)",
                value=False,
                key=f"sage_derived_{object_name}",
                help=(
                    "Check if this column's value is computed in Python from other "
                    "fields rather than coming directly from SOQL.  A builder must "
                    "be registered in main.DERIVED_BUILDERS."
                ),
            )
            submitted = st.form_submit_button("Add field", type="primary")
            if submitted:
                if not sf_field.strip() or not bq_column.strip():
                    st.error("Both Salesforce field and BigQuery column are required.")
                elif bq_column in existing_columns:
                    st.error(f"BigQuery column `{bq_column}` already exists.")
                else:
                    _insert_field(
                        client,
                        object_name=object_name,
                        sf_field=sf_field.strip(),
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

    with st.expander("⚙️ Trigger pipeline run", expanded=False):
        st.markdown(
            "After changing the manifest, run the pipeline to materialise the "
            "additions/removals in BigQuery.  Incremental is fast and safe; "
            "backfill truncates and reloads everything."
        )
        project = _secret("GCP_PROJECT_ID", "gong-transcripts-490013")
        job = _secret("CLOUD_RUN_JOB_NAME", "salesforce-pipeline")
        region = _secret("CLOUD_RUN_JOB_REGION", "us-central1")

        col1, col2 = st.columns(2)
        if col1.button("▶️ Trigger incremental sync", key=f"sage_trigger_inc_{obj['object_name']}", type="primary"):
            ok, msg = _trigger_cloud_run_job(
                project=project, region=region, job=job, mode="incremental"
            )
            if ok:
                st.success(f"Submitted execution: `{msg}`")
                st.caption(
                    "Track progress in the GCP console → Cloud Run → Jobs → executions."
                )
            else:
                st.error(msg)

        if col2.button("⚠️ Trigger backfill", key=f"sage_trigger_bf_{obj['object_name']}"):
            st.session_state[f"sage_bf_pending_{obj['object_name']}"] = True

        if st.session_state.get(f"sage_bf_pending_{obj['object_name']}"):
            confirm = st.text_input(
                "Backfill truncates and reloads every manifest-managed table. "
                "Type **BACKFILL** to confirm:",
                key=f"sage_bf_confirm_{obj['object_name']}",
            )
            if confirm == "BACKFILL":
                ok, msg = _trigger_cloud_run_job(
                    project=project, region=region, job=job, mode="backfill"
                )
                if ok:
                    st.success(f"Backfill submitted: `{msg}`")
                    st.session_state[f"sage_bf_pending_{obj['object_name']}"] = False
                else:
                    st.error(msg)


def _page_add_object(client, existing_object_names: set[str], existing_tables: set[str], actor: str) -> None:
    """Form to create a new sObject entry in the manifest.

    A new entry needs at minimum: the SF object name, the BQ table name,
    and a primary key field.  Everything else is optional and can be edited
    later via the object's own tab.

    After submission the user is rerun back to the standard tab list — the
    new tab appears alongside the existing ones, and they can start adding
    fields immediately.
    """
    st.subheader("Add a new Salesforce object to the manifest")
    st.caption(
        "Creating an object here makes the SAGE pipeline start syncing it on "
        "the next run.  The BigQuery table will be created automatically with "
        "just the primary-key column; add the rest of the fields once the "
        "object's own tab appears."
    )

    with st.form(key="sage_add_object"):
        col1, col2 = st.columns(2)
        object_name = col1.text_input(
            "Salesforce object name",
            placeholder="e.g. User, Contact, Case, Lead",
            help="The exact SOQL object API name.  Case-sensitive.",
        )
        bq_table = col2.text_input(
            "BigQuery table name",
            value=_suggest_bq_table(object_name),
            placeholder="auto-suggested from object name",
            help="Will land under `gong-transcripts-490013.salesforce_data.<this>`.",
        )

        st.markdown("**Primary key** — the SF field that uniquely identifies a record. "
                    "Almost always `Id`.")
        col3, col4, col5 = st.columns([2, 2, 1])
        primary_key_sf_field = col3.text_input(
            "SF primary-key field",
            value="Id",
            key="sage_add_obj_pk_sf",
        )
        primary_key_bq_column = col4.text_input(
            "BQ primary-key column",
            value=_suggest_pk_column(object_name),
            placeholder="auto-suggested",
            key="sage_add_obj_pk_bq",
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
        )
        incremental_field = col7.text_input(
            "Incremental field",
            value="LastModifiedDate",
            help="SF datetime field for incremental syncs.  Almost always "
                 "LastModifiedDate.",
        )

        source_label = st.text_input(
            "Audit source label",
            value=_suggest_source_label(object_name),
            placeholder="auto-suggested",
            help="Written to the `source` column on every row this object "
                 "produces, for traceability.",
        )

        extra_soql_raw = st.text_input(
            "Extra SOQL fields (optional, comma-separated)",
            placeholder="e.g. OwnerId, RecordTypeId",
            help="SF fields to include in the SELECT but **not** map to a BQ "
                 "column.  Used for derived-column inputs or forward-compat.",
        )

        submitted = st.form_submit_button("Create object", type="primary")

        if submitted:
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
                    f"Created `{object_name}`.  Switch to its tab to add fields, "
                    f"then trigger an incremental sync."
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

    tab_names = (
        [o["object_name"] for o in objects]
        + ["➕ Add object", "📜 History"]
    )
    tabs = st.tabs(tab_names)

    # Object tabs come first.
    for tab, obj in zip(tabs[: len(objects)], objects):
        with tab:
            _page_object(client, obj, actor)

    with tabs[-2]:
        _page_add_object(
            client,
            existing_object_names={o["object_name"] for o in objects},
            existing_tables={o["bq_table"] for o in objects},
            actor=actor,
        )

    with tabs[-1]:
        _page_history(client)
