#!/usr/bin/env python3
"""Add the Settings > Audio > Tuning frequency selector to a 432-mode Metro build."""
from pathlib import Path
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


# The first patch already introduced TUNING_MODE and TUNING_RATIO_432.
constants = root / "app/src/main/java/code/name/monkey/retromusic/Constants.kt"
if 'const val TUNING_FREQUENCY = "tuning_frequency"' not in constants.read_text(encoding="utf-8"):
    replace_once(
        "app/src/main/java/code/name/monkey/retromusic/Constants.kt",
        'const val PLAYBACK_PITCH = "playback_pitch"\n',
        'const val PLAYBACK_PITCH = "playback_pitch"\n'
        'const val TUNING_FREQUENCY = "tuning_frequency"\n',
    )

pref_util = root / "app/src/main/java/code/name/monkey/retromusic/util/PreferenceUtil.kt"
pref_text = pref_util.read_text(encoding="utf-8")
if "sharedPreferences.contains(TUNING_FREQUENCY)" not in pref_text:
    replace_once(
        "app/src/main/java/code/name/monkey/retromusic/util/PreferenceUtil.kt",
        "    private val sharedPreferences = PreferenceManager.getDefaultSharedPreferences(App.getContext())\n",
        "    private val sharedPreferences = PreferenceManager.getDefaultSharedPreferences(App.getContext())\n"
        "\n"
        "    init {\n"
        "        if (!sharedPreferences.contains(TUNING_FREQUENCY)) {\n"
        "            sharedPreferences.edit { putString(TUNING_FREQUENCY, \"432\") }\n"
        "        }\n"
        "    }\n",
    )

pref_text = pref_util.read_text(encoding="utf-8")
if "val tuningFrequency: Int" not in pref_text:
    replace_once(
        "app/src/main/java/code/name/monkey/retromusic/util/PreferenceUtil.kt",
        "    var playbackSpeed\n"
        "        get() = sharedPreferences\n"
        "            .getFloat(PLAYBACK_SPEED, TUNING_RATIO_432)\n",
        "    val tuningFrequency: Int\n"
        "        get() = sharedPreferences.getString(TUNING_FREQUENCY, \"432\")?.toIntOrNull() ?: 432\n"
        "\n"
        "    fun applyTuningFrequency(frequency: Int = tuningFrequency) {\n"
        "        val ratio = frequency.toFloat() / 440F\n"
        "        if (tuningMode == TUNING_MODE_PITCH) {\n"
        "            playbackSpeed = 1F\n"
        "            playbackPitch = ratio\n"
        "        } else {\n"
        "            playbackSpeed = ratio\n"
        "            playbackPitch = 1F\n"
        "        }\n"
        "    }\n"
        "\n"
        "    var playbackSpeed\n"
        "        get() = sharedPreferences\n"
        "            .getFloat(PLAYBACK_SPEED, TUNING_RATIO_432)\n",
    )

# Settings > Audio selector.
audio_xml = root / "app/src/main/res/xml/pref_audio.xml"
if 'android:key="tuning_frequency"' not in audio_xml.read_text(encoding="utf-8"):
    replace_once(
        "app/src/main/res/xml/pref_audio.xml",
        "    <code.name.monkey.retromusic.preferences.DurationPreference\n",
        "    <code.name.monkey.appthemehelper.common.prefs.supportv7.ATEListPreference\n"
        "        android:defaultValue=\"432\"\n"
        "        android:entries=\"@array/tuning_frequency_entries\"\n"
        "        android:entryValues=\"@array/tuning_frequency_values\"\n"
        "        android:key=\"tuning_frequency\"\n"
        "        android:layout=\"@layout/list_item_view\"\n"
        "        android:summary=\"@string/pref_summary_tuning\"\n"
        "        android:title=\"@string/pref_title_tuning\" />\n\n"
        "    <code.name.monkey.retromusic.preferences.DurationPreference\n",
    )

