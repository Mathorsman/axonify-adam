#!/usr/bin/env python3
"""
Refactors sf_query_tool.py from a flat-tab layout into a 6-page sidebar navigation.
Run once; produces the updated file in-place.
"""
import sys, re
sys.stdout.reconfigure(encoding="utf-8")

PATH = "C:/Users/mhorsman/Documents/Salesforce Query Tool/sf_query_tool.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

# ── Helpers ───────────────────────────────────────────────────────────────────
def text(start, end):
    """Extract 1-based inclusive line range as a string."""
    return "".join(lines[start - 1 : end])

def dedent4(s):
    """Remove exactly 4 leading spaces from every non-blank line."""
    out = []
    for l in s.splitlines(keepends=True):
        if l.startswith("    "):
            out.append(l[4:])
        elif l.strip() == "":
            out.append("\n")
        else:
            out.append(l)
    return "".join(out)

# ── Extract existing tab bodies ───────────────────────────────────────────────
# tab_ai body (8-space indent, inside `with tab_ai:`)
ai_body        = text(6422, 6633)

# tab_shortcuts body — start AFTER the subheader/caption (already in SHORTCUTS_PAGE)
# keep at 8-space indent so it sits inside `with _sub_audit:`
shortcuts_body = text(6643, 6668)

# tab_visual body (8-space indent)
visual_body    = text(6673, 6742)

# tab_raw body (8-space indent)
raw_body       = text(6747, 6782)

# tab_actions body — dedent4 to 4-space (inside render_results_page())
actions_body   = dedent4(text(6793, 7294))

# ── Inject nav_to("results") after every add_to_history in query paths ────────
# Single AI query (24 spaces)
ai_body = ai_body.replace(
    "                        add_to_history(edited_soql, ai_object, len(df))\n",
    "                        add_to_history(edited_soql, ai_object, len(df))\n"
    "                        nav_to(\"results\")\n",
    1,
)
# Multi-step AI query (20 spaces)
ai_body = ai_body.replace(
    "                    add_to_history(f\"-- Multi-step: {combined_label}\", ai_object, final_count)\n",
    "                    add_to_history(f\"-- Multi-step: {combined_label}\", ai_object, final_count)\n"
    "                    nav_to(\"results\")\n",
    1,
)
# Visual builder (28 spaces)
visual_body = visual_body.replace(
    "                            add_to_history(vq_soql, vq_object, len(df))\n",
    "                            add_to_history(vq_soql, vq_object, len(df))\n"
    "                            nav_to(\"results\")\n",
    1,
)
# Raw SOQL (28 spaces)
raw_body = raw_body.replace(
    "                            add_to_history(raw_soql, obj, len(df))\n",
    "                            add_to_history(raw_soql, obj, len(df))\n"
    "                            nav_to(\"results\")\n",
    1,
)
# Shortcuts Load button — navigate to Query Builder after loading
shortcuts_body = shortcuts_body.replace(
    "                        st.success(f\"\u2705 Loaded: **{shortcut['title']}** \u2014 switch to Raw SOQL tab to run it.\")\n",
    "                        nav_to(\"query\")\n",
    1,
)

# ── Build new main block ──────────────────────────────────────────────────────

NAV_TO = '''\
def nav_to(page: str):
    """Navigate to a named page by setting session state and triggering a rerun."""
    st.session_state.page = page
    st.rerun()


'''

