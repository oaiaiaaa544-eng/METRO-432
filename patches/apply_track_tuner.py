#!/usr/bin/env python3
"""Fix global/per-track tuning and add a song-level tuner + smooth live retuning."""
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_track_tuner.py <Metro source directory>")
root = Path(sys.argv[1])
app = root / "app/src/main"


def read(rel: str) -> str:
    p = app / rel
    if not p.is_file():
        raise SystemExit(f"Missing expected source file: {p}")
    return p.read_text(encoding="utf-8")


def write(rel: str, value: str) -> None:
    (app / rel).write_text(value, encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    data = read(rel)
    count = data.count(old)
    if count != 1:
        raise SystemExit(f"Expected one match in {rel}; found {count}")
    write(rel, data.replace(old, new, 1))


# One canonical setting key: the settings list writes a String value, while the
# playback engine reads an Int. Read/write the same key and migrate the earlier
# integer-key value if it exists.
pref = "java/code/name/monkey/retromusic/util/PreferenceUtil.kt"
replace_once(
    pref,
    '''    val tuningFrequency: Int
        get() = sharedPreferences.getString(TUNING_FREQUENCY, "432")?.toIntOrNull() ?: 432
''',
    '''    val tuningFrequency: Int
        get() = tuningFrequencyHz
''',
)
replace_once(
    pref,
    '''    var tuningFrequencyHz: Int
        get() = sharedPreferences.getInt(TUNING_FREQUENCY_HZ, 432)
        set(value) = sharedPreferences.edit { putInt(TUNING_FREQUENCY_HZ, value.coerceIn(174, 963)) }
''',
    '''    var tuningFrequencyHz: Int
        get() = sharedPreferences.getString(TUNING_FREQUENCY, null)?.toIntOrNull()
            ?: sharedPreferences.getInt(TUNING_FREQUENCY_HZ, 432)
        set(value) = sharedPreferences.edit {
            putString(TUNING_FREQUENCY, value.coerceIn(174, 963).toString())
            remove(TUNING_FREQUENCY_HZ)
        }
''',
)

# Reapply the effective frequency for global changes and per-track override changes.
service = "java/code/name/monkey/retromusic/service/MusicService.kt"
replace_once(
    service,
    '''            PLAYBACK_SPEED, PLAYBACK_PITCH, TUNING_FREQUENCY_HZ, TUNING_MODE -> {
                updateMediaSessionPlaybackState()
                playbackManager.setPlaybackSpeedPitch(playbackSpeed, playbackPitch)
            }
            TUNING_FREQUENCY -> {
                updateMediaSessionPlaybackState()
                val tuningRatio = code.name.monkey.retromusic.util.PreferenceUtil.tuningFrequency.toFloat() / 440F
                playbackManager.setPlaybackSpeedPitch(playbackSpeed, playbackPitch * tuningRatio)
            }
''',
    '''            PLAYBACK_SPEED, PLAYBACK_PITCH, TUNING_FREQUENCY, TUNING_FREQUENCY_HZ, TUNING_MODE -> {
                updateMediaSessionPlaybackState()
                // Playback implementations resolve the active and queued song IDs independently.
                playbackManager.setPlaybackSpeedPitch(playbackSpeed, playbackPitch)
            }
''',
)

# Add an interpolated 450 ms ramp when preferences change while audio is live.
local = "java/code/name/monkey/retromusic/service/LocalPlayback.kt"
source = read(local)
source = source.replace(
    "import android.content.BroadcastReceiver\n",
    "import android.animation.Animator\nimport android.animation.AnimatorListenerAdapter\nimport android.animation.ValueAnimator\nimport android.content.BroadcastReceiver\n",
    1,
)
source = source.replace(
    "import android.media.PlaybackParams\n",
    "import android.media.PlaybackParams\nimport android.view.animation.DecelerateInterpolator\n",
    1,
)
source = source.replace(
    "import code.name.monkey.retromusic.util.PreferenceUtil.playbackSpeed\n",
    "import code.name.monkey.retromusic.util.PreferenceUtil.playbackSpeed\nimport java.util.WeakHashMap\n",
    1,
)
source = source.replace(
    "import code.name.monkey.retromusic.util.PreferenceUtil\n",
    "import code.name.monkey.retromusic.util.PreferenceUtil\nimport code.name.monkey.retromusic.util.TuningPresets\n",
    1,
)
source = source.replace(
    "    private var isPausedByTransientLossOfFocus = false\n",
    "    private var isPausedByTransientLossOfFocus = false\n"
    "    private val tuningAnimators = WeakHashMap<MediaPlayer, ValueAnimator>()\n",
    1,
)
old_method = '''    /** Apply manual speed/pitch together with the global or per-track tuning ratio. */
    protected fun applyPlaybackTuning(
        player: MediaPlayer,
        songId: Long,
        speed: Float = playbackSpeed,
        pitch: Float = playbackPitch,
    ) {
        if (!VersionUtils.hasMarshmallow()) return
        val ratio = PreferenceUtil.effectiveTuningFrequencyHz(songId) / 440f
        try {
            // A-reference tuning shifts pitch only; tempo stays at the user's playback-speed setting.
            player.playbackParams = PlaybackParams()
                .setSpeed(speed.coerceIn(0.1f, 8f))
                .setPitch((pitch * ratio).coerceIn(0.1f, 8f))
        } catch (_: IllegalStateException) {
            // The player may be transitioning between reset/prepared states.
        } catch (_: IllegalArgumentException) {
            // Guard against unsupported parameter combinations on vendor MediaPlayer builds.
        }
    }
'''
new_method = '''    /** Apply the selected solfeggio preset in pitch-preserving or varispeed mode. */
    protected fun applyPlaybackTuning(
        player: MediaPlayer,
        songId: Long,
        speed: Float = playbackSpeed,
        pitch: Float = playbackPitch,
        smooth: Boolean = false,
    ) {
        if (!VersionUtils.hasMarshmallow()) return
        val preset = TuningPresets.forFrequency(PreferenceUtil.effectiveTuningFrequencyHz(songId))
        val rateMode = PreferenceUtil.tuningMode == "rate"
        // Android PlaybackParams uses pitch=1 for tempo-preserving time-stretch;
        // pitch=speed selects resampling/varispeed. Do not apply the preset twice.
        val targetSpeed = (
            speed * if (rateMode) preset.varispeedMultiplier else 1f
        ).coerceIn(0.1f, 8f)
        val presetPitch = if (rateMode) preset.varispeedMultiplier else preset.pitchRatio
        val targetPitch = (pitch * presetPitch).coerceIn(0.1f, 8f)

        fun apply(speedValue: Float, pitchValue: Float) {
            try {
                player.playbackParams = PlaybackParams()
                    .setSpeed(speedValue.coerceIn(0.1f, 8f))
                    .setPitch(pitchValue.coerceIn(0.1f, 8f))
            } catch (_: IllegalStateException) {
                // MediaPlayer may be resetting or not yet prepared.
            } catch (_: IllegalArgumentException) {
                // Some vendor MediaPlayer builds reject unsupported parameter pairs.
            }
        }

        tuningAnimators.remove(player)?.cancel()
        if (!smooth) {
            apply(targetSpeed, targetPitch)
            return
        }

        val startParams = try {
            player.playbackParams
        } catch (_: IllegalStateException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
        val startSpeed = startParams?.speed ?: targetSpeed
        val startPitch = startParams?.pitch ?: targetPitch
        if (kotlin.math.abs(startPitch - targetPitch) < 0.0005f &&
            kotlin.math.abs(startSpeed - targetSpeed) < 0.0005f
        ) {
            apply(targetSpeed, targetPitch)
            return
        }

        val animator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 450L
            interpolator = DecelerateInterpolator()
            addUpdateListener { animation ->
                val fraction = animation.animatedValue as Float
                apply(
                    startSpeed + (targetSpeed - startSpeed) * fraction,
                    startPitch + (targetPitch - startPitch) * fraction,
                )
            }
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    if (tuningAnimators[player] === animation) tuningAnimators.remove(player)
                }
            })
        }
        tuningAnimators[player] = animator
        animator.start()
    }
'''
if source.count(old_method) != 1:
    raise SystemExit(f"Expected one applyPlaybackTuning method; found {source.count(old_method)}")
source = source.replace(old_method, new_method, 1)
write(local, source)

# Live setting changes go through the smooth path for every active/prepared player.
replace_once(
    "java/code/name/monkey/retromusic/service/MultiPlayer.kt",
    '''    override fun setPlaybackSpeedPitch(speed: Float, pitch: Float) {
        applyPlaybackTuning(mCurrentMediaPlayer, currentSongId, speed, pitch)
        mNextMediaPlayer?.let { applyPlaybackTuning(it, nextSongId, speed, pitch) }
    }
''',
    '''    override fun setPlaybackSpeedPitch(speed: Float, pitch: Float) {
        applyPlaybackTuning(mCurrentMediaPlayer, currentSongId, speed, pitch, smooth = true)
        mNextMediaPlayer?.let { applyPlaybackTuning(it, nextSongId, speed, pitch, smooth = true) }
    }
''',
)
replace_once(
    "java/code/name/monkey/retromusic/service/CrossFadePlayer.kt",
    '''    override fun setPlaybackSpeedPitch(speed: Float, pitch: Float) {
        getCurrentPlayer()?.let { applyPlaybackTuning(it, songIdFor(it), speed, pitch) }
        getNextPlayer()?.let { next ->
            // Each MediaPlayer retains the ID of the track loaded into it across player swaps.
            if (next.isPlaying) applyPlaybackTuning(next, songIdFor(next), speed, pitch)
        }
    }
''',
    '''    override fun setPlaybackSpeedPitch(speed: Float, pitch: Float) {
        getCurrentPlayer()?.let { applyPlaybackTuning(it, songIdFor(it), speed, pitch, smooth = true) }
        getNextPlayer()?.let { next ->
            // Apply to the prepared crossfade deck too, before it becomes audible.
            applyPlaybackTuning(next, songIdFor(next), speed, pitch, smooth = true)
        }
    }
''',
)

# Song list rows display each song's effective setting, as in the reference player.
adapter = "java/code/name/monkey/retromusic/adapter/song/SongAdapter.kt"
replace_once(
    adapter,
    '''    private fun getSongText(song: Song): String {
        return song.artistName
    }
''',
    '''    private fun getSongText(song: Song): String {
        val frequency = PreferenceUtil.effectiveTuningFrequencyHz(song.id)
        return "${song.artistName}  •  ${frequency} Hz"
    }
''',
)

# Expose a song-specific tuner from every standard song overflow menu.
for rel in [
    "res/menu/menu_item_song.xml",
    "res/menu/menu_item_playing_queue_song.xml",
    "res/menu/menu_item_playlist_song.xml",
    "res/menu/menu_player.xml",
]:
    data = read(rel)
    if "action_tune_track" not in data:
        item = '''    <item
        android:id="@+id/action_tune_track"
        android:title="@string/tuning_set_track"
        app:showAsAction="never" />
'''
        data = data.replace("</menu>", item + "</menu>", 1)
        write(rel, data)

# Dialog lets a user select A=432/528/639 or inherit the global setting.
dialog_path = app / "java/code/name/monkey/retromusic/dialogs/TrackTuningDialog.kt"
dialog_path.write_text('''package code.name.monkey.retromusic.dialogs

import android.app.Dialog
import android.os.Bundle
import androidx.fragment.app.DialogFragment
import code.name.monkey.retromusic.R
import code.name.monkey.retromusic.extensions.colorButtons
import code.name.monkey.retromusic.extensions.materialDialog
import code.name.monkey.retromusic.util.PreferenceUtil

class TrackTuningDialog : DialogFragment() {
    override fun onCreateDialog(savedInstanceState: Bundle?): Dialog {
        val songId = requireArguments().getLong(ARG_SONG_ID, -1L)
        val labels = resources.getStringArray(R.array.tuning_frequency_entries)
        val frequencies = resources.getStringArray(R.array.tuning_frequency_values)
            .mapNotNull { it.toIntOrNull() }
            .toIntArray()
        val current = PreferenceUtil.trackTuningFrequencyHz(songId)
            ?: PreferenceUtil.tuningFrequencyHz
        val selected = frequencies.indexOf(current).coerceAtLeast(0)

        return materialDialog(R.string.tuning_set_track)
            .setSingleChoiceItems(labels, selected) { dialog, which ->
                if (which in frequencies.indices) {
                    PreferenceUtil.setTrackTuningFrequencyHz(songId, frequencies[which])
                }
                dialog.dismiss()
            }
            .setNeutralButton(R.string.tuning_use_global) { _, _ ->
                PreferenceUtil.setTrackTuningFrequencyHz(songId, null)
            }
            .setNegativeButton(android.R.string.cancel, null)
            .create()
            .colorButtons()
    }

    companion object {
        private const val ARG_SONG_ID = "song_id"

        fun newInstance(songId: Long): TrackTuningDialog = TrackTuningDialog().apply {
            arguments = Bundle().apply { putLong(ARG_SONG_ID, songId) }
        }
    }
}
''', encoding="utf-8")

player_fragment = "java/code/name/monkey/retromusic/fragments/base/AbsPlayerFragment.kt"
player_source = read(player_fragment)
if "R.id.action_tune_track ->" not in player_source:
    player_anchor = '''            R.id.action_playback_speed -> {
                PlaybackSpeedDialog.newInstance().show(childFragmentManager, "PLAYBACK_SETTINGS")
                return true
            }
'''
    player_insert = player_anchor + '''
            R.id.action_tune_track -> {
                TrackTuningDialog.newInstance(song.id).show(childFragmentManager, "TRACK_TUNING")
                return true
            }
'''
    if player_source.count(player_anchor) != 1:
        raise SystemExit("Could not locate playback speed item in AbsPlayerFragment")
    player_source = player_source.replace(player_anchor, player_insert, 1)
write(player_fragment, player_source)

menu_helper = "java/code/name/monkey/retromusic/helper/menu/SongMenuHelper.kt"
source = read(menu_helper)
if "import code.name.monkey.retromusic.dialogs.TrackTuningDialog" not in source:
    source = source.replace(
        "import code.name.monkey.retromusic.dialogs.SongDetailDialog\n",
        "import code.name.monkey.retromusic.dialogs.SongDetailDialog\n"
        "import code.name.monkey.retromusic.dialogs.TrackTuningDialog\n",
        1,
    )
if "R.id.action_tune_track ->" not in source:
    source = source.replace(
        "        when (menuItemId) {\n",
        "        when (menuItemId) {\n"
        "            R.id.action_tune_track -> {\n"
        "                TrackTuningDialog.newInstance(song.id)\n"
        "                    .show(activity.supportFragmentManager, \"TRACK_TUNING\")\n"
        "                return true\n"
        "            }\n",
        1,
    )
write(menu_helper, source)

# Labels for the per-song tuner.
strings = "res/values/strings.xml"
data = read(strings)
for name, value in {
    "tuning_set_track": "Tune this song",
    "tuning_use_global": "Use global tuning",
}.items():
    if f'name="{name}"' not in data:
        data = data.replace(
            "</resources>",
            f'    <string name="{name}">{value}</string>\n</resources>',
            1,
        )
write(strings, data)

# Apply the supplied eight-preset table exactly, for both global and per-track tuning.
preset_source = '''package code.name.monkey.retromusic.util

/**
 * Calibrated preset data supplied for Metro's solfeggio tuning selector.
 * Pitch mode uses pitchShiftCents; rate mode uses varispeedMultiplier.
 */
data class TuningPreset(
    val frequencyHz: Int,
    val nearestNote: String,
    val pitchShiftCents: Float,
    val resultingA4ReferenceHz: Float,
    val varispeedMultiplier: Float,
) {
    val pitchRatio: Float
        get() = Math.pow(2.0, pitchShiftCents.toDouble() / 1200.0).toFloat()
}

object TuningPresets {
    val all = listOf(
        TuningPreset(396, "G4", 17.60f, 444.49f, 1.0102f),
        TuningPreset(417, "G#4 / Ab4", 7.05f, 441.80f, 1.0041f),
        TuningPreset(432, "A4", -31.77f, 432.00f, 0.9818f),
        TuningPreset(528, "C5", 15.64f, 443.99f, 1.0091f),
        TuningPreset(639, "D#5 / Eb5", 45.97f, 451.84f, 1.0269f),
        TuningPreset(741, "F#5 / Gb5", 2.36f, 440.60f, 1.0014f),
        TuningPreset(852, "G#5 / Ab5", 44.02f, 451.33f, 1.0258f),
        TuningPreset(963, "B5", -43.96f, 428.97f, 0.9749f),
    )

    fun isSupported(frequencyHz: Int): Boolean =
        all.any { it.frequencyHz == frequencyHz }

    fun normalizeFrequency(frequencyHz: Int): Int =
        if (isSupported(frequencyHz)) frequencyHz else 432

    fun forFrequency(frequencyHz: Int): TuningPreset =
        all.firstOrNull { it.frequencyHz == frequencyHz }
            ?: all.first { it.frequencyHz == 432 }
}
'''
write("java/code/name/monkey/retromusic/util/TuningPresets.kt", preset_source)

arrays_text = read("res/values/arrays.xml")
for resource_name in (
    "tuning_frequency_entries",
    "tuning_frequency_values",
    "tuning_mode_entries",
    "tuning_mode_values",
):
    arrays_text = re.sub(
        rf'\s*<string-array\s+name="{resource_name}"[^>]*>.*?</string-array>',
        "",
        arrays_text,
        flags=re.DOTALL,
    )
preset_arrays = '''    <string-array name="tuning_frequency_entries">
        <item>396 Hz — G4 — +17.60 cents</item>
        <item>417 Hz — G#4 / Ab4 — +7.05 cents</item>
        <item>432 Hz — A4 — -31.77 cents (Default)</item>
        <item>528 Hz — C5 — +15.64 cents</item>
        <item>639 Hz — D#5 / Eb5 — +45.97 cents</item>
        <item>741 Hz — F#5 / Gb5 — +2.36 cents</item>
        <item>852 Hz — G#5 / Ab5 — +44.02 cents</item>
        <item>963 Hz — B5 — -43.96 cents</item>
    </string-array>
    <string-array name="tuning_frequency_values">
        <item>396</item>
        <item>417</item>
        <item>432</item>
        <item>528</item>
        <item>639</item>
        <item>741</item>
        <item>852</item>
        <item>963</item>
    </string-array>
    <string-array name="tuning_mode_entries">
        <item>@string/tuning_pitch_mode</item>
        <item>@string/tuning_rate_mode</item>
    </string-array>
    <string-array name="tuning_mode_values">
        <item>pitch</item>
        <item>rate</item>
    </string-array>
'''
if "<resources>\n" not in arrays_text:
    raise SystemExit("Could not locate <resources> in arrays.xml")
arrays_text = arrays_text.replace("<resources>\n", "<resources>\n" + preset_arrays, 1)
write("res/values/arrays.xml", arrays_text)

# Replace the three-choice page with the eight supplied presets and both playback modes.
write(
    "res/xml/pref_tuning.xml",
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

    <code.name.monkey.appthemehelper.common.prefs.supportv7.ATEListPreference
        android:defaultValue="pitch"
        android:entries="@array/tuning_mode_entries"
        android:entryValues="@array/tuning_mode_values"
        android:key="tuning_mode"
        android:layout="@layout/list_item_view"
        android:summary="@string/pref_summary_tuning_mode"
        android:title="@string/tuning_mode" />

</androidx.preference.PreferenceScreen>
""",
    encoding="utf-8",
)

# Make the current tuning mode and all options clear in Settings.
strings_text = read("res/values/strings.xml")
string_values = {
    "tuning_system_settings_summary": "Choose from eight reference-frequency presets",
    "pref_summary_tuning_system": "Choose a preset. 432 Hz is the default.",
    "pref_summary_tuning_mode": "Pitch mode preserves song duration. Rate mode changes pitch and playback speed together.",
    "tuning_pitch_mode": "Pitch only (tempo preserved)",
    "tuning_rate_mode": "Rate (varispeed: speed + pitch)",
}
for name, value in string_values.items():
    pattern = rf'(<string name="{re.escape(name)}">).*?(</string>)'
    strings_text, changed = re.subn(pattern, lambda m: m.group(1) + value + m.group(2), strings_text, count=1, flags=re.DOTALL)
    if changed == 0:
        strings_text = strings_text.replace(
            "</resources>",
            f'    <string name="{name}">{value}</string>\n</resources>',
            1,
        )
write("res/values/strings.xml", strings_text)

# Restrict stored global/per-track values to the eight calibrated table entries.
preference_file = "java/code/name/monkey/retromusic/util/PreferenceUtil.kt"
replace_once(
    preference_file,
    '''    var tuningFrequencyHz: Int
        get() = sharedPreferences.getString(TUNING_FREQUENCY, null)?.toIntOrNull()
            ?: sharedPreferences.getInt(TUNING_FREQUENCY_HZ, 432)
        set(value) = sharedPreferences.edit {
            putString(TUNING_FREQUENCY, value.coerceIn(174, 963).toString())
            remove(TUNING_FREQUENCY_HZ)
        }
''',
    '''    var tuningFrequencyHz: Int
        get() = TuningPresets.normalizeFrequency(
            sharedPreferences.getString(TUNING_FREQUENCY, null)?.toIntOrNull()
                ?: sharedPreferences.getInt(TUNING_FREQUENCY_HZ, 432)
        )
        set(value) = sharedPreferences.edit {
            putString(TUNING_FREQUENCY, TuningPresets.normalizeFrequency(value).toString())
            remove(TUNING_FREQUENCY_HZ)
        }
''',
)
replace_once(
    preference_file,
    '''        return if (sharedPreferences.contains(key)) sharedPreferences.getInt(key, tuningFrequencyHz) else null
''',
    '''        return if (sharedPreferences.contains(key)) {
            sharedPreferences.getInt(key, tuningFrequencyHz).takeIf { TuningPresets.isSupported(it) }
        } else null
''',
)
replace_once(
    preference_file,
    '''            else putInt(key, frequencyHz.coerceIn(174, 963))
''',
    '''            else if (TuningPresets.isSupported(frequencyHz)) putInt(key, frequencyHz)
            else remove(key)
''',
)

print("Applied all eight supplied presets, pitch/rate modes, per-track choices and smooth 450 ms retuning.")