audio_settings = root / "app/src/main/java/code/name/monkey/retromusic/fragments/settings/AudioSettings.kt"
settings_text = audio_settings.read_text(encoding="utf-8")
if "import androidx.preference.ListPreference" not in settings_text:
    replace_once(
        "app/src/main/java/code/name/monkey/retromusic/fragments/settings/AudioSettings.kt",
        "import androidx.preference.Preference\n",
        "import androidx.preference.ListPreference\nimport androidx.preference.Preference\n",
    )
if "import code.name.monkey.retromusic.TUNING_FREQUENCY" not in settings_text:
    replace_once(
        "app/src/main/java/code/name/monkey/retromusic/fragments/settings/AudioSettings.kt",
        "import code.name.monkey.retromusic.R\n",
        "import code.name.monkey.retromusic.R\n"
        "import code.name.monkey.retromusic.TUNING_FREQUENCY\n"
        "import code.name.monkey.retromusic.util.PreferenceUtil\n",
    )
settings_text = audio_settings.read_text(encoding="utf-8")
if "val tuningPreference: ListPreference?" not in settings_text:
    replace_once(
        "app/src/main/java/code/name/monkey/retromusic/fragments/settings/AudioSettings.kt",
        "    override fun invalidateSettings() {\n",
        "    override fun invalidateSettings() {\n"
        "        val tuningPreference: ListPreference? = findPreference(TUNING_FREQUENCY)\n"
        "        tuningPreference?.let { pref ->\n"
        "            pref.summary = getString(R.string.tuning_frequency_current, pref.value ?: \"432\")\n"
        "            pref.setOnPreferenceChangeListener { preference, newValue ->\n"
        "                val frequency = newValue.toString().toIntOrNull() ?: 432\n"
        "                PreferenceUtil.applyTuningFrequency(frequency)\n"
        "                preference.summary = getString(R.string.tuning_frequency_current, frequency)\n"
        "                true\n"
        "            }\n"
        "        }\n",
    )

# Solfeggio list. The 432 Hz default is retained for existing and new installations.
arrays = root / "app/src/main/res/values/arrays.xml"
arrays_text = arrays.read_text(encoding="utf-8")
if "tuning_frequency_entries" not in arrays_text:
    arrays_text = arrays_text.replace(
        "<resources>\n",
        "<resources>\n"
        "    <string-array name=\"tuning_frequency_entries\">\n"
        "        <item>432 Hz — Default</item>\n"
        "        <item>528 Hz</item>\n"
        "        <item>639 Hz</item>\n"
        "    </string-array>\n"
        "    <string-array name=\"tuning_frequency_values\">\n"
        "        <item>432</item><item>528</item><item>639</item>\n"
        "    </string-array>\n",
        1,
    )
    arrays.write_text(arrays_text, encoding="utf-8")

strings = root / "app/src/main/res/values/strings.xml"
strings_text = strings.read_text(encoding="utf-8")
if "pref_title_tuning" not in strings_text:
    replace_once(
        "app/src/main/res/values/strings.xml",
        '    <string name="playback_settings">Playback Settings</string>\n',
        '    <string name="playback_settings">Playback Settings</string>\n'
        '    <string name="pref_title_tuning">Tuning</string>\n'
        '    <string name="pref_summary_tuning">Choose 432 Hz (default), 528 Hz, or 639 Hz</string>\n'
        '    <string name="tuning_frequency_current">Selected frequency: %1$s Hz</string>\n',
    )

