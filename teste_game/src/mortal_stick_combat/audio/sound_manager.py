"""Efeitos sonoros e música sintetizados em tempo de execução (sem arquivos de áudio).

Cada som é montado a partir de osciladores com envelope, varreduras de frequência e ruído
filtrado. Há variações de altura para os golpes, evitando o efeito "metralhadora" de repetir
sempre a mesma amostra. A música é um loop procedural gerado em segundo plano.
"""

import math
import random
import threading
from array import array

import pygame

from ..config import settings as config

MUSIC_GAIN = 0.32      # volume da música em relação ao volume geral
MUSIC_BPM = 128


class _Synth:
    """Pequeno sintetizador de buffers mono (listas de floats entre -1 e 1)."""

    def __init__(self, rate):
        self.rate = rate

    def tone(self, dur, f0, f1=None, wave="sine", vol=0.5, attack=0.004, decay=3.0, vibrato=0.0):
        n = max(1, int(self.rate * dur))
        f1 = f0 if f1 is None else f1
        out = [0.0] * n
        phase = 0.0
        atk = max(1, int(attack * self.rate))
        two_pi = 2 * math.pi
        for i in range(n):
            u = i / n
            freq = f0 * ((f1 / f0) ** u) if f0 > 0 and f1 > 0 else f0 + (f1 - f0) * u
            if vibrato:
                freq *= 1.0 + 0.03 * math.sin(two_pi * vibrato * i / self.rate)
            phase += two_pi * freq / self.rate
            if wave == "sine":
                value = math.sin(phase)
            elif wave == "square":
                value = 0.7 if math.sin(phase) >= 0 else -0.7
            elif wave == "saw":
                value = 2.0 * ((phase / two_pi) % 1.0) - 1.0
            else:  # triangle
                value = 2.0 * abs(2.0 * ((phase / two_pi) % 1.0) - 1.0) - 1.0
            env = min(1.0, i / atk) * ((1.0 - u) ** decay)
            out[i] = value * env * vol
        return out

    def noise(self, dur, vol=0.5, smooth=0.5, smooth_end=None, attack=0.002, decay=3.0):
        n = max(1, int(self.rate * dur))
        smooth_end = smooth if smooth_end is None else smooth_end
        out = [0.0] * n
        y = 0.0
        atk = max(1, int(attack * self.rate))
        rnd = random.random
        for i in range(n):
            u = i / n
            alpha = smooth + (smooth_end - smooth) * u
            y += alpha * ((rnd() * 2.0 - 1.0) - y)
            out[i] = y * min(1.0, i / atk) * ((1.0 - u) ** decay) * vol
        return out

    @staticmethod
    def mix(*parts):
        """Soma buffers; cada parte é ``buffer`` ou ``(buffer, atraso_em_amostras)``."""
        length = 0
        norm = []
        for part in parts:
            buf, delay = part if isinstance(part, tuple) else (part, 0)
            norm.append((buf, delay))
            length = max(length, len(buf) + delay)
        out = [0.0] * length
        for buf, delay in norm:
            for i, value in enumerate(buf):
                out[i + delay] += value
        return out

    def delay(self, seconds):
        return int(self.rate * seconds)


