#!/usr/bin/env python3
"""Integrate Mornye's native extension runtime and Extension Repo UI into Metro Stream."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_mornye_extensions.py <Metro-dev directory>")

root = Path(sys.argv[1])
app = root / "app"

def replace_once(path: Path, old: str, new: str) -> None:
    data = path.read_text(encoding="utf-8")
    count = data.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one replacement in {path}, got {count}: {old[:100]!r}")
    path.write_text(data.replace(old, new, 1), encoding="utf-8")

required = [
    app / "build.gradle",
    app / "src/main/AndroidManifest.xml",
    app / "src/main/res/values/donottranslate.xml",
]
for path in required:
    if not path.is_file():
        raise SystemExit(f"Required Metro source file missing: {path}")

# Mornye's current Android Rust backend targets API 24 and uses UniFFI/JNA.
replace_once(app / "build.gradle", "        minSdk 21", "        minSdk 24")
replace_once(
    app / "build.gradle",
    "applicationId 'io.github.muntashirakon.Music'",
    "applicationId 'io.github.muntashirakon.Music.stream'",
)
replace_once(
    app / "build.gradle",
    "dependencies {",
    "dependencies {\n    implementation 'net.java.dev.jna:jna:5.19.1@aar'",
)
replace_once(
    app / "src/main/res/values/donottranslate.xml",
    '<string name="app_name" translatable="false">Metro</string>',
    '<string name="app_name" translatable="false">Metro Stream</string>',
)

manifest = app / "src/main/AndroidManifest.xml"
manifest_text = manifest.read_text(encoding="utf-8")
if 'android.permission.INTERNET' not in manifest_text:
    anchor = '    <uses-permission android:name="android.permission.DISABLE_KEYGUARD" />'
    if manifest_text.count(anchor) != 1:
        raise SystemExit("Could not find INTERNET permission insertion point")
    manifest_text = manifest_text.replace(
        anchor,
        '    <uses-permission android:name="android.permission.INTERNET" />\n' + anchor,
        1,
    )

# Launch into the Extension Repo; the full Metro player remains available from its button.
main_action = '                <action android:name="android.intent.action.MAIN" />\n'
launcher_category = '                <category android:name="android.intent.category.LAUNCHER" />\n'
if manifest_text.count(main_action) != 1 or manifest_text.count(launcher_category) != 1:
    raise SystemExit("Expected one original Metro launcher intent")
manifest_text = manifest_text.replace(main_action, "", 1).replace(launcher_category, "", 1)
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
main_activity = '        <activity\n            android:name=".activities.MainActivity"'
if manifest_text.count(main_activity) != 1:
    raise SystemExit("Could not find Metro MainActivity declaration")
manifest_text = manifest_text.replace(main_activity, launcher + main_activity, 1)
manifest.write_text(manifest_text, encoding="utf-8")

activity_path = app / "src/main/java/code/name/monkey/retromusic/online/MornyeExtensionsActivity.kt"
activity_path.parent.mkdir(parents=True, exist_ok=True)
activity_path.write_text(r'''package code.name.monkey.retromusic.online

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.ColorDrawable
import android.net.Uri
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.bumptech.glide.Glide
import com.google.android.material.button.MaterialButton
import com.mornye.backend.ExtensionManager
import com.mornye.backend.ExtensionRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom
import android.util.Base64

/**
 * Mornye Extension Repo for Metro Stream.
 *
 * Packages are downloaded through Mornye's ExtensionRepository (including its
 * registry checksum/runtime validation), then installed and enabled by the
 * native ExtensionManager backed by Mornye's Rust/QuickJS runtime.
 */
class MornyeExtensionsActivity : AppCompatActivity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val entries = ArrayList<ExtensionEntry>()
    private val installedIds = HashSet<String>()
    private var activeCategory = "All"
    private var manager: ExtensionManager? = null
    private var repository: ExtensionRepository? = null

    private lateinit var list: LinearLayout
    private lateinit var countLabel: TextView
    private lateinit var searchInput: EditText
    private lateinit var progress: ProgressBar
    private lateinit var categoryButtons: MutableMap<String, MaterialButton>

    companion object {
        private const val REGISTRY_URL = "https://raw.githubusercontent.com/mornyeapp/Mornye-Extension/main/registry.json"
        private const val REPO_URL = "https://github.com/mornyeapp/Mornye-Extension"
        private const val SOUND_CLOUD_ID = "soundcloud"
        private const val BG = 0xFF000000.toInt()
        private const val SURFACE = 0xFF151515.toInt()
        private const val SURFACE_2 = 0xFF202020.toInt()
        private const val PEACH = 0xFFE6C9C4.toInt()
        private const val ACCENT = 0xFFFFB4A8.toInt()
        private const val MUTED = 0xFFB9A6A2.toInt()
        private const val INSTALLED = 0xFF777777.toInt()
        private const val TEXT = 0xFFF9F4F3.toInt()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Extension Repo"
        window.statusBarColor = SURFACE
        window.navigationBarColor = BG
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        buildScreen()
        loadCatalog()
    }

    override fun onDestroy() {
        try { repository?.shutdown() } catch (_: Exception) {}
        try { manager?.shutdown() } catch (_: Exception) {}
        scope.cancel()
        super.onDestroy()
    }

    private fun buildScreen() {
        val outer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(BG)
        }
        val toolbar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(12), dp(14), dp(12))
            setBackgroundColor(SURFACE)
        }
        toolbar.addView(TextView(this).apply {
            text = "Extension Repo"
            textSize = 25f
            setTextColor(TEXT)
            typeface = Typeface.create("sans-serif", Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, -2, 1f)
        })
        toolbar.addView(topAction("↗", "Open Mornye Extension Repo") { openUrl(REPO_URL) })
        toolbar.addView(topAction("▶", "Open Metro Player") {
            startActivity(Intent(this, code.name.monkey.retromusic.activities.MainActivity::class.java))
        })
        outer.addView(toolbar)

        val searchWrap = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(18), 0, dp(18), 0)
            background = rounded(SURFACE_2, 999)
        }
        searchWrap.addView(TextView(this).apply {
            text = "⌕"
            textSize = 34f
            setTextColor(PEACH)
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(dp(42), -1)
        })
        searchInput = EditText(this).apply {
            hint = "Search extensions..."
            setHintTextColor(MUTED)
            setTextColor(TEXT)
            textSize = 18f
            singleLine = true
            background = null
            setPadding(dp(12), 0, 0, 0)
            imeOptions = android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH
            layoutParams = LinearLayout.LayoutParams(0, -1, 1f)
        }
        searchWrap.addView(searchInput)
        outer.addView(searchWrap, LinearLayout.LayoutParams(-1, dp(62)).apply {
            setMargins(0, dp(14), 0, dp(14))
        })

        val categoryScroll = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            clipToPadding = false
        }
        val categoryRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        categoryButtons = linkedMapOf()
        listOf("All", "Metadata", "Download", "Utility").forEach { category ->
            val button = categoryButton(category)
            categoryButtons[category] = button
            categoryRow.addView(button, LinearLayout.LayoutParams(-2, dp(44)).apply {
                marginEnd = dp(10)
            })
        }
        categoryScroll.addView(categoryRow)
        outer.addView(categoryScroll, LinearLayout.LayoutParams(-1, dp(48)).apply {
            bottomMargin = dp(14)
        })

        countLabel = TextView(this).apply {
            text = "Loading extensions..."
            textSize = 16f
            setTextColor(PEACH)
            setPadding(0, 0, 0, dp(12))
        }
        outer.addView(countLabel)

        val scroller = ScrollView(this).apply {
            isFillViewport = false
            clipToPadding = false
            overScrollMode = View.OVER_SCROLL_NEVER
        }
        list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, 0, dp(16))
        }
        scroller.addView(list)
        outer.addView(scroller, LinearLayout.LayoutParams(-1, 0, 1f))

        progress = ProgressBar(this).apply { visibility = View.GONE }
        outer.addView(progress, LinearLayout.LayoutParams(-2, -2).apply {
            gravity = Gravity.CENTER_HORIZONTAL
        })

        val footer = MaterialButton(this).apply {
            text = "Open Metro Player"
            isAllCaps = false
            textSize = 15f
            setTextColor(Color.BLACK)
            backgroundTintList = ColorStateList.valueOf(ACCENT)
            cornerRadius = dp(18)
            setOnClickListener {
                startActivity(Intent(this@MornyeExtensionsActivity,
                    code.name.monkey.retromusic.activities.MainActivity::class.java))
            }
        }
        outer.addView(footer, LinearLayout.LayoutParams(-1, dp(52)).apply {
            setMargins(dp(16), dp(8), dp(16), dp(12))
        })
        setContentView(outer)

        searchInput.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { renderEntries() }
            override fun afterTextChanged(s: Editable?) {}
        })
        refreshCategoryButtons()
    }

    private fun topAction(glyph: String, description: String, click: () -> Unit): TextView =
        TextView(this).apply {
            text = glyph
            contentDescription = description
            textSize = 25f
            setTextColor(PEACH)
            gravity = Gravity.CENTER
            setOnClickListener { click() }
            layoutParams = LinearLayout.LayoutParams(dp(46), dp(46))
        }

    private fun categoryButton(category: String): MaterialButton = MaterialButton(this).apply {
        text = when (category) {
            "All" -> "⠿  All"
            "Metadata" -> "◇  Metadata"
            "Download" -> "⇩  Download"
            else -> "⚒  Utility"
        }
        isAllCaps = false
        textSize = 15f
        insetTop = 0
        insetBottom = 0
        cornerRadius = dp(14)
        strokeWidth = dp(1)
        setOnClickListener {
            activeCategory = category
            refreshCategoryButtons()
            renderEntries()
        }
    }

    private fun refreshCategoryButtons() {
        categoryButtons.forEach { (category, button) ->
            val selected = category == activeCategory
            button.backgroundTintList = ColorStateList.valueOf(if (selected) 0xFF61413D.toInt() else BG)
            button.strokeColor = ColorStateList.valueOf(if (selected) 0xFF61413D.toInt() else 0xFF55413E.toInt())
            button.setTextColor(if (selected) ACCENT else PEACH)
        }
    }

    private fun loadCatalog() {
        progress.visibility = View.VISIBLE
        countLabel.text = "Loading extensions..."
        scope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    val runtime = ensureRuntime()
                    Pair(fetchRegistry(), readInstalled(runtime.first))
                }
                entries.clear()
                entries.addAll(result.first)
                installedIds.clear()
                installedIds.addAll(result.second)
                renderEntries()
            } catch (error: Exception) {
                countLabel.text = "Extension catalogue unavailable"
                list.removeAllViews()
                addMessage("Could not load the Mornye Extension Repo: " + (error.message ?: "network error"))
            } finally {
                progress.visibility = View.GONE
            }
        }
    }

    /** Construct the real Mornye Rust/QuickJS extension manager and registry client. */
    @Synchronized
    private fun ensureRuntime(): Pair<ExtensionManager, ExtensionRepository> {
        if (manager != null && repository != null) return Pair(manager!!, repository!!)
        System.loadLibrary("mornye_mobile")
        val base = File(filesDir, "mornye").apply { mkdirs() }
        val sourceDir = File(base, "installed")
        val dataDir = File(base, "extension-data")
        val cacheDir = File(base, "repository-cache")
        val masterKey = masterKey(File(noBackupFilesDir, "mornye-master-key"))
        val nativeManager = ExtensionManager(
            sourceDir.absolutePath,
            dataDir.absolutePath,
            masterKey,
            "metro-stream-1.0",
            30_000uL
        )
        nativeManager.loadAll()
        val nativeRepository = ExtensionRepository(nativeManager, cacheDir.absolutePath)
        nativeRepository.setRegistryUrls(listOf(REGISTRY_URL))
        manager = nativeManager
        repository = nativeRepository
        return Pair(nativeManager, nativeRepository)
    }

    private fun masterKey(file: File): String {
        if (file.isFile) return file.readText(Charsets.UTF_8).trim()
        file.parentFile?.mkdirs()
        val bytes = ByteArray(32)
        SecureRandom().nextBytes(bytes)
        val value = Base64.encodeToString(bytes, Base64.NO_WRAP)
        file.writeText(value, Charsets.UTF_8)
        return value
    }

    private fun readInstalled(nativeManager: ExtensionManager): Set<String> {
        val array = JSONArray(nativeManager.installed())
        val result = HashSet<String>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val id = item.optString("id", item.optString("name"))
            if (id.isNotBlank()) result.add(id)
        }
        return result
    }

    private fun fetchRegistry(): List<ExtensionEntry> {
        val body = String(getBytes(REGISTRY_URL, 4 * 1024 * 1024), Charsets.UTF_8)
        val root = JSONObject(body)
        val array = root.optJSONArray("extensions") ?: return emptyList()
        val result = ArrayList<ExtensionEntry>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val id = item.optString("id")
            // SoundCloud is not included as a Metro Stream source.
            if (id.isBlank() || id.equals(SOUND_CLOUD_ID, true)) continue
            val downloadUrl = item.optString("download_url")
            if (!id.matches(Regex("[A-Za-z0-9._-]{1,80}"))) continue
            if (!downloadUrl.startsWith("https://raw.githubusercontent.com/mornyeapp/Mornye-Extension/")) continue
            val tags = ArrayList<String>()
            val tagArray = item.optJSONArray("tags")
            if (tagArray != null) for (index in 0 until tagArray.length()) tags.add(tagArray.optString(index))
            result.add(ExtensionEntry(
                id = id,
                displayName = item.optString("display_name", item.optString("name", id)),
                version = item.optString("version", ""),
                description = item.optString("description", "No description supplied."),
                category = item.optString("category", "utility"),
                tags = tags,
                iconUrl = item.optString("icon_url", "")
            ))
        }
        return result.sortedWith(compareBy<ExtensionEntry> { categoryFor(it) }.thenBy { it.displayName.lowercase() })
    }

    private fun install(entry: ExtensionEntry, button: MaterialButton) {
        button.isEnabled = false
        button.text = "Installing..."
        progress.visibility = View.VISIBLE
        scope.launch {
            try {
                val installed = withContext(Dispatchers.IO) {
                    val (nativeManager, nativeRepository) = ensureRuntime()
                    val packageDir = File(filesDir, "mornye/packages").apply { mkdirs() }
                    // Mornye validates the package runtime, archive and registry SHA-256 before install.
                    val packagePath = nativeRepository.download(entry.id, packageDir.absolutePath, "")
                    nativeManager.install(packagePath)
                    nativeManager.setEnabled(entry.id, true)
                    readInstalled(nativeManager)
                }
                installedIds.clear()
                installedIds.addAll(installed)
                Toast.makeText(this@MornyeExtensionsActivity, entry.displayName + " installed", Toast.LENGTH_LONG).show()
                renderEntries()
            } catch (error: Exception) {
                button.text = "Install"
                button.isEnabled = true
                Toast.makeText(this@MornyeExtensionsActivity,
                    "Install failed: " + (error.message ?: "unknown error"), Toast.LENGTH_LONG).show()
            } finally {
                progress.visibility = View.GONE
            }
        }
    }

    private fun renderEntries() {
        if (!::list.isInitialized) return
        val query = if (::searchInput.isInitialized) searchInput.text.toString().trim().lowercase() else ""
        val visible = entries.filter { entry ->
            val matchesCategory = activeCategory == "All" || categoryFor(entry) == activeCategory
            val haystack = (entry.displayName + " " + entry.id + " " + entry.description + " " + entry.tags.joinToString(" ")).lowercase()
            matchesCategory && (query.isEmpty() || haystack.contains(query))
        }
        countLabel.text = visible.size.toString() + " extensions"
        list.removeAllViews()
        if (visible.isEmpty()) {
            addMessage(if (query.isBlank()) "No extensions in this category." else "No extensions match your search.")
            return
        }
        visible.forEach { list.addView(extensionCard(it)) }
    }

    private fun extensionCard(entry: ExtensionEntry): View {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(14), dp(16), dp(14), dp(16))
            background = rounded(SURFACE, dp(18))
            layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(6) }
        }
        val iconBox = LinearLayout(this).apply {
            gravity = Gravity.CENTER
            background = rounded(if (categoryFor(entry) == "Download") 0xFF74352F.toInt() else SURFACE_2, dp(16))
            layoutParams = LinearLayout.LayoutParams(dp(58), dp(58)).apply { marginEnd = dp(14) }
        }
        if (entry.iconUrl.isNotBlank()) {
            val image = ImageView(this).apply {
                scaleType = ImageView.ScaleType.CENTER_CROP
                contentDescription = entry.displayName
                layoutParams = LinearLayout.LayoutParams(dp(58), dp(58))
            }
            Glide.with(this).load(entry.iconUrl)
                .placeholder(ColorDrawable(SURFACE_2))
                .error(ColorDrawable(SURFACE_2)).into(image)
            iconBox.addView(image)
        } else {
            iconBox.addView(categoryGlyph(entry))
        }
        card.addView(iconBox)

        val details = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, -2, 1f)
        }
        val nameRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        nameRow.addView(TextView(this).apply {
            text = entry.displayName
            textSize = 18f
            setTextColor(TEXT)
            typeface = Typeface.create("sans-serif", Typeface.MEDIUM)
            maxLines = 2
            layoutParams = LinearLayout.LayoutParams(0, -2, 1f)
        })
        nameRow.addView(TextView(this).apply {
            text = "v" + entry.version
            textSize = 12f
            setTextColor(PEACH)
            background = rounded(SURFACE_2, dp(12))
            setPadding(dp(8), dp(4), dp(8), dp(4))
        })
        details.addView(nameRow)
        details.addView(TextView(this).apply {
            text = entry.description
            textSize = 14f
            setTextColor(PEACH)
            maxLines = 2
            ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding(0, dp(5), 0, 0)
        })
        card.addView(details)

        val installed = entry.id in installedIds
        val action = MaterialButton(this).apply {
            text = if (installed) "✓  Installed" else "Install"
            isAllCaps = false
            textSize = 14f
            cornerRadius = dp(40)
            minWidth = dp(94)
            minHeight = dp(48)
            insetTop = 0
            insetBottom = 0
            if (installed) {
                setTextColor(INSTALLED)
                backgroundTintList = ColorStateList.valueOf(SURFACE)
                strokeWidth = dp(1)
                strokeColor = ColorStateList.valueOf(0xFF333333.toInt())
                isEnabled = false
            } else {
                setTextColor(0xFF401B17.toInt())
                backgroundTintList = ColorStateList.valueOf(ACCENT)
                strokeWidth = 0
                setOnClickListener { install(entry, this) }
            }
        }
        card.addView(action, LinearLayout.LayoutParams(dp(100), dp(52)).apply {
            marginStart = dp(9)
        })
        return card
    }

    private fun categoryFor(entry: ExtensionEntry): String = when {
        entry.category.equals("integration", true) || entry.category.equals("metadata", true) -> "Metadata"
        entry.category.equals("download", true) -> "Download"
        entry.category.equals("utility", true) -> "Utility"
        else -> "Utility"
    }

    private fun categoryGlyph(entry: ExtensionEntry): TextView = TextView(this).apply {
        text = if (categoryFor(entry) == "Download") "⇩" else "↗"
        textSize = 28f
        gravity = Gravity.CENTER
        setTextColor(PEACH)
        layoutParams = LinearLayout.LayoutParams(dp(58), dp(58))
    }

    private fun addMessage(message: String) {
        list.addView(TextView(this).apply {
            text = message
            textSize = 15f
            setTextColor(PEACH)
            gravity = Gravity.CENTER
            setPadding(dp(12), dp(28), dp(12), dp(28))
        })
    }

    private fun rounded(color: Int, radius: Int): GradientDrawable = GradientDrawable().apply {
        setColor(color)
        cornerRadius = radius.toFloat()
    }

    private fun getBytes(address: String, limit: Int): ByteArray {
        val connection = (URL(address).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15000
            readTimeout = 25000
            requestMethod = "GET"
            setRequestProperty("User-Agent", "Metro-Stream/1.0")
            setRequestProperty("Accept", "application/json, */*")
        }
        try {
            if (connection.responseCode !in 200..299) throw IllegalStateException("HTTP " + connection.responseCode)
            if (connection.contentLengthLong > limit) throw IllegalStateException("Response is too large")
            return connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                var total = 0
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    total += n
                    if (total > limit) throw IllegalStateException("Response exceeded size limit")
                    output.write(buffer, 0, n)
                }
                output.toByteArray()
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun openUrl(url: String) {
        try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
        catch (_: Exception) { Toast.makeText(this, "No browser available", Toast.LENGTH_SHORT).show() }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private data class ExtensionEntry(
        val id: String,
        val displayName: String,
        val version: String,
        val description: String,
        val category: String,
        val tags: List<String>,
        val iconUrl: String
    )
}
''', encoding="utf-8")

(root / "MORNYE_EXTENSION_NOTICE.md").write_text(
    """# Mornye Extension Runtime Integration

Metro Stream embeds Mornye's mobile Rust/QuickJS extension backend. Its Extension Repo uses the official registry at https://github.com/mornyeapp/Mornye-Extension. Package downloads go through Mornye's ExtensionRepository, which validates supported runtime, archive integrity, and the published SHA-256 digest; packages are then installed and enabled with ExtensionManager.

SoundCloud is excluded from Metro Stream's Extension Repo and is not used as a built-in streaming provider. Other providers are exposed according to the upstream registry and their declared capabilities, account requirements, and service terms.

Mornye is licensed under LGPL-3.0-only with the incorporated GPL-3.0 terms; upstream notices and licenses are retained in the native backend checkout used by the build.
""",
    encoding="utf-8",
)

print("Mornye Rust/QuickJS runtime and Extension Repo UI integrated; SoundCloud excluded.")
