"""Som do aplicativo: efeitos da interface e música ambiente (opcionais).

Usa ``pygame.mixer`` quando disponível. Qualquer falha (sem pygame, sem dispositivo de áudio,
arquivo ausente ou manifesto inválido) apenas desativa o som: o app nunca quebra por causa dele.

Os efeitos e a música são sintetizados por ``synth.py`` (em segundo plano, sem travar a interface).
Se existir um arquivo para o mesmo nome no ``sound_manifest.json``, ele tem prioridade.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .logger import get_logger
from .paths import assets_dir

log = get_logger("sound")

MUSIC_GAIN = 0.30            # volume da música relativo ao volume geral
HOVER_MIN_GAP = 0.09         # evita "metralhadora" ao passar o mouse sobre vários botões


class SoundManager:
    def __init__(self, enabled: bool = True, volume: int = 70, base: Path | None = None,
                 music_enabled: bool = True):
        self.enabled = enabled
        self.music_enabled = music_enabled
        self.volume = max(0, min(100, int(volume)))
        self._base = base or assets_dir()
        self._sounds: dict[str, object] = {}
        self._mixer = None
        self._ready = False
        self._music = None
        self._music_channel = None
        self._music_wanted = False
        self._building = False
        self._lock = threading.Lock()
        self._last_hover = 0.0

    # ------------------------------------------------------------------ inicialização
    def _init(self) -> None:
        if self._ready:
            return
        self._ready = True
        try:
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            import pygame.mixer as mixer  # type: ignore

            mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            mixer.set_num_channels(12)
            self._mixer = mixer
        except Exception as exc:
            log.info("Áudio indisponível (%s: %s); o app seguirá sem som", type(exc).__name__, exc)
            self._mixer = None
            return
        try:
            manifest = json.loads((self._base / "sound_manifest.json").read_text(encoding="utf-8"))
            entries = manifest.get("sounds", [])
        except (OSError, ValueError, AttributeError):
            entries = []
        for item in entries:
            try:
                name, file = str(item["name"]), str(item["file"])
                path = (self._base / file).resolve()
                if self._base.resolve() not in path.parents or not path.is_file():
                    continue
                self._sounds[name] = self._mixer.Sound(str(path))
            except Exception:
                continue
        if not self._building:
            self._building = True
            threading.Thread(target=self._build_async, name="duette-audio", daemon=True).start()

    def _build_async(self) -> None:
        """Sintetiza efeitos e música sem bloquear a interface."""
        try:
            from . import synth

            mixer = self._mixer
            rate, _fmt, channels = mixer.get_init()  # type: ignore[union-attr]
            for name, buf in synth.build_ui_sounds(rate).items():
                if name in self._sounds:
                    continue  # arquivo do manifesto tem prioridade
                sound = mixer.Sound(buffer=synth.to_pcm(buf, 1.0, channels))  # type: ignore[union-attr]
                with self._lock:
                    self._sounds[name] = sound
            music = mixer.Sound(buffer=synth.to_pcm(synth.build_ambient(rate), 0.9, channels))  # type: ignore[union-attr]
            with self._lock:
                self._music = music
            log.debug("Áudio sintetizado: %d efeitos e música", len(self._sounds))
            if self._music_wanted:
                self._play_music()
        except Exception as exc:
            log.warning("Falha ao sintetizar áudio: %s: %s", type(exc).__name__, exc)

    # ------------------------------------------------------------------ configuração
    def configure(self, enabled: bool, volume: int, music_enabled: bool | None = None) -> None:
        self.enabled = enabled
        self.volume = max(0, min(100, int(volume)))
        if music_enabled is not None:
            self.music_enabled = music_enabled
        self._apply_music_volume()
        if self.enabled and self.music_enabled and self._music_wanted:
            self._play_music()
        elif self._music is not None and not (self.enabled and self.music_enabled):
            self._fade_out()

    # ------------------------------------------------------------------ efeitos
    def play(self, name: str) -> None:
        if not self.enabled:
            return
        self._init()
        if name == "hover":
            now = time.monotonic()
            if now - self._last_hover < HOVER_MIN_GAP:
                return
            self._last_hover = now
        with self._lock:
            sound = self._sounds.get(name)
        if sound is None:
            return
        try:
            sound.set_volume(self.volume / 100.0 * (0.35 if name == "hover" else 1.0))  # type: ignore[attr-defined]
            sound.play()  # type: ignore[attr-defined]
        except Exception:
            pass

    # ------------------------------------------------------------------ música
    def start_music(self) -> None:
        """Pede a música ambiente; ela toca assim que estiver sintetizada."""
        self._music_wanted = True
        if not (self.enabled and self.music_enabled):
            return
        self._init()
        if self._music is not None:
            self._play_music()

    def stop_music(self) -> None:
        self._music_wanted = False
        self._fade_out()

    def _play_music(self) -> None:
        if not (self.enabled and self.music_enabled) or self._music is None:
            return
        try:
            self._apply_music_volume()
            if self._music_channel is None or not self._music_channel.get_busy():
                self._music_channel = self._music.play(loops=-1, fade_ms=1800)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _fade_out(self) -> None:
        if self._music is not None:
            try:
                self._music.fadeout(600)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._music_channel = None

    def _apply_music_volume(self) -> None:
        if self._music is not None:
            try:
                self._music.set_volume(self.volume / 100.0 * MUSIC_GAIN)  # type: ignore[attr-defined]
            except Exception:
                pass

    def shutdown(self) -> None:
        self._music_wanted = False
        if self._mixer is not None:
            try:
                self._mixer.stop()
            except Exception:
                pass