class SoundManager:
    def __init__(self):
        self.enabled = False
        self.rate = 22050
        self.channels = 1
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            init = pygame.mixer.get_init()
            if init:
                self.rate, fmt, self.channels = init
                self.enabled = fmt == -16
            pygame.mixer.set_num_channels(20)
        except Exception as e:
            print("Aviso: Mixer de áudio não inicializado.", e)

        self.sounds = {}
        self._volume = config.VIDEO_SETTINGS.get("volume", 70) / 100.0
        self._music = None
        self._music_channel = None
        self._music_building = False
        self._music_wanted = False
        self._lock = threading.Lock()
        if self.enabled:
            try:
                self._generate_sfx()
            except Exception as e:  # o jogo deve funcionar mesmo sem som
                print("Aviso: falha ao gerar efeitos sonoros.", e)
                self.enabled = False
            self.set_volume(config.VIDEO_SETTINGS.get("volume", 70))

    # ------------------------------------------------------------------ geração
    def _to_sound(self, buf, gain=1.0):
        data = array("h")
        for value in buf:
            value *= gain
            value = math.tanh(value * 1.2) if abs(value) > 0.7 else value  # saturação suave
            data.append(int(max(-1.0, min(1.0, value)) * 32000))
        if self.channels > 1:
            stereo = array("h")
            for sample in data:
                stereo.extend([sample] * self.channels)
            data = stereo
        return pygame.mixer.Sound(buffer=data.tobytes())

    def _generate_sfx(self):
        s = _Synth(self.rate)
        add = lambda name, buf, gain=1.0: self.sounds.__setitem__(name, self._to_sound(buf, gain))
        variants = lambda name, makers: self.sounds.__setitem__(name, [self._to_sound(m(), 1.0) for m in makers])

        # Interface
        add("click", s.tone(0.05, 700, 500, "sine", 0.45, decay=2))
        add("nav", s.tone(0.06, 520, 640, "triangle", 0.4, decay=2))
        add("confirm", s.mix(s.tone(0.09, 520, 520, "triangle", 0.4, decay=1.5),
                             (s.tone(0.14, 780, 780, "triangle", 0.4, decay=2), s.delay(0.07))))
        add("back", s.tone(0.1, 520, 300, "triangle", 0.4, decay=2))
        add("pause", s.tone(0.12, 600, 280, "square", 0.25, decay=2))
        add("unpause", s.tone(0.12, 280, 600, "square", 0.25, decay=2))

        # Movimento
        add("jump", s.mix(s.tone(0.15, 260, 560, "sine", 0.5, decay=2),
                          s.noise(0.08, 0.08, 0.15, 0.4)))
        add("double_jump", s.mix(s.tone(0.18, 420, 980, "sine", 0.45, decay=2.2),
                                 (s.tone(0.12, 1300, 1700, "triangle", 0.18, decay=2), s.delay(0.05))))
        add("land", s.mix(s.tone(0.13, 130, 55, "sine", 0.7, decay=2.5), s.noise(0.09, 0.3, 0.12, 0.05)))
        add("step", s.noise(0.04, 0.22, 0.25, 0.1, decay=2))

        # Golpes no ar (com variações de altura)
        variants("whoosh_light", [lambda f=f: s.noise(0.16, 0.42, f, f * 0.3, attack=0.03, decay=1.6)
                                  for f in (0.55, 0.45, 0.65)])
        variants("whoosh_heavy", [lambda f=f: s.mix(s.noise(0.3, 0.55, f, f * 0.2, attack=0.07, decay=1.8),
                                                    s.tone(0.28, 160, 70, "sine", 0.25, decay=2))
                                  for f in (0.3, 0.24)])
        variants("swing_blade", [lambda f=f: s.mix(s.noise(0.2, 0.3, 0.7, 0.35, attack=0.02, decay=1.8),
                                                   s.tone(0.2, f, f * 1.8, "triangle", 0.12, decay=2.5))
                                 for f in (900, 1050)])
        add("bow", s.mix(s.tone(0.2, 900, 220, "triangle", 0.35, decay=3), s.noise(0.06, 0.2, 0.5, 0.2)))
        add("whirl", s.mix(s.tone(0.28, 520, 760, "sine", 0.3, decay=1.5, vibrato=26),
                           s.noise(0.25, 0.12, 0.5, 0.3, attack=0.05, decay=1.5)))
        add("whiff", s.noise(0.1, 0.2, 0.3, 0.1, attack=0.02, decay=1.8))

        # Impactos
        variants("hit_light", [lambda p=p: s.mix(s.tone(0.14, 210 * p, 80 * p, "sine", 0.75, decay=2.6),
                                                 s.noise(0.08, 0.5, 0.45, 0.1, decay=2.2))
                               for p in (1.0, 0.88, 1.12)])
        variants("hit_heavy", [lambda p=p: s.mix(s.tone(0.3, 150 * p, 45 * p, "sine", 0.95, decay=2.4),
                                                 s.noise(0.2, 0.65, 0.3, 0.06, decay=2.4),
                                                 (s.tone(0.12, 320 * p, 160 * p, "square", 0.2, decay=3), 0))
                               for p in (1.0, 0.9)])
        variants("hit_blade", [lambda p=p: s.mix(s.noise(0.1, 0.5, 0.6, 0.25, decay=2.5),
                                                 s.tone(0.28, 1320 * p, 1300 * p, "sine", 0.28, decay=3.2),
                                                 s.tone(0.22, 2210 * p, 2190 * p, "sine", 0.16, decay=3.6),
                                                 s.tone(0.14, 180, 90, "sine", 0.55, decay=2.4))
                               for p in (1.0, 1.08)])
        add("crit", s.mix(s.tone(0.35, 1000, 1000, "sine", 0.3, decay=3.5),
                          (s.tone(0.3, 1500, 1500, "sine", 0.28, decay=3.5), s.delay(0.04)),
                          s.tone(0.3, 140, 40, "sine", 0.8, decay=2.2)))
        add("combo", s.mix(s.tone(0.18, 880, 880, "triangle", 0.35, decay=2.5),
                           (s.tone(0.22, 1320, 1320, "triangle", 0.35, decay=2.5), s.delay(0.07))))
        add("counter", s.mix(s.tone(0.2, 300, 900, "saw", 0.22, decay=2.5), s.noise(0.1, 0.3, 0.5, 0.2)))

        # Estados da luta
        add("beep", s.tone(0.16, 660, 660, "square", 0.3, decay=1.8))
        add("gong", s.mix(s.tone(1.1, 110, 108, "sine", 0.6, decay=2.2),
                          s.tone(1.0, 233, 231, "sine", 0.3, decay=2.4),
                          s.tone(0.8, 351, 349, "sine", 0.2, decay=2.6),
                          s.noise(0.15, 0.35, 0.3, 0.1)))
        add("ko", s.mix(s.tone(0.9, 190, 38, "sine", 1.0, decay=1.8),
                        s.noise(0.5, 0.7, 0.25, 0.04, decay=2.2),
                        (s.tone(0.6, 90, 30, "square", 0.25, decay=2), s.delay(0.08))))
        add("win", s.mix(*[(s.tone(0.34, f, f, "triangle", 0.4, decay=1.6), s.delay(i * 0.11))
                           for i, f in enumerate((523, 659, 784, 1047))]))
        add("heartbeat", s.mix(s.tone(0.12, 80, 50, "sine", 0.9, decay=2.5),
                               (s.tone(0.1, 70, 45, "sine", 0.7, decay=2.5), s.delay(0.17))))

    def _build_music(self):
        """Loop de 4 compassos (Am - F - C - G) com baixo, arpejo, bumbo e chimbal."""
        s = _Synth(self.rate)
        beat = 60.0 / MUSIC_BPM
        bar = beat * 4
        roots = [110.0, 87.31, 130.81, 98.0]                       # A2 F2 C3 G2
        chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63),
                  (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]
        total = int(self.rate * bar * len(roots))
        out = [0.0] * total
        for b, root in enumerate(roots):
            base = int(self.rate * bar * b)
            for step in range(8):                                   # colcheias
                at = base + int(self.rate * beat * step / 2)
                bass = s.tone(beat * 0.55, root, root, "triangle", 0.34, attack=0.006, decay=1.6)
                arp = s.tone(beat * 0.45, chords[b][step % 3] * 2, chords[b][step % 3] * 2, "sine",
                             0.15, attack=0.004, decay=2.4)
                for i, v in enumerate(bass if step % 2 == 0 else ()):
                    if at + i < total:
                        out[at + i] += v
                for i, v in enumerate(arp):
                    if at + i < total:
                        out[at + i] += v
            for q in range(4):                                      # bumbo nas semínimas
                at = base + int(self.rate * beat * q)
                for i, v in enumerate(s.tone(0.16, 120, 42, "sine", 0.55, attack=0.002, decay=2.2)):
                    if at + i < total:
                        out[at + i] += v
                at += int(self.rate * beat / 2)                     # chimbal no contratempo
                for i, v in enumerate(s.noise(0.05, 0.14, 0.9, 0.9, decay=2.0)):
                    if at + i < total:
                        out[at + i] += v
        return self._to_sound(out, 0.9)

    # ------------------------------------------------------------------ reprodução
    def play(self, name, volume=1.0):
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if isinstance(sound, list):
            sound = random.choice(sound)
        if sound is None:
            return
        try:
            channel = sound.play()
            if channel is not None and volume != 1.0:
                channel.set_volume(max(0.0, min(1.0, volume)))
        except pygame.error:
            pass

    def start_music(self):
        """Inicia a música (gerada em segundo plano na primeira vez)."""
        if not self.enabled or not config.VIDEO_SETTINGS.get("music", True):
            return
        self._music_wanted = True
        with self._lock:
            if self._music is None:
                if not self._music_building:
                    self._music_building = True
                    threading.Thread(target=self._build_music_async, name="musica", daemon=True).start()
                return
        self._play_music()

    def _build_music_async(self):
        try:
            music = self._build_music()
        except Exception as e:
            print("Aviso: falha ao gerar a música.", e)
            music = None
        with self._lock:
            self._music = music
            self._music_building = False
        if music is not None and self._music_wanted:
            self._play_music()

    def _play_music(self):
        try:
            self._music.set_volume(self._volume * MUSIC_GAIN)
            if self._music_channel is None or not self._music_channel.get_busy():
                self._music_channel = self._music.play(loops=-1)
        except (pygame.error, AttributeError):
            pass

    def stop_music(self, fade_ms=400):
        self._music_wanted = False
        if self._music is not None:
            try:
                self._music.fadeout(fade_ms)
            except pygame.error:
                pass
        self._music_channel = None

    def toggle_music(self):
        """Liga/desliga a música e grava a preferência."""
        playing = self._music_wanted
        config.VIDEO_SETTINGS["music"] = not playing
        config.save_video_settings()
        if playing:
            self.stop_music()
        else:
            self.start_music()

    def duck_music(self, ducked):
        """Abaixa a música (ex.: ao pausar)."""
        if self._music is not None:
            try:
                self._music.set_volume(self._volume * MUSIC_GAIN * (0.35 if ducked else 1.0))
            except pygame.error:
                pass

    def set_volume(self, percent):
        percent = max(0, min(100, int(percent)))
        self._volume = percent / 100.0
        for sound in self.sounds.values():
            for item in sound if isinstance(sound, list) else (sound,):
                item.set_volume(self._volume)
        if self._music is not None:
            try:
                self._music.set_volume(self._volume * MUSIC_GAIN)
            except pygame.error:
                pass
