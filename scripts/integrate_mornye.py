#!/usr/bin/env python3
"""Integrate Mornye's Flutter Android host as a library inside METRO."""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1]).resolve()
metro, mornye = root / "Metro-dev", root / "Mornye"
android = mornye / "android"
if not (metro / "app/build.gradle").exists() or not (android / "app/build.gradle.kts").exists():
    raise SystemExit("Expected Metro-dev and Mornye source trees")

def r(p): return p.read_text(encoding="utf-8")
def w(p, s): p.write_text(s, encoding="utf-8")
def once(s, old, new, label):
    if s.count(old) != 1: raise SystemExit(f"{label}: expected one insertion point, got {s.count(old)}")
    return s.replace(old, new, 1)

w(android / "settings.gradle.kts", '''pluginManagement {
    val flutterSdkPath = run {
        val properties = java.util.Properties()
        file("local.properties").inputStream().use { properties.load(it) }
        properties.getProperty("flutter.sdk") ?: error("flutter.sdk missing in local.properties")
    }
    includeBuild("$flutterSdkPath/packages/flutter_tools/gradle")
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "9.5.1" apply false
    id("com.android.library") version "9.5.1" apply false
    id("org.jetbrains.kotlin.android") version "2.4.21" apply false
    id("org.jetbrains.kotlin.plugin.parcelize") version "2.4.21" apply false
    id("com.google.devtools.ksp") version "2.3.12" apply false
    id("androidx.navigation.safeargs.kotlin") version "2.9.6" apply false
}
include(":mornye")
project(":mornye").projectDir = file("app")
include(":metro")
project(":metro").projectDir = file("../../Metro-dev/app")
include(":appthemehelper")
project(":appthemehelper").projectDir = file("../../Metro-dev/appthemehelper")
''')
w(android / "build.gradle.kts", '''allprojects {
    repositories {
        google()
        mavenCentral()
        maven { url = uri("https://jitpack.io") }
    }
}
extra["media3Version"] = "1.11.1"
subprojects {
    configurations.configureEach {
        resolutionStrategy.eachDependency {
            if (requested.group == "androidx.media3") {
                useVersion(rootProject.extra["media3Version"] as String)
            }
        }
    }
}
val newBuildDir = rootProject.layout.buildDirectory.dir("../../build").get()
rootProject.layout.buildDirectory.value(newBuildDir)
subprojects { project.layout.buildDirectory.value(newBuildDir.dir(project.name)) }
project.evaluationDependsOn(":mornye")
tasks.register<Delete>("clean") { delete(rootProject.layout.buildDirectory) }
''')
gp = android / "gradle.properties"
props = {"lifecycle_version":"2.6.1", "navigation_version":"2.9.6", "mdc_version":"1.9.0-beta01",
         "preference_version":"1.2.0", "appcompat_version":"1.6.1", "core_version":"1.10.0-rc01"}
gpt = r(gp) if gp.exists() else ""
for k,v in props.items():
    if not re.search(rf"(?m)^{k}=", gpt): gpt += ("" if not gpt or gpt.endswith("\n") else "\n") + f"{k}={v}\n"
w(gp, gpt)

