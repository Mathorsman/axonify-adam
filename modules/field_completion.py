"""
Field completion rate strategy.

Wraps Salesforce's per-field-type quirks (long text not filterable, picklist
defaults inflating "populated", compound fields needing component checks,
booleans always populated) so the AI Query Builder can answer "what is the
completion rate of <field>?" for any field type with a consistent result.

Public surface:
    resolve_field_reference(sf, sobject, hint) -> (api_name, field_meta) | None
    compute_field_completion(sf, sobject, field_api_name, ...) -> dict
    run_field_completion(params, status_cb) -> dict          # strategy entrypoint
"""
from __future__ import annotations

# Always-populated types — Salesforce never returns null for these,
# so completion is 100% by definition. (Booleans default to false, IDs
# always exist, autonumber is auto-assigned, formulas always compute.)
ALWAYS_POPULATED_TYPES = {"id", "autonumber", "boolean", "checkbox"}

# Long-text fields — cannot use `WHERE Field = null` in SOQL.
LONG_TEXT_TYPES = {"textarea"}      # describe() returns 'textarea' for both LongText and RichText

# Encrypted / blob types — cannot be aggregated or null-filtered.
UNSUPPORTED_TYPES = {"encryptedstring", "base64", "anytype"}

# Compound types — must look at component fields, not the parent field.
COMPOUND_TYPES = {"address", "location"}


# ──────────────────────────────────────────────────────────────────────────────
# Field reference resolution
# ──────────────────────────────────────────────────────────────────────────────

def resolve_field_reference(
    sf,
    sobject: str,
    hint: str,
) -> tuple[str, dict] | None:
    """
    Resolve a user-typed field hint to (api_name, field_metadata).

    Resolution tiers (first hit wins):
      1. Exact API name match (case-insensitive)
      2. Exact label match (case-insensitive)
      3. Hint substring inside API name (with __c stripped, _ → space)
      4. Hint substring inside label
      5. rapidfuzz token_sort_ratio >= 80 against label or API name

    Returns None when no field matches confidently.
    """
    try:
        desc = getattr(sf, sobject).describe()
    except Exception:
        return None
    fields = desc.get("fields", [])
    if not fields:
        return None

    hint_clean = (hint or "").strip()
    if not hint_clean:
        return None
    hint_lower = hint_clean.lower()
    hint_norm  = hint_lower.replace("_", " ").replace("__c", "").strip()

    # Tier 1 — exact API name
    for f in fields:
        if f["name"].lower() == hint_lower:
            return f["name"], f

    # Tier 2 — exact label
    for f in fields:
        if (f.get("label") or "").lower() == hint_lower:
            return f["name"], f

    # Tier 3/4 — substring containment on API name or label (prefer shortest match)
    sub_matches = []
    for f in fields:
        api_norm   = f["name"].lower().replace("__c", "").replace("_", " ").strip()
        label_norm = (f.get("label") or "").lower().strip()
        if hint_norm and (hint_norm in api_norm or hint_norm in label_norm):
            sub_matches.append(f)
    if sub_matches:
        sub_matches.sort(key=lambda f: len(f["name"]))
        return sub_matches[0]["name"], sub_matches[0]

    # Tier 5 — fuzzy match (graceful when rapidfuzz is missing)
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return None

    best = (0, None)
    for f in fields:
        api_norm   = f["name"].lower().replace("__c", "").replace("_", " ")
        label_norm = (f.get("label") or "").lower()
        score = max(
            fuzz.token_sort_ratio(hint_norm, api_norm),
            fuzz.token_sort_ratio(hint_norm, label_norm),
        )
        if score > best[0]:
            best = (score, f)
    if best[1] and best[0] >= 80:
        return best[1]["name"], best[1]

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Completion-rate computation
# ──────────────────────────────────────────────────────────────────────────────