SIDEBAR_NAV = '''\
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# SIDEBAR NAVIGATION
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def render_sidebar_nav():
    """
    Renders the full sidebar: connection status, page navigation buttons,
    safety toggles, and org reference.
    Returns (dry_run_mode, auto_backup).
    """
    st.markdown("### \u26a1 SF Query Tool")
    try:
        sf = get_sf_connection()
        st.markdown(
            f\'<span class="pill-active">\u25cf Connected</span> \'
            f\'<span style="font-family:\\\'IBM Plex Mono\\\',monospace;font-size:0.72rem;color:#6e7681;">{sf.sf_instance}</span>\',
            unsafe_allow_html=True,
        )
        if st.button("\U0001f513 Log out", key="logout",
            help="Clears the saved token. You will need to log in again on next page load."):
            st.session_state.sf = None
            try:
                os.remove(TOKEN_CACHE_FILE)
            except Exception:
                pass
            st.rerun()
    except Exception:
        st.markdown(\'<span class="pill-retired">\u25cf Disconnected</span>\', unsafe_allow_html=True)
        st.stop()

    page = st.session_state.get("page", "query")

    def _nav_btn(label: str, target: str):
        """
        Renders a sidebar nav button.
        When this button\'s page is active, emits a .nav-active-marker div
        immediately before it so the CSS adjacent-sibling rule fires.
        """
        if page == target:
            st.markdown(\'<div class="nav-active-marker"></div>\', unsafe_allow_html=True)
        if st.button(label, key=f"nav_{target}"):
            nav_to(target)

    # \u2500\u2500 WORKFLOW \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    st.markdown(\'<div class="nav-section-label">WORKFLOW</div>\', unsafe_allow_html=True)
    _nav_btn("\U0001f50e  Query Builder", "query")
    _results_label = "\U0001f4cb  Results & Actions"
    if st.session_state.query_results is not None:
        _results_label += f"  ({len(st.session_state.query_results):,})"
    _nav_btn(_results_label, "results")

    st.markdown("---")

    # \u2500\u2500 OPERATIONS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    st.markdown(\'<div class="nav-section-label">OPERATIONS</div>\', unsafe_allow_html=True)
    _nav_btn("\U0001f9f9  Cleanup Shortcuts", "shortcuts")
    _nav_btn("\U0001f500  Deduplication", "dedupe")
    _nav_btn("\U0001f5fa\ufe0f  Territory Mgmt  \U0001f195", "territory")

    st.markdown("---")

    # \u2500\u2500 REFERENCE \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    st.markdown(\'<div class="nav-section-label">REFERENCE</div>\', unsafe_allow_html=True)
    _hist_label = "\U0001f4dc  History & Logs"
    if st.session_state.query_history:
        _hist_label += f"  ({len(st.session_state.query_history)})"
    _nav_btn(_hist_label, "history")

    st.markdown("---")

    # \u2500\u2500 SAFETY \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    st.markdown(\'<div class="nav-section-label">SAFETY</div>\', unsafe_allow_html=True)
    dry_run_mode = st.toggle("Dry Run Mode", value=True,
        help="Preview all changes before they execute. Strongly recommended for production.")
    auto_backup = st.toggle("Auto-Backup Before Changes", value=True,
        help="Saves affected records to CSV before any update or delete.")

    if not dry_run_mode:
        st.markdown(\'<div class="safety-banner">\u26a0\ufe0f Dry Run OFF \u2014 changes execute immediately.</div>\', unsafe_allow_html=True)
    if not auto_backup:
        st.markdown(\'<div class="safety-banner">\u26a0\ufe0f Auto-Backup OFF \u2014 no CSV created before changes.</div>\', unsafe_allow_html=True)

    # \u2500\u2500 Org Reference \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    st.markdown("---")
    with st.expander("Active Tools (protect)", expanded=False):
        for tool in ACTIVE_TOOLS:
            st.markdown(f\'<span class="pill-active">{tool}</span>\', unsafe_allow_html=True)
    with st.expander("Retired Tools (cleanup)", expanded=False):
        for tool in RETIRED_TOOLS:
            st.markdown(f\'<span class="pill-retired">{tool}</span>\', unsafe_allow_html=True)

    return dry_run_mode, auto_backup


'''

