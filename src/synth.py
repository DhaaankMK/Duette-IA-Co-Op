"""Sintetizador de áudio do Duette (somente biblioteca padrão).

Gera, em tempo de execução, os efeitos da interface e uma música ambiente em loop, sem depender
de arquivos de áudio. Os buffers são listas de floats (-1..1) e são convertidos para PCM de 16 bits
mono por ``to_pcm``. Nenhuma função aqui toca em rede, disco ou entradas externas.
"""

from __future__ import annotations

import math
import random
from array import array

Buffer = list[float]


class Synth:
    def __init__(self, rate: int = 22050):
        self.rate = rate

    def n(self, seconds: float) -> int:
        return max(1, int(self.rate * seconds))

    def tone(self, dur: float, f0: float, f1: float | None = None, wave: str = "sine", vol: float = 0.5,
             attack: float = 0.004, decay: float = 3.0, vibrato: float = 0.0) -> Buffer:
        count = self.n(dur)
        f1 = f0 if f1 is None else f1
        out = [0.0] * count
        phase = 0.0
        atk = max(1, int(attack * self.rate))
        two_pi = 2 * math.pi
        for i in range(count):
            u = i / count
            freq = f0 * ((f1 / f0) ** u)
            if vibrato:
                freq *= 1.0 + 0.012 * math.sin(two_pi * vibrato * i / self.rate)
            phase += two_pi * freq / self.rate
            if wave == "sine":
                value = math.sin(phase)
            elif wave == "square":
                value = 0.6 if math.sin(phase) >= 0 else -0.6
            elif wave == "saw":
                value = 2.0 * ((phase / two_pi) % 1.0) - 1.0
            else:
                value = 2.0 * abs(2.0 * ((phase / two_pi) % 1.0) - 1.0) - 1.0
            out[i] = value * min(1.0, i / atk) * ((1.0 - u) ** decay) * vol
        return out

    def pad(self, dur: float, freqs: tuple[float, ...], vol: float = 0.12) -> Buffer:
        """Acorde suave: várias senoides levemente desafinadas com ataque e saída longos."""
        count = self.n(dur)
        out = [0.0] * count
        two_pi = 2 * math.pi
        voices = [(f * d, two_pi * f * d / self.rate) for f in freqs for d in (0.997, 1.003)]
        fade = max(1, int(self.rate * min(0.9, dur / 3)))
        for i in range(count):
            env = min(1.0, i / fade, (count - i) / fade)
            total = 0.0
            for _f, step in voices:
                total += math.sin(step * i)
            out[i] = total / len(voices) * env * vol
        return out

    def noise(self, dur: float, vol: float = 0.4, smooth: float = 0.5, smooth_end: float | None = None,
              attack: float = 0.002, decay: float = 3.0) -> Buffer:
        count = self.n(dur)
        smooth_end = smooth if smooth_end is None else smooth_end
        out = [0.0] * count
        y = 0.0
        atk = max(1, int(attack * self.rate))
        for i in range(count):
            u = i / count
            y += (smooth + (smooth_end - smooth) * u) * ((random.random() * 2.0 - 1.0) - y)
            out[i] = y * min(1.0, i / atk) * ((1.0 - u) ** decay) * vol
        return out

    def mix(self, *parts) -> Buffer:
        """Soma buffers; cada parte é ``buffer`` ou ``(buffer, atraso_em_segundos)``."""
        norm = []
        length = 0
        for part in parts:
            buf, delay = part if isinstance(part, tuple) else (part, 0.0)
            offset = int(self.rate * delay)
            norm.append((buf, offset))
            length = max(length, len(buf) + offset)
        out = [0.0] * length
        for buf, offset in norm:
            for i, value in enumerate(buf):
                out[i + offset] += value
        return out


def to_pcm(buf: Buffer, gain: float = 1.0, channels: int = 1) -> bytes:
    data = array("h")
    for value in buf:
        value *= gain
        if abs(value) > 0.7:
            value = math.tanh(value * 1.2)
        data.append(int(max(-1.0, min(1.0, value)) * 32000))
    if channels > 1:
        wide = array("h")
        for sample in data:
            wide.extend([sample] * channels)
        data = wide
    return data.tobytes()


def build_ui_sounds(rate: int = 22050) -> dict[str, Buffer]:
    s = Synth(rate)
    note = lambda f, d=0.18, v=0.3, w="triangle": s.tone(d, f, f, w, v, decay=2.2)
    return {
        "click": s.mix(s.tone(0.05, 760, 520, "sine", 0.45, decay=2)),
        "hover": s.tone(0.035, 900, 980, "sine", 0.12, attack=0.006, decay=2),
        "nav": s.mix(s.noise(0.18, 0.18, 0.5, 0.15, attack=0.04, decay=1.6), s.tone(0.16, 360, 620, "sine", 0.2, decay=2)),
        "confirm": s.mix(note(523, 0.1), (note(784, 0.16), 0.07)),
        "success": s.mix(note(523, 0.14), (note(659, 0.14), 0.09), (note(784, 0.14), 0.18), (note(1047, 0.3), 0.27)),
        "error": s.mix(s.tone(0.18, 300, 200, "square", 0.22, decay=1.8), (s.tone(0.22, 230, 150, "square", 0.22, decay=1.8), 0.12)),
        "notify": s.mix(note(880, 0.1, 0.28), (note(1320, 0.22, 0.26), 0.09)),
        "pop": s.mix(s.tone(0.12, 300, 900, "sine", 0.5, decay=2.6), (s.tone(0.1, 1200, 1500, "triangle", 0.12, decay=2.5), 0.05)),
        "intro": s.mix(
            s.pad(1.8, (261.63, 392.0, 523.25), 0.18),
            *[(s.tone(0.5, f, f, "triangle", 0.26, decay=2.2), 0.14 * i)
              for i, f in enumerate((523.25, 659.25, 783.99, 1046.5))],
            (s.tone(0.9, 2093, 2093, "sine", 0.1, decay=3.4), 0.55),
        ),
    }


def build_ambient(rate: int = 22050, bpm: int = 84) -> Buffer:
    """Loop calmo de 4 compassos (Am9 - Fmaj7 - Cmaj7 - G6) com pad, baixo e notas suaves."""
    s = Synth(rate)
    beat = 60.0 / bpm
    bar = beat * 4
    chords = [
        ((220.0, 261.63, 329.63, 392.0), 110.0),     # Am7/9
        ((174.61, 261.63, 329.63, 440.0), 87.31),    # Fmaj7
        ((196.0, 261.63, 329.63, 493.88), 130.81),   # Cmaj7
        ((196.0, 246.94, 293.66, 329.63), 98.0),     # G6
    ]
    total = int(rate * bar * len(chords))
    out = [0.0] * total
    rng = random.Random(7)

    def add(buf: Buffer, at: int) -> None:
        for i, value in enumerate(buf):
            out[(at + i) % total] += value

    for index, (freqs, bass) in enumerate(chords):
        base = int(rate * bar * index)
        add(s.pad(bar + 0.6, freqs, 0.13), base)
        add(s.tone(bar * 0.9, bass, bass, "sine", 0.3, attack=0.02, decay=1.2), base)
        for step in range(8):
            if rng.random() < 0.75:
                f = freqs[rng.randrange(len(freqs))] * (2 if step % 3 else 4) / (1 if step % 3 else 2)
                add(s.tone(beat * 0.9, f, f, "triangle", 0.07, attack=0.006, decay=3.0),
                    base + int(rate * beat * step / 2))
    return out