def compute_field_completion(
    sf,
    sobject: str,
    field_api_name: str,
    *,
    where_clause: str = "",
    treat_picklist_default_as_empty: bool = True,
    treat_whitespace_as_empty: bool = True,
    long_text_sample_cap: int = 50_000,
    status_cb=None,
) -> dict:
    """
    Compute completion rate for a single field. Returns a structured dict:

        {
          "object", "field", "field_label", "field_type",
          "total_records", "complete_count", "incomplete_count", "completion_pct",
          "method", "notes": [str], "scope_filter",
          "error": <str>?      # set only on hard failure
        }

    Nulls, empty strings, and (optionally) whitespace-only or picklist-default
    values count as "not complete." Never raises — failures land in `error`.
    """
    def _say(msg, style="info"):
        if status_cb:
            status_cb(msg, style)

    # ── Resolve field metadata via describe ──────────────────────────────────
    try:
        desc = getattr(sf, sobject).describe()
    except Exception as exc:
        return _err(sobject, field_api_name, f"Cannot describe {sobject}: {exc}")

    fmeta = next((f for f in desc.get("fields", []) if f["name"] == field_api_name), None)
    if fmeta is None:
        return _err(sobject, field_api_name,
                    f"Field '{field_api_name}' not found on {sobject}.")

    field_type   = (fmeta.get("type") or "").lower()
    field_label  = fmeta.get("label") or field_api_name
    notes: list[str] = []

    # ── Build base WHERE conditions ──────────────────────────────────────────
    base_conditions: list[str] = []
    has_isdeleted = any(f["name"] == "IsDeleted" for f in desc.get("fields", []))
    if has_isdeleted:
        base_conditions.append("IsDeleted = false")
    if where_clause and where_clause.strip():
        base_conditions.append(f"({where_clause.strip()})")

    def _count(extra: str | None = None) -> int:
        parts = list(base_conditions)
        if extra:
            parts.append(extra)
        where_sql = (" WHERE " + " AND ".join(parts)) if parts else ""
        res = sf.query(f"SELECT COUNT(Id) cnt FROM {sobject}{where_sql}")
        return res["records"][0]["cnt"] or 0

    scope_str = " AND ".join(base_conditions) or "(none)"

    # ── Total records in scope ───────────────────────────────────────────────
    _say("Counting total records…")
    try:
        total = _count()
    except Exception as exc:
        # IsDeleted may not exist on some objects (e.g. User) — retry without
        if has_isdeleted and base_conditions and base_conditions[0].startswith("IsDeleted"):
            base_conditions.pop(0)
            try:
                total = _count()
                scope_str = " AND ".join(base_conditions) or "(none)"
            except Exception as exc2:
                return _err(sobject, field_api_name, f"Could not count records: {exc2}")
        else:
            return _err(sobject, field_api_name, f"Could not count records: {exc}")

    if total == 0:
        return _result(sobject, field_api_name, field_label, field_type,
                       total=0, complete=0, method="none",
                       notes=["No records found in scope."], scope=scope_str)

    # ── Type-based dispatch ──────────────────────────────────────────────────
    # Resolve formula fields to their underlying scalar type so the rest of
    # the dispatch logic doesn't have to special-case formulas.
    if field_type == "calculated" or fmeta.get("calculatedFormula"):
        soap = (fmeta.get("soapType") or "").replace("xsd:", "").lower()
        formula_map = {
            "string":   "string",   "boolean":  "boolean",
            "double":   "double",   "int":      "int",
            "date":     "date",     "datetime": "datetime",
            "currency": "currency",
        }
        notes.append(f"Formula field — counted using underlying type ({soap or 'string'}).")
        field_type = formula_map.get(soap, "string")

    if field_type in ALWAYS_POPULATED_TYPES:
        return _result(sobject, field_api_name, field_label, field_type,
                       total=total, complete=total, method="type_always_populated",
                       notes=notes + [f"`{field_type}` fields are always populated by "
                                      f"Salesforce — completion is 100% by definition."],
                       scope=scope_str)

    if field_type in COMPOUND_TYPES:
        return _compute_compound(sf, sobject, fmeta, base_conditions, total,
                                 _count, notes, scope_str, status_cb)

    if field_type in LONG_TEXT_TYPES:
        return _compute_long_text(sf, sobject, fmeta, base_conditions, total,
                                  scope_str, notes, status_cb,
                                  treat_whitespace_as_empty, long_text_sample_cap)

    if field_type in UNSUPPORTED_TYPES:
        return _err(sobject, field_api_name,
                    f"`{field_type}` fields cannot be aggregated — Salesforce "
                    f"does not permit null filters or bulk reads on this type.",
                    field_label=field_label, field_type=field_type,
                    total=total, scope=scope_str, notes=notes)

    if field_type in ("picklist", "multipicklist") and treat_picklist_default_as_empty:
        default_val = next(
            (pv["value"] for pv in (fmeta.get("picklistValues") or [])
             if pv.get("defaultValue")),
            None,
        )
        if default_val:
            return _compute_picklist_with_default(
                sf, sobject, fmeta, base_conditions, total, _count,
                default_val, notes, scope_str, status_cb,
            )

    return _compute_scalar(sf, sobject, fmeta, base_conditions, total, _count,
                           notes, scope_str, status_cb,
                           treat_whitespace_as_empty)


