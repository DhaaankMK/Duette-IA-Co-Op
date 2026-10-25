"""Testes do sintetizador e do gerenciador de som da interface (sem dispositivo de áudio real)."""

from __future__ import annotations

import math
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from src import synth  # noqa: E402
from src.sound import SoundManager  # noqa: E402


class SynthTests(unittest.TestCase):
    def test_ui_sounds_are_finite_and_bounded(self):
        sounds = synth.build_ui_sounds(8000)
        for name in ("click", "hover", "nav", "confirm", "success", "error", "notify", "pop", "intro"):
            self.assertIn(name, sounds)
            buf = sounds[name]
            self.assertTrue(buf and all(math.isfinite(v) for v in buf), name)
            self.assertLess(max(abs(v) for v in buf), 2.0, name)

    def test_ambient_loop_length(self):
        buf = synth.build_ambient(4000, bpm=84)
        self.assertAlmostEqual(len(buf) / 4000, 4 * 4 * 60 / 84, delta=0.01)

    def test_pcm_conversion(self):
        data = synth.to_pcm([0.0, 1.0, -1.0, 5.0], 1.0, channels=2)
        self.assertEqual(len(data), 4 * 2 * 2)       # 4 amostras x 2 canais x 2 bytes


class SoundManagerTests(unittest.TestCase):
    def test_disabled_manager_never_touches_mixer(self):
        sm = SoundManager(enabled=False)
        sm.play("click")
        sm.start_music()
        self.assertFalse(sm._ready)

    def test_play_and_music_do_not_raise(self):
        sm = SoundManager(enabled=True, volume=30)
        sm.play("click")
        sm.start_music()
        deadline = time.time() + 20
        while time.time() < deadline and (sm._mixer is not None) and sm._music is None:
            time.sleep(0.1)
        if sm._mixer is not None:
            self.assertIn("success", sm._sounds)
            sm.play("success")
            sm.configure(True, 50, music_enabled=False)
        sm.stop_music()
        sm.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