w(android / "app/build.gradle.kts", '''plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("dev.flutter.flutter-gradle-plugin")
}
val buildDartDefines = providers.exec {
    workingDir(rootProject.projectDir.parentFile)
    commandLine("bash", "scripts/flutter_git_commit.sh", project.findProperty("dart-defines")?.toString().orEmpty())
}.standardOutput.asText.get().trim()
project.extensions.extraProperties["dart-defines"] = buildDartDefines
if (!project.hasProperty("split-debug-info") && !project.hasProperty("code-size-directory")) {
    project.extensions.extraProperties["split-debug-info"] = rootProject.file("../build/symbols/android").absolutePath
}
val rustBackendDir = rootProject.file("../rust_backend")
val rustAndroidAbis = providers.environmentVariable("MORNYE_RUST_ANDROID_ABIS").orElse("arm64-v8a,armeabi-v7a").get().split(",")
val validAbis = setOf("arm64-v8a", "armeabi-v7a")
require(rustAndroidAbis.isNotEmpty() && rustAndroidAbis.size == rustAndroidAbis.toSet().size && rustAndroidAbis.all { it in validAbis }) {
    "MORNYE_RUST_ANDROID_ABIS must contain unique arm64-v8a and/or armeabi-v7a values"
}
val discordSdkEnabled = providers.environmentVariable("MORNYE_DISCORD_SDK").orElse("1").get() != "0"
android {
    namespace = "com.zarz.mornye"
    compileSdk = 37
    ndkVersion = "30.0.16248370"
    buildFeatures { buildConfig = true }
    packaging { if (discordSdkEnabled) jniLibs.pickFirsts += "**/libdiscord_partner_sdk.so" }
    externalNativeBuild { cmake { path = file("src/main/cpp/CMakeLists.txt"); version = "4.1.2" } }
    sourceSets.getByName("main") {
        java.srcDir("src/rust/kotlin")
        java.srcDir(rustBackendDir.resolve("target/bindings/kotlin"))
        jniLibs.srcDir(rustBackendDir.resolve("target/android/jniLibs"))
    }
    compileOptions {
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_25
        targetCompatibility = JavaVersion.VERSION_25
    }
    kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_25) } }
    defaultConfig {
        minSdk = 24
        consumerProguardFiles("proguard-rules.pro")
        buildConfigField("String", "APPLICATION_ID", "\\"com.zarz.mornye\\"")
        buildConfigField("int", "VERSION_CODE", "169")
        buildConfigField("String", "VERSION_NAME", "\\"5.4.0\\"")
        externalNativeBuild { cmake { arguments += listOf("-DANDROID_STL=c++_static", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5") } }
        ndk { abiFilters += rustAndroidAbis }
    }
}
val buildRustBackend = tasks.register<Exec>("buildRustBackend") {
    workingDir(rootProject.projectDir.parentFile)
    commandLine("bash", "scripts/build_rust_backend.sh", "android")
    environment("MORNYE_RUST_ANDROID_ABIS", rustAndroidAbis.joinToString(","))
    environment("ANDROID_NDK_HOME", System.getenv("ANDROID_NDK_HOME") ?: android.sdkDirectory.resolve("ndk/30.0.16248370").absolutePath)
    inputs.files(fileTree(rustBackendDir) {
        include("**/*.rs", "**/*.toml", "**/*.lock", "**/*.js", "**/*.tsv", "**/*.pem")
        exclude("target/**", "smoke/**")
    })
    inputs.property("MORNYE_RUST_ANDROID_ABIS", rustAndroidAbis.joinToString(","))
    inputs.file(rootProject.file("../scripts/build_rust_backend.sh"))
    outputs.dir(rustBackendDir.resolve("target/bindings/kotlin"))
    outputs.dir(rustBackendDir.resolve("target/android/jniLibs"))
}
tasks.named("preBuild").configure { dependsOn(buildRustBackend) }
tasks.withType<org.gradle.api.tasks.Copy>().configureEach {
    if (name.startsWith("copyFlutterAssets")) {
        exclude(
            "flutter_assets/packages/liquid_glass_easy/lib/assets/shaders/liquid_glass_desktop.frag",
            "flutter_assets/packages/liquid_glass_easy/lib/assets/shaders/metaball_glass_desktop.frag",
            "flutter_assets/packages/flutter_local_notifications_web/web/notifications_service_worker.js",
        )
    }
}
flutter { source = "../.." }
dependencies {
    val discordSdk = file("../../third_party/mornye_discord/sdk/discord_partner_sdk.aar")
    if (discordSdkEnabled && discordSdk.exists()) implementation(files(discordSdk))
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
    implementation("net.java.dev.jna:jna:5.19.1@aar")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.11.0")
    implementation("androidx.documentfile:documentfile:1.1.0")
    implementation("androidx.activity:activity-ktx:1.13.0")
    implementation("com.google.android.gms:play-services-cast-framework:23.0.0")
    implementation("androidx.media3:media3-exoplayer:" + rootProject.extra["media3Version"])
    compileOnly("com.antonkarpenko:ffmpeg-kit-audio:2.2.3")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20260814")
    debugImplementation("androidx.test:runner:1.7.0")
    debugImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.media:media:1.8.0")
}
''')

