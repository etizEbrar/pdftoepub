#!/usr/bin/env python3
"""Rename exported attachments from UUIDs to their readable names.

xcresulttool writes each attachment as <uuid>.png and records the name the test
gave it in manifest.json, so "01-home" only exists in that file.
"""

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
manifest = out / "manifest.json"
if not manifest.exists():
    sys.exit("no manifest.json — nothing was exported")

renamed = 0
for test in json.loads(manifest.read_text()):
    for att in test.get("attachments", []):
        src = out / att["exportedFileName"]
        name = att.get("suggestedHumanReadableName") or att["exportedFileName"]
        if not name.lower().endswith(".png"):
            continue
        # "01-home_0_<uuid>.png" -> "01-home.png"
        stem = name.split("_")[0]
        if src.exists():
            src.replace(out / f"{stem}.png")
            renamed += 1
print(f"  {renamed} screenshot(s) named")
