"""Efeitos visuais: faíscas, poeira, anéis de choque, textos flutuantes e estilhaços."""

import math
import random

import pygame

MAX_EFFECTS = 420


def _alpha_circle(surface, color, pos, radius, alpha, width=0):
    radius = max(1, int(radius))
    layer = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
    pygame.draw.circle(layer, (*color[:3], max(0, min(255, int(alpha)))), (radius + 2, radius + 2), radius, width)
    surface.blit(layer, (int(pos[0]) - radius - 2, int(pos[1]) - radius - 2))


class Spark:
    """Faísca em forma de traço, ejetada no impacto."""

    def __init__(self, x, y, angle, speed, color, life=14):
        self.x, self.y = x, y
        self.vx, self.vy = math.cos(angle) * speed, math.sin(angle) * speed
        self.color, self.life, self.max_life = color, life, life

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.35
        self.vx *= 0.94
        self.life -= 1

    def draw(self, surface):
        fade = self.life / self.max_life
        tail = (self.x - self.vx * 1.8, self.y - self.vy * 1.8)
        color = tuple(int(c * (0.4 + 0.6 * fade)) for c in self.color)
        pygame.draw.line(surface, color, (int(self.x), int(self.y)), (int(tail[0]), int(tail[1])),
                         max(1, int(3 * fade)))


class Dust:
    """Nuvem de poeira translúcida que cresce e some."""

    def __init__(self, x, y, vx, vy, size, life=22, color=(170, 170, 180)):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.size, self.life, self.max_life, self.color = size, life, life, color

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vx *= 0.92
        self.vy *= 0.9
        self.life -= 1

    def draw(self, surface):
        fade = self.life / self.max_life
        _alpha_circle(surface, self.color, (self.x, self.y), self.size * (1.6 - fade * 0.6), 110 * fade)


class Ring:
    """Onda de choque circular."""

    def __init__(self, x, y, r0, r1, color, life=16, width=4):
        self.x, self.y, self.r0, self.r1 = x, y, r0, r1
        self.color, self.life, self.max_life, self.width = color, life, life, width

    def update(self):
        self.life -= 1

    def draw(self, surface):
        u = 1.0 - self.life / self.max_life
        radius = self.r0 + (self.r1 - self.r0) * (1 - (1 - u) ** 2)
        _alpha_circle(surface, self.color, (self.x, self.y), radius, 230 * (1 - u),
                      max(1, int(self.width * (1 - u)) + 1))


class FloatText:
    """Texto que sobe e desaparece (dano, COMBO, CRÍTICO...)."""

    _cache = {}

    def __init__(self, x, y, text, color, size=28, life=48, rise=1.1):
        key = (text, color, size)
        if key not in FloatText._cache:
            if len(FloatText._cache) > 80:
                FloatText._cache.clear()
            font = pygame.font.SysFont(None, size, bold=True)
            body = font.render(text, True, color)
            edge = font.render(text, True, (10, 10, 16))
            img = pygame.Surface((body.get_width() + 4, body.get_height() + 4), pygame.SRCALPHA)
            for dx, dy in ((0, 2), (4, 2), (2, 0), (2, 4)):
                img.blit(edge, (dx, dy))
            img.blit(body, (2, 2))
            FloatText._cache[key] = img
        self.image = FloatText._cache[key]
        self.x, self.y, self.rise = x, y, rise
        self.life = self.max_life = life

    def update(self):
        self.y -= self.rise * (0.4 + self.life / self.max_life)
        self.life -= 1

    def draw(self, surface):
        u = 1.0 - self.life / self.max_life
        scale = 1.0 + 0.5 * max(0.0, 1.0 - u * 6.0)       # "pop" inicial
        image = self.image
        if scale > 1.02:
            image = pygame.transform.smoothscale(
                image, (int(image.get_width() * scale), int(image.get_height() * scale)))
        if u > 0.6:
            image = image.copy()
            image.set_alpha(int(255 * (1 - (u - 0.6) / 0.4)))
        surface.blit(image, image.get_rect(center=(int(self.x), int(self.y))))