QUERY_PAGE_HEADER = '''\
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# PAGE: QUERY BUILDER  (page = "query")
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def render_query_page(dry_run_mode: bool, auto_backup: bool):
    """
    Query Builder page.  A horizontal mode radio selects between AI, Visual,
    and Raw SOQL modes.  After a successful run the user is auto-navigated to
    the Results & Actions page.  Recent queries are shown at the bottom.
    """
    st.header("Query Builder")

    query_mode = st.radio(
        "",
        ["\U0001f916  AI", "\U0001f527  Visual", "\U0001f4dd  Raw SOQL"],
        horizontal=True,
        key="query_mode",
        label_visibility="collapsed",
    )

    st.markdown("---")

    # \u2500\u2500 AI mode \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if query_mode == "\U0001f916  AI":
'''

QUERY_PAGE_VISUAL = '''\
    # \u2500\u2500 Visual mode \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    elif query_mode == "\U0001f527  Visual":
'''

QUERY_PAGE_RAW = '''\
    # \u2500\u2500 Raw SOQL mode \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    else:  # "\U0001f4dd  Raw SOQL"
'''

RECENT_QUERIES_STRIP = '''\
    # \u2500\u2500 Recent queries strip \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if st.session_state.query_history:
        st.markdown("---")
        st.caption("Recent queries \u2014 click to reload into Raw SOQL mode")
        for _i, _h in enumerate(st.session_state.query_history[:5]):
            _label = f"{_h[\'timestamp\']}  {_h[\'object\']} ({_h[\'rows\']:,})"
            if st.button(_label, key=f"recent_q_{_i}"):
                st.session_state.last_soql   = _h["soql"]
                st.session_state.last_object = _h["object"]
                st.session_state["query_mode"] = "\U0001f4dd  Raw SOQL"
                st.rerun()


'''

RESULTS_PAGE_HEADER = '''\
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# PAGE: RESULTS & ACTIONS  (page = "results")
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def render_results_page(dry_run_mode: bool, auto_backup: bool):
    """
    Results & Actions page.
    Shows the results grid with per-row checkboxes, then the full Update /
    Delete / AI-assistant panel.  Breadcrumb lets the user return to the
    Query Builder.
    """
    if st.button("\u2190 Back to Query", key="back_to_query"):
        nav_to("query")

    if st.session_state.query_results is None or st.session_state.query_results.empty:
        st.info("No results yet. Run a query first.")
        if st.button("\U0001f50e  Go to Query Builder", key="goto_query_empty"):
            nav_to("query")
        return

    render_results_grid(st.session_state.query_results)
    st.markdown("---")
    st.subheader("Actions")

'''

SHORTCUTS_PAGE = '''\
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# PAGE: CLEANUP SHORTCUTS  (page = "shortcuts")
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def render_shortcuts_page(dry_run_mode: bool, auto_backup: bool):
    """
    Cleanup Shortcuts page.  Sub-tabs for Audit Shortcuts, Website Cleanup,
    and User Hub keep all operational reference tools in one place.
    """
    _sub_audit, _sub_web, _sub_hub = st.tabs([
        "\U0001f50d  Audit Shortcuts",
        "\U0001f310  Website Cleanup",
        "\U0001f510  User Hub",
    ])
    with _sub_audit:
        st.subheader("Audit Shortcuts")
        st.caption(
            "Pre-built queries for the Axonify cleanup project. "
            "Click Load to send a query to the Query Builder, then run it from there."
        )
'''

SHORTCUTS_PAGE_WEB = '''\
    with _sub_web:
        render_website_cleanup_tab(auto_backup=auto_backup, dry_run_mode=dry_run_mode)
    with _sub_hub:
        render_user_hub()


'''

DEDUPE_PAGE = '''\
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# PAGE: DEDUPLICATION  (page = "dedupe")
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def render_dedupe_page(dry_run_mode: bool, auto_backup: bool):
    """
    Deduplication page.  A horizontal radio selects between Account and
    Contact deduplication.
    """
    st.header("Deduplication")

    dedupe_object = st.radio(
        "Object",
        ["\U0001f3e2  Accounts", "\U0001f465  Contacts"],
        horizontal=True,
        key="dedupe_object_selector",
    )

    if dedupe_object == "\U0001f3e2  Accounts":
        render_dedupe_tab(auto_backup=auto_backup, dry_run_mode=dry_run_mode)
    else:
        render_contact_dedupe_tab(auto_backup=auto_backup, dry_run_mode=dry_run_mode)


'''

