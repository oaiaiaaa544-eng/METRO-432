#!/usr/bin/env python3
"""Add independent A=432/528/639 tuning systems without changing playback tempo."""
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_solfeggio.py <Metro-dev directory>")
root = Path(sys.argv[1])


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = root / relative_path
    data = path.read_text(encoding="utf-8")
    count = data.count(old)
    if count != 1:
        raise SystemExit(f"Expected one match in {relative_path}; found {count}")
    path.write_text(data.replace(old, new, 1), encoding="utf-8")


def add_string(name: str, value: str) -> None:
    path = root / "app/src/main/res/values/strings.xml"
    data = path.read_text(encoding="utf-8")
    if f'name="{name}"' not in data:
        data = data.replace(
            "</resources>",
            f'    <string name="{name}">{value}</string>\n</resources>',
            1,
        )
        path.write_text(data, encoding="utf-8")


# Preference key and read-only getter. The selection is global and defaults to A=432.
constants = root / "app/src/main/java/code/name/monkey/retromusic/Constants.kt"
constants_text = constants.read_text(encoding="utf-8")
if 'const val TUNING_FREQUENCY = "tuning_frequency"' not in constants_text:
    replace_once(
        "app/src/main/java/code/name/monkey/retromusic/Constants.kt",
        'const val PLAYBACK_PITCH = "playback_pitch"\n',
        'const val PLAYBACK_PITCH = "playback_pitch"\n'
        'const val TUNING_FREQUENCY = "tuning_frequency"\n',
    )

# Keep these legacy constants available if the base patch references them.
constants_text = constants.read_text(encoding="utf-8")
missing_mode_constants = []
if "const val TUNING_MODE_RATE" not in constants_text:
    missing_mode_constants.append('const val TUNING_MODE_RATE = "rate"\n')
if "const val TUNING_MODE_PITCH" not in constants_text:
    missing_mode_constants.append('const val TUNING_MODE_PITCH = "pitch"\n')
if missing_mode_constants:
    constants.write_text(
        constants_text.rstrip() + "\n" + "".join(missing_mode_constants),
        encoding="utf-8",
    )

pref_util = root / "app/src/main/java/code/name/monkey/retromusic/util/PreferenceUtil.kt"
pref_text = pref_util.read_text(encoding="utf-8")
if "val tuningFrequency: Int" not in pref_text:
    marker = "    var playbackSpeed\n"
    if pref_text.count(marker) != 1:
        raise SystemExit("Could not locate playbackSpeed in PreferenceUtil.kt")
    tuning_property = (
        '    val tuningFrequency: Int\n'
        '        get() = sharedPreferences.getString(TUNING_FREQUENCY, "432")?.toIntOrNull() ?: 432\n\n'
    )
    pref_util.write_text(pref_text.replace(marker, tuning_property + marker, 1), encoding="utf-8")

# Update the running player when the global A-reference changes. The base patch
# may already have grouped TUNING_FREQUENCY with the speed/pitch preference keys,
# or may have created a dedicated branch; normalize either form.
music_service_path = "app/src/main/java/code/name/monkey/retromusic/service/MusicService.kt"
service_file = root / music_service_path
service_text = service_file.read_text(encoding="utf-8")
branch_pattern = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?P<label>(?:PLAYBACK_SPEED|PLAYBACK_PITCH|TUNING_FREQUENCY)"
    r"(?:[ \t]*,[ \t]*(?:PLAYBACK_SPEED|PLAYBACK_PITCH|TUNING_FREQUENCY))*)"
    r"[ \t]*->[ \t]*\{.*?^\1\}",
    re.DOTALL,
)
branch_match = branch_pattern.search(service_text)
new_branch = """\g<indent>PLAYBACK_SPEED, PLAYBACK_PITCH, TUNING_FREQUENCY -> {
\g<indent>    updateMediaSessionPlaybackState()
\g<indent>    val tuningRatio = code.name.monkey.retromusic.util.PreferenceUtil.tuningFrequency.toFloat() / 440F
\g<indent>    playbackManager.setPlaybackSpeedPitch(playbackSpeed, playbackPitch * tuningRatio)
\g<indent>}"""
if branch_match:
    service_text = service_text[:branch_match.start()] + branch_match.expand(new_branch) + service_text[branch_match.end():]
elif "TUNING_FREQUENCY ->" not in service_text:
    crossfade_case = "            CROSS_FADE_DURATION -> {"
    if service_text.count(crossfade_case) != 1:
        raise SystemExit("Could not locate CROSS_FADE_DURATION in MusicService.kt")
    service_text = service_text.replace(
        crossfade_case,
        """            TUNING_FREQUENCY -> {
                updateMediaSessionPlaybackState()
                val tuningRatio = code.name.monkey.retromusic.util.PreferenceUtil.tuningFrequency.toFloat() / 440F
                playbackManager.setPlaybackSpeedPitch(playbackSpeed, playbackPitch * tuningRatio)
            }

""" + crossfade_case,
        1,
    )
