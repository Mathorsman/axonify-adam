
# ══════════════════════════════════════════════════════════════════════════════
# TERRITORY REASSIGNMENT WIZARD
# ══════════════════════════════════════════════════════════════════════════════

# ── SOP default rep/BDR alignment (used as initial defaults for the
#    editable alignment table; matched by name against active SF users) ────────
_SOP_DEFAULT_ALIGNMENT = {
    "Territory 1": {"ae": "",                "bdr": "Aman Lokhandwala"},
    "Territory 2": {"ae": "Kelly Wasden",    "bdr": "Jonathan Markle"},
    "Territory 3": {"ae": "Adam George",     "bdr": "Jonathan Markle"},
    "Territory 4": {"ae": "Jen Tolbert",     "bdr": "Lexxi Himes"},
    "Europe 1":    {"ae": "Grant McNulty",   "bdr": "Lexxi Himes"},
}

NO_CHANGE = "— No change —"
_ALIGNMENT_FILE = "territory_alignment.json"


def _load_alignment_from_disk() -> dict | None:
    """Load saved alignment from JSON file. Returns None if no file exists."""
    import json as _json
    try:
        with open(_ALIGNMENT_FILE, "r", encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def _save_alignment_to_disk(alignment: dict):
    """Persist alignment dict to JSON file."""
    import json as _json
    with open(_ALIGNMENT_FILE, "w", encoding="utf-8") as f:
        _json.dump(alignment, f, indent=2, ensure_ascii=False)


@st.cache_data(ttl=300, show_spinner=False)
def _get_active_users_for_reassign() -> list[dict]:
    """Fetch all active users for the reassignment rep pickers. Cached 5 min."""
    sf = get_sf_connection()
    res = sf.query(
        "SELECT Id, Name, Email FROM User "
        "WHERE IsActive = true ORDER BY Name LIMIT 500"
    )
    return [
        {
            "id":    r["Id"],
            "name":  r["Name"],
            "email": r.get("Email") or "",
        }
        for r in res.get("records", [])
    ]


def _build_alignment_defaults(users: list[dict]) -> dict:
    """
    Build the initial alignment table state from SOP defaults.
    Returns {territory: {"ae_label": ..., "bdr_label": ...}}.
    """
    name_to_label = {u["name"].lower(): f"{u['name']} ({u['email']})" for u in users}
    result = {}
    for terr in TERRITORY_MAP:
        sop = _SOP_DEFAULT_ALIGNMENT.get(terr, {})
        ae_name = sop.get("ae", "")
        bdr_name = sop.get("bdr", "")
        ae_label = name_to_label.get(ae_name.lower(), NO_CHANGE) if ae_name else NO_CHANGE
        bdr_label = name_to_label.get(bdr_name.lower(), NO_CHANGE) if bdr_name else NO_CHANGE
        result[terr] = {"ae_label": ae_label, "bdr_label": bdr_label}
    return result


def _is_bdr_sop_eligible(record: dict) -> bool:
    """
    Returns True if this account meets the SOP criteria for BDR assignment.

    Rule: BDR is eligible if EITHER:
      - ICP_Account__c is True (checkbox), OR
      - NumberOfEmployees >= 1000

    If neither condition is met, the account should never receive a BDR,
    even if BDR_on_Account__c is currently blank.
    """
    icp = record.get("ICP_Account__c") or False
    employees = record.get("NumberOfEmployees") or 0

    return bool(icp) or int(employees) >= 1000


def render_alignment_subtab():
    """
    Editable Rep/BDR alignment table.
    Each territory row has selectbox columns for Account Owner (AE) and
    BDR on Account, populated from active Salesforce users.
    Saved to territory_alignment.json so changes persist across sessions.
    The Reassign wizard reads from this table to pre-populate its pickers.
    """
    import pandas as pd

    st.markdown("### Rep / BDR Alignment")
    st.caption(
        "Configure which AE and BDR should be assigned per territory. "
        "These selections pre-populate the Reassign wizard and are saved "
        "automatically."
    )

    with st.spinner("Loading active users…"):
        users = _get_active_users_for_reassign()
    user_labels = [f"{u['name']} ({u['email']})" for u in users]
    options = [NO_CHANGE] + user_labels

    # Load alignment: disk file → SOP defaults as fallback
    if "territory_rep_alignment" not in st.session_state:
        disk_data = _load_alignment_from_disk()
        if disk_data:
            # Validate that saved labels still exist in active user list
            valid_options_set = set(options)
            validated = {}
            for terr in TERRITORY_MAP:
                saved = disk_data.get(terr, {})
                ae_l  = saved.get("ae_label", NO_CHANGE)
                bdr_l = saved.get("bdr_label", NO_CHANGE)
                if ae_l not in valid_options_set:
                    ae_l = NO_CHANGE
                if bdr_l not in valid_options_set:
                    bdr_l = NO_CHANGE
                validated[terr] = {"ae_label": ae_l, "bdr_label": bdr_l}
            st.session_state.territory_rep_alignment = validated
        else:
            st.session_state.territory_rep_alignment = _build_alignment_defaults(users)

    alignment = st.session_state.territory_rep_alignment

    rows = []
    for terr in TERRITORY_MAP:
        a = alignment.get(terr, {"ae_label": NO_CHANGE, "bdr_label": NO_CHANGE})
        rows.append({
            "Territory":            terr,
            "Account Owner (AE)":   a["ae_label"],
            "BDR on Account":       a["bdr_label"],
        })

    df = pd.DataFrame(rows)

    edited = st.data_editor(
        df,
        column_config={
            "Territory": st.column_config.TextColumn("Territory", disabled=True),
            "Account Owner (AE)": st.column_config.SelectboxColumn(
                "Account Owner (AE)",
                options=options,
                required=True,
            ),
            "BDR on Account": st.column_config.SelectboxColumn(
                "BDR on Account",
                options=options,
                required=True,
            ),
        },
        width="stretch",
        hide_index=True,
        key="alignment_editor",
    )

    # Persist edits to session state AND disk
    new_alignment = {}
    for _, row in edited.iterrows():
        new_alignment[row["Territory"]] = {
            "ae_label":  row["Account Owner (AE)"],
            "bdr_label": row["BDR on Account"],
        }

    # Save to disk if changed
    if new_alignment != st.session_state.territory_rep_alignment:
        _save_alignment_to_disk(new_alignment)
        st.session_state.territory_rep_alignment = new_alignment
    elif not os.path.exists(_ALIGNMENT_FILE):
        # First load with defaults — save them too
        _save_alignment_to_disk(new_alignment)

    st.session_state.territory_rep_alignment = new_alignment

    # ── Current alignment summary ────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Current Alignment Summary")
    for terr in TERRITORY_MAP:
        a = new_alignment.get(terr, {})
        ae = a.get("ae_label", NO_CHANGE)
        bdr = a.get("bdr_label", NO_CHANGE)
        colour = TERRITORY_COLOURS.get(terr, "#555")
        st.markdown(
            f'<span style="background:{colour};color:#fff;padding:2px 10px;'
            f'border-radius:12px;font-size:0.8rem;font-weight:600;">{terr}</span>'
            f'&nbsp; AE: **{ae}** &nbsp;|&nbsp; BDR: **{bdr}**',
            unsafe_allow_html=True,
        )


def render_reassign_subtab():
    """
    4-step wizard for bulk-reassigning account ownership (AE) and/or
    BDR on Account within a single territory.

    Supports two scopes:
      - "From a specific rep"  — filters by current OwnerId
      - "All accounts in territory" — targets all qualifying accounts

    Enforces SOP exclusion rules:
      - Customer / Customer Logo accounts are auto-excluded
      - Accounts in Customer Holding Account hierarchies are auto-excluded
      - Accounts owned by Axonify or inactive users are auto-included
      - Accounts owned by other active users are flagged for manual review

    Session state keys consumed:
        rz_step, rz_territory, rz_scope,
        rz_from_user_id, rz_ae_user_id, rz_bdr_user_id,
        rz_accounts_df, rz_excluded_df, rz_excluded_ids,
        rz_migrate_contacts, rz_migrate_opps, rz_result
    """
    import pandas as pd

    CLOSED_STAGES = {"Closed Won", "Closed - Won", "Closed Lost", "Closed - Lost", "Abandoned"}

    dry_run_mode = st.session_state.get("dry_run_mode", True)
    auto_backup  = st.session_state.get("auto_backup",  True)

    # ── Defaults guard ────────────────────────────────────────────────────────
    _rz_defaults = {
        "rz_step": 1, "rz_territory": "", "rz_scope": "all_accounts",
        "rz_from_user_id": "", "rz_ae_user_id": "", "rz_bdr_user_id": "",
        "rz_accounts_df": None, "rz_excluded_df": None,
        "rz_excluded_ids": set(), "rz_migrate_contacts": True,
        "rz_migrate_opps": True, "rz_result": None,
    }
    for _k, _v in _rz_defaults.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v if not isinstance(_v, set) else set()

    def _reset():
        for _k, _v in _rz_defaults.items():
            st.session_state[_k] = _v if not isinstance(_v, set) else set()
        st.rerun()

    # ── Persistent top bar ────────────────────────────────────────────────────
    _hd_col, _reset_col = st.columns([9, 1])
    with _hd_col:
        st.subheader("Territory Reassignment Wizard")
    with _reset_col:
        if st.button("↺ Reset", key="rz_reset", help="Clear all wizard state and start over"):
            _reset()

    # ── Step indicator ────────────────────────────────────────────────────────
    step = st.session_state.rz_step
    _step_labels = ["Configure", "Preview Records", "Set Scope", "Confirm & Execute"]
    _ind_cols = st.columns(4)
    for _si, (_col, _lbl) in enumerate(zip(_ind_cols, _step_labels), 1):
        with _col:
            if _si < step:
                _fg, _bg, _icon = "#34d399", "rgba(52,211,153,0.08)", "✓"
                _border = "#34d399"
            elif _si == step:
                _fg, _bg, _icon = "#7aaaff", "rgba(122,170,255,0.10)", str(_si)
                _border = "#7aaaff"
            else:
                _fg, _bg, _icon = "#4a5a6e", "transparent", str(_si)
                _border = "#2a3340"
            st.markdown(
                f'<div style="text-align:center;padding:8px 4px;border-radius:6px;'
                f'background:{_bg};border:1px solid {_border};">'
                f'<div style="font-size:1rem;font-weight:600;color:{_fg};">{_icon}</div>'
                f'<div style="font-size:0.68rem;color:{_fg};margin-top:3px;">{_lbl}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1 — CONFIGURE TERRITORY, SCOPE, AE & BDR
    # ══════════════════════════════════════════════════════════════════════════
    if step == 1:
        with st.spinner("Loading active users…"):
            users = _get_active_users_for_reassign()
        user_labels   = [f"{u['name']} ({u['email']})" for u in users]
        user_by_label = {f"{u['name']} ({u['email']})": u for u in users}

        # ── Territory selection ──────────────────────────────────────────────
        territory = st.selectbox(
            "Territory to reassign",
            list(TERRITORY_MAP.keys()),
            key="rz_territory_sel",
        )

        _terr_values = TERRITORY_MAP.get(territory, [])
        _is_europe   = (territory == "Europe 1")
        _desc_prefix = "Countries" if _is_europe else "States / Provinces"
        st.info(f"**{territory}**\n\n{_desc_prefix}: {', '.join(_terr_values)}")

        # ── Scope toggle ─────────────────────────────────────────────────────
        scope = st.radio(
            "Reassignment scope",
            ["All accounts in territory", "From a specific rep"],
            key="rz_scope_sel",
            horizontal=True,
            help=(
                "**All accounts** targets every qualifying account in the territory "
                "(with SOP exclusion rules applied). "
                "**From a specific rep** filters to accounts currently owned by one person."
            ),
        )
        _scope_key = "all_accounts" if scope == "All accounts in territory" else "specific_rep"

        # ── Outgoing rep (only for specific_rep mode) ────────────────────────
        from_label = None
        _from_user = None
        if _scope_key == "specific_rep":
            from_label = st.selectbox(
                "Outgoing rep (current owner)",
                user_labels,
                key="rz_from_sel",
            )
            _from_user = user_by_label.get(from_label)

        st.markdown("---")

        # ── AE / BDR pickers ─────────────────────────────────────────────────
        st.markdown("#### Assignment")

        # Read defaults from alignment table if available
        alignment = st.session_state.get("territory_rep_alignment", {})
        terr_align = alignment.get(territory, {})
        _default_ae_label  = terr_align.get("ae_label", NO_CHANGE)
        _default_bdr_label = terr_align.get("bdr_label", NO_CHANGE)

        ae_options  = [NO_CHANGE] + user_labels
        bdr_options = [NO_CHANGE] + user_labels

        # Find default index for AE
        _ae_idx = 0
        if _default_ae_label in ae_options:
            _ae_idx = ae_options.index(_default_ae_label)

        # Find default index for BDR
        _bdr_idx = 0
        if _default_bdr_label in bdr_options:
            _bdr_idx = bdr_options.index(_default_bdr_label)

        _col_ae, _col_bdr = st.columns(2)
        with _col_ae:
            ae_label = st.selectbox(
                "Assign Account Owner (AE)",
                ae_options,
                index=_ae_idx,
                key="rz_ae_sel",
                help="Set OwnerId on selected accounts. Choose 'No change' to skip.",
            )
        with _col_bdr:
            bdr_label = st.selectbox(
                "Assign BDR on Account",
                bdr_options,
                index=_bdr_idx,
                key="rz_bdr_sel",
                help="Set BDR_on_Account__c on selected accounts. Choose 'No change' to skip.",
            )

        _ae_user  = user_by_label.get(ae_label)  if ae_label  != NO_CHANGE else None
        _bdr_user = user_by_label.get(bdr_label) if bdr_label != NO_CHANGE else None

        _no_assignment = (_ae_user is None and _bdr_user is None)
        if _no_assignment:
            st.warning("Select at least one of AE or BDR to assign.")

        # Validation for specific_rep mode: outgoing rep shouldn't equal incoming AE
        _same_rep = False
        if _scope_key == "specific_rep" and _from_user and _ae_user:
            _same_rep = _from_user["id"] == _ae_user["id"]
            if _same_rep:
                st.warning("Outgoing rep and incoming AE cannot be the same person.")

        if st.button(
            "Next: Preview Records →",
            type="primary",
            key="rz_next_1",
            disabled=(_no_assignment or _same_rep),
        ):
            st.session_state.rz_territory    = territory
            st.session_state.rz_scope        = _scope_key
            st.session_state.rz_from_user_id = _from_user["id"] if _from_user else ""
            st.session_state.rz_ae_user_id   = _ae_user["id"]   if _ae_user   else ""
            st.session_state.rz_bdr_user_id  = _bdr_user["id"]  if _bdr_user  else ""
            st.session_state.rz_accounts_df  = None
            st.session_state.rz_excluded_df  = None
            st.session_state.rz_step         = 2
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2 — PREVIEW AFFECTED RECORDS (with exclusion rules)
    # ══════════════════════════════════════════════════════════════════════════
    elif step == 2:
        territory    = st.session_state.rz_territory
        scope        = st.session_state.rz_scope
        from_user_id = st.session_state.rz_from_user_id
        ae_user_id   = st.session_state.rz_ae_user_id
        bdr_user_id  = st.session_state.rz_bdr_user_id

        with st.spinner("Loading users…"):
            _all_users  = _get_active_users_for_reassign()
        _user_by_id = {u["id"]: u for u in _all_users}

        # Build the banner description
        _parts = [f"📍 <b>{territory}</b>"]
        if scope == "specific_rep":
            from_name = _user_by_id.get(from_user_id, {}).get("name", from_user_id)
            _parts.append(f"From: <b>{from_name}</b>")
        else:
            _parts.append("Scope: <b>All accounts</b>")
        if ae_user_id:
            ae_name = _user_by_id.get(ae_user_id, {}).get("name", ae_user_id)
            _parts.append(f"AE → <b>{ae_name}</b>")
        if bdr_user_id:
            bdr_name = _user_by_id.get(bdr_user_id, {}).get("name", bdr_user_id)
            _parts.append(f"BDR → <b>{bdr_name}</b>")

        st.markdown(
            f'<div class="safety-banner" style="'
            f'background:rgba(30,50,90,0.4);border-color:#2a4a7f;color:var(--text-secondary);">'
            f'{" &nbsp;|&nbsp; ".join(_parts)}</div>',
            unsafe_allow_html=True,
        )

        # ── Load accounts once, cache in session state ────────────────────────
        if st.session_state.rz_accounts_df is None:
            sf          = get_sf_connection()
            _is_europe  = (territory == "Europe 1")
            _values     = TERRITORY_MAP[territory]
            _vals_clause = ", ".join(f"'{v}'" for v in _values)

            # Build location filter and per-level field aliases for EU vs NA
            if _is_europe:
                _loc_filter  = f"BillingCountry IN ({_vals_clause})"
                _state_field = "BillingCountry"
                _loc_col     = "BillingCountry"
                _par_col     = "Parent.BillingCountry"
                _pp_col      = "Parent.Parent.BillingCountry"
                _ppp_col     = "Parent.Parent.Parent.BillingCountry"
            else:
                _loc_filter  = f"BillingState IN ({_vals_clause})"
                _state_field = "BillingState"
                _loc_col     = "BillingState"
                _par_col     = "Parent.BillingState"
                _pp_col      = "Parent.Parent.BillingState"
                _ppp_col     = "Parent.Parent.Parent.BillingState"

            _owner_filter = ""
            if scope == "specific_rep" and from_user_id:
                _owner_filter = f"AND OwnerId = '{from_user_id}' "

            # Common SELECT for all passes — parent billing fields included so
            # the Customer Holding Account exclusion check works for all records
            _select_fields = (
                "Id, Name, BillingState, BillingCountry, Type, "
                "Owner.Name, Owner.IsActive, BDR_on_Account__c, "
                "ICP_Account__c, NumberOfEmployees, "
                "Parent.Name, Parent.BillingState, Parent.BillingCountry, Parent.Type, "
                "Parent.Parent.Type, Parent.Parent.BillingState, Parent.Parent.BillingCountry, "
                "Parent.Parent.Parent.Type, Parent.Parent.Parent.BillingState, "
                "Parent.Parent.Parent.BillingCountry"
            )

            # ── Pass 1: accounts whose own billing location is in territory ──
            with st.spinner("Querying Salesforce (pass 1 of 2: direct billing match)…"):
                _acct_soql = (
                    f"SELECT {_select_fields} "
                    f"FROM Account "
                    f"WHERE IsDeleted = false "
                    f"AND {_loc_filter} "
                    f"{_owner_filter}"
                    f"AND Type != 'Customer' "
                    f"AND Type != 'Customer Logo' "
                    f"ORDER BY Name"
                )
                _pass1_records = sf.query_all(_acct_soql).get("records", [])
                for r in _pass1_records:
                    r["_match_source"] = "direct"

            # ── Pass 2: accounts whose ancestor billing location is in ────────
            # territory but whose own billing location is NOT
            with st.spinner("Querying Salesforce (pass 2 of 2: parent hierarchy match)…"):
                # SOQL NULL safety: "col NOT IN (...)" evaluates to FALSE
                # (not TRUE) when col is NULL.  We must explicitly OR the
                # null case so accounts with a blank billing field are still
                # considered "not in territory" and therefore eligible for
                # the parent-hierarchy match.
                _not_own    = f"({_loc_col} NOT IN ({_vals_clause}) OR {_loc_col} = null)"
                _par_not_in = f"({_par_col} NOT IN ({_vals_clause}) OR {_par_col} = null)"
                _pp_not_in  = f"({_pp_col}  NOT IN ({_vals_clause}) OR {_pp_col}  = null)"

                # Level 1 — direct parent's billing location in territory
                _p1_records = sf.query_all(
                    f"SELECT {_select_fields} FROM Account "
                    f"WHERE IsDeleted = false "
                    f"AND {_par_col} IN ({_vals_clause}) "
                    f"AND {_not_own} "
                    f"{_owner_filter}"
                    f"AND Type != 'Customer' "
                    f"AND Type != 'Customer Logo' "
                    f"ORDER BY Name"
                ).get("records", [])

                # Level 2 — grandparent's billing location in territory
                _p2_records = sf.query_all(
                    f"SELECT {_select_fields} FROM Account "
                    f"WHERE IsDeleted = false "
                    f"AND {_pp_col} IN ({_vals_clause}) "
                    f"AND {_par_not_in} "
                    f"AND {_not_own} "
                    f"{_owner_filter}"
                    f"AND Type != 'Customer' "
                    f"AND Type != 'Customer Logo' "
                    f"ORDER BY Name"
                ).get("records", [])

                # Level 3 — great-grandparent's billing location in territory
                _p3_records = sf.query_all(
                    f"SELECT {_select_fields} FROM Account "
                    f"WHERE IsDeleted = false "
                    f"AND {_ppp_col} IN ({_vals_clause}) "
                    f"AND {_pp_not_in} "
                    f"AND {_par_not_in} "
                    f"AND {_not_own} "
                    f"{_owner_filter}"
                    f"AND Type != 'Customer' "
                    f"AND Type != 'Customer Logo' "
                    f"ORDER BY Name"
                ).get("records", [])

                _pass2_records = _p1_records + _p2_records + _p3_records
                for r in _pass2_records:
                    r["_match_source"] = "parent_hierarchy"

            # ── Merge and deduplicate (Pass 1 takes precedence) ───────────────
            _seen_ids = set()
            _acct_records = []
            for r in (_pass1_records + _pass2_records):
                if r["Id"] not in _seen_ids:
                    _seen_ids.add(r["Id"])
                    _acct_records.append(r)

            if not _acct_records:
                _msg = f"No qualifying accounts found in **{territory}**."
                if scope == "specific_rep":
                    _fn = _user_by_id.get(from_user_id, {}).get("name", from_user_id)
                    _msg = (
                        f"No qualifying accounts found for **{_fn}** in **{territory}**. "
                        "They may not own any accounts in this territory, or all their "
                        "accounts are excluded (Customer / Customer Logo)."
                    )
                st.info(_msg)
                if st.button("← Back", key="rz_back_2_empty"):
                    st.session_state.rz_step = 1
                    st.rerun()
                return

            # ── Pre-check: accounts with open opps owned by active users ─────
            # These accounts are excluded from reassignment.
            _all_acct_ids = [r["Id"] for r in _acct_records]
            _CHUNK = 200
            _stage_not_in = ", ".join(f"'{s}'" for s in CLOSED_STAGES)

            # { account_id: [opp_owner_name, ...] }
            _active_opp_owners: dict[str, list[str]] = {}
            for _ci in range(0, len(_all_acct_ids), _CHUNK):
                _chunk_ids = _all_acct_ids[_ci : _ci + _CHUNK]
                _ids_str   = ", ".join(f"'{x}'" for x in _chunk_ids)
                _aoo_res = sf.query_all(
                    f"SELECT AccountId, Owner.Name FROM Opportunity "
                    f"WHERE AccountId IN ({_ids_str}) "
                    f"AND StageName NOT IN ({_stage_not_in}) "
                    f"AND IsDeleted = false "
                    f"AND Owner.IsActive = true"
                )
                for _r in _aoo_res.get("records", []):
                    _aid = _r["AccountId"]
                    _oname = (_r.get("Owner") or {}).get("Name", "Unknown")
                    _active_opp_owners.setdefault(_aid, []).append(_oname)

            # ── Classify each record by exclusion rules ───────────────────────
            _includable = []     # records that go into the editable grid
            _excluded   = []     # records excluded by SOP rules

            # Build set of active user IDs for BDR eligibility check
            _active_user_ids = {u["id"] for u in _all_users}

            for r in _acct_records:
                _owner_dict  = r.get("Owner") or {}
                if isinstance(_owner_dict, dict):
                    _owner_name  = _owner_dict.get("Name", "")
                    _owner_active = _owner_dict.get("IsActive", True)
                else:
                    _owner_name  = ""
                    _owner_active = True

                _acct_type = r.get("Type") or ""

                # Exclusion: Customer / Customer Logo already filtered in
                # SOQL, but double-check
                if _acct_type in ("Customer", "Customer Logo"):
                    _excluded.append({
                        "Id":           r["Id"],
                        "Account Name": r["Name"],
                        "State":        r.get(_state_field) or "",
                        "Type":         _acct_type,
                        "Owner":        _owner_name,
                        "Reason":       f"Type = {_acct_type}",
                    })
                    continue

                # Exclusion: Customer Holding Account in the hierarchy.
                # For direct-billing matches: exclude if the account itself
                # OR any ancestor up to 3 levels is a CHA.
                # For parent-hierarchy matches: only exclude if the account
                # itself is a CHA.  The parent's location is the qualifying
                # signal for these accounts, so a CHA parent does NOT
                # disqualify the subsidiary (that is precisely why it was
                # surfaced via the hierarchy pass).
                _CHA = "Customer Holding Account"
                _is_parent_hier_match = r.get("_match_source") == "parent_hierarchy"

                if _is_parent_hier_match:
                    _cha_types_to_check = [_acct_type]
                else:
                    _cha_types_to_check = [
                        _acct_type,
                        (r.get("Parent") or {}).get("Type", "")
                        if isinstance(r.get("Parent"), dict) else "",
                    ]
                    # Parent.Parent
                    _pp = r.get("Parent") or {}
                    if isinstance(_pp, dict):
                        _pp2 = _pp.get("Parent") or {}
                        if isinstance(_pp2, dict):
                            _cha_types_to_check.append(_pp2.get("Type", "") or "")
                            # Parent.Parent.Parent
                            _pp3 = _pp2.get("Parent") or {}
                            if isinstance(_pp3, dict):
                                _cha_types_to_check.append(_pp3.get("Type", "") or "")

                if any(pt == _CHA for pt in _cha_types_to_check):
                    _excluded.append({
                        "Id":           r["Id"],
                        "Account Name": r["Name"],
                        "State":        r.get(_state_field) or "",
                        "Type":         _acct_type,
                        "Owner":        _owner_name,
                        "Reason":       "Type = Customer Holding Account",
                    })
                    continue

                # Exclusion: account has open opportunities owned by
                # active users — should not be reassigned
                _opp_owners = _active_opp_owners.get(r["Id"])
                if _opp_owners:
                    _unique_owners = sorted(set(_opp_owners))
                    _owners_str = ", ".join(_unique_owners[:3])
                    if len(_unique_owners) > 3:
                        _owners_str += f" (+{len(_unique_owners) - 3} more)"
                    _excluded.append({
                        "Id":           r["Id"],
                        "Account Name": r["Name"],
                        "State":        r.get(_state_field) or "",
                        "Type":         _acct_type,
                        "Owner":        _owner_name,
                        "Reason":       f"Open opps owned by active user(s): {_owners_str}",
                    })
                    continue

                # Determine auto-include vs manual review
                _is_axonify_owned = _owner_name.lower().strip() == "axonify"
                _is_inactive_owned = not _owner_active

                if _is_axonify_owned:
                    _status = "Auto-include (Axonify-owned)"
                    _include = True
                elif _is_inactive_owned:
                    _status = "Auto-include (inactive owner)"
                    _include = True
                else:
                    _status = f"Review (active owner: {_owner_name})"
                    _include = False

                # BDR eligibility — two-stage check:
                #   Stage 1: Does this account meet SOP criteria (ICP or size)?
                #   Stage 2: Is the BDR field currently empty or inactive?
                # Both stages must pass for the BDR assignment to apply.

                _sop_eligible = _is_bdr_sop_eligible(r)

                if not _sop_eligible:
                    # Account does not meet ICP or employee threshold — never assign a BDR
                    _bdr_eligible = False
                    _bdr_status   = "Skipped (SOP: low ICP & <1k employees)"
                else:
                    # Account meets SOP — now check whether the field is already occupied
                    _current_bdr = r.get("BDR_on_Account__c") or ""
                    if not _current_bdr:
                        _bdr_eligible = True
                        _bdr_status   = "Eligible (empty)"
                    elif _current_bdr not in _active_user_ids:
                        _bdr_eligible = True
                        _bdr_status   = "Eligible (inactive BDR)"
                    else:
                        _bdr_eligible = False
                        _bdr_name_match = _user_by_id.get(_current_bdr, {}).get("name", _current_bdr)
                        _bdr_status   = f"Skipped (active: {_bdr_name_match})"

                _match_label = (
                    "Own address"
                    if r.get("_match_source") == "direct"
                    else "Via parent hierarchy"
                )

                _includable.append({
                    "Include":      _include,
                    "Id":           r["Id"],
                    "Account Name": r["Name"],
                    "State":        r.get(_state_field) or "",
                    "Type":         _acct_type,
                    "Owner":        _owner_name,
                    "Status":       _status,
                    "Match":        _match_label,
                    "BDR Eligible": _bdr_eligible,
                    "BDR Status":   _bdr_status,
                })

            # ── Batch contact & opp counts for includable records ─────────────
            _incl_ids = [row["Id"] for row in _includable]
            _CHUNK    = 200

            _contact_counts: dict = {}
            for _ci in range(0, len(_incl_ids), _CHUNK):
                _chunk_ids = _incl_ids[_ci : _ci + _CHUNK]
                _ids_str   = ", ".join(f"'{x}'" for x in _chunk_ids)
                _cres = sf.query_all(
                    f"SELECT AccountId, COUNT(Id) cnt FROM Contact "
                    f"WHERE AccountId IN ({_ids_str}) AND IsDeleted = false "
                    f"GROUP BY AccountId"
                )
                for _r in _cres.get("records", []):
                    _contact_counts[_r["AccountId"]] = _r["cnt"]

            _opp_counts: dict = {}
            _stage_not_in = ", ".join(f"'{s}'" for s in CLOSED_STAGES)
            for _ci in range(0, len(_incl_ids), _CHUNK):
                _chunk_ids = _incl_ids[_ci : _ci + _CHUNK]
                _ids_str   = ", ".join(f"'{x}'" for x in _chunk_ids)
                _ores = sf.query_all(
                    f"SELECT AccountId, COUNT(Id) cnt FROM Opportunity "
                    f"WHERE AccountId IN ({_ids_str}) "
                    f"AND StageName NOT IN ({_stage_not_in}) "
                    f"AND IsDeleted = false GROUP BY AccountId"
                )
                for _r in _ores.get("records", []):
                    _opp_counts[_r["AccountId"]] = _r["cnt"]

            for row in _includable:
                row["Contacts"]  = _contact_counts.get(row["Id"], 0)
                row["Open Opps"] = _opp_counts.get(row["Id"], 0)

            st.session_state.rz_accounts_df = pd.DataFrame(_includable) if _includable else pd.DataFrame()
            st.session_state.rz_excluded_df = pd.DataFrame(_excluded) if _excluded else pd.DataFrame()

        # ── Summary banner ───────────────────────────────────────────────────
        _df          = st.session_state.rz_accounts_df
        _excluded_df = st.session_state.rz_excluded_df

        if _df is not None and not _df.empty:
            _n_auto    = len(_df[_df["Status"].str.startswith("Auto-include")]) if "Status" in _df.columns else 0
            _n_review  = len(_df[_df["Status"].str.startswith("Review")]) if "Status" in _df.columns else 0
        else:
            _n_auto = _n_review = 0
        _n_excluded = len(_excluded_df) if _excluded_df is not None and not _excluded_df.empty else 0

        _banner_parts = [
            f'✅ <b>{_n_auto:,}</b> auto-included',
            f'👁 <b>{_n_review:,}</b> flagged for manual review',
            f'🚫 <b>{_n_excluded:,}</b> excluded (Customer / Customer Holding)',
        ]

        # BDR eligibility counts (when BDR assignment is selected)
        if bdr_user_id and _df is not None and not _df.empty and "BDR Eligible" in _df.columns:
            _n_bdr_eligible = int(_df["BDR Eligible"].sum())
            _n_bdr_skipped  = len(_df) - _n_bdr_eligible
            _banner_parts.append(
                f'📝 <b>{_n_bdr_eligible:,}</b> BDR-eligible · '
                f'<b>{_n_bdr_skipped:,}</b> BDR skipped (active BDR)'
            )

        st.markdown(
            f'<div style="padding:8px 14px;background:rgba(20,40,70,0.3);'
            f'border-radius:6px;margin-bottom:12px;font-size:0.85rem;">'
            f'{" &nbsp;|&nbsp; ".join(_banner_parts)}</div>',
            unsafe_allow_html=True,
        )

        if _df is None or _df.empty:
            st.info("No qualifying accounts to display after applying exclusion rules.")
            if st.button("← Back", key="rz_back_2_empty2"):
                st.session_state.rz_step = 1
                st.rerun()
            return

        # ── Parent-hierarchy informational banner ──────────────────────────────
        if "Match" in _df.columns:
            _n_parent_hier = int((_df["Match"] == "Via parent hierarchy").sum())
            if _n_parent_hier > 0:
                territory = st.session_state.rz_territory
                st.info(
                    f"ℹ️  {_n_parent_hier:,} account(s) included via parent hierarchy — "
                    f"their own billing address is in a different territory, but their "
                    f"ultimate parent is in **{territory}**. These are marked "
                    f'"Via parent hierarchy" in the Match column.'
                )

        # ── Editable grid ─────────────────────────────────────────────────────
        _col_config = {
            "Include":      st.column_config.CheckboxColumn("Include", default=True),
            "Id":           st.column_config.TextColumn("Id",           disabled=True),
            "Account Name": st.column_config.TextColumn("Account Name", disabled=True),
            "State":        st.column_config.TextColumn("State",        disabled=True),
            "Type":         st.column_config.TextColumn("Type",         disabled=True),
            "Owner":        st.column_config.TextColumn("Owner",        disabled=True),
            "Status":       st.column_config.TextColumn("Status",       disabled=True),
            "Match":        st.column_config.TextColumn("Match",        disabled=True),
            "Contacts":     st.column_config.NumberColumn("Contacts",   disabled=True),
            "Open Opps":    st.column_config.NumberColumn("Open Opps",  disabled=True),
            "BDR Eligible": None,  # hide boolean column from grid
        }

        # Show BDR Status column only when BDR assignment is selected
        if bdr_user_id:
            _col_config["BDR Status"] = st.column_config.TextColumn("BDR Status", disabled=True)
        else:
            _col_config["BDR Status"] = None  # hide when not relevant

        _edited = st.data_editor(
            _df,
            column_config=_col_config,
            width="stretch",
            hide_index=True,
            key="rz_accounts_editor",
        )

        _selected    = _edited[_edited["Include"] == True]
        _excl_count  = len(_edited) - len(_selected)
        _total_conts = int(_selected["Contacts"].sum()) if not _selected.empty else 0
        _total_opps  = int(_selected["Open Opps"].sum()) if not _selected.empty else 0

        st.caption(
            f"{len(_selected):,} accounts selected · "
            f"{_total_conts:,} contacts · "
            f"{_total_opps:,} open opportunities · "
            f"{_excl_count:,} unchecked"
        )

        # ── Show excluded records in collapsible ──────────────────────────────
        if _excluded_df is not None and not _excluded_df.empty:
            with st.expander(f"🚫 Excluded records ({len(_excluded_df):,})", expanded=False):
                st.caption(
                    "These accounts were automatically excluded per SOP rules "
                    "(Customer/Customer Logo type or Customer Holding Account hierarchy). "
                    "They will not be reassigned."
                )
                st.dataframe(_excluded_df, width="stretch", hide_index=True)

        _b_col, _r_col, _n_col = st.columns([1, 1, 4])
        with _b_col:
            if st.button("← Back", key="rz_back_2"):
                st.session_state.rz_step = 1
                st.rerun()
        with _r_col:
            if st.button("🔄 Refresh", key="rz_refresh_2", help="Re-query Salesforce and rebuild the candidate list"):
                st.session_state.rz_accounts_df = None
                st.session_state.rz_excluded_df = None
                st.rerun()
        with _n_col:
            if st.button(
                "Next: Set Scope →",
                type="primary",
                key="rz_next_2",
                disabled=(len(_selected) == 0),
            ):
                st.session_state.rz_accounts_df  = _edited
                st.session_state.rz_excluded_ids = set(
                    _edited[_edited["Include"] == False]["Id"].tolist()
                )
                st.session_state.rz_step = 3
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 3 — SET MIGRATION SCOPE
    # ══════════════════════════════════════════════════════════════════════════
    elif step == 3:
        territory    = st.session_state.rz_territory
        ae_user_id   = st.session_state.rz_ae_user_id
        bdr_user_id  = st.session_state.rz_bdr_user_id

        with st.spinner("Loading users…"):
            _all_users  = _get_active_users_for_reassign()
        _user_by_id = {u["id"]: u for u in _all_users}
        ae_name  = _user_by_id.get(ae_user_id, {}).get("name", "No change") if ae_user_id else "No change"
        bdr_name = _user_by_id.get(bdr_user_id, {}).get("name", "No change") if bdr_user_id else "No change"

        _df       = st.session_state.rz_accounts_df
        _selected = _df[_df["Include"] == True]
        _n_accts  = len(_selected)
        _n_conts  = int(_selected["Contacts"].sum()) if not _selected.empty else 0
        _n_opps   = int(_selected["Open Opps"].sum()) if not _selected.empty else 0

        # BDR eligibility counts
        _n_bdr_eligible = 0
        _n_bdr_skipped  = 0
        if bdr_user_id and "BDR Eligible" in _selected.columns:
            _n_bdr_eligible = int(_selected["BDR Eligible"].sum())
            _n_bdr_skipped  = _n_accts - _n_bdr_eligible

        # AE banner
        if ae_user_id:
            st.markdown(
                f'<div class="safety-banner" style="'
                f'background:rgba(30,50,90,0.4);border-color:#2a4a7f;color:var(--text-secondary);">'
                f'🏢 <b>Account Owner (AE)</b> — <b>{_n_accts:,}</b> accounts · '
                f'OwnerId → <b>{ae_name}</b></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="safety-banner" style="'
                f'background:rgba(50,50,50,0.3);border-color:#444;color:var(--text-secondary);">'
                f'🏢 <b>Account Owner (AE)</b> — <i>No change</i></div>',
                unsafe_allow_html=True,
            )

        # BDR banner
        if bdr_user_id:
            st.markdown(
                f'<div class="safety-banner" style="'
                f'background:rgba(30,70,50,0.4);border-color:#2a7f4a;color:var(--text-secondary);">'
                f'👤 <b>BDR on Account</b> — <b>{_n_bdr_eligible:,}</b> of '
                f'{_n_accts:,} eligible · BDR_on_Account__c → <b>{bdr_name}</b>'
                f'{"" if _n_bdr_skipped == 0 else f" · <i>{_n_bdr_skipped:,} skipped (active BDR already set)</i>"}'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="safety-banner" style="'
                f'background:rgba(50,50,50,0.3);border-color:#444;color:var(--text-secondary);">'
                f'👤 <b>BDR on Account</b> — <i>No change</i></div>',
                unsafe_allow_html=True,
            )

        # Contact/Opp migration toggles — only relevant when AE is changing
        migrate_contacts = False
        migrate_opps     = False
        if ae_user_id:
            migrate_contacts = st.toggle(
                f"Migrate Contacts ({_n_conts:,} contacts at selected accounts)",
                value=st.session_state.rz_migrate_contacts,
                key="rz_contacts_toggle",
                help="Contacts keep their current owner when OFF",
            )
            migrate_opps = st.toggle(
                f"Migrate open Opportunities ({_n_opps:,} open opps at selected accounts)",
                value=st.session_state.rz_migrate_opps,
                key="rz_opps_toggle",
                help="Closed Won/Lost opportunities are NEVER touched regardless of this setting",
            )
        else:
            st.caption("ℹ️ Contact and Opportunity migration is only available when changing Account Owner (AE).")

        _b_col, _n_col = st.columns([1, 5])
        with _b_col:
            if st.button("← Back", key="rz_back_3"):
                st.session_state.rz_step = 2
                st.rerun()
        with _n_col:
            if st.button("Next: Review & Confirm →", type="primary", key="rz_next_3"):
                st.session_state.rz_migrate_contacts = migrate_contacts
                st.session_state.rz_migrate_opps     = migrate_opps
                st.session_state.rz_result           = None
                st.session_state.rz_step             = 4
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 4 — CONFIRM & EXECUTE
    # ══════════════════════════════════════════════════════════════════════════
    elif step == 4:
        territory        = st.session_state.rz_territory
        ae_user_id       = st.session_state.rz_ae_user_id
        bdr_user_id      = st.session_state.rz_bdr_user_id
        migrate_contacts = st.session_state.rz_migrate_contacts
        migrate_opps     = st.session_state.rz_migrate_opps
        _df              = st.session_state.rz_accounts_df
        _selected        = _df[_df["Include"] == True]
        _n_accts         = len(_selected)
        _n_conts         = int(_selected["Contacts"].sum()) if not _selected.empty else 0
        _n_opps          = int(_selected["Open Opps"].sum()) if not _selected.empty else 0
        _account_ids     = _selected["Id"].tolist()

        # BDR-eligible subset: only accounts where current BDR is null or inactive
        _bdr_eligible_ids = set()
        if bdr_user_id and "BDR Eligible" in _selected.columns:
            _bdr_eligible_ids = set(
                _selected[_selected["BDR Eligible"] == True]["Id"].tolist()
            )
        _n_bdr_eligible = len(_bdr_eligible_ids)
        _n_bdr_skipped  = _n_accts - _n_bdr_eligible if bdr_user_id else 0

        # ── One-shot override: "Go Live" from dry-run results ─────────────────
        _force_live = st.session_state.pop("rz_force_live", False)
        if _force_live:
            dry_run_mode = False

        with st.spinner("Loading users…"):
            _all_users  = _get_active_users_for_reassign()
        _user_by_id = {u["id"]: u for u in _all_users}
        ae_name  = _user_by_id.get(ae_user_id, {}).get("name", "No change") if ae_user_id else "No change"
        bdr_name = _user_by_id.get(bdr_user_id, {}).get("name", "No change") if bdr_user_id else "No change"

        # ── Show results if execution already ran ─────────────────────────────
        if st.session_state.rz_result is not None and not _force_live:
            _res = st.session_state.rz_result
            if _res.get("dry_run"):
                # ── Dry-run results: offer Go Live path ───────────────────────
                st.info(
                    "**Dry Run** — no records were changed. "
                    "Review the preview below, then execute for real."
                )
                for _obj, _r in _res.get("objects", {}).items():
                    if _r["failed"] > 0:
                        st.warning(
                            f"⚠️ {_obj}: {_r['success']:,} would succeed, "
                            f"{_r['failed']:,} would fail"
                        )
                        for _err in _r["errors"][:10]:
                            st.caption(f"  • {_err}")
                    else:
                        st.markdown(
                            f"🔍 **{_obj}**: {_r['success']:,} records would be updated"
                        )
                st.divider()
                _go_live_confirmed = st.checkbox(
                    "I have reviewed the dry-run results and want to execute on live data.",
                    key="rz_go_live_confirm",
                )
                _gl_col, _reset_col = st.columns([1, 1])
                with _gl_col:
                    if st.button(
                        "⚡ Execute for Real",
                        type="primary",
                        key="rz_go_live_btn",
                        disabled=(not _go_live_confirmed),
                    ):
                        st.session_state.rz_result     = None
                        st.session_state.rz_force_live = True
                        st.rerun()
                with _reset_col:
                    if st.button("↺ Start a new reassignment", key="rz_done_dry"):
                        _reset()
                return
            else:
                # ── Live execution results ────────────────────────────────────
                st.success(
                    f"✅ Reassignment complete · {territory}"
                )
                for _obj, _r in _res.get("objects", {}).items():
                    if _r["failed"] > 0:
                        st.warning(
                            f"⚠️ {_obj}: {_r['success']:,} succeeded, "
                            f"{_r['failed']:,} failed"
                        )
                        for _err in _r["errors"][:10]:
                            st.caption(f"  • {_err}")
                    else:
                        st.markdown(
                            f"📋 **{_obj}**: {_r['success']:,} records updated"
                        )
                if st.button("↺ Start a new reassignment", key="rz_done"):
                    _reset()
                return

        # ── Summary table ─────────────────────────────────────────────────────
        _summary_rows = []

        if ae_user_id:
            _summary_rows.append({
                "Object":  "Account (Owner)",
                "Records": _n_accts,
                "Field":   "OwnerId",
                "New Value": ae_name,
                "Action":  "✅ Will update",
            })
        if bdr_user_id:
            _bdr_action = f"✅ Will update ({_n_bdr_skipped:,} skipped — active BDR)" if _n_bdr_skipped else "✅ Will update"
            _summary_rows.append({
                "Object":  "Account (BDR)",
                "Records": _n_bdr_eligible,
                "Field":   "BDR_on_Account__c",
                "New Value": bdr_name,
                "Action":  _bdr_action,
            })
        if ae_user_id:
            _summary_rows.append({
                "Object":  "Contact",
                "Records": _n_conts,
                "Field":   "OwnerId",
                "New Value": ae_name if migrate_contacts else "—",
                "Action":  "✅ Will migrate" if migrate_contacts else "⊘ Skipped",
            })
            _summary_rows.append({
                "Object":  "Opportunity (open only)",
                "Records": _n_opps,
                "Field":   "OwnerId",
                "New Value": ae_name if migrate_opps else "—",
                "Action":  "✅ Will migrate" if migrate_opps else "⊘ Skipped",
            })

        st.dataframe(pd.DataFrame(_summary_rows), width="stretch", hide_index=True)

        _fields_changing = []
        if ae_user_id:
            _fields_changing.append("OwnerId")
        if bdr_user_id:
            _fields_changing.append("BDR_on_Account__c")

        # ── "Go Live" path: skip confirmation, execute immediately ────────────
        _should_execute = False
        if _force_live:
            st.info("🔄 Executing live reassignment from dry-run preview…")
            _should_execute = True
        else:
            st.error(
                f"⚠️ This operation updates **{', '.join(_fields_changing)}** in bulk "
                f"on live Salesforce records. "
                "It cannot be automatically reversed. Verify the summary above before proceeding."
            )

            _confirmed = st.checkbox(
                "I have reviewed the summary and want to proceed.",
                key="rz_confirm_chk",
            )
            _btn_label = (
                "🔍 Preview (Dry Run)" if dry_run_mode
                else "⚡ Execute Reassignment"
            )

            _b_col, _exec_col = st.columns([1, 4])
            with _b_col:
                if st.button("← Back", key="rz_back_4"):
                    st.session_state.rz_step = 3
                    st.rerun()
            with _exec_col:
                if st.button(
                    _btn_label,
                    type="primary",
                    key="rz_execute",
                    disabled=(not _confirmed),
                ):
                    _should_execute = True

        if _should_execute:
            _result_objects: dict = {}
            _CHUNK = 200

            # ── Determine total phases for progress tracking ───────────
            _total_phases = 1  # Account update is always phase 1
            if ae_user_id and migrate_contacts:
                _total_phases += 1
            if ae_user_id and migrate_opps:
                _total_phases += 1
            _phase = 0

            _progress_bar = st.progress(0, text="Preparing…")

            with st.status("Running reassignment…", expanded=True) as _status:
                sf = get_sf_connection()

                # ── 1. Account updates (AE + BDR) ─────────────────────────
                # BDR is only set on accounts where the current BDR is
                # null or belongs to an inactive user.
                _phase += 1
                _progress_bar.progress(
                    (_phase - 1) / _total_phases,
                    text=f"Phase {_phase}/{_total_phases} — Updating accounts…",
                )
                st.write(f"⏳ **Phase {_phase}/{_total_phases}** — Updating {len(_account_ids):,} accounts…")

                _acct_payload = []
                for _aid in _account_ids:
                    _rec = {"Id": _aid}
                    if ae_user_id:
                        _rec["OwnerId"] = ae_user_id
                    if bdr_user_id and _aid in _bdr_eligible_ids:
                        _rec["BDR_on_Account__c"] = bdr_user_id
                    # Only include if there's something to update
                    if len(_rec) > 1:
                        _acct_payload.append(_rec)

                if not dry_run_mode:
                    if auto_backup:
                        _backup_cols = [c for c in ["Id", "Account Name", "State", "Type", "Owner"] if c in _selected.columns]
                        backup_records(
                            _selected[_backup_cols].copy(),
                            "Reassign_Account",
                            "Account",
                        )
                    _acct_result = execute_update(sf, "Account", _acct_payload)
                else:
                    _acct_result = {
                        "success": len(_acct_payload), "failed": 0, "errors": [],
                    }
                _acct_label = "Account"
                if ae_user_id and bdr_user_id:
                    _acct_label = "Account (Owner + BDR)"
                elif ae_user_id:
                    _acct_label = "Account (Owner)"
                elif bdr_user_id:
                    _acct_label = "Account (BDR)"
                _result_objects[_acct_label] = _acct_result
                st.write(f"✅ Accounts — {_acct_result['success']:,} succeeded, {_acct_result['failed']:,} failed")

                # ── 2. Contacts (only if AE is changing) ──────────────────
                if ae_user_id and migrate_contacts:
                    _phase += 1
                    _progress_bar.progress(
                        (_phase - 1) / _total_phases,
                        text=f"Phase {_phase}/{_total_phases} — Migrating contacts…",
                    )
                    st.write(f"⏳ **Phase {_phase}/{_total_phases}** — Querying & migrating contacts…")

                    _cont_ids = []
                    for _ci in range(0, len(_account_ids), _CHUNK):
                        _chunk   = _account_ids[_ci : _ci + _CHUNK]
                        _ids_str = ", ".join(f"'{x}'" for x in _chunk)
                        _cres    = sf.query_all(
                            f"SELECT Id FROM Contact "
                            f"WHERE AccountId IN ({_ids_str}) "
                            f"AND IsDeleted = false"
                        )
                        _cont_ids.extend(r["Id"] for r in _cres.get("records", []))

                    _cont_payload = [
                        {"Id": _cid, "OwnerId": ae_user_id}
                        for _cid in _cont_ids
                    ]
                    if _cont_payload and not dry_run_mode:
                        st.write(f"   Updating {len(_cont_payload):,} contacts…")
                        _cont_result = execute_update(sf, "Contact", _cont_payload)
                    else:
                        _cont_result = {
                            "success": len(_cont_payload), "failed": 0, "errors": [],
                        }
                    _result_objects["Contact"] = _cont_result
                    st.write(f"✅ Contacts — {_cont_result['success']:,} succeeded, {_cont_result['failed']:,} failed")

                # ── 3. Open Opportunities (only if AE is changing) ────────
                if ae_user_id and migrate_opps:
                    _phase += 1
                    _progress_bar.progress(
                        (_phase - 1) / _total_phases,
                        text=f"Phase {_phase}/{_total_phases} — Migrating opportunities…",
                    )
                    st.write(f"⏳ **Phase {_phase}/{_total_phases}** — Querying & migrating open opportunities…")

                    _stage_not_in = ", ".join(f"'{s}'" for s in CLOSED_STAGES)
                    _opp_ids      = []
                    for _ci in range(0, len(_account_ids), _CHUNK):
                        _chunk   = _account_ids[_ci : _ci + _CHUNK]
                        _ids_str = ", ".join(f"'{x}'" for x in _chunk)
                        _ores    = sf.query_all(
                            f"SELECT Id FROM Opportunity "
                            f"WHERE AccountId IN ({_ids_str}) "
                            f"AND StageName NOT IN ({_stage_not_in}) "
                            f"AND IsDeleted = false"
                        )
                        _opp_ids.extend(r["Id"] for r in _ores.get("records", []))

                    _opp_payload = [
                        {"Id": _oid, "OwnerId": ae_user_id}
                        for _oid in _opp_ids
                    ]
                    if _opp_payload and not dry_run_mode:
                        st.write(f"   Updating {len(_opp_payload):,} opportunities…")
                        _opp_result = execute_update(sf, "Opportunity", _opp_payload)
                    else:
                        _opp_result = {
                            "success": len(_opp_payload), "failed": 0, "errors": [],
                        }
                    _result_objects["Opportunity (open only)"] = _opp_result
                    st.write(f"✅ Opportunities — {_opp_result['success']:,} succeeded, {_opp_result['failed']:,} failed")

                # ── Complete ───────────────────────────────────────────────
                _progress_bar.progress(1.0, text="Complete!")
                _status.update(label="Reassignment complete!", state="complete", expanded=True)

            st.session_state.rz_result = {
                "dry_run": dry_run_mode,
                "objects": _result_objects,
            }
            st.rerun()