def _compute_scalar(sf, sobject, fmeta, base_conditions, total, _count,
                    notes, scope_str, status_cb, treat_whitespace_as_empty):
    """Standard scalar — count nulls, plus empty strings for text-like types."""
    field    = fmeta["name"]
    ftype    = (fmeta.get("type") or "").lower()
    label    = fmeta.get("label") or field

    # Text-like types: also count empty string as incomplete
    text_like = {"string", "textarea", "url", "email", "phone", "picklist",
                 "multipicklist", "reference"}

    if status_cb:
        status_cb("Running completion query…")

    try:
        # Build the "incomplete" predicate
        if ftype in text_like:
            incomplete_pred = f"({field} = null OR {field} = '')"
        else:
            incomplete_pred = f"{field} = null"

        incomplete = _count(incomplete_pred)
    except Exception as exc:
        # Fallback: try just null check
        try:
            incomplete = _count(f"{field} = null")
            notes.append("Empty-string check failed for this type; counted nulls only.")
        except Exception as exc2:
            return _err(sobject, field, f"SOQL count failed: {exc2}",
                        field_label=label, field_type=ftype,
                        total=total, scope=scope_str, notes=notes)

    complete = max(0, total - incomplete)

    # Optional whitespace pass for text fields — sample up to 5,000 records
    # and check for whitespace-only values that SOQL `= ''` doesn't catch.
    if treat_whitespace_as_empty and ftype in {"string", "textarea"}:
        try:
            ws_count = _count_whitespace(sf, sobject, field, base_conditions,
                                         sample_cap=5_000, status_cb=status_cb)
            if ws_count and ws_count > 0:
                # Whitespace records were counted in `complete`; subtract them.
                complete = max(0, complete - ws_count)
                incomplete = total - complete
                notes.append(f"{ws_count:,} whitespace-only value(s) counted as empty.")
        except Exception:
            # Whitespace pass is best-effort — never fail the whole operation
            pass

    return _result(sobject, field, label, ftype,
                   total=total, complete=complete, method="soql_count",
                   notes=notes, scope=scope_str)


def _compute_picklist_with_default(sf, sobject, fmeta, base_conditions, total,
                                    _count, default_val, notes, scope_str, status_cb):
    """Picklist with a configured default — count non-null AND not-default as complete."""
    field = fmeta["name"]
    label = fmeta.get("label") or field

    if status_cb:
        status_cb("Running completion query (excluding picklist default)…")

    safe_default = default_val.replace("'", "\\'")
    try:
        complete = _count(f"{field} != null AND {field} != '{safe_default}'")
    except Exception as exc:
        return _err(sobject, field, f"SOQL count failed: {exc}",
                    field_label=label, field_type=fmeta.get("type", ""),
                    total=total, scope=scope_str, notes=notes)

    incomplete = max(0, total - complete)
    notes = notes + [f"Picklist default value `{default_val}` counted as empty."]

    return _result(sobject, field, label, fmeta.get("type", ""),
                   total=total, complete=complete, method="soql_count_with_default",
                   notes=notes, scope=scope_str)