else:
    service_text = re.sub(
        r"(?ms)^([ \t]*)TUNING_FREQUENCY[ \t]*->[ \t]*\{.*?^\1\}",
        """\1TUNING_FREQUENCY -> {
\1    updateMediaSessionPlaybackState()
\1    val tuningRatio = code.name.monkey.retromusic.util.PreferenceUtil.tuningFrequency.toFloat() / 440F
\1    playbackManager.setPlaybackSpeedPitch(playbackSpeed, playbackPitch * tuningRatio)
\1}""",
        service_text,
        count=1,
    )
service_file.write_text(service_text, encoding="utf-8")

# New tracks (including the crossfade-prepared track) use the same pitch-only rule.
local_playback = "app/src/main/java/code/name/monkey/retromusic/service/LocalPlayback.kt"
replace_once(
    local_playback,
    """        val rateMode = PreferenceUtil.tuningMode == "rate"
        try {
            // Rate mode changes tempo and pitch together; Pitch mode changes pitch only.
            player.playbackParams = PlaybackParams()
                .setSpeed((speed * if (rateMode) ratio else 1f).coerceIn(0.1f, 8f))
                .setPitch((pitch * ratio).coerceIn(0.1f, 8f))
""",
    """        try {
            // A-reference tuning shifts pitch only; tempo stays at the user's playback-speed setting.
            player.playbackParams = PlaybackParams()
                .setSpeed(speed.coerceIn(0.1f, 8f))
                .setPitch((pitch * ratio).coerceIn(0.1f, 8f))
""",
)

# Remove the former selector from Audio if a previous patch version placed it there.
audio_xml = root / "app/src/main/res/xml/pref_audio.xml"
audio_text = audio_xml.read_text(encoding="utf-8")
audio_text = re.sub(
    r'\s*<[\w.]+(?=[^>]*android:key="tuning_frequency")[^>]*/>',
    "",
    audio_text,
    flags=re.DOTALL,
)
audio_xml.write_text(audio_text, encoding="utf-8")

# Standalone tuning page: three independent A-reference choices.
arrays = root / "app/src/main/res/values/arrays.xml"
arrays_text = arrays.read_text(encoding="utf-8")
for resource_name in ("tuning_frequency_entries", "tuning_frequency_values"):
    arrays_text, _ = re.subn(
        rf'\s*<(?:string-array|array)\s+name="{resource_name}"[^>]*>.*?</(?:string-array|array)>',
        "",
        arrays_text,
        flags=re.DOTALL,
    )
canonical_arrays = (
    '    <string-array name="tuning_frequency_entries">\n'
    '        <item>A=432 Hz (Default)</item>\n'
    '        <item>A=528 Hz</item>\n'
    '        <item>A=639 Hz</item>\n'
    '    </string-array>\n'
    '    <string-array name="tuning_frequency_values">\n'
    '        <item>432</item>\n'
    '        <item>528</item>\n'
    '        <item>639</item>\n'
    '    </string-array>\n'
)
if "<resources>\n" not in arrays_text:
    raise SystemExit("Could not locate <resources> in arrays.xml")
arrays_text = arrays_text.replace("<resources>\n", "<resources>\n" + canonical_arrays, 1)
arrays.write_text(arrays_text, encoding="utf-8")

strings_path = root / "app/src/main/res/values/strings.xml"
strings_text = strings_path.read_text(encoding="utf-8")
for name, value in {
    "tuning_system_title": "Tuning",
    "tuning_system_settings_summary": "Choose A=432 Hz, A=528 Hz, or A=639 Hz",
    "pref_title_tuning_system": "Reference tuning",
    "pref_summary_tuning_system": "Changes pitch while keeping playback speed at your selected setting.",
}.items():
    add_string(name, value)

(root / "app/src/main/res/xml/pref_tuning.xml").write_text(
    """<?xml version="1.0" encoding="utf-8"?>
<androidx.preference.PreferenceScreen xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto">

    <code.name.monkey.appthemehelper.common.prefs.supportv7.ATEListPreference
        android:defaultValue="432"
        android:entries="@array/tuning_frequency_entries"
        android:entryValues="@array/tuning_frequency_values"
        android:key="tuning_frequency"
        android:layout="@layout/list_item_view"
        android:summary="@string/pref_summary_tuning_system"
        android:title="@string/pref_title_tuning_system" />

</androidx.preference.PreferenceScreen>
""",
    encoding="utf-8",
)

