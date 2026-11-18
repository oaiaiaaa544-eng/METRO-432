#!/usr/bin/env python3
"""Respect Internet Archive stream-only flags and expose per-item rights details."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix_internet_archive_stream_only.py <Metro source directory>")
root = Path(sys.argv[1])
base = root / "app/src/main"
def patch(rel: str, old: str, new: str) -> None:
    path = base / rel
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected one patch anchor in {rel}; found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

track = "java/code/name/monkey/retromusic/fragments/home/InternetArchiveTrack.kt"
patch(track, "    val downloads: Long,\n) {",
      "    val downloads: Long,\n    val downloadAllowed: Boolean,\n) {")

service = "java/code/name/monkey/retromusic/fragments/home/InternetArchiveService.kt"
patch(service,
      '            if (isTruthy(metadata.opt("access-restricted-item"))) return null\n            val files = root.optJSONArray("files") ?: return null',
      '            if (isTruthy(metadata.opt("access-restricted-item"))) return null\n'
      '            // Stream-only items may play online but cannot be saved or added to offline playlists.\n'
      '            val streamOnly = metadata.stringOrArray("collection").split(\',\')\n'
      '                .any { it.trim().equals("stream_only", ignoreCase = true) }\n'
      '            val files = root.optJSONArray("files") ?: return null')
patch(service,
      '                format = file.format,\n                downloads = downloads,\n            )',
      '                format = file.format,\n                downloads = downloads,\n                downloadAllowed = !streamOnly,\n            )')

downloader = "java/code/name/monkey/retromusic/fragments/home/InternetArchiveDownloader.kt"
patch(downloader,
      '    suspend fun download(context: Context, track: InternetArchiveTrack): Song = withContext(Dispatchers.IO) {\n        val mimeType = mimeType(track.fileName)',
      '    suspend fun download(context: Context, track: InternetArchiveTrack): Song = withContext(Dispatchers.IO) {\n'
      '        if (!track.downloadAllowed) throw IOException("This Internet Archive item is stream-only and cannot be downloaded")\n'
      '        val mimeType = mimeType(track.fileName)')

adapter = "java/code/name/monkey/retromusic/fragments/home/InternetArchiveAdapter.kt"
patch(adapter, "import android.view.LayoutInflater\n",
      "import android.content.Intent\nimport android.net.Uri\nimport android.view.LayoutInflater\n")
patch(adapter, "import androidx.recyclerview.widget.RecyclerView\n",
      "import androidx.core.view.isVisible\nimport androidx.recyclerview.widget.RecyclerView\n")
patch(adapter,
      '                if (track.format.isNotBlank()) append(" • ${track.format}")\n            }\n            Glide.with(binding.archiveArtwork)',
      '                if (track.format.isNotBlank()) append(" • ${track.format}")\n'
      '                if (!track.downloadAllowed) append(" • Stream only")\n'
      '            }\n'
      '            binding.archiveDownloadButton.isVisible = track.downloadAllowed\n'
      '            binding.archivePlaylistButton.isVisible = track.downloadAllowed\n'
      '            binding.archiveDetailsLink.setOnClickListener {\n'
      '                binding.root.context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(track.itemUrl)))\n'
      '            }\n'
      '            Glide.with(binding.archiveArtwork)')

item = "res/layout/item_internet_archive_track.xml"
patch(item,
      '            <LinearLayout\n                android:layout_width="match_parent"\n                android:layout_height="wrap_content"\n                android:layout_marginTop="6dp"',
      '            <TextView\n'
      '                android:id="@+id/archiveDetailsLink"\n'
      '                android:layout_width="wrap_content"\n'
      '                android:layout_height="wrap_content"\n'
      '                android:layout_marginTop="4dp"\n'
      '                android:text="@string/internet_archive_view_details"\n'
      '                android:textAppearance="?android:attr/textAppearanceSmall"\n'
      '                android:clickable="true"\n'
      '                android:focusable="true" />\n\n'
      '            <LinearLayout\n'
      '                android:layout_width="match_parent"\n'
      '                android:layout_height="wrap_content"\n'
      '                android:layout_marginTop="6dp"')

strings = base / "res/values/strings.xml"
s = strings.read_text(encoding="utf-8")
s = s.replace(
    "Audio and downloads are served by Internet Archive. Availability and rights vary by item.",
    "Audio is served by Internet Archive. Check each item’s rights and permitted uses; stream-only items are playback only."
)
if 'name="internet_archive_view_details"' not in s:
    s = s.replace("</resources>",
        '    <string name="internet_archive_view_details">View rights and item details on Internet Archive</string>\n</resources>', 1)
strings.write_text(s, encoding="utf-8")
print("Internet Archive stream-only handling and item-rights links applied.")