def _compute_long_text(sf, sobject, fmeta, base_conditions, total, scope_str,
                       notes, status_cb, treat_whitespace_as_empty, sample_cap):
    """Long-text / rich-text — Salesforce can't filter these in WHERE, so
    we have to fetch and count in Python. Capped at sample_cap records."""
    field = fmeta["name"]
    ftype = (fmeta.get("type") or "").lower()
    label = fmeta.get("label") or field

    where_sql = (" WHERE " + " AND ".join(base_conditions)) if base_conditions else ""
    full_query = f"SELECT Id, {field} FROM {sobject}{where_sql}"

    if status_cb:
        status_cb("Long text field — scanning records (this may take a moment)…")

    # Cap the scan to avoid runaway queries on big objects
    capped = total > sample_cap

    fetched = 0
    empty   = 0
    try:
        result = sf.query(f"{full_query} LIMIT {sample_cap}" if capped else full_query)
        records = result.get("records", [])
        fetched += len(records)
        for r in records:
            val = r.get(field)
            if val is None or (isinstance(val, str) and
                               (val == "" or (treat_whitespace_as_empty and not val.strip()))):
                empty += 1

        # Paginate through any remaining records (only relevant when not capped)
        while not capped and not result.get("done", True) and result.get("nextRecordsUrl"):
            result = sf.query_more(result["nextRecordsUrl"], identifier_is_url=True)
            records = result.get("records", [])
            fetched += len(records)
            for r in records:
                val = r.get(field)
                if val is None or (isinstance(val, str) and
                                   (val == "" or (treat_whitespace_as_empty and not val.strip()))):
                    empty += 1
    except Exception as exc:
        return _err(sobject, field, f"Long-text scan failed: {exc}",
                    field_label=label, field_type=ftype,
                    total=total, scope=scope_str, notes=notes)

    complete   = max(0, fetched - empty)
    method     = "python_scan_capped" if capped else "python_scan"

    if capped:
        # Pro-rate to the full population so the percentage is meaningful
        # but flag the sampling clearly in `notes`.
        rate = complete / fetched if fetched > 0 else 0.0
        complete   = int(round(total * rate))
        incomplete = total - complete
        notes = notes + [
            f"Long text field — scan capped at {sample_cap:,} records "
            f"(of {total:,}); rate extrapolated."
        ]
    else:
        notes = notes + [f"Long text field — scanned all {fetched:,} records in Python."]

    return _result(sobject, field, label, ftype,
                   total=total, complete=complete, method=method,
                   notes=notes, scope=scope_str)


def _compute_compound(sf, sobject, fmeta, base_conditions, total, _count,
                      notes, scope_str, status_cb):
    """Compound (Address, Location) — count records where every component is null."""
    field = fmeta["name"]
    label = fmeta.get("label") or field
    ftype = (fmeta.get("type") or "").lower()

    # Address compound expansion: BillingAddress -> {BillingStreet, BillingCity, ...}
    address_components = []
    if ftype == "address":
        # Salesforce convention: prefix from the compound name + component suffix
        prefix = field.replace("Address", "")  # 'BillingAddress' -> 'Billing'
        for suffix in ("Street", "City", "State", "PostalCode", "Country"):
            cand = f"{prefix}{suffix}"
            address_components.append(cand)
    elif ftype == "location":
        prefix = field.rsplit("__c", 1)[0] if field.endswith("__c") else field
        address_components = [f"{prefix}__Latitude__s", f"{prefix}__Longitude__s"]
    else:
        return _err(sobject, field, f"Unrecognised compound field type: {ftype}",
                    field_label=label, field_type=ftype, total=total,
                    scope=scope_str, notes=notes)

    # Verify components actually exist on the object
    try:
        desc = getattr(sf, sobject).describe()
        valid = {f["name"] for f in desc.get("fields", [])}
        address_components = [c for c in address_components if c in valid]
    except Exception:
        pass

    if not address_components:
        return _err(sobject, field, "Could not resolve compound field components.",
                    field_label=label, field_type=ftype, total=total,
                    scope=scope_str, notes=notes)

    if status_cb:
        status_cb(f"Compound field — checking {len(address_components)} components…")

    try:
        # "Complete" = at least one component populated
        any_populated = " OR ".join(f"{c} != null" for c in address_components)
        complete = _count(f"({any_populated})")
    except Exception as exc:
        return _err(sobject, field, f"Compound completion query failed: {exc}",
                    field_label=label, field_type=ftype, total=total,
                    scope=scope_str, notes=notes)

    return _result(sobject, field, label, ftype,
                   total=total, complete=complete, method="compound_components",
                   notes=notes + [f"Counted as complete when any component "
                                  f"({', '.join(address_components)}) is populated."],
                   scope=scope_str)


