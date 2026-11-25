"""Source fidelity, constrained polyphony, and original-file library regressions."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import mido

from backend.music.compiler import compile_song, normalize_settings
from backend.music.legacy import parse_legacy, parse_score
from backend.music.library import MusicLibrary
from backend.music.midi_reader import parse_midi
from backend.music.models import KEYS, PITCHES, ParsedSong, SourceNote
from backend.music.scheduler import TimelineClock


def midi_bytes(tracks, midi_type=1, ticks=480):
    midi = mido.MidiFile(type=midi_type, ticks_per_beat=ticks)
    for messages in tracks:
        midi.tracks.append(mido.MidiTrack(messages))
    output = BytesIO()
    midi.save(file=output)
    return output.getvalue()


def one_note(pitch=64, duration=480):
    return midi_bytes([[
        mido.Message("note_on", note=pitch, velocity=90),
        mido.Message("note_off", note=pitch, time=duration),
    ]], midi_type=0)


def source(notes, duration=None):
    result = tuple(SourceNote(start, start + 500_000, pitch, velocity, track, channel)
                   for start, pitch, track, channel, velocity in notes)
    ids = sorted({note.track for note in result})
    return ParsedSong("midi", result, tuple({"id": ident} for ident in ids),
                      duration if duration is not None else max(n.start_us for n in result) + 100_000)


class MidiReaderTests(unittest.TestCase):
    def test_tick_zero_tempo_and_later_changes_apply_across_tracks(self):
        raw = midi_bytes([
            [mido.MetaMessage("set_tempo", tempo=250_000),
             mido.MetaMessage("set_tempo", tempo=1_000_000, time=480)],
            [mido.Message("note_on", note=64, velocity=90, time=480),
             mido.Message("note_on", note=64, velocity=0, time=480)],
        ])
        parsed = parse_midi(raw)
        self.assertEqual((parsed.notes[0].start_us, parsed.notes[0].end_us), (250_000, 1_250_000))
        self.assertEqual(parsed.duration_us, 1_250_000)

    def test_same_tick_chord_survives_multiple_tracks_and_velocity_zero_release(self):
        parsed = parse_midi(midi_bytes([
            [mido.Message("note_on", note=pitch, velocity=80, time=120),
             mido.Message("note_on", note=pitch, velocity=0, time=480)]
            for pitch in PITCHES
        ]))
        self.assertEqual(len(parsed.notes), 9)
        self.assertEqual({n.start_us for n in parsed.notes}, {125_000})
        self.assertEqual({n.end_us for n in parsed.notes}, {625_000})
        self.assertEqual(compile_song(parsed).events[0].mask, 0x1ff)

    def test_sustain_is_preserved_without_extending_game_pulses(self):
        parsed = parse_midi(midi_bytes([[
            mido.Message("control_change", control=64, value=127),
            mido.Message("note_on", note=64, velocity=90),
            mido.Message("note_off", note=64, time=480),
            mido.Message("control_change", control=64, value=0, time=480),
        ]]))
        self.assertEqual([(c.control, c.value) for c in parsed.controls], [(64, 127), (64, 0)])
        self.assertEqual([e.time_us for e in compile_song(parsed).events], [0, 50_000])
        self.assertTrue(parsed.warnings)

    def test_overlapping_equal_pitches_are_paired_fifo_and_dangling_notes_retained(self):
        parsed = parse_midi(midi_bytes([[
            mido.Message("note_on", note=64, velocity=70),
            mido.Message("note_on", note=64, velocity=80, time=96),
            mido.Message("note_off", note=64, time=96),
        ]]))
        self.assertEqual([(n.start_us, n.end_us) for n in parsed.notes], [(0, 200_000), (100_000, 200_000)])
        self.assertTrue(parsed.warnings)

    def test_rejects_independent_type2_smpte_and_malformed_files(self):
        for data in (midi_bytes([[]], midi_type=2), b"not a midi"):
            with self.assertRaises(ValueError):
                parse_midi(data)
        data = bytearray(one_note())
        data[12:14] = b"\xe7\x28"
        with self.assertRaisesRegex(ValueError, "SMPTE"):
            parse_midi(bytes(data))

    def test_percussion_only_file_can_still_be_mapped_and_played(self):
        parsed = parse_midi(midi_bytes([[
            mido.MetaMessage("track_name", name="Drums"),
            mido.Message("note_on", channel=9, note=64, velocity=80),
            mido.Message("note_off", channel=9, note=64, time=480),
        ]]))
        self.assertTrue(parsed.tracks[0]["percussion"])
        self.assertEqual(parsed.tracks[0]["channels"], [10])
        self.assertTrue(compile_song(parsed).analysis["can_play"])
        self.assertEqual(compile_song(parsed).analysis["playable_notes"], 1)


class CompilerTests(unittest.TestCase):
    def test_chord_masks_preserve_overlapping_strikes_without_releasing_others(self):
        parsed = source([(0, 64, 0, 0, 90), (20_000, 65, 0, 0, 90)])
        compiled = compile_song(parsed)
        self.assertEqual([(e.time_us, e.mask) for e in compiled.events],
                         [(0, 2), (20_000, 6), (50_000, 4), (70_000, 0)])

    def test_same_key_duplicates_and_fast_retriggers_all_get_separate_pulses(self):
        parsed = source([(0, 64, 0, 0, 90), (0, 64, 1, 0, 80),
                         (59_999, 64, 0, 0, 80), (60_000, 64, 0, 0, 80)])
        result = compile_song(parsed)
        self.assertEqual(result.analysis["merged_notes"], 0)
        self.assertEqual(result.analysis["playable_notes"], 4)
        self.assertEqual(result.analysis["skipped_notes"], 0)
        self.assertTrue(result.analysis["can_play"])
        onsets = [event.time_us for event in result.events if event.onset_keys]
        self.assertEqual(len(onsets), 4)
        self.assertTrue(all(b - a >= 60_000 for a, b in zip(onsets, onsets[1:])))

    def test_all_accidentals_map_to_keys_and_old_strict_settings_do_not_block(self):
        parsed = source([(0, 52, 0, 0, 90), (200_000, 61, 0, 0, 90)])
        result = compile_song(parsed, {"root": 0})
        self.assertEqual(result.events[0].onset_keys, ("F",))
        self.assertEqual(result.analysis["unmapped_notes"], 0)
        self.assertEqual(result.analysis["playable_notes"], 2)
        self.assertTrue(result.analysis["can_play"])
        self.assertTrue(compile_song(parsed, {"range_policy": "nearest"}).analysis["can_play"])
        self.assertTrue(compile_song(parsed, {"conflict_policy": "skip"}).analysis["can_play"])
        self.assertTrue(compile_song(parsed, {"range_policy": "strict", "conflict_policy": "skip"}).analysis["can_play"])

    def test_capacity_checks_overlapping_pulses_not_only_exact_chords(self):
        parsed = source([(0, pitch, 0, 0, 90) for pitch in PITCHES[:6]] + [(20_000, PITCHES[6], 0, 0, 90)])
        self.assertEqual(compile_song(parsed).analysis["max_keys"], 7)
        restricted = compile_song(parsed, max_keys=6)
        self.assertEqual(restricted.analysis["capacity_conflicts"], 1)
        self.assertTrue(restricted.analysis["can_play"])
        self.assertEqual(restricted.analysis["playable_notes"], 7)
        self.assertLessEqual(restricted.analysis["max_keys"], 6)
        self.assertEqual(restricted.analysis["skipped_notes"], 0)

    def test_tracks_transposition_speed_and_no_automatic_onset_quantization(self):
        parsed = source([(100_000, 63, 0, 0, 90), (105_000, 65, 1, 0, 90), (180_000, 63, 0, 0, 90)])
        result = compile_song(parsed, {"selected_tracks": [0], "transpose": 1})
        self.assertEqual([e.time_us for e in result.events if e.onset_keys], [0, 80_000])
        fast = compile_song(parsed, {"selected_tracks": [0], "transpose": 1, "speed": 2})
        self.assertEqual(fast.analysis["retrigger_conflicts"], 1)
        accurate = compile_song(parsed, {"range_policy": "degree", "root": 0})
        self.assertEqual([e.time_us for e in accurate.events if e.onset_keys][:2], [0, 5_000])

    def test_converter_golden_key_and_millisecond_timing_sequence(self):
        # A B-major phrase: old converter output, fixed independently of the
        # shared mapping implementation. Include E to disambiguate the key.
        phrase = [(0,59),(172414,61),(344828,63),(689655,59),(862069,56),
                  (1379310,61),(1724138,58),(2068965,54),(2241379,51),
                  (2758620,58),(3103448,56),(3448275,54),(3620689,47),
                  (4137930,54),(4482758,51),(5517240,49),(6000000,52)]
        result = compile_song(source([(t,p,0,0,90) for t,p in phrase]))
        onsets = [(event.time_us, event.onset_keys[0]) for event in result.events if event.onset_keys]
        self.assertEqual(result.analysis["detected_root"], 11)
        self.assertEqual([key for _,key in onsets[:16]], list("TYFTBYKHFKBHTHFY"))
        self.assertEqual([(b[0]-a[0])//1000-50 for a,b in zip(onsets,onsets[1:])][:15],
                         [122,122,295,122,467,295,295,122,467,295,295,122,467,295,984])

    def test_every_pitch_is_preserved_even_on_single_key_devices(self):
        result = compile_song(source([(0,pitch,0,0,90) for pitch in range(128)]), max_keys=1)
        self.assertTrue(result.analysis["can_play"])
        self.assertEqual(result.analysis["source_notes"], 128)
        self.assertEqual(sum(len(event.onset_keys) for event in result.events), 128)
        self.assertEqual(result.analysis["skipped_notes"], 0)
        self.assertEqual(result.analysis["max_keys"], 1)

    def test_standalone_converter_and_direct_player_keep_the_same_default_mapping(self):
        messages = []
        for pitch in (59,61,63,64,66,68,70,71):
            messages.extend([mido.Message("note_on", note=pitch, velocity=90),
                             mido.Message("note_off", note=pitch, time=192)])
        raw = midi_bytes([messages], midi_type=0)
        direct = compile_song(parse_midi(raw))
        onsets = [(event.time_us,event.onset_keys[0]) for event in direct.events if event.onset_keys]
        expected = [(key, (onsets[i+1][0]-at)//1000-50 if i+1<len(onsets) else 0)
                    for i,(at,key) in enumerate(onsets)]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phrase.mid"
            path.write_bytes(raw)
            output = Path(temp) / "phrase.txt"
            script = Path(__file__).resolve().parents[1] / "scripts" / "midi2score.py"
            subprocess.run([sys.executable, str(script), str(path), "-o", str(output)],
                           cwd=temp, check=True, capture_output=True)
            self.assertEqual(parse_score(output.read_text(encoding="utf-8")), expected)

    def test_invalid_settings_rejected(self):
        for settings in ({"speed": float("nan")}, {"speed": 0}, {"transpose": True},
                         {"range_policy": "major"}, {"selected_tracks": [True]}, {"bogus": 1}):
            with self.assertRaises(ValueError):
                normalize_settings(settings)

    def test_old_score_keeps_hold_plus_pause_and_trailing_rest(self):
        self.assertEqual(parse_score("# test\nb: 100\nF=20 # note\nx 500\nGG 100\nU"), [("B", 100), ("F", 20), ("U", 0)])
        compiled = compile_song(parse_legacy(b"B 100\nF 200\n"))
        self.assertEqual([e.time_us for e in compiled.events if e.onset_keys], [0, 150_000])
        self.assertEqual(compiled.duration_us, 400_000)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.library = MusicLibrary(self.root / "music", self.root / "scores")

    def test_import_retains_original_bytes_hash_id_and_duplicate_identity(self):
        raw = one_note()
        result = self.library.import_file("../漂亮.mid", raw)
        ident = result["song"]["id"]
        self.assertEqual(ident, hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["song"]["filename"], "漂亮.mid")
        self.assertEqual(self.library.original(ident), raw)
        self.assertTrue(self.library.import_file("another.mid", raw)["duplicate"])
        self.assertEqual(len(self.library.summaries()), 1)

    def test_settings_roundtrip_and_cached_analysis_does_not_reparse(self):
        ident = self.library.import_file("song.mid", one_note())["song"]["id"]
        self.library.update_settings(ident, {"selected_tracks": [0], "speed": 1.5})
        settings = self.library.settings(ident)
        settings["selected_tracks"].append(999)
        self.assertEqual(self.library.settings(ident)["selected_tracks"], [0])
        with patch.object(self.library, "_parse", side_effect=AssertionError("reparsed")):
            for _ in range(10):
                self.library.detail(ident)
                self.library.refresh()
        reopened = MusicLibrary(self.root / "music", self.root / "scores")
        self.assertEqual(reopened.settings(ident)["speed"], 1.5)
        self.assertEqual(reopened.detail(ident)["analysis"]["playable_notes"], 1)

    def test_existing_imports_adopt_converter_defaults_without_reimporting(self):
        ident = self.library.import_file("old.mid", one_note())["song"]["id"]
        path = self.library.root / "settings" / (ident + ".json")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"range_policy": "octave", "conflict_policy": "strict", "speed": .5}))
        reopened = MusicLibrary(self.library.root, self.library.legacy_dir)
        settings = reopened.settings(ident)
        self.assertEqual(settings["range_policy"], "degree")
        self.assertEqual(settings["conflict_policy"], "adapt")
        self.assertIsNone(settings["root"])
        self.assertEqual(settings["speed"], .5)

    def test_delete_removes_entry_and_settings_but_preserves_external_original(self):
        external = self.root / "personal.mid"
        raw = one_note()
        external.write_bytes(raw)
        ident = self.library.import_file(external.name, raw)["song"]["id"]
        self.library.update_settings(ident, {"speed": .5})
        self.library.performance(ident)
        self.library.delete(ident)
        self.assertEqual(self.library.refresh(), [])
        self.assertEqual(external.read_bytes(), raw)
        self.assertFalse((self.library.root / "originals" / (ident + ".mid")).exists())
        self.assertFalse((self.library.root / "settings" / (ident + ".json")).exists())
        self.assertNotIn(ident, self.library._parsed)
        self.assertNotIn(ident, self.library._settings)
        self.assertFalse(any(key[0] == ident for key in self.library._compiled))
        self.assertEqual(MusicLibrary(self.library.root, self.library.legacy_dir).refresh(), [])
        backup = next((self.library.root / "trash").iterdir())
        self.assertEqual((backup / "original.mid").read_bytes(), raw)
        self.assertEqual(json.loads((backup / "settings.json").read_text())["speed"], .5)
        self.assertFalse(self.library.import_file(external.name, raw)["duplicate"])
        self.assertEqual(self.library.settings(ident)["speed"], 1)

    def test_delete_legacy_does_not_reappear_after_refresh_or_restart(self):
        self.library.legacy_dir.mkdir()
        path = self.library.legacy_dir / "old.txt"
        path.write_bytes(b"B 100\nF 200\n")
        ident = self.library.refresh()[0]["id"]
        self.library.delete(ident)
        self.assertFalse(path.exists())
        self.assertEqual(self.library.refresh(), [])
        self.assertEqual(MusicLibrary(self.library.root, self.library.legacy_dir).refresh(), [])
        self.assertEqual(next((self.library.root / "trash").glob("*/original.txt")).read_bytes(), b"B 100\nF 200\n")

    def test_delete_manifest_failure_restores_files_index_and_cached_settings(self):
        ident = self.library.import_file("keep.mid", one_note())["song"]["id"]
        self.library.update_settings(ident, {"speed": .5})
        self.library.performance(ident)
        index = self.library.root / "index.json"
        original_index = index.read_bytes()
        replace = os.replace

        def fail_manifest(source_path, target_path):
            if Path(target_path) == index:
                raise OSError("simulated disk failure")
            return replace(source_path, target_path)

        with patch("backend.music.library.os.replace", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.library.delete(ident)
        self.assertEqual(index.read_bytes(), original_index)
        self.assertEqual(self.library.original(ident), one_note())
        self.assertEqual(self.library.settings(ident)["speed"], .5)
        self.assertEqual(MusicLibrary(self.library.root, self.library.legacy_dir).settings(ident)["speed"], .5)
        self.library.delete(ident)
        self.assertEqual(self.library.refresh(), [])

    def test_legacy_refresh_detects_edits_without_rewriting_original(self):
        scores = self.root / "scores"
        scores.mkdir()
        path = scores / "old.txt"
        path.write_bytes(b"B 100\n")
        original = path.read_bytes()
        ident = self.library.refresh()[0]["id"]
        self.assertEqual(self.library.detail(ident)["analysis"]["playable_notes"], 1)
        self.assertEqual(path.read_bytes(), original)
        path.write_bytes(b"B 100\nF 200\n")
        self.library.refresh()
        self.assertEqual(self.library.detail(ident)["analysis"]["playable_notes"], 2)

    def test_unsafe_index_cannot_escape_originals_directory(self):
        path = self.root / "music"
        path.mkdir()
        (path / "index.json").write_text(json.dumps({"songs": [{"id": "a" * 64, "extension": "/../../other", "name": "x", "filename": "x"}]}))
        with self.assertRaises(ValueError):
            self.library.refresh()

    def test_failed_manifest_commit_preserves_index_and_can_retry_import(self):
        self.library.import_file("first.mid", one_note(64))
        index = self.root / "music" / "index.json"
        old_index = index.read_bytes()
        replace = os.replace

        def fail_manifest(source_path, target_path):
            if Path(target_path).name == "index.json":
                raise OSError("simulated disk failure")
            return replace(source_path, target_path)

        with patch("backend.music.library.os.replace", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.library.import_file("second.mid", one_note(65))
        self.assertEqual(index.read_bytes(), old_index)
        self.assertEqual(len(self.library.summaries()), 1)
        self.assertFalse(index.with_name("index.json.tmp").exists())
        retried = self.library.import_file("second.mid", one_note(65))
        self.assertFalse(retried["duplicate"])
        reopened = MusicLibrary(self.root / "music", self.root / "scores")
        self.assertEqual(len(reopened.summaries()), 2)


class TimelineTests(unittest.TestCase):
    def test_processing_cost_does_not_accumulate_and_pause_rebases_clock(self):
        current = [10.]
        clock = TimelineClock(lambda: current[0])
        current[0] += .31  # includes work after an event nominally at .30
        self.assertAlmostEqual(clock.seconds_until(400_000), .09)
        clock.pause()
        current[0] += 100
        self.assertEqual(clock.position_us(), 310_000)
        clock.resume()
        current[0] += .09
        self.assertEqual(clock.position_us(), 400_000)


if __name__ == "__main__":
    unittest.main()
