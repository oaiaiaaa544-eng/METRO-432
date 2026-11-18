#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix_internet_archive_strings.py <Metro source directory>")
strings = Path(sys.argv[1]) / "app/src/main/res/values/strings.xml"
text = strings.read_text(encoding="utf-8")
for name, value in {
    "search": "Search",
    "play": "Play",
    "download": "Download",
}.items():
    if f'name="{name}"' not in text:
        text = text.replace(
            "</resources>",
            f'    <string name="{name}">{value}</string>\n</resources>',
            1,
        )
strings.write_text(text, encoding="utf-8")
print("Added missing Internet Archive action labels.")