mapp = android / "app/src/main/kotlin/com/zarz/mornye/MornyeApplication.kt"
s = r(mapp).replace("import android.app.Application\n", "")
s = s.replace("class MornyeApplication : Application() {", "open class MornyeApplication : android.app.Application() {")
s = s.replace("    override fun onCreate() {", "    open override fun onCreate() {")
w(mapp, s)
mf = android / "app/src/main/AndroidManifest.xml"
s = r(mf).replace('        android:name=".MornyeApplication"\n', "")
launcher = '''            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
                <category android:name="android.intent.category.LEANBACK_LAUNCHER"/>
            </intent-filter>
'''
if launcher in s: s = s.replace(launcher, "", 1)
elif "android.intent.category.LAUNCHER" in s: raise SystemExit("Mornye launcher filter changed unexpectedly")
s = s.replace('android:name="androidx.core.content.FileProvider"', 'android:name=".MornyeFileProvider"', 1)
w(mf, s)
w(android / "app/src/main/kotlin/com/zarz/mornye/MornyeFileProvider.kt",
  "package com.zarz.mornye\n\n/** Isolated provider identity inside the METRO host APK. */\nclass MornyeFileProvider : androidx.core.content.FileProvider()\n")

appg = metro / "app/build.gradle"
s = r(appg)
s = re.sub(r"(?s)^apply plugin:.*?\n\nandroid \{", """plugins {
    id 'com.android.application'
    id 'org.jetbrains.kotlin.android'
    id 'androidx.navigation.safeargs.kotlin'
    id 'org.jetbrains.kotlin.plugin.parcelize'
    id 'com.google.devtools.ksp'
}

android {""", s, count=1)
s = s.replace("compileSdk 33", "compileSdk 37").replace("minSdk 21", "minSdk 24")
s = s.replace("buildFeatures {\n        viewBinding true\n    }", "buildFeatures {\n        viewBinding true\n        buildConfig true\n    }")
if "implementation project(':mornye')" not in s:
    s = once(s, "implementation project(':appthemehelper')", "implementation project(':appthemehelper')\n    implementation project(':mornye')", "Metro dependency")
w(appg, s)
theme = metro / "appthemehelper/build.gradle"
s = r(theme).replace("apply plugin: 'com.android.library'\napply plugin: 'kotlin-android'",
'''plugins {
    id 'com.android.library'
    id 'org.jetbrains.kotlin.android'
}''')
s = s.replace("compileSdk 33", "compileSdk 37").replace("        targetSdk 33\n", "")
w(theme, s)
metro_manifest = metro / "app/src/main/AndroidManifest.xml"
if 'android:name=".App"' not in r(metro_manifest): raise SystemExit("METRO Application declaration not found")

home = metro / "app/src/main/res/layout/home_content.xml"
s = r(home)
if "@+id/mornyeCard" not in s:
    anchor = '''    <include
        android:id="@+id/abs_playlists"
        layout="@layout/abs_playlists" />
'''
    card = anchor + '''
    <com.google.android.material.card.MaterialCardView
        android:id="@+id/mornyeCard"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginStart="16dp"
        android:layout_marginTop="12dp"
        android:layout_marginEnd="16dp"
        android:layout_marginBottom="8dp"
        android:clickable="true"
        android:focusable="true"
        android:foreground="?attr/selectableItemBackground"
        app:cardCornerRadius="16dp"
        app:cardElevation="1dp"
        app:strokeWidth="0dp">
        <LinearLayout
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:gravity="center_vertical"
            android:orientation="horizontal"
            android:padding="16dp">
            <ImageView
                android:layout_width="42dp"
                android:layout_height="42dp"
                android:contentDescription="@string/mornye"
                android:src="@drawable/ic_library_music"
                android:tint="?attr/colorControlActivated" />
            <LinearLayout
                android:layout_width="0dp"
                android:layout_height="wrap_content"
                android:layout_marginStart="14dp"
                android:layout_weight="1"
                android:orientation="vertical">
                <TextView
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:text="@string/mornye"
                    android:textAppearance="?attr/textAppearanceSubtitle1"
                    android:textStyle="bold" />
                <TextView
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="3dp"
                    android:text="@string/mornye_home_summary"
                    android:textAppearance="?attr/textAppearanceBody2" />
            </LinearLayout>
            <ImageView
                android:layout_width="24dp"
                android:layout_height="24dp"
                android:contentDescription="@string/open_mornye"
                android:src="@drawable/ic_keyboard_arrow_right" />
        </LinearLayout>
    </com.google.android.material.card.MaterialCardView>
'''
    if 'xmlns:app=' not in s:
        s = s.replace('xmlns:tools="http://schemas.android.com/tools"',
                      'xmlns:tools="http://schemas.android.com/tools"\n    xmlns:app="http://schemas.android.com/apk/res-auto"', 1)
    s = once(s, anchor, card, "For You layout")
    w(home, s)