(root / "app/src/main/java/code/name/monkey/retromusic/fragments/settings/TuningSettings.kt").write_text(
    """package code.name.monkey.retromusic.fragments.settings

import android.os.Bundle
import androidx.preference.ListPreference
import code.name.monkey.retromusic.R
import code.name.monkey.retromusic.TUNING_FREQUENCY
import code.name.monkey.retromusic.util.PreferenceUtil

class TuningSettings : AbsSettingsFragment() {
    override fun invalidateSettings() {
        val tuningPreference: ListPreference? = findPreference(TUNING_FREQUENCY)
        tuningPreference?.let { preference ->
            setSummary(preference, PreferenceUtil.tuningFrequency.toString())
            preference.setOnPreferenceChangeListener { changedPreference, newValue ->
                setSummary(changedPreference, newValue)
                true
            }
        }
    }

    override fun onCreatePreferences(savedInstanceState: Bundle?, rootKey: String?) {
        addPreferencesFromResource(R.xml.pref_tuning)
    }
}
""",
    encoding="utf-8",
)

# Put the new Tuning entry directly above Audio on the main Settings screen.
main_layout_path = "app/src/main/res/layout/fragment_main_settings.xml"
main_layout = (root / main_layout_path).read_text(encoding="utf-8")
if 'android:id="@+id/tuningSettings"' not in main_layout:
    audio_tile = '        <code.name.monkey.retromusic.views.SettingListItemView\n            android:id="@+id/audioSettings"'
    tuning_tile = (
        '        <code.name.monkey.retromusic.views.SettingListItemView\n'
        '            android:id="@+id/tuningSettings"\n'
        '            android:layout_width="match_parent"\n'
        '            android:layout_height="wrap_content"\n'
        '            app:settingListItemIcon="@drawable/ic_equalizer"\n'
        '            app:settingListItemIconColor="@color/md_blue_A400"\n'
        '            app:settingListItemText="@string/tuning_system_settings_summary"\n'
        '            app:settingListItemTitle="@string/tuning_system_title" />\n\n'
    )
    replace_once(main_layout_path, audio_tile, tuning_tile + audio_tile)

main_settings_path = "app/src/main/java/code/name/monkey/retromusic/fragments/settings/MainSettingsFragment.kt"
main_settings = (root / main_settings_path).read_text(encoding="utf-8")
if "R.id.tuningSettings ->" not in main_settings:
    replace_once(
        main_settings_path,
        "                R.id.audioSettings -> R.id.action_mainSettingsFragment_to_audioSettings\n",
        "                R.id.tuningSettings -> R.id.action_mainSettingsFragment_to_tuningSettings\n"
        "                R.id.audioSettings -> R.id.action_mainSettingsFragment_to_audioSettings\n",
    )
if "binding.tuningSettings.setOnClickListener(this)" not in main_settings:
    replace_once(
        main_settings_path,
        "        binding.audioSettings.setOnClickListener(this)\n",
        "        binding.tuningSettings.setOnClickListener(this)\n"
        "        binding.audioSettings.setOnClickListener(this)\n",
    )

# Register the destination and action in the Settings navigation graph.
navigation_path = "app/src/main/res/navigation/settings_graph.xml"
navigation_text = (root / navigation_path).read_text(encoding="utf-8")
if 'android:id="@+id/action_mainSettingsFragment_to_tuningSettings"' not in navigation_text:
    action = (
        '        <action\n'
        '            android:id="@+id/action_mainSettingsFragment_to_tuningSettings"\n'
        '            app:destination="@id/tuningSettings"\n'
        '            app:enterAnim="@anim/retro_fragment_open_enter"\n'
        '            app:exitAnim="@anim/retro_fragment_open_exit"\n'
        '            app:popEnterAnim="@anim/retro_fragment_close_enter"\n'
        '            app:popExitAnim="@anim/retro_fragment_close_exit" />\n\n'
    )
    replace_once(
        navigation_path,
        '        <action\n            android:id="@+id/action_mainSettingsFragment_to_audioSettings"',
        action + '        <action\n            android:id="@+id/action_mainSettingsFragment_to_audioSettings"',
    )
if 'android:id="@+id/tuningSettings"' not in navigation_text:
    fragment = (
        '    <fragment\n'
        '        android:id="@+id/tuningSettings"\n'
        '        android:name="code.name.monkey.retromusic.fragments.settings.TuningSettings"\n'
        '        android:label="Tuning" />\n\n'
    )
    replace_once(
        navigation_path,
        '    <fragment\n        android:id="@+id/audioSettings"',
        fragment + '    <fragment\n        android:id="@+id/audioSettings"',
    )
    navigation_text = (root / navigation_path).read_text(encoding="utf-8")