HISTORY_PAGE = '''\
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# PAGE: HISTORY & LOGS  (page = "history")
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def render_history_page():
    """
    History & Logs page.
    Section 1 \u2014 Query History: all queries run this session as a table;
                each row has a Load button that reloads the SOQL and navigates
                to the Query Builder.
    Section 2 \u2014 Audit Logs: CSV files written to sf_backups/ by auto-backup.
    """
    import pandas as _pd

    st.header("History & Logs")

    # \u2500\u2500 Query History \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    st.subheader("Query History")

    if not st.session_state.query_history:
        st.info("No queries run yet this session.")
    else:
        hist_df = _pd.DataFrame(st.session_state.query_history)
        st.dataframe(hist_df[["timestamp", "object", "rows", "soql"]], width="stretch", hide_index=True)

        st.caption("Click Load to copy a query into the Raw SOQL editor.")
        for _i, _h in enumerate(st.session_state.query_history):
            _label = f"{_h[\'timestamp\']}  {_h[\'object\']} ({_h[\'rows\']:,})"
            _col1, _col2 = st.columns([5, 1])
            with _col1:
                st.caption(_label)
            with _col2:
                if st.button("Load", key=f"hist_load_{_i}"):
                    st.session_state.last_soql   = _h["soql"]
                    st.session_state.last_object = _h["object"]
                    st.session_state["query_mode"] = "\U0001f4dd  Raw SOQL"
                    nav_to("query")

    st.markdown("---")

    # \u2500\u2500 Audit Logs \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    st.subheader("Audit Logs")

    if not os.path.isdir(BACKUP_DIR):
        st.info(f"No audit logs yet. Backup files will appear in `{BACKUP_DIR}/` after the first update or delete.")
    else:
        try:
            _files = sorted(
                [f for f in os.listdir(BACKUP_DIR) if f.endswith(".csv") or f.endswith(".log")],
                reverse=True,
            )
            if not _files:
                st.info(f"No CSV files in `{BACKUP_DIR}/` yet.")
            else:
                st.caption(f"{len(_files)} file(s) in `{BACKUP_DIR}/`")
                for _fname in _files[:50]:
                    _fpath = os.path.join(BACKUP_DIR, _fname)
                    try:
                        _size = os.path.getsize(_fpath)
                        _size_str = f"{_size / 1024:.1f} KB" if _size >= 1024 else f"{_size} B"
                    except Exception:
                        _size_str = "?"
                    st.text(f"\U0001f4c4  {_fname}  ({_size_str})")
        except Exception as e:
            st.error(f"Could not list backup files: {e}")


'''

