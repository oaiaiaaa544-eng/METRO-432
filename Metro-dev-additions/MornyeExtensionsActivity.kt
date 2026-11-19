package code.name.monkey.retromusic.online

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
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

/** Metro Stream's Mornye-powered Extension Repo screen. */
class MornyeExtensionsActivity : AppCompatActivity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val entries = ArrayList<Entry>()
    private val installedIds = HashSet<String>()
    private var category = "All"
    private var manager: ExtensionManager? = null
    private var repository: ExtensionRepository? = null
    private lateinit var list: LinearLayout
    private lateinit var count: TextView
    private lateinit var search: EditText
    private lateinit var progress: ProgressBar
    private lateinit var filters: MutableMap<String, MaterialButton>

    companion object {
        private const val REGISTRY = "https://raw.githubusercontent.com/mornyeapp/Mornye-Extension/main/registry.json"
        private const val REPO = "https://github.com/mornyeapp/Mornye-Extension"
        private const val BG = 0xFF000000.toInt()
        private const val SURFACE = 0xFF151515.toInt()
        private const val SURFACE2 = 0xFF202020.toInt()
        private const val PEACH = 0xFFE6C9C4.toInt()
        private const val ACCENT = 0xFFFFB4A8.toInt()
        private const val TEXT = 0xFFF9F4F3.toInt()
        private const val MUTED = 0xFFB9A6A2.toInt()
        private const val INSTALLED = 0xFF777777.toInt()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Extension Repo"
        window.statusBarColor = SURFACE
        window.navigationBarColor = BG
        window.decorView.systemUiVisibility = 0
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        buildUi()
        refresh()
    }

    override fun onDestroy() {
        try { repository?.shutdown(); repository?.close() } catch (_: Exception) {}
        try { manager?.shutdown(); manager?.close() } catch (_: Exception) {}
        scope.cancel()
        super.onDestroy()
    }

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(BG)
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(12), dp(10), dp(12))
            setBackgroundColor(SURFACE)
        }
        bar.addView(TextView(this).apply {
            text = "Extension Repo"
            textSize = 25f
            setTextColor(TEXT)
            typeface = Typeface.create("sans-serif", Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, -2, 1f)
        })
        bar.addView(topAction("▶", "Open Metro Player") {
            startActivity(Intent(this, code.name.monkey.retromusic.activities.MainActivity::class.java))
        })
        bar.addView(topAction("↗", "Open Mornye Extension Repo") { openUrl(REPO) })
        root.addView(bar)

        val searchBox = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(18), 0, dp(18), 0)
            background = rounded(SURFACE2, 100)
        }
        searchBox.addView(TextView(this).apply {
            text = "⌕"
            textSize = 34f
            setTextColor(PEACH)
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(dp(42), -1)
        })
        search = EditText(this).apply {
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
        searchBox.addView(search)
        root.addView(searchBox, LinearLayout.LayoutParams(-1, dp(62)).apply {
            setMargins(0, 0, 0, dp(14))
        })

        val filterScroll = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            clipToPadding = false
            layoutParams = LinearLayout.LayoutParams(-1, dp(48)).apply { bottomMargin = dp(18) }
        }
        val filterRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        filters = linkedMapOf()
        listOf("All", "Metadata", "Download", "Utility").forEach { name ->
            val chip = MaterialButton(this).apply {
                text = when (name) {
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
                    category = name
                    updateFilters()
                    render()
                }
            }
            filters[name] = chip
            filterRow.addView(chip, LinearLayout.LayoutParams(-2, dp(44)).apply { marginEnd = dp(10) })
        }
        filterScroll.addView(filterRow)
        root.addView(filterScroll)
        updateFilters()

        count = TextView(this).apply {
            text = "Loading extensions..."
            textSize = 16f
            setTextColor(PEACH)
            setPadding(dp(16), 0, dp(16), dp(14))
        }
        root.addView(count)
        val scroller = ScrollView(this).apply {
            overScrollMode = android.view.View.OVER_SCROLL_NEVER
            clipToPadding = false
        }
        list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, 0, dp(12))
        }
        scroller.addView(list)
        root.addView(scroller, LinearLayout.LayoutParams(-1, 0, 1f))
        progress = ProgressBar(this).apply { visibility = android.view.View.GONE }
        root.addView(progress, LinearLayout.LayoutParams(-2, -2).apply {
            gravity = Gravity.CENTER_HORIZONTAL
        })
        val player = MaterialButton(this).apply {
            text = "Open Metro Player"
            isAllCaps = false
            textSize = 15f
            setTextColor(0xFF401B17.toInt())
            backgroundTintList = ColorStateList.valueOf(ACCENT)
            cornerRadius = dp(18)
            setOnClickListener {
                startActivity(Intent(this@MornyeExtensionsActivity,
                    code.name.monkey.retromusic.activities.MainActivity::class.java))
            }
        }
        root.addView(player, LinearLayout.LayoutParams(-1, dp(52)).apply {
            setMargins(dp(16), dp(8), dp(16), dp(12))
        })
        setContentView(root)
        search.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { render() }
            override fun afterTextChanged(s: Editable?) {}
        })
    }

    private fun topAction(glyph: String, hint: String, action: () -> Unit) = TextView(this).apply {
        text = glyph
        contentDescription = hint
        textSize = 25f
        setTextColor(PEACH)
        gravity = Gravity.CENTER
        layoutParams = LinearLayout.LayoutParams(dp(44), dp(44))
        setOnClickListener { action() }
    }

    private fun updateFilters() {
        filters.forEach { (key, chip) ->
            val selected = key == category
            chip.backgroundTintList = ColorStateList.valueOf(if (selected) 0xFF61413D.toInt() else BG)
            chip.strokeColor = ColorStateList.valueOf(if (selected) 0xFF61413D.toInt() else 0xFF55413E.toInt())
            chip.setTextColor(if (selected) ACCENT else PEACH)
        }
    }

    private fun refresh() {
        progress.visibility = android.view.View.VISIBLE
        count.text = "Loading extensions..."
        scope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    val native = ensureRuntime()
                    val catalog = fetchRegistry()
                    val installed = readInstalled(native.first)
                    Pair(catalog, installed)
                }
                entries.clear()
                entries.addAll(result.first)
                installedIds.clear()
                installedIds.addAll(result.second)
                render()
            } catch (error: Exception) {
                count.text = "Extension catalogue unavailable"
                list.removeAllViews()
                message("Could not load the Mornye Extension Repo: " + (error.message ?: "network error"))
            } finally {
                progress.visibility = android.view.View.GONE
            }
        }
    }

    @Synchronized
    private fun ensureRuntime(): Pair<ExtensionManager, ExtensionRepository> {
        if (manager != null && repository != null) return Pair(manager!!, repository!!)
        System.loadLibrary("mornye_mobile")
        val base = File(filesDir, "mornye").apply { mkdirs() }
        val keyFile = File(noBackupFilesDir, "mornye-master-key")
        val nativeManager = ExtensionManager.withLyricsSettings(
            File(base, "installed").absolutePath,
            File(base, "extension-data").absolutePath,
            loadMasterKey(keyFile),
            "5.4.0",
            30_000uL,
            "[]",
            "{}"
        )
        nativeManager.loadAll()
        val nativeRepository = ExtensionRepository(nativeManager,
            File(base, "repository-cache").absolutePath)
        nativeRepository.setRegistryUrls(listOf(REGISTRY))
        manager = nativeManager
        repository = nativeRepository
        return Pair(nativeManager, nativeRepository)
    }

    private fun loadMasterKey(file: File): String {
        if (file.isFile) return file.readText(Charsets.UTF_8).trim()
        file.parentFile?.mkdirs()
        val bytes = ByteArray(32)
        SecureRandom().nextBytes(bytes)
        val value = Base64.encodeToString(bytes, Base64.NO_WRAP)
        file.writeText(value, Charsets.UTF_8)
        return value
    }

    private fun readInstalled(nativeManager: ExtensionManager): Set<String> {
        val items = JSONArray(nativeManager.installed())
        val result = HashSet<String>()
        for (i in 0 until items.length()) {
            val item = items.optJSONObject(i) ?: continue
            val id = item.optString("id", item.optString("name"))
            if (id.isNotBlank()) result.add(id)
        }
        return result
    }

    private fun fetchRegistry(): List<Entry> {
        val root = JSONObject(String(readUrl(REGISTRY, 4 * 1024 * 1024), Charsets.UTF_8))
        val array = root.optJSONArray("extensions") ?: return emptyList()
        val result = ArrayList<Entry>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val id = item.optString("id")
            if (id.isBlank() || id.equals("soundcloud", true)) continue
            val packageUrl = item.optString("download_url")
            val digest = item.optString("sha256")
            if (!id.matches(Regex("[A-Za-z0-9._-]{1,80}"))) continue
            if (!packageUrl.startsWith("https://raw.githubusercontent.com/mornyeapp/Mornye-Extension/")) continue
            if (!digest.matches(Regex("[a-fA-F0-9]{64}"))) continue
            val tags = ArrayList<String>()
            item.optJSONArray("tags")?.let { tagArray ->
                for (j in 0 until tagArray.length()) tags.add(tagArray.optString(j))
            }
            result.add(Entry(
                id,
                item.optString("display_name", item.optString("name", id)),
                item.optString("version"),
                item.optString("description", "No description supplied."),
                item.optString("category", "utility"),
                tags,
                item.optString("icon_url"),
                packageUrl,
                digest
            ))
        }
        return result.sortedWith(compareBy<Entry> { categoryFor(it) }.thenBy { it.name.lowercase() })
    }

    private fun install(entry: Entry, button: MaterialButton) {
        button.isEnabled = false
        button.text = "Installing..."
        progress.visibility = android.view.View.VISIBLE
        scope.launch {
            try {
                val found = withContext(Dispatchers.IO) {
                    val (nativeManager, nativeRepository) = ensureRuntime()
                    val destination = File(filesDir, "mornye/packages").apply { mkdirs() }
                    val packagePath = nativeRepository.download(entry.id, destination.absolutePath, "")
                    nativeManager.install(packagePath)
                    nativeManager.setEnabled(entry.id, true)
                    readInstalled(nativeManager)
                }
                installedIds.clear()
                installedIds.addAll(found)
                Toast.makeText(this@MornyeExtensionsActivity,
                    entry.name + " installed", Toast.LENGTH_LONG).show()
                render()
            } catch (error: Exception) {
                button.text = "Install"
                button.isEnabled = true
                Toast.makeText(this@MornyeExtensionsActivity,
                    "Install failed: " + (error.message ?: "unknown error"), Toast.LENGTH_LONG).show()
            } finally {
                progress.visibility = android.view.View.GONE
            }
        }
    }

    private fun render() {
        if (!::list.isInitialized) return
        val query = search.text.toString().trim().lowercase()
        val visible = entries.filter { entry ->
            val matchCategory = category == "All" || categoryFor(entry) == category
            val haystack = (entry.name + " " + entry.id + " " + entry.description + " " + entry.tags.joinToString(" ")).lowercase()
            matchCategory && (query.isEmpty() || haystack.contains(query))
        }
        count.text = visible.size.toString() + " extensions"
        list.removeAllViews()
        if (visible.isEmpty()) {
            message(if (query.isEmpty()) "No extensions in this category." else "No extensions match your search.")
            return
        }
        visible.forEach { list.addView(card(it)) }
    }

    private fun card(entry: Entry): View {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(14), dp(16), dp(14), dp(16))
            background = rounded(SURFACE, dp(18))
            layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(6) }
        }
        val iconBox = LinearLayout(this).apply {
            gravity = Gravity.CENTER
            background = rounded(if (entry.id == "ytmusic-spotiflac") Color.BLACK else
                if (categoryFor(entry) == "Download") 0xFF74352F.toInt() else SURFACE2, dp(16))
            layoutParams = LinearLayout.LayoutParams(dp(58), dp(58)).apply { marginEnd = dp(16) }
        }
        if (entry.icon.isNotBlank()) {
            val image = ImageView(this).apply {
                scaleType = ImageView.ScaleType.CENTER_CROP
                layoutParams = LinearLayout.LayoutParams(dp(58), dp(58))
            }
            Glide.with(this).load(entry.icon)
                .placeholder(ColorDrawable(SURFACE2)).error(ColorDrawable(SURFACE2))
                .into(image)
            iconBox.addView(image)
        } else {
            iconBox.addView(TextView(this).apply {
                text = if (categoryFor(entry) == "Download") "⇩" else "↗"
                textSize = 28f
                gravity = Gravity.CENTER
                setTextColor(PEACH)
            })
        }
        card.addView(iconBox)

        val detail = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, -2, 1f)
        }
        val nameRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        nameRow.addView(TextView(this).apply {
            text = entry.name
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
            background = rounded(SURFACE2, dp(12))
            setPadding(dp(8), dp(4), dp(8), dp(4))
        })
        detail.addView(nameRow)
        detail.addView(TextView(this).apply {
            text = entry.description
            textSize = 14f
            setTextColor(PEACH)
            maxLines = 2
            ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding(0, dp(5), 0, 0)
        })
        card.addView(detail)

        val alreadyInstalled = entry.id in installedIds
        val action = MaterialButton(this).apply {
            text = if (alreadyInstalled) "✓  Installed" else "Install"
            isAllCaps = false
            textSize = 14f
            cornerRadius = dp(40)
            minWidth = dp(94)
            minHeight = dp(48)
            insetTop = 0
            insetBottom = 0
            if (alreadyInstalled) {
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
            marginStart = dp(10)
        })
        return card
    }

    private fun categoryFor(entry: Entry): String = when {
        entry.category.equals("integration", true) ||
            entry.category.equals("metadata", true) -> "Metadata"
        entry.category.equals("download", true) -> "Download"
        else -> "Utility"
    }

    private fun message(value: String) {
        list.addView(TextView(this).apply {
            text = value
            textSize = 15f
            setTextColor(PEACH)
            gravity = Gravity.CENTER
            setPadding(dp(12), dp(28), dp(12), dp(28))
        })
    }

    private fun rounded(color: Int, radius: Int) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = radius.toFloat()
    }

    private fun readUrl(address: String, limit: Int): ByteArray {
        val connection = (URL(address).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15000
            readTimeout = 25000
            setRequestProperty("User-Agent", "Metro-Stream/1.0")
        }
        try {
            if (connection.responseCode !in 200..299) throw IllegalStateException("HTTP " + connection.responseCode)
            if (connection.contentLengthLong > limit) throw IllegalStateException("Registry is too large")
            return connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                var total = 0
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    total += n
                    if (total > limit) throw IllegalStateException("Registry exceeded size limit")
                    output.write(buffer, 0, n)
                }
                output.toByteArray()
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun openUrl(address: String) {
        try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(address))) }
        catch (_: Exception) {
            Toast.makeText(this, "No browser available", Toast.LENGTH_SHORT).show()
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private data class Entry(
        val id: String,
        val name: String,
        val version: String,
        val description: String,
        val category: String,
        val tags: List<String>,
        val icon: String,
        val packageUrl: String,
        val sha256: String
    )
}