class Shard:
    """Estilhaço giratório (impactos pesados e KO)."""

    def __init__(self, x, y, color, power=1.0):
        angle = random.uniform(-math.pi, 0)
        speed = random.uniform(3, 9) * power
        self.x, self.y = x, y
        self.vx, self.vy = math.cos(angle) * speed, math.sin(angle) * speed
        self.rot, self.spin = random.uniform(0, 6.28), random.uniform(-0.4, 0.4)
        self.size = random.uniform(3, 7)
        self.color, self.life = color, random.randint(24, 40)
        self.max_life = self.life

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.45
        self.rot += self.spin
        self.life -= 1

    def draw(self, surface):
        pts = [(self.x + math.cos(self.rot + a) * self.size * r, self.y + math.sin(self.rot + a) * self.size * r)
               for a, r in ((0, 1.0), (2.4, 0.7), (4.2, 0.9))]
        pygame.draw.polygon(surface, self.color, pts)


class Mote:
    """Partícula ambiente que sobe (brasas, brilhos)."""

    def __init__(self, x, y, color, life=40):
        self.x, self.y = x, y
        self.vx, self.vy = random.uniform(-0.6, 0.6), random.uniform(-1.6, -0.5)
        self.color, self.life, self.max_life = color, life, life

    def update(self):
        self.x += self.vx + math.sin(self.life * 0.3) * 0.3
        self.y += self.vy
        self.life -= 1

    def draw(self, surface):
        fade = self.life / self.max_life
        pygame.draw.circle(surface, tuple(int(c * fade) for c in self.color), (int(self.x), int(self.y)),
                           max(1, int(2.5 * fade)))


class Effects:
    def __init__(self):
        self.items = []

    def add(self, item):
        if len(self.items) < MAX_EFFECTS:
            self.items.append(item)

    def update(self):
        for item in self.items:
            item.update()
        self.items = [i for i in self.items if i.life > 0]

    def draw(self, surface):
        for item in self.items:
            item.draw(surface)

    # ------------------------------------------------------------------ receitas
    def hit(self, x, y, direction, power, color):
        """Impacto de golpe: faíscas direcionais, anel e (se forte) estilhaços."""
        count = 8 + int(power * 10)
        for _ in range(count):
            angle = (0 if direction > 0 else math.pi) + random.uniform(-0.9, 0.9)
            self.add(Spark(x, y, angle, random.uniform(4, 9 + power * 5), random.choice((color, (255, 255, 255), (255, 210, 80)))))
        self.add(Ring(x, y, 6, 30 + power * 28, (255, 255, 255), life=12, width=4))
        if power > 0.6:
            for _ in range(int(4 + power * 6)):
                self.add(Shard(x, y, color, power))

    def dust(self, x, y, count=4, spread=5.0, size=7):
        for _ in range(count):
            self.add(Dust(x + random.uniform(-8, 8), y, random.uniform(-spread, spread) * 0.4,
                          random.uniform(-1.2, -0.2), random.uniform(size * 0.6, size)))

    def land(self, x, y, power):
        self.dust(x, y, 4 + int(power * 4), spread=7 + power * 4, size=8 + power * 4)
        self.add(Ring(x, y - 2, 4, 26 + power * 20, (200, 200, 215), life=12, width=3))

    def jump_ring(self, x, y):
        self.add(Ring(x, y, 6, 30, (0, 225, 255), life=14, width=3))

    def text(self, x, y, text, color=(255, 255, 255), size=28, life=48):
        self.add(FloatText(x, y, text, color, size, life))

    def ko_burst(self, x, y, color):
        for _ in range(26):
            self.add(Shard(x, y, color, 1.6))
        self.add(Ring(x, y, 10, 160, (255, 255, 255), life=24, width=8))
        self.add(Ring(x, y, 10, 110, (255, 220, 0), life=20, width=5))