MAIN_FUNC = '''\
def main():
    # \u2500\u2500 Session state defaults \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    defaults = {
        "sf":                 None,
        "anthropic_client":   None,
        "query_results":      None,
        "last_soql":          "",
        "last_object":        "",
        "dry_run_pending":    None,
        "query_history":      [],
        "ai_generated_soql":  "",
        "ai_steps":           [],
        "ai_explanation":     "",
        "ai_safety_notes":    [],
        "ai_gen_count":       0,
        "excluded_ids":       set(),
        "page":               "query",
        # Dedupe tab state
        "dedupe_candidates":  None,
        "dedupe_review_idx":  0,
        "dedupe_dismissed":   set(),
        "dedupe_merged":      set(),
        "ai_update_plan":     None,
        # Contact deduplication state
        "contact_dedupe_candidates":  None,
        "contact_dedupe_review_idx":  0,
        "contact_dedupe_dismissed":   set(),
        "contact_dedupe_merged":      set(),
        "contact_dedupe_case_ids":    None,
    }
    _valid_action_types = {
        "\U0001f916  AI Update Assistant",
        "\u270f\ufe0f  Update a field value",
        "\U0001f5d1\ufe0f  Delete these records",
    }
    if st.session_state.get("action_type_v2") not in _valid_action_types:
        st.session_state["action_type_v2"] = "\U0001f916  AI Update Assistant"
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # \u2500\u2500 Header \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    st.markdown(f"""
    <div class="app-header">
      <h1>\u26a1 Salesforce Query Tool</h1>
      <div class="subtitle">{ORG_NAME} \u00b7 AI-Assisted \u00b7 Dry Run \u00b7 Auto-Backup \u00b7 v5.0</div>
    </div>
    """, unsafe_allow_html=True)

    # \u2500\u2500 Sidebar \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    with st.sidebar:
        dry_run_mode, auto_backup = render_sidebar_nav()

    # \u2500\u2500 Page routing \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    page = st.session_state.page
    if page == "query":
        render_query_page(dry_run_mode, auto_backup)
    elif page == "results":
        render_results_page(dry_run_mode, auto_backup)
    elif page == "shortcuts":
        render_shortcuts_page(dry_run_mode, auto_backup)
    elif page == "dedupe":
        render_dedupe_page(dry_run_mode, auto_backup)
    elif page == "territory":
        render_territory_tab()
    elif page == "history":
        render_history_page()
    else:
        render_query_page(dry_run_mode, auto_backup)

'''

# ── Assemble the new main block ───────────────────────────────────────────────
new_main_block = (
    NAV_TO
    + SIDEBAR_NAV
    + QUERY_PAGE_HEADER
    + ai_body          # 8-space content inside `if query_mode == "🤖  AI":`
    + "\n"
    + QUERY_PAGE_VISUAL
    + visual_body      # 8-space content inside `elif query_mode == "🔧  Visual":`
    + "\n"
    + QUERY_PAGE_RAW
    + raw_body         # 8-space content inside `else:`
    + "\n"
    + RECENT_QUERIES_STRIP
    + RESULTS_PAGE_HEADER
    + actions_body     # 4-space content (dedented from original 8-space)
    + "\n\n"
    + SHORTCUTS_PAGE
    + shortcuts_body   # 8-space content inside `with _sub_audit:`
    + "\n"
    + SHORTCUTS_PAGE_WEB
    + DEDUPE_PAGE
    + HISTORY_PAGE
    + MAIN_FUNC
)

# ── Splice: replace def main(): ... (lines 6296-7324) ────────────────────────
pre_main  = "".join(lines[:6295])   # everything before def main(): (line 6296)
post_main = "".join(lines[7324:])   # everything from USER HUB section onward

final_source = pre_main + new_main_block + post_main

with open(PATH, "w", encoding="utf-8") as f:
    f.write(final_source)

# Quick sanity check
new_lines = final_source.splitlines()
print(f"Done. Lines: {len(new_lines):,}")
print(f"nav_to defined:              {'def nav_to(' in final_source}")
print(f"render_sidebar_nav defined:  {'def render_sidebar_nav(' in final_source}")
print(f"render_query_page defined:   {'def render_query_page(' in final_source}")
print(f"render_results_page defined: {'def render_results_page(' in final_source}")
print(f"render_shortcuts_page:       {'def render_shortcuts_page(' in final_source}")
print(f"render_dedupe_page defined:  {'def render_dedupe_page(' in final_source}")
print(f"render_history_page defined: {'def render_history_page(' in final_source}")
print(f"def main() present:          {'def main():' in final_source}")
print(f"nav_to(results) injected:    {'nav_to(\"results\")' in final_source}")
print(f"nav_to(query) injected:      {'nav_to(\"query\")' in final_source}")
print(f"old st.tabs call gone:       {'tab_ai, tab_shortcuts' not in final_source}")
print(f"bad pandas import gone:      {'import pandas as pd as' not in final_source}")
