"""HUD da luta: barras de vida, cronômetro, contagem, KO, resultado, pausa e painel de fala da IA."""

import math

import pygame

from ..config import settings as config

WHITE = (255, 255, 255)
CYAN = (0, 225, 255)
YELLOW = (255, 220, 0)
RED = (230, 50, 50)
INK = (10, 10, 18)
PANEL = (14, 16, 28)

STRATEGY_LABELS = {
    "aggressive": ("AGRESSIVA", (255, 90, 80)),
    "balanced": ("EQUILIBRADA", (255, 215, 70)),
    "defensive": ("DEFENSIVA", (90, 170, 255)),
    "retreat": ("RECUANDO", (255, 150, 60)),
    "idle": ("AGUARDANDO", (160, 160, 175)),
}


def wrap_text(font, text, max_width, max_lines=3):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if font.size(trial)[0] <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,; ") + "…"
    return lines


def draw_robot_icon(surface, rect, t, talking=False, tint=CYAN):
    """Cabeça de robô vetorial (mesma identidade do avatar padrão do Duette)."""
    x, y, w, h = rect
    pygame.draw.line(surface, (150, 160, 190), (x + w // 2, y + 2), (x + w // 2, y - 6), 3)
    pygame.draw.circle(surface, tint if int(t * 3) % 2 == 0 else (255, 90, 90), (x + w // 2, y - 8), 4)
    pygame.draw.rect(surface, (70, 80, 110), (x, y + 2, w, h - 2), border_radius=12)
    pygame.draw.rect(surface, (150, 165, 205), (x, y + 2, w, h - 2), 3, border_radius=12)
    blink = (t * 1.0) % 4.0 > 3.85
    for ex in (x + w * 0.3, x + w * 0.7):
        eye = pygame.Rect(0, 0, 10, 3 if blink else 10)
        eye.center = (int(ex), y + int(h * 0.42))
        pygame.draw.rect(surface, tint, eye, border_radius=3)
    mouth_h = 3 + (int(abs(math.sin(t * 14)) * 7) if talking else 0)
    mouth = pygame.Rect(0, 0, int(w * 0.42), mouth_h)
    mouth.center = (x + w // 2, y + int(h * 0.75))
    pygame.draw.rect(surface, (20, 25, 40), mouth, border_radius=3)


class HUD:
    def __init__(self):
        self.f_small = pygame.font.SysFont(None, 20)
        self.f_med = pygame.font.SysFont(None, 26, bold=True)
        self.f_body = pygame.font.SysFont(None, 25)
        self.f_big = pygame.font.SysFont("Impact", 64)
        self.f_huge = pygame.font.SysFont("Impact", 120)
        self.ghost = [1.0, 1.0]
        self._cache = {}

    # ------------------------------------------------------------------ utilidades
    def text(self, surface, font, content, color, pos, anchor="topleft", shadow=True):
        img = font.render(content, True, color)
        rect = img.get_rect(**{anchor: pos})
        if shadow:
            surface.blit(font.render(content, True, INK), rect.move(2, 2))
        surface.blit(img, rect)
        return rect

    def update(self, game):
        for i, player in enumerate((game.p1, game.p2)):
            target = max(0.0, player.health / max(1, player.max_health))
            if self.ghost[i] > target:
                self.ghost[i] = max(target, self.ghost[i] - 0.006)
            else:
                self.ghost[i] = target

    # ------------------------------------------------------------------ barras
    def _bar(self, surface, x, y, w, h, frac, ghost, mirror, t):
        slant = 10
        def poly(a, b):
            if mirror:
                return [(x + w - b, y), (x + w - a + slant, y), (x + w - a, y + h), (x + w - b - slant, y + h)]
            return [(x + a + slant, y), (x + b + slant, y), (x + b, y + h), (x + a, y + h)]
        pygame.draw.polygon(surface, (8, 8, 14), poly(0, w))
        if ghost > frac:
            pygame.draw.polygon(surface, (235, 235, 245), poly(0, int(w * ghost)))
        if frac > 0:
            if frac > 0.5:
                color = (60, 225, 110)
            elif frac > 0.25:
                color = (255, 205, 50)
            else:
                color = (255, 65, 55) if int(t * 6) % 2 == 0 else (255, 120, 90)
            pygame.draw.polygon(surface, color, poly(0, int(w * frac)))
            shine = [(px, py) for px, py in poly(0, int(w * frac))]
            pygame.draw.line(surface, (255, 255, 255), shine[0] if not mirror else shine[0],
                             shine[1] if not mirror else shine[1], 2)
        pygame.draw.polygon(surface, WHITE, poly(0, w), 2)

    def _portrait(self, surface, player, center, ring_color):
        pygame.draw.circle(surface, PANEL, center, 25)
        pygame.draw.circle(surface, ring_color, center, 25, 3)
        pygame.draw.circle(surface, player.color, (center[0], center[1] + 2), 13)
        pygame.draw.circle(surface, INK, (center[0], center[1] + 2), 13, 2)
        for dx in (-4, 4):
            pygame.draw.circle(surface, INK, (center[0] + dx + (2 if center[0] < 400 else -2), center[1]), 2)

    def draw_top(self, surface, game):
        w = surface.get_width()
        t = game.frame / 60.0
        margin, portrait = 22, 52
        bar_w = (w - 2 * (margin + portrait + 6) - 130) // 2
        y, h = 26, 26
        entries = ((game.p1, game.label_p1, False, margin + portrait + 6, 0, (70, 130, 255)),
                   (game.p2, game.label_p2, True, w - margin - portrait - 6 - bar_w, 1, (240, 70, 70)))
        for player, label, mirror, bx, idx, ring in entries:
            self._portrait(surface, player, (margin + 26, 42) if not mirror else (w - margin - 26, 42), ring)
            frac = max(0.0, player.health / max(1, player.max_health))
            self._bar(surface, bx, y, bar_w, h, frac, self.ghost[idx], mirror, t)
            anchor = "topright" if mirror else "topleft"
            ax = bx + bar_w if mirror else bx
            self.text(surface, self.f_med, label, WHITE, (ax, y + h + 6), anchor)
            info = f"{player.weapon_name}  ·  DANO {int(player.weapon_info['damage'])}"
            self.text(surface, self.f_small, info, (190, 195, 215), (ax, y + h + 28), anchor)
            # Barra fina de recarga do ataque (cheia = pronto).
            ready = 1.0 - player.attack_cooldown_fraction
            cw = int(bar_w * 0.5 * ready)
            cx0 = ax - int(bar_w * 0.5) if mirror else ax
            pygame.draw.rect(surface, (30, 32, 48), (cx0, y + h + 50, int(bar_w * 0.5), 4))
            pygame.draw.rect(surface, CYAN if ready >= 1 else (255, 150, 60),
                             (cx0 + (int(bar_w * 0.5) - cw if mirror else 0), y + h + 50, cw, 4))
            combo, timer = game.combo_show[idx]
            if combo >= 2 and timer > 0:
                self.text(surface, self.f_med, f"COMBO x{combo}", YELLOW, (ax, y + h + 62), anchor)
        # Cronômetro central.
        seconds = int(game.match_time)
        plate = pygame.Rect(0, 0, 96, 44)
        plate.midtop = (w // 2, 14)
        pygame.draw.rect(surface, PANEL, plate, border_radius=10)
        pygame.draw.rect(surface, (110, 120, 160), plate, 2, border_radius=10)
        self.text(surface, self.f_med, f"{seconds // 60}:{seconds % 60:02d}", WHITE, plate.center, "center")
        self.text(surface, self.f_small, "VS", (255, 120, 120), (w // 2, plate.bottom + 10), "center")

    # ------------------------------------------------------------------ painel de fala da IA
    def draw_ai_panel(self, surface, game):
        client = game.ai
        if not client:
            return
        w, h = surface.get_size()
        floor = h - 120
        pw = min(w - 60, 640)
        panel = pygame.Rect((w - pw) // 2, floor + 16, pw, 92)
        t = game.frame / 60.0
        backing = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(backing, (12, 14, 26, 225), backing.get_rect(), border_radius=14)
        surface.blit(backing, panel)
        pygame.draw.rect(surface, (70, 85, 130), panel, 2, border_radius=14)

        messages = client.messages()
        last = messages[-1] if messages else None
        shown_for = (4.0 + len(last["text"]) * 0.07) if last else 0.0
        fresh = bool(last) and last["age"] < shown_for
        talking = bool(last) and last["age"] * 45 < len(last["text"])

        draw_robot_icon(surface, (panel.x + 16, panel.y + 24, 54, 50), t, talking)
        name = client.ai_name
        self.text(surface, self.f_med, name, CYAN, (panel.x + 86, panel.y + 10))
        label, color = STRATEGY_LABELS.get(client.strategy, ("OBSERVANDO", (150, 160, 180)))
        badge = self.f_small.render(label, True, INK)
        brect = badge.get_rect(topright=(panel.right - 16, panel.y + 12)).inflate(16, 6)
        pygame.draw.rect(surface, color, brect, border_radius=9)
        surface.blit(badge, badge.get_rect(center=brect.center))

        body = pygame.Rect(panel.x + 86, panel.y + 36, panel.w - 106, 52)
        if last:
            visible = last["text"][: int(last["age"] * 45) + 1]
            lines = wrap_text(self.f_body, last["text"], body.w, 2)
            remaining = len(visible)
            tone = WHITE if fresh else (130, 138, 160)
            for i, line in enumerate(lines):
                chunk = line[:max(0, remaining)]
                remaining -= len(line) + 1
                if chunk:
                    self.text(surface, self.f_body, chunk, tone, (body.x, body.y + i * 24), shadow=False)
        else:
            self.text(surface, self.f_body, "Observando a luta...", (130, 138, 160), body.topleft, shadow=False)

    # ------------------------------------------------------------------ telas de estado
    def draw_countdown(self, surface, game):
        w, h = surface.get_size()
        step = game.phase_timer // 40            # 0,1,2 = 3,2,1 ; 3 = LUTE!
        u = (game.phase_timer % 40) / 40.0
        if step >= 3:
            label, color = "LUTE!", (255, 90, 60)
            u = (game.phase_timer - 120) / 30.0
        else:
            label, color = str(3 - step), YELLOW
        img = self.f_huge.render(label, True, color)
        scale = 1.0 + 0.8 * (1 - min(1.0, u * 3)) if step < 3 else 1.0 + 0.4 * u
        img = pygame.transform.smoothscale(img, (int(img.get_width() * scale), int(img.get_height() * scale)))
        img.set_alpha(int(255 * (1.0 - max(0.0, u - 0.7) / 0.3)))
        shadow = pygame.transform.smoothscale(self.f_huge.render(label, True, INK), img.get_size())
        shadow.set_alpha(img.get_alpha())
        surface.blit(shadow, shadow.get_rect(center=(w // 2 + 4, h // 2 - 60 + 4)))
        surface.blit(img, img.get_rect(center=(w // 2, h // 2 - 60)))

    def draw_ko(self, surface, game):
        w, h = surface.get_size()
        u = min(1.0, game.ko_timer / 14.0)
        img = self.f_huge.render("K.O.", True, (255, 60, 50))
        scale = 2.2 - 1.2 * (1 - (1 - u) ** 3)
        img = pygame.transform.smoothscale(img, (int(img.get_width() * scale), int(img.get_height() * scale)))
        surface.blit(img, img.get_rect(center=(w // 2, h // 2 - 70)))

    def draw_result(self, surface, game):
        w, h = surface.get_size()
        u = min(1.0, (game.ko_timer - 70) / 18.0)
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, int(170 * u)))
        surface.blit(overlay, (0, 0))
        panel = pygame.Rect(0, 0, min(560, w - 60), 300)
        panel.center = (w // 2, int(h * 0.46 + (1 - u) * 40))
        pygame.draw.rect(surface, PANEL, panel, border_radius=18)
        pygame.draw.rect(surface, YELLOW, panel, 3, border_radius=18)
        self.text(surface, self.f_big, game.winner_text, YELLOW, (panel.centerx, panel.y + 44), "center")
        stats = game.stats
        rows = (("Golpes certeiros", stats["hits"][0], stats["hits"][1]),
                ("Dano causado", int(stats["damage"][0]), int(stats["damage"][1])),
                ("Maior combo", stats["best_combo"][0], stats["best_combo"][1]),
                ("Vida restante", f"{int(game.p1.health)}", f"{int(game.p2.health)}"))
        self.text(surface, self.f_med, game.label_p1, (120, 170, 255), (panel.x + 330 - 150, panel.y + 92), "center")
        self.text(surface, self.f_med, game.label_p2, (255, 120, 120), (panel.x + 330 + 80, panel.y + 92), "center")
        for i, (name, a, b) in enumerate(rows):
            ry = panel.y + 124 + i * 30
            self.text(surface, self.f_body, name, (190, 195, 215), (panel.x + 30, ry))
            self.text(surface, self.f_body, str(a), WHITE, (panel.x + 330 - 150, ry), "midtop")
            self.text(surface, self.f_body, str(b), WHITE, (panel.x + 330 + 80, ry), "midtop")
        seconds = int(game.match_time)
        self.text(surface, self.f_small, f"Duração da luta: {seconds // 60}:{seconds % 60:02d}", (150, 155, 180),
                  (panel.centerx, panel.y + 252), "center")
        self.text(surface, self.f_med, "R: revanche     ENTER / ESC: menu", WHITE, (panel.centerx, panel.bottom - 22), "center")

    def draw_pause(self, surface, game):
        w, h = surface.get_size()
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        surface.blit(overlay, (0, 0))
        self.text(surface, self.f_big, "PAUSADO", YELLOW, (w // 2, h // 2 - 70), "center")
        lines = ("P1: A / D mover · W pular (duplo) · E atacar",
                 "P2: ← / → mover · ↑ pular · K atacar" if not game.ai else "P2: controlado pela IA do Duette",
                 "M liga/desliga a música",
                 "P continua · ESC volta ao menu")
        for i, line in enumerate(lines):
            self.text(surface, self.f_body, line, WHITE if i == 3 else (190, 195, 215), (w // 2, h // 2 - 10 + i * 30), "center")

    def draw_floor_hint(self, surface, game):
        """Dicas de controle no chão quando não há IA."""
        w, h = surface.get_size()
        self.text(surface, self.f_small, "P1: A/D · W · E        P2: ←/→ · ↑ · K        P pausa · M música",
                  (160, 165, 190), (w // 2, h - 52), "center", shadow=False)
