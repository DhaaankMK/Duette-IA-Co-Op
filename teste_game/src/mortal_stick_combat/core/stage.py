"""Cenários animados: fundo pré-renderizado (rápido) + camadas animadas leves."""

import math
import random

import pygame

from ..config import settings as config

STAGES = ["DOJO", "NEON", "VULCÃO"]
STAGE_INFO = {
    "DOJO": "Dojo ao luar",
    "NEON": "Cidade neon",
    "VULCÃO": "Cratera do vulcão",
}
FLOOR_MARGIN = 120


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(width, height, top, bottom):
    surf = pygame.Surface((width, height))
    for y in range(height):
        pygame.draw.line(surf, _lerp(top, bottom, y / max(1, height - 1)), (0, y), (width, y))
    return surf


def _ridge(width, base, amp, seed, step=24):
    rnd = random.Random(seed)
    pts = [(0, base)]
    phase = rnd.uniform(0, 6)
    for x in range(0, width + step, step):
        pts.append((x, base - amp * (0.5 + 0.5 * math.sin(x * 0.011 + phase)) - rnd.uniform(0, amp * 0.25)))
    pts.append((width + step, base))
    return pts


class Stage:
    def __init__(self, name, width=None, height=None):
        self.name = name if name in STAGES else STAGES[0]
        self.w = width or config.SCREEN_WIDTH
        self.h = height or config.SCREEN_HEIGHT
        self.floor_y = self.h - FLOOR_MARGIN
        self.t = 0.0
        self.rnd = random.Random(self.name)
        self.stars = [(self.rnd.randint(0, self.w), self.rnd.randint(0, int(self.floor_y * 0.6)),
                       self.rnd.uniform(0, 6.28)) for _ in range(70)]
        self.clouds = [[self.rnd.uniform(0, self.w), self.rnd.randint(30, int(self.floor_y * 0.4)),
                        self.rnd.uniform(0.1, 0.35), self.rnd.randint(60, 140)] for _ in range(5)]
        self.motes = []
        self.back = pygame.Surface((self.w, self.h))
        self.build()

    # ------------------------------------------------------------------ pré-renderização
    def build(self):
        builder = {"DOJO": self._build_dojo, "NEON": self._build_neon, "VULCÃO": self._build_volcano}[self.name]
        builder(self.back)
        self._floor(self.back)
        vignette = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for i in range(10):
            pygame.draw.rect(vignette, (0, 0, 0, 7 * (10 - i)), (i * 10, i * 8, self.w - i * 20, self.h - i * 16), 12)
        self.back.blit(vignette, (0, 0))

    def _build_dojo(self, s):
        s.blit(_gradient(self.w, self.h, (10, 14, 40), (52, 40, 78)), (0, 0))
        moon = (int(self.w * 0.76), int(self.floor_y * 0.27))
        for r, a in ((95, 18), (70, 30), (50, 50)):
            glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow, (255, 240, 200, a), (r, r), r)
            s.blit(glow, (moon[0] - r, moon[1] - r))
        pygame.draw.circle(s, (250, 245, 220), moon, 38)
        pygame.draw.circle(s, (225, 220, 195), (moon[0] - 10, moon[1] + 6), 8)
        pygame.draw.circle(s, (225, 220, 195), (moon[0] + 12, moon[1] - 10), 5)
        for base, amp, col, seed in ((self.floor_y - 20, 150, (30, 30, 62), 1), (self.floor_y, 105, (20, 20, 45), 2)):
            pygame.draw.polygon(s, col, _ridge(self.w, base, amp, seed) + [(self.w, self.h), (0, self.h)])
        # Pagode ao fundo
        px, py = int(self.w * 0.2), self.floor_y - 10
        for i in range(4):
            wdt = 120 - i * 22
            top = py - 34 * (i + 1)
            pygame.draw.polygon(s, (14, 12, 30), [(px - wdt, top + 24), (px + wdt, top + 24),
                                                  (px + wdt - 24, top), (px - wdt + 24, top)])
            pygame.draw.rect(s, (22, 18, 40), (px - wdt + 30, top + 24, wdt * 2 - 60, 10))
        pygame.draw.line(s, (14, 12, 30), (px, py - 150), (px, py - 190), 4)

    def _build_neon(self, s):
        s.blit(_gradient(self.w, self.h, (14, 6, 38), (70, 18, 80)), (0, 0))
        rnd = random.Random("neon")
        for layer, (col, hmin, hmax, wmin, wmax) in enumerate(
                (((26, 14, 56), 120, 300, 50, 90), ((14, 8, 34), 80, 230, 60, 110))):
            x = -20
            while x < self.w:
                bw, bh = rnd.randint(wmin, wmax), rnd.randint(hmin, hmax)
                top = self.floor_y - bh
                pygame.draw.rect(s, col, (x, top, bw, bh + 20))
                for wx in range(x + 8, x + bw - 8, 14):
                    for wy in range(top + 10, self.floor_y - 6, 18):
                        if rnd.random() < (0.28 if layer == 0 else 0.4):
                            pygame.draw.rect(s, rnd.choice(((255, 220, 120), (120, 220, 255), (255, 120, 220))),
                                             (wx, wy, 6, 8))
                x += bw + rnd.randint(2, 14)
        self.signs = [(int(self.w * 0.18), int(self.floor_y * 0.45), (255, 40, 180), "NEON"),
                      (int(self.w * 0.68), int(self.floor_y * 0.35), (40, 230, 255), "DUELO")]

    def _build_volcano(self, s):
        s.blit(_gradient(self.w, self.h, (28, 6, 10), (150, 44, 14)), (0, 0))
        cx = int(self.w * 0.5)
        pygame.draw.polygon(s, (24, 10, 12), [(cx - self.w * 0.42, self.floor_y), (cx - 70, self.floor_y * 0.38),
                                              (cx + 70, self.floor_y * 0.38), (cx + self.w * 0.42, self.floor_y)])
        pygame.draw.polygon(s, (255, 130, 30), [(cx - 70, self.floor_y * 0.38), (cx + 70, self.floor_y * 0.38),
                                                (cx + 36, self.floor_y * 0.34), (cx - 36, self.floor_y * 0.34)])
        for side in (-1, 1):
            pygame.draw.polygon(s, (255, 90, 20), [(cx + side * 40, self.floor_y * 0.38),
                                                   (cx + side * 62, self.floor_y * 0.38),
                                                   (cx + side * 150, self.floor_y), (cx + side * 118, self.floor_y)])
        for base, amp, col, seed in ((self.floor_y, 90, (14, 6, 8), 5),):
            pygame.draw.polygon(s, col, _ridge(self.w, base, amp, seed) + [(self.w, self.h), (0, self.h)])

    def _floor(self, s):
        fy = self.floor_y
        top, bottom, line = {"DOJO": ((70, 52, 40), (34, 24, 22), (240, 200, 120)),
                             "NEON": ((34, 20, 60), (14, 8, 30), (255, 60, 190)),
                             "VULCÃO": ((46, 24, 24), (18, 10, 12), (255, 110, 30))}[self.name]
        s.blit(_gradient(self.w, self.h - fy, top, bottom), (0, fy))
        spacing = 64
        for i in range(-12, self.w // spacing + 14):
            x0 = i * spacing
            xb = self.w / 2 + (x0 - self.w / 2) * 1.9
            pygame.draw.line(s, _lerp(top, (0, 0, 0), 0.45), (x0, fy), (xb, self.h), 2)
        for k in range(1, 5):
            y = fy + (self.h - fy) * (k / 4) ** 1.6
            pygame.draw.line(s, _lerp(top, (0, 0, 0), 0.4), (0, y), (self.w, y), 2)
        pygame.draw.line(s, line, (0, fy), (self.w, fy), 5)
        glow = pygame.Surface((self.w, 26), pygame.SRCALPHA)
        for i in range(13):
            pygame.draw.line(glow, (*line, 70 - i * 5), (0, i * 2), (self.w, i * 2), 2)
        s.blit(glow, (0, fy + 3))

    # ------------------------------------------------------------------ animação
    def update(self):
        self.t += 1 / 60
        for cloud in self.clouds:
            cloud[0] = (cloud[0] + cloud[2]) % (self.w + 200)
        rnd = random
        if self.name == "VULCÃO" and rnd.random() < 0.5 and len(self.motes) < 70:
            self.motes.append([rnd.uniform(0, self.w), self.floor_y + rnd.uniform(0, 30), rnd.uniform(-0.3, 0.3),
                               rnd.uniform(-1.8, -0.6), rnd.randint(60, 140)])
        elif self.name == "DOJO" and rnd.random() < 0.15 and len(self.motes) < 40:
            self.motes.append([rnd.uniform(0, self.w), -10, rnd.uniform(-1.2, -0.3), rnd.uniform(0.5, 1.2), 600])
        elif self.name == "NEON" and len(self.motes) < 90:
            self.motes.append([rnd.uniform(0, self.w + 100), -10, -2.0, rnd.uniform(9, 14), 70])
        for m in self.motes:
            m[0] += m[2]
            m[1] += m[3]
            m[4] -= 1
        self.motes = [m for m in self.motes if m[4] > 0 and m[1] < self.h + 10]

    def draw(self, surface):
        surface.blit(self.back, (0, 0))
        if self.name == "DOJO":
            for x, y, ph in self.stars:
                b = int(150 + 100 * math.sin(self.t * 2 + ph))
                surface.set_at((x, y), (b, b, b))
        if self.name in ("DOJO", "NEON"):
            for x, y, speed, size in self.clouds:
                layer = pygame.Surface((size * 2, size // 2), pygame.SRCALPHA)
                pygame.draw.ellipse(layer, (200, 200, 235, 22 if self.name == "DOJO" else 14), layer.get_rect())
                surface.blit(layer, (x - 100, y))
        if self.name == "NEON":
            for x, y, col, text in getattr(self, "signs", ()):
                if int(self.t * 8 + x) % 23 == 0:
                    continue  # tremulação do letreiro
                font = pygame.font.SysFont("Impact", 40)
                label = font.render(text, True, col)
                glow = pygame.transform.smoothscale(label, (label.get_width() + 14, label.get_height() + 10))
                glow.set_alpha(70)
                surface.blit(glow, (x - 7, y - 5))
                surface.blit(label, (x, y))
            for x, y, vx, vy, _life in self.motes:
                pygame.draw.line(surface, (120, 130, 190), (x, y), (x + vx * 1.5, y + vy * 1.5), 1)
        elif self.name == "DOJO":
            for x, y, vx, vy, _life in self.motes:
                pygame.draw.ellipse(surface, (255, 190, 210), (int(x), int(y), 6, 4))
        else:
            pulse = 0.5 + 0.5 * math.sin(self.t * 3)
            glow = pygame.Surface((self.w, 14), pygame.SRCALPHA)
            glow.fill((255, 90, 20, int(40 + 40 * pulse)))
            surface.blit(glow, (0, self.floor_y - 10))
            for x, y, vx, vy, life in self.motes:
                c = (255, int(120 + 100 * (life / 140)), 30)
                pygame.draw.circle(surface, c, (int(x), int(y)), 2)
