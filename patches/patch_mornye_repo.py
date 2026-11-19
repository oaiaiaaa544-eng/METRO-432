#!/usr/bin/env python3
"""Prepare a separate Metro Stream package and Mornye Extension Repo launcher."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_mornye_repo.py <Metro-dev directory>")
root = Path(sys.argv[1])
app = root / "app"

def replace_once(path, old, new):
    data = path.read_text(encoding="utf-8")
    count = data.count(old)
    if count != 1:
        raise SystemExit(f"Expected one replacement in {path}, found {count}: {old[:90]!r}")
    path.write_text(data.replace(old, new, 1), encoding="utf-8")

replace_once(app / "build.gradle", "        minSdk 21", "        minSdk 24")
replace_once(app / "build.gradle",
             "applicationId 'io.github.muntashirakon.Music'",
             "applicationId 'io.github.muntashirakon.Music.stream'")
replace_once(app / "build.gradle", "dependencies {",
             "dependencies {\n    // UniFFI bindings for Mornye's native Rust/QuickJS extension runtime.\n    implementation 'net.java.dev.jna:jna:5.19.1@aar'")
replace_once(app / "src/main/res/values/donottranslate.xml",
             '<string name="app_name" translatable="false">Metro</string>',
             '<string name="app_name" translatable="false">Metro Stream</string>')

manifest = app / "src/main/AndroidManifest.xml"
data = manifest.read_text(encoding="utf-8")
if "android.permission.INTERNET" not in data:
    data = data.replace(
        '    <uses-permission android:name="android.permission.DISABLE_KEYGUARD" />',
        '    <uses-permission android:name="android.permission.INTERNET" />\n'
        '    <uses-permission android:name="android.permission.DISABLE_KEYGUARD" />',
        1,
    )
data = data.replace('                <action android:name="android.intent.action.MAIN" />\n', "", 1)
data = data.replace('                <category android:name="android.intent.category.LAUNCHER" />\n', "", 1)
anchor = '        <activity\n            android:name=".activities.MainActivity"'
if data.count(anchor) != 1:
    raise SystemExit("Could not find unique Metro MainActivity declaration")
launcher = '''        <activity
            android:name=".online.MornyeExtensionsActivity"
            android:exported="true"
            android:label="Extension Repo">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
'''
data = data.replace(anchor, launcher + anchor, 1)
manifest.write_text(data, encoding="utf-8")

kt = app / "src/main/java/code/name/monkey/retromusic/online/MornyeExtensionsActivity.kt"
if not kt.is_file():
    raise SystemExit("MornyeExtensionsActivity.kt is missing from the repository overlay")

(root / "MORNYE_EXTENSION_NOTICE.md").write_text(
    """# Mornye Extension Runtime Integration

Metro Stream embeds the Mornye mobile Rust/QuickJS backend and uses its native
ExtensionRepository and ExtensionManager to retrieve, validate, install,
enable, and manage .sflx provider packages.

Default provider catalogue:
https://github.com/mornyeapp/Mornye-Extension

SoundCloud is intentionally excluded from Metro Stream's extension catalogue
and from the build-time integration. Other providers are sourced from the live
Mornye registry. Provider requirements, authorization, service availability,
and provider terms continue to apply.

Mornye is licensed under LGPL-3.0-only with incorporated GPL-3.0 terms. Its
upstream source and license notices are retained in the build dependency.
""",
    encoding="utf-8",
)
print("Metro Stream now opens the Mornye Extension Repo; SoundCloud is excluded.")
