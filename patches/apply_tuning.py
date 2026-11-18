#!/usr/bin/env python3
"""Apply the Metro 432 Hz tuning-mode implementation to the source archive."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_tuning.py <Metro-dev directory>")

root = Path(sys.argv[1])
if not (root / "app/build.gradle").is_file():
    raise SystemExit(f"Android project not found under {root}")

def replace_once(relative_path: str, old: str, new: str) -> None:
    path = root / relative_path
    content = path.read_text(encoding="utf-8")
    count = content.count(old)
    if count != 1:
        raise SystemExit(f"Expected one match in {relative_path}; found {count}")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")

replace_once(
    "app/src/main/java/code/name/monkey/retromusic/Constants.kt",
    'const val PLAYBACK_PITCH = "playback_pitch"\n',
    'const val PLAYBACK_PITCH = "playback_pitch"\n'
    'const val TUNING_MODE = "tuning_mode"\n'
    'const val TUNING_MODE_RATE = "rate"\n'
    'const val TUNING_MODE_PITCH = "pitch"\n'
    'const val TUNING_RATIO_432 = 0.9818182F\n',
)

replace_once(
    "app/src/main/java/code/name/monkey/retromusic/util/PreferenceUtil.kt",
    "    private val sharedPreferences = PreferenceManager.getDefaultSharedPreferences(App.getContext())\n",
    "    private val sharedPreferences = PreferenceManager.getDefaultSharedPreferences(App.getContext())\n"
    "\n"
    "    // Migrate existing installs to the 432 Hz default once.\n"
    "    init {\n"
    "        if (!sharedPreferences.contains(TUNING_MODE)) {\n"
    "            sharedPreferences.edit {\n"
    "                putString(TUNING_MODE, TUNING_MODE_RATE)\n"
    "                putFloat(PLAYBACK_SPEED, TUNING_RATIO_432)\n"
    "                putFloat(PLAYBACK_PITCH, 1F)\n"
    "            }\n"
    "        }\n"
    "    }\n",
)

replace_once(
    "app/src/main/java/code/name/monkey/retromusic/util/PreferenceUtil.kt",
    "    var playbackSpeed\n        get() = sharedPreferences\n            .getFloat(PLAYBACK_SPEED, 1F)\n",
    "    var tuningMode: String\n"
    "        get() = sharedPreferences.getString(TUNING_MODE, TUNING_MODE_RATE) ?: TUNING_MODE_RATE\n"
    "        set(value) = sharedPreferences.edit { putString(TUNING_MODE, value) }\n"
    "\n"
    "    var playbackSpeed\n"
    "        get() = sharedPreferences\n"
    "            .getFloat(PLAYBACK_SPEED, TUNING_RATIO_432)\n",
)

dialog = """package code.name.monkey.retromusic.dialogs

import android.app.Dialog
import android.os.Bundle
import androidx.fragment.app.DialogFragment
import code.name.monkey.retromusic.R
import code.name.monkey.retromusic.TUNING_MODE_PITCH
import code.name.monkey.retromusic.TUNING_MODE_RATE
import code.name.monkey.retromusic.TUNING_RATIO_432
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
                PreferenceUtil.playbackSpeed = if (pitchMode) 1f else TUNING_RATIO_432
                PreferenceUtil.playbackPitch = if (pitchMode) TUNING_RATIO_432 else 1f
            }
            .setNeutralButton(R.string.reset_action) { _, _ ->
                PreferenceUtil.tuningMode = TUNING_MODE_RATE
                PreferenceUtil.playbackSpeed = TUNING_RATIO_432
                PreferenceUtil.playbackPitch = 1f
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

    <TextView
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="@string/tuning_frequency"
        android:textAppearance="@style/TextViewBody1" />

    <TextView
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginTop="4dp"
        android:text="@string/tuning_frequency_432"
        android:textAppearance="@style/TextViewBody1" />

    <TextView
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginTop="20dp"
        android:text="@string/tuning_mode"
        android:textAppearance="@style/TextViewBody1" />

    <RadioGroup
        android:id="@+id/tuning_mode_group"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:orientation="vertical">
        <RadioButton
            android:id="@+id/rate_mode"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:text="@string/rate_mode" />
        <RadioButton
            android:id="@+id/pitch_mode"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:text="@string/pitch_mode" />
    </RadioGroup>

    <TextView
        android:id="@+id/tuning_mode_description"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginTop="8dp"
        android:text="@string/pitch_mode_description"
        android:textAppearance="@style/TextViewBody2" />
</LinearLayout>
"""
(root / "app/src/main/res/layout/dialog_playback_speed.xml").write_text(layout, encoding="utf-8")

replace_once(
    "app/src/main/res/values/strings.xml",
    '    <string name="playback_settings">Playback Settings</string>\n',
    '    <string name="playback_settings">Playback Settings</string>\n'
    '    <string name="tuning_frequency">Tuning frequency</string>\n'
    '    <string name="tuning_frequency_432">432 Hz (standard and default)</string>\n'
    '    <string name="tuning_mode">Tuning mode</string>\n'
    '    <string name="rate_mode">Rate Mode — best quality; slightly changes playback speed and duration</string>\n'
    '    <string name="pitch_mode">Pitch Mode — preserves original playback speed and song duration; may introduce minor artifacts</string>\n'
    '    <string name="rate_mode_description">Rate Mode applies the tuning change through playback rate. Audio quality is prioritized, with a slight duration change.</string>\n'
    '    <string name="pitch_mode_description">Pitch Mode changes pitch independently. Playback speed, rhythm, and song duration remain unchanged.</string>\n',
)

print("Applied 432 Hz default, legacy-install migration, and Rate/Pitch mode selector.")