# Show a proper title in the settings toolbar.
settings_fragment_path = "app/src/main/java/code/name/monkey/retromusic/fragments/settings/SettingsFragment.kt"
settings_fragment = (root / settings_fragment_path).read_text(encoding="utf-8")
if "R.id.tuningSettings -> R.string.tuning_system_title" not in settings_fragment:
    replace_once(
        settings_fragment_path,
        "            R.id.audioSettings -> R.string.pref_header_audio\n",
        "            R.id.tuningSettings -> R.string.tuning_system_title\n"
        "            R.id.audioSettings -> R.string.pref_header_audio\n",
    )


# Keep Metro's normal manual speed/pitch dialog; tuning-system choice is separate.
(root / "app/src/main/java/code/name/monkey/retromusic/dialogs/PlaybackSpeedDialog.kt").write_text(
    """package code.name.monkey.retromusic.dialogs

import android.app.Dialog
import android.os.Bundle
import androidx.fragment.app.DialogFragment
import code.name.monkey.retromusic.R
import code.name.monkey.retromusic.databinding.DialogPlaybackSpeedBinding
import code.name.monkey.retromusic.extensions.accent
import code.name.monkey.retromusic.extensions.colorButtons
import code.name.monkey.retromusic.extensions.materialDialog
import code.name.monkey.retromusic.util.PreferenceUtil
import com.google.android.material.slider.Slider

class PlaybackSpeedDialog : DialogFragment() {

    override fun onCreateDialog(savedInstanceState: Bundle?): Dialog {
        val binding = DialogPlaybackSpeedBinding.inflate(layoutInflater)
        binding.playbackSpeedSlider.accent()
        binding.playbackPitchSlider.accent()
        binding.playbackSpeedSlider.addOnChangeListener(Slider.OnChangeListener { _, value, _ ->
            binding.speedValue.text = "$value"
        })
        binding.playbackPitchSlider.addOnChangeListener(Slider.OnChangeListener { _, value, _ ->
            binding.pitchValue.text = "$value"
        })
        binding.playbackSpeedSlider.value = PreferenceUtil.playbackSpeed
        binding.playbackPitchSlider.value = PreferenceUtil.playbackPitch

        return materialDialog(R.string.playback_settings)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.save) { _, _ ->
                updatePlaybackAndPitch(
                    binding.playbackSpeedSlider.value,
                    binding.playbackPitchSlider.value
                )
            }
            .setNeutralButton(R.string.reset_action) { _, _ ->
                updatePlaybackAndPitch(1F, 1F)
            }
            .setView(binding.root)
            .create()
            .colorButtons()
    }

    private fun updatePlaybackAndPitch(speed: Float, pitch: Float) {
        PreferenceUtil.playbackSpeed = speed
        PreferenceUtil.playbackPitch = pitch
    }

    companion object {
        fun newInstance(): PlaybackSpeedDialog = PlaybackSpeedDialog()
    }
}
""",
    encoding="utf-8",
)

(root / "app/src/main/res/layout/dialog_playback_speed.xml").write_text(
    """<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    xmlns:tools="http://schemas.android.com/tools"
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    android:orientation="vertical"
    android:paddingHorizontal="16dp"
    android:paddingVertical="16dp">

    <TextView
        android:id="@+id/playback_speed_title"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="@string/playback_speed"
        android:textAppearance="@style/TextViewBody1" />

    <com.google.android.material.slider.Slider
        android:id="@+id/playback_speed_slider"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:stepSize="0.05"
        android:valueFrom="0.25"
        android:valueTo="4.00"
        app:labelBehavior="gone"
        app:tickVisible="false" />

    <TextView
        android:id="@+id/speed_value"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:gravity="center"
        android:textAppearance="@style/TextViewBody1"
        tools:text="1.00" />

    <TextView
        android:id="@+id/playback_pitch_title"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginTop="16dp"
        android:text="@string/playback_pitch"
        android:textAppearance="@style/TextViewBody1" />

    <com.google.android.material.slider.Slider
        android:id="@+id/playback_pitch_slider"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:stepSize="0.05"
        android:valueFrom="0.50"
        android:valueTo="2.00"
        app:labelBehavior="gone"
        app:tickVisible="false" />

    <TextView
        android:id="@+id/pitch_value"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:gravity="center"
        android:textAppearance="@style/TextViewBody1"
        tools:text="1.00" />
</LinearLayout>
""",
    encoding="utf-8",
)

print("Added Settings > Tuning with A=432 Hz (default), A=528 Hz, and A=639 Hz. Tuning changes pitch only; playback speed is not multiplied by the tuning ratio.")
