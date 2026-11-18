#!/usr/bin/env python3
"""Fix global/per-track tuning and add a song-level tuner + smooth live retuning."""
from pathlib import Path
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
new_method = '''    /** Apply the exact A4 reference ratio; live changes are ramped to avoid an audible pitch step. */
    protected fun applyPlaybackTuning(
        player: MediaPlayer,
        songId: Long,
        speed: Float = playbackSpeed,
        pitch: Float = playbackPitch,
        smooth: Boolean = false,
    ) {
        if (!VersionUtils.hasMarshmallow()) return
        val ratio = PreferenceUtil.effectiveTuningFrequencyHz(songId).toFloat() / 440f
        val targetSpeed = speed.coerceIn(0.1f, 8f)
        val targetPitch = (pitch * ratio).coerceIn(0.1f, 8f)

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
    "tuning_set_track": "Set this song's tuning",
    "tuning_use_global": "Use global tuning",
}.items():
    if f'name="{name}"' not in data:
        data = data.replace(
            "</resources>",
            f'    <string name="{name}">{value}</string>\n</resources>',
            1,
        )
write(strings, data)

print("Applied unified 432/528/639 global tuning, per-song tuning UI and live 450 ms pitch ramp.")