def _count_whitespace(sf, sobject, field, base_conditions, sample_cap, status_cb):
    """Sample up to `sample_cap` non-null records and count whitespace-only values."""
    parts = list(base_conditions)
    parts.append(f"{field} != null")
    parts.append(f"{field} != ''")
    where_sql = " WHERE " + " AND ".join(parts)
    soql = f"SELECT Id, {field} FROM {sobject}{where_sql} LIMIT {sample_cap}"
    res = sf.query(soql)
    ws = 0
    for r in res.get("records", []):
        v = r.get(field)
        if isinstance(v, str) and not v.strip():
            ws += 1
    return ws


# ──────────────────────────────────────────────────────────────────────────────
# Result helpers
# ──────────────────────────────────────────────────────────────────────────────

def _result(sobject, field, label, ftype, *, total, complete, method, notes, scope):
    """Build a successful result dict."""
    incomplete = max(0, total - complete)
    pct = round(complete / total * 100, 2) if total > 0 else 0.0
    return {
        "object":           sobject,
        "field":            field,
        "field_label":      label,
        "field_type":       ftype,
        "total_records":    int(total),
        "complete_count":   int(complete),
        "incomplete_count": int(incomplete),
        "completion_pct":   pct,
        "method":           method,
        "notes":            notes,
        "scope_filter":     scope,
    }


def _err(sobject, field, msg, *, field_label=None, field_type=None,
         total=None, scope=None, notes=None):
    """Build an error result dict."""
    return {
        "object":           sobject,
        "field":            field,
        "field_label":      field_label or field,
        "field_type":       field_type or "",
        "total_records":    total,
        "complete_count":   None,
        "incomplete_count": None,
        "completion_pct":   None,
        "method":           "error",
        "notes":            notes or [],
        "scope_filter":     scope or "(none)",
        "error":            msg,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Strategy entrypoint (called from PYTHON_STRATEGIES registry)
# ──────────────────────────────────────────────────────────────────────────────

def run_field_completion(params: dict, sf=None, status_cb=None) -> dict:
    """
    PYTHON_STRATEGIES registry entrypoint.

    Expects params:
        sobject (str)              Salesforce object API name. Required.
        field (str)                Field API name OR human label/hint. Required.
        where_clause (str)         Optional SOQL filter (without WHERE keyword).
        treat_picklist_default_as_empty (bool, default True)
        treat_whitespace_as_empty (bool, default True)

    Returns the structured completion dict from compute_field_completion(),
    augmented with `resolved_from_hint` if fuzzy resolution was used.
    """
    if sf is None:
        # Imported here to avoid a circular import — the strategy is registered
        # in sf_query_tool.py which already owns get_sf_connection.
        from sf_query_tool import get_sf_connection
        sf = get_sf_connection()

    sobject     = (params.get("sobject") or params.get("object") or "").strip()
    field_hint  = (params.get("field") or params.get("field_api_name") or "").strip()
    where       = (params.get("where_clause") or "").strip()

    if not sobject:
        return _err("(unknown)", field_hint, "Missing 'sobject' parameter.")
    if not field_hint:
        return _err(sobject, "(unknown)", "Missing 'field' parameter.")

    # Resolve hint → API name. Skip resolution if the hint looks like an exact
    # API name we can use directly (saves a describe round-trip on hot paths).
    resolved = resolve_field_reference(sf, sobject, field_hint)
    if resolved is None:
        return _err(sobject, field_hint,
                    f"Could not find a field on {sobject} matching '{field_hint}'.")

    api_name, _fmeta = resolved
    result = compute_field_completion(
        sf, sobject, api_name,
        where_clause=where,
        treat_picklist_default_as_empty=bool(
            params.get("treat_picklist_default_as_empty", True)
        ),
        treat_whitespace_as_empty=bool(
            params.get("treat_whitespace_as_empty", True)
        ),
        status_cb=status_cb,
    )

    if api_name.lower() != field_hint.lower():
        result["resolved_from_hint"] = field_hint
    return result