strings = metro / "app/src/main/res/values/strings.xml"
s = r(strings)
if '<string name="mornye">Mornye</string>' not in s:
    s = s.replace("<resources>", '''<resources>
    <string name="mornye">Mornye</string>
    <string name="open_mornye">Open Mornye</string>
    <string name="mornye_home_summary">Search music, connect extensions and stream your picks</string>
    <string name="mornye_settings_summary">Open Mornye music search, streaming and extensions</string>''', 1)
    w(strings, s)
home_fragment = metro / "app/src/main/java/code/name/monkey/retromusic/fragments/home/HomeFragment.kt"
s = r(home_fragment)
if "com.zarz.mornye.MainActivity" not in s:
    s = s.replace("import android.os.Bundle\n", "import android.content.Intent\nimport android.os.Bundle\n", 1)
    s = once(s, "    private fun setupListeners() {\n",
        "    private fun setupListeners() {\n        binding.mornyeCard.setOnClickListener {\n            startActivity(Intent(requireContext(), com.zarz.mornye.MainActivity::class.java))\n        }\n", "HomeFragment")
    w(home_fragment, s)
binding = metro / "app/src/main/java/code/name/monkey/retromusic/fragments/home/HomeBinding.kt"
s = r(binding)
if "mornyeCard" not in s:
    s = s.replace("    val suggestions = homeBinding.homeContent.suggestions\n",
        "    val suggestions = homeBinding.homeContent.suggestions\n" +
        "    val mornyeCard = homeBinding.homeContent.root.findViewById<android.view.View>(code.name.monkey.retromusic.R.id.mornyeCard)\n", 1)
    w(binding, s)
settings_xml = metro / "app/src/main/res/layout/fragment_main_settings.xml"
s = r(settings_xml)
if "@+id/mornyeSettings" not in s:
    row = '''        <code.name.monkey.retromusic.views.SettingListItemView
            android:id="@+id/mornyeSettings"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            app:settingListItemIcon="@drawable/ic_library_music"
            app:settingListItemIconColor="@color/md_deep_purple_A400"
            app:settingListItemText="@string/mornye_settings_summary"
            app:settingListItemTitle="@string/mornye" />

'''
    s = once(s, '        <code.name.monkey.retromusic.views.SettingListItemView\n            android:id="@+id/audioSettings"', row +
        '        <code.name.monkey.retromusic.views.SettingListItemView\n            android:id="@+id/audioSettings"', "Settings layout")
    w(settings_xml, s)
settings_fragment = metro / "app/src/main/java/code/name/monkey/retromusic/fragments/settings/MainSettingsFragment.kt"
s = r(settings_fragment)
if "R.id.mornyeSettings" not in s:
    s = s.replace("import android.os.Bundle\n", "import android.content.Intent\nimport android.os.Bundle\n", 1)
    s = once(s, "    override fun onClick(view: View) {\n",
        "    override fun onClick(view: View) {\n        if (view.id == R.id.mornyeSettings) {\n            startActivity(Intent(requireContext(), com.zarz.mornye.MainActivity::class.java))\n            return\n        }\n", "Settings click handler")
if "binding.mornyeSettings.setOnClickListener(this)" not in s:
    s = once(s, "        binding.audioSettings.setOnClickListener(this)\n",
        "        binding.audioSettings.setOnClickListener(this)\n        binding.mornyeSettings.setOnClickListener(this)\n", "Settings listener")
w(settings_fragment, s)
appkt = metro / "app/src/main/java/code/name/monkey/retromusic/App.kt"
s = r(appkt)
if "import com.zarz.mornye.MornyeApplication" not in s:
    s = s.replace("import android.app.Application\n", "", 1)
    s = s.replace("import org.koin.android.ext.koin.androidContext\n",
                  "import com.zarz.mornye.MornyeApplication\nimport org.koin.android.ext.koin.androidContext\n", 1)
    s = s.replace("class App : Application() {", "class App : MornyeApplication() {")
w(appkt, s)

assert "implementation project(':mornye')" in r(appg)
assert "class App : MornyeApplication()" in r(appkt)
assert "com.zarz.mornye.MainActivity" in r(home_fragment)
assert "com.zarz.mornye.MainActivity" in r(settings_fragment)
assert 'android:name=".MornyeApplication"' not in r(mf)
assert 'android:name=".MornyeFileProvider"' in r(mf)
assert "android.intent.action.MAIN" not in r(mf)
assert 'android:key="tuning_frequency"' in r(metro / "app/src/main/res/xml/pref_audio.xml")
print("Mornye embedded into METRO source; UI links, app bootstrap, and 432 Hz tuning checks passed.")
