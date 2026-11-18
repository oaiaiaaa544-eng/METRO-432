#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix_internet_archive_binding.py <Metro source directory>")
path = Path(sys.argv[1]) / "app/src/main/java/code/name/monkey/retromusic/fragments/home/HomeBinding.kt"
content = path.read_text(encoding="utf-8")
old = "val archiveMusic = homeBinding.archiveMusic"
new = "val archiveMusic = requireNotNull(homeBinding.archiveMusic)"
if old in content:
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
elif new not in content:
    raise SystemExit("Could not find Internet Archive binding property")
print("Made the required Internet Archive View Binding non-null.")
