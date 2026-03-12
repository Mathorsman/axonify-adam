#!/usr/bin/env python3
"""
_splice_reassign.py
────────────────────
Reads _reassign_func.py and inserts its contents just before
def render_territory_tab() in sf_query_tool.py.
Run once; overwrites in-place.
"""
import ast
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "sf_query_tool.py")
FUNC = os.path.join(HERE, "_reassign_func.py")

with open(PATH, "r", encoding="utf-8") as f:
    source = f.read()

with open(FUNC, "r", encoding="utf-8") as f:
    insertion = f.read().rstrip("\n") + "\n\n"

MARKER = "\ndef render_territory_tab():"

if MARKER not in source:
    print("ERROR: marker not found — def render_territory_tab(): missing from source.")
    sys.exit(1)

if "def render_reassign_subtab" in source:
    print("ALREADY DONE: render_reassign_subtab already present — nothing to do.")
    sys.exit(0)

new_source = source.replace(MARKER, "\n" + insertion + MARKER, 1)

# Syntax check before writing
try:
    ast.parse(new_source)
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(new_source)

lines = new_source.count("\n") + 1
print(f"Done.  Lines: {lines:,}")
checks = [
    "_get_active_users_for_reassign",
    "def render_reassign_subtab(",
    "render_reassign_subtab()",
    "rz_step",
    "def render_territory_tab(",
]
for c in checks:
    tag = "✓" if c in new_source else "✗ MISSING"
    print(f"  {c.ljust(42)} {tag}")