# Keep the current Rate/Pitch picker and show the chosen tuning frequency in it.
dialog = """package code.name.monkey.retromusic.dialogs

import android.app.Dialog
import android.os.Bundle
import androidx.fragment.app.DialogFragment
import code.name.monkey.retromusic.R
import code.name.monkey.retromusic.TUNING_MODE_PITCH
import code.name.monkey.retromusic.TUNING_MODE_RATE
import code.name.monkey.retromusic.databinding.DialogPlaybackSpeedBinding
import code.name.monkey.retromusic.extensions.colorButtons
import code.name.monkey.retromusic.extensions.materialDialog
import code.name.monkey.retromusic.util.PreferenceUtil

class PlaybackSpeedDialog : DialogFragment() {
    override fun onCreateDialog(savedInstanceState: Bundle?): Dialog {
        val binding = DialogPlaybackSpeedBinding.inflate(layoutInflater)
        binding.tuningModeGroup.check(
            if (PreferenceUtil.tuningMode == TUNING_MODE_PITCH) R.id.pitch_mode else R.id.rate_mode
        )
        binding.tuningFrequencyValue.text = getString(
            R.string.tuning_frequency_current, PreferenceUtil.tuningFrequency
        )
        fun updateDescription() {
            binding.tuningModeDescription.setText(
                if (binding.tuningModeGroup.checkedRadioButtonId == R.id.pitch_mode)
                    R.string.pitch_mode_description else R.string.rate_mode_description
            )
        }
        binding.tuningModeGroup.setOnCheckedChangeListener { _, _ -> updateDescription() }
        updateDescription()
        return materialDialog(R.string.playback_settings)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.save) { _, _ ->
                val pitchMode = binding.tuningModeGroup.checkedRadioButtonId == R.id.pitch_mode
                PreferenceUtil.tuningMode = if (pitchMode) TUNING_MODE_PITCH else TUNING_MODE_RATE
                PreferenceUtil.applyTuningFrequency()
            }
            .setNeutralButton(R.string.reset_action) { _, _ ->
                PreferenceUtil.tuningMode = TUNING_MODE_RATE
                PreferenceUtil.applyTuningFrequency()
            }
            .setView(binding.root)
            .create()
            .colorButtons()
    }

    companion object {
        fun newInstance(): PlaybackSpeedDialog = PlaybackSpeedDialog()
    }
}
"""
(root / "app/src/main/java/code/name/monkey/retromusic/dialogs/PlaybackSpeedDialog.kt").write_text(dialog, encoding="utf-8")

layout = """<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    android:orientation="vertical"
    android:paddingHorizontal="24dp"
    android:paddingVertical="16dp">
    <TextView android:layout_width="match_parent" android:layout_height="wrap_content"
        android:text="@string/tuning_frequency" android:textAppearance="@style/TextViewBody1" />
    <TextView android:id="@+id/tuning_frequency_value" android:layout_width="match_parent"
        android:layout_height="wrap_content" android:layout_marginTop="4dp"
        android:textAppearance="@style/TextViewBody1" />
    <TextView android:layout_width="match_parent" android:layout_height="wrap_content"
        android:layout_marginTop="20dp" android:text="@string/tuning_mode"
        android:textAppearance="@style/TextViewBody1" />
    <RadioGroup android:id="@+id/tuning_mode_group" android:layout_width="match_parent"
        android:layout_height="wrap_content" android:orientation="vertical">
        <RadioButton android:id="@+id/rate_mode" android:layout_width="match_parent"
            android:layout_height="wrap_content" android:text="@string/rate_mode" />
        <RadioButton android:id="@+id/pitch_mode" android:layout_width="match_parent"
            android:layout_height="wrap_content" android:text="@string/pitch_mode" />
    </RadioGroup>
    <TextView android:id="@+id/tuning_mode_description" android:layout_width="match_parent"
        android:layout_height="wrap_content" android:layout_marginTop="8dp"
        android:text="@string/pitch_mode_description" android:textAppearance="@style/TextViewBody2" />
</LinearLayout>
"""
(root / "app/src/main/res/layout/dialog_playback_speed.xml").write_text(layout, encoding="utf-8")

print("Added Settings > Audio > Tuning with only 432 Hz (default), 528 Hz, and 639 Hz.")
