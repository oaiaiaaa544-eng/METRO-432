#!/usr/bin/env python3
"""Add the Mornye provider catalogue/download screen to Metro Stream."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_mornye_extensions.py <Metro-dev directory>")
root = Path(sys.argv[1])
app = root / "app"

def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"Expected one match in {path}, found {n}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

for rel in [
    "build.gradle",
    "src/main/AndroidManifest.xml",
    "src/main/res/layout/home_content.xml",
    "src/main/java/code/name/monkey/retromusic/fragments/home/HomeFragment.kt",
    "src/main/java/code/name/monkey/retromusic/fragments/home/HomeBinding.kt",
]:
    if not (app / rel).is_file():
        raise SystemExit(f"Required Metro file missing: {rel}")

replace_once(app / "build.gradle",
             "applicationId 'io.github.muntashirakon.Music'",
             "applicationId 'io.github.muntashirakon.Music.stream'")

replace_once(app / "src/main/res/layout/home_content.xml",
             '        layout="@layout/abs_playlists" />',
             '''        layout="@layout/abs_playlists" />

    <com.google.android.material.button.MaterialButton
        android:id="@+id/mornyeExtensions"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginStart="16dp"
        android:layout_marginTop="8dp"
        android:layout_marginEnd="16dp"
        android:layout_marginBottom="8dp"
        android:text="Music providers · Mornye extensions" />''')

binding = app / "src/main/java/code/name/monkey/retromusic/fragments/home/HomeBinding.kt"
replace_once(binding,
             "    val recyclerView = homeBinding.homeContent.recyclerView",
             "    val recyclerView = homeBinding.homeContent.recyclerView\n    val mornyeExtensions = homeBinding.homeContent.mornyeExtensions")

fragment = app / "src/main/java/code/name/monkey/retromusic/fragments/home/HomeFragment.kt"
s = fragment.read_text(encoding="utf-8")
if "import android.content.Intent" not in s:
    s = s.replace("import android.os.Bundle\n", "import android.content.Intent\nimport android.os.Bundle\n", 1)
if "import code.name.monkey.retromusic.online.MornyeExtensionsActivity" not in s:
    s = s.replace("import code.name.monkey.retromusic.model.Song\n",
                  "import code.name.monkey.retromusic.model.Song\nimport code.name.monkey.retromusic.online.MornyeExtensionsActivity\n", 1)
anchor = "        binding.history.setOnClickListener {"
if s.count(anchor) != 1:
    raise SystemExit("HomeFragment history listener anchor not found exactly once")
s = s.replace(anchor,
              "        binding.mornyeExtensions.setOnClickListener {\n"
              "            startActivity(Intent(requireContext(), MornyeExtensionsActivity::class.java))\n"
              "        }\n\n" + anchor, 1)
fragment.write_text(s, encoding="utf-8")

replace_once(app / "src/main/AndroidManifest.xml",
             '        tools:ignore="UnusedAttribute">',
             '''        tools:ignore="UnusedAttribute">
        <activity
            android:name=".online.MornyeExtensionsActivity"
            android:exported="false"
            android:label="Music providers" />''')

activity = app / "src/main/java/code/name/monkey/retromusic/online/MornyeExtensionsActivity.kt"
activity.parent.mkdir(parents=True, exist_ok=True)
activity.write_text(r'''package code.name.monkey.retromusic.online

import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Mornye-Extension catalogue client. It fetches the upstream registry,
 * checks package SHA-256 digests, and stores .sflx packages privately.
 *
 * The .sflx runtime belongs to Mornye's Rust/QuickJS host. Metro currently
 * uses its native SoundCloud provider for actual streaming and does not
 * evaluate downloaded extension JavaScript.
 */
class MornyeExtensionsActivity : AppCompatActivity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var list: LinearLayout
    private lateinit var progress: ProgressBar
    private lateinit var refreshButton: MaterialButton

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Music providers"
        val scroll = ScrollView(this)
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(20), dp(20), dp(28))
        }
        scroll.addView(page)
        page.addView(TextView(this).apply {
            text = "Mornye Extension Library"
            textSize = 24f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        })
        page.addView(TextView(this).apply {
            text = "Browse community music providers from the official Mornye-Extension registry. Provider packages are checksum-verified before saving."
            textSize = 14f
            setPadding(0, dp(8), 0, dp(14))
        })
        refreshButton = MaterialButton(this).apply {
            text = "Refresh provider catalogue"
            setOnClickListener { loadCatalog() }
        }
        page.addView(refreshButton)
        progress = ProgressBar(this).apply { visibility = View.GONE }
        page.addView(progress)
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        page.addView(list)
        page.addView(TextView(this).apply {
            text = "Playback: Metro's SoundCloud search, For You feed and player are built in. Downloaded .sflx packages are stored in the app-private library; running them requires Mornye's Rust/QuickJS extension runtime, which is not bundled in this native Metro build."
            textSize = 12f
            setPadding(0, dp(18), 0, 0)
        })
        setContentView(scroll)
        loadCatalog()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun loadCatalog() {
        progress.visibility = View.VISIBLE
        refreshButton.isEnabled = false
        list.removeAllViews()
        scope.launch {
            try {
                val entries = withContext(Dispatchers.IO) { fetchRegistry() }
                entries.forEach { list.addView(extensionCard(it)) }
                if (entries.isEmpty()) addMessage("No provider packages are available.")
            } catch (error: Exception) {
                addMessage("Could not load the Mornye catalogue: " + (error.message ?: "network error"))
            } finally {
                progress.visibility = View.GONE
                refreshButton.isEnabled = true
            }
        }
    }

    private fun extensionCard(entry: ExtensionEntry): View {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(12), dp(14), dp(12))
            setBackgroundResource(android.R.drawable.dialog_holo_light_frame)
        }
        card.addView(TextView(this).apply {
            text = entry.displayName + "  ·  " + entry.version
            textSize = 18f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        })
        card.addView(TextView(this).apply {
            text = entry.category.uppercase() + "  ·  " + entry.tags.joinToString(", ")
            textSize = 11f
            setPadding(0, dp(4), 0, dp(6))
        })
        card.addView(TextView(this).apply {
            text = entry.description
            textSize = 13f
        })
        val action = MaterialButton(this).apply {
            text = if (packageFile(entry.id).isFile) "Saved · download again" else "Download provider package"
            setOnClickListener { download(entry, this) }
        }
        card.addView(action, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, 0, dp(10))
            addView(card)
        }
    }

    private fun download(entry: ExtensionEntry, button: MaterialButton) {
        button.isEnabled = false
        button.text = "Downloading and verifying…"
        scope.launch {
            try {
                val file = withContext(Dispatchers.IO) { downloadPackage(entry) }
                button.text = "Saved · download again"
                Toast.makeText(this@MornyeExtensionsActivity, "Saved " + file.name, Toast.LENGTH_LONG).show()
            } catch (error: Exception) {
                button.text = "Download failed · retry"
                Toast.makeText(this@MornyeExtensionsActivity, error.message ?: "Download failed", Toast.LENGTH_LONG).show()
            } finally {
                button.isEnabled = true
            }
        }
    }

    private fun fetchRegistry(): List<ExtensionEntry> {
        val address = "https://raw.githubusercontent.com/mornyeapp/Mornye-Extension/main/registry.json"
        val root = JSONObject(getText(address, 4 * 1024 * 1024))
        val extensions = root.optJSONArray("extensions") ?: return emptyList()
        val entries = ArrayList<ExtensionEntry>()
        for (index in 0 until extensions.length()) {
            val item = extensions.optJSONObject(index) ?: continue
            val id = item.optString("id")
            val url = item.optString("download_url")
            val hash = item.optString("sha256")
            if (!id.matches(Regex("[a-zA-Z0-9._-]{1,80}"))) continue
            if (!url.startsWith("https://raw.githubusercontent.com/mornyeapp/Mornye-Extension/")) continue
            if (!hash.matches(Regex("[a-fA-F0-9]{64}"))) continue
            val tagArray = item.optJSONArray("tags")
            val tags = ArrayList<String>()
            if (tagArray != null) for (i in 0 until tagArray.length()) tags.add(tagArray.optString(i))
            entries.add(ExtensionEntry(
                id = id,
                displayName = item.optString("display_name", item.optString("name", id)),
                version = item.optString("version", ""),
                description = item.optString("description", "No description supplied."),
                category = item.optString("category", "provider"),
                tags = tags,
                downloadUrl = url,
                sha256 = hash
            ))
        }
        return entries.sortedWith(compareBy<ExtensionEntry> { it.category }.thenBy { it.displayName.lowercase() })
    }

    private fun downloadPackage(entry: ExtensionEntry): File {
        val bytes = getBytes(entry.downloadUrl, 24 * 1024 * 1024)
        val actual = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }
        if (!actual.equals(entry.sha256, ignoreCase = true)) {
            throw IllegalStateException("SHA-256 mismatch for " + entry.displayName)
        }
        val folder = File(filesDir, "mornye/extensions")
        if (!folder.exists() && !folder.mkdirs()) throw IllegalStateException("Could not create extension folder")
        val destination = packageFile(entry.id)
        val temporary = File(folder, entry.id + ".sflx.tmp")
        temporary.writeBytes(bytes)
        if (destination.exists() && !destination.delete()) throw IllegalStateException("Could not replace package")
        if (!temporary.renameTo(destination)) {
            temporary.delete()
            throw IllegalStateException("Could not save provider package")
        }
        return destination
    }

    private fun packageFile(id: String): File =
        File(File(filesDir, "mornye/extensions"), id + ".sflx")

    private fun getText(address: String, limit: Int): String =
        String(getBytes(address, limit), Charsets.UTF_8)

    private fun getBytes(address: String, limit: Int): ByteArray {
        val connection = (URL(address).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15000
            readTimeout = 25000
            requestMethod = "GET"
            setRequestProperty("User-Agent", "Metro-Stream/1.0")
            setRequestProperty("Accept", "application/json, application/octet-stream, */*")
        }
        try {
            val status = connection.responseCode
            if (status !in 200..299) throw IllegalStateException("HTTP " + status)
            if (connection.contentLengthLong > limit) throw IllegalStateException("Download exceeds size limit")
            return connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                var total = 0
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    total += count
                    if (total > limit) throw IllegalStateException("Response exceeds size limit")
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun addMessage(message: String) {
        list.addView(TextView(this).apply {
            text = message
            textSize = 14f
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(16), 0, dp(16))
        })
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private data class ExtensionEntry(
        val id: String,
        val displayName: String,
        val version: String,
        val description: String,
        val category: String,
        val tags: List<String>,
        val downloadUrl: String,
        val sha256: String
    )
}
''', encoding="utf-8")

(root / "MORNYE_EXTENSION_NOTICE.md").write_text(
    """# Mornye Extension catalogue integration

Metro Stream reads the public provider catalogue from https://github.com/mornyeapp/Mornye-Extension and stores selected .sflx packages in app-private storage after verifying their published SHA-256 digest.

Mornye-Extension is a registry and package collection, not a standalone Android SDK. Downloaded packages are not evaluated by this native Kotlin app. Metro's built-in SoundCloud integration supplies the working streaming provider. Full .sflx execution requires Mornye's Rust/QuickJS host runtime.

The registry repository identifies its license as LGPL-3.0-only together with incorporated GPL-3.0 terms. Downloaded provider packages retain their own license notices.
""",
    encoding="utf-8"
)

print("Mornye extension catalogue added; streaming package id is io.github.muntashirakon.Music.stream")
