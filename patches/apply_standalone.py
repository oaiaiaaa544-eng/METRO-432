#!/usr/bin/env python3
"""Give the restored Metro 432 build its own install identity."""
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_standalone.py <Metro-dev directory>")

root = Path(sys.argv[1])
gradle_file = root / "app/build.gradle"
gradle = gradle_file.read_text(encoding="utf-8")

old_id = "io.github.muntashirakon.Music"
new_id = "io.github.muntashirakon.metro432"
if new_id not in gradle:
    if gradle.count(old_id) != 1:
        raise SystemExit("Could not find the expected original Metro applicationId exactly once")
    gradle = gradle.replace(old_id, new_id, 1)
gradle = gradle.replace("            applicationIdSuffix '.debug'\n", "")
gradle_file.write_text(gradle, encoding="utf-8")

# Keep a distinct launcher label as well as a distinct Android package ID.
label_file = root / "app/src/main/res/values/donottranslate.xml"
label_text = label_file.read_text(encoding="utf-8")
label_text, count = re.subn(
    r'(<string\s+name="app_name"[^>]*>)Metro(</string>)',
    r'\1Metro 432\2',
    label_text,
    count=1,
)
if count != 1 and 'name="app_name"' not in label_text:
    raise SystemExit("Could not locate the Metro launcher label")
label_file.write_text(label_text, encoding="utf-8")

# The requested build exposes only the three tuning choices discussed.
arrays_file = root / "app/src/main/res/values/arrays.xml"
arrays_text = arrays_file.read_text(encoding="utf-8")
def replace_array(text: str, name: str, items: list[str]) -> str:
    block = "    <string-array name=\"" + name + "\">\n"
    block += "".join("        <item>" + item + "</item>\n" for item in items)
    block += "    </string-array>"
    pattern = r'    <string-array name="' + re.escape(name) + r'">.*?    </string-array>'
    updated, n = re.subn(pattern, block.rstrip(), text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"Could not find {name} in arrays.xml")
    return updated

arrays_text = replace_array(
    arrays_text,
    "tuning_frequency_entries",
    ["432 Hz — Default", "528 Hz", "639 Hz"],
)
arrays_text = replace_array(
    arrays_text,
    "tuning_frequency_values",
    ["432", "528", "639"],
)
arrays_file.write_text(arrays_text, encoding="utf-8")

print(f"Standalone app identity set to {new_id}; launcher name Metro 432.")
