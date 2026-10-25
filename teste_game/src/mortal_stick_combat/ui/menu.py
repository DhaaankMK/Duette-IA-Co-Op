import math
import random

import pygame

from ..config.settings import *
from ..config import settings as config
from ..core.stage import Stage, STAGES, STAGE_INFO
from ..entities.player import Player

SETTINGS_ROWS = 8          # 0..6 opções, 7 = voltar
SELECT_ROWS = 6            # 0 estilo P1, 1 arma P1, 2 estilo P2, 3 arma P2, 4 cenário, 5 iniciar
PANEL_BG = (16, 18, 32)


class Showcase:
    """Lutador de vitrine: usa o mesmo desenho do jogo, mas só com animação (sem física)."""

    def __init__(self, style, weapon, x, floor, facing, period=150, offset=0):
        self.player = Player(x, floor - 100, style, weapon)
        self.player.floor_override = floor
        self.player.is_grounded = True
        self.player.facing = facing
        self.period = period
        self.t = offset

    def tick(self):
        p = self.player
        self.t += 1
        p.preview_tick()
        if not p.punching and self.t % self.period == 0:
            p.punching = True
            p.punch_timer = p.attack_duration
            p.attack_hit = False
        p.state = "attack" if p.punching else "idle"
        p.state_time = 0.0 if p.state == "idle" else p.state_time

    def draw(self, surface):
        self.player.draw(surface)


class Menu:
    def __init__(self, sound_manager=None):
        self.sound_manager = sound_manager
        self.title_font = pygame.font.SysFont("Impact", 72)
        self.panel_title_font = pygame.font.SysFont("Impact", 34)
        self.sub_font = pygame.font.SysFont(None, 28)
        self.font = pygame.font.SysFont(None, 32, bold=True)
        self.small_font = pygame.font.SysFont(None, 21)
        self.state = "MAIN"
        self.selected_option = 0
        self.options = ["JOGAR", "SETTINGS", "SAIR"]
        styles, weapons = load_content()
        self.styles_list = list(styles.keys())
        self.weapons_list = list(weapons.keys())
        self.p1_choices = [0, 0]
        self.p2_choices = [0, 0]
        self.stage_choice = 0
        self.select_cursor = 0
        self.settings_cursor = 0
        self.anim_timer = 0.0
        self._stages = {}
        self._size = None
        self._showcases = {}
        self._intro = [Showcase(random.choice(self.styles_list), random.choice(["ESPADA", "KATANA", "MARTELO"]),
                                0, 0, 1, 140, 0),
                       Showcase(random.choice(self.styles_list), random.choice(["LANCA", "MACHADO", "BASTÃO"]),
                                0, 0, -1, 140, 70)]

    # ------------------------------------------------------------------ som
    def _play(self, name):
        if self.sound_manager:
            self.sound_manager.play(name)

    # ------------------------------------------------------------------ entrada
    def handle_input(self, event):
        if event.type != pygame.KEYDOWN:
            return None
        if event.key == pygame.K_ESCAPE:
            self._play("back")
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self._play("confirm")
        elif event.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT,
                           pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d):
            self._play("nav")
        else:
            self._play("click")

        if self.state == "MAIN":
            if event.key in (pygame.K_UP, pygame.K_w):
                self.selected_option = (self.selected_option - 1) % len(self.options)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.selected_option = (self.selected_option + 1) % len(self.options)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                choice = self.options[self.selected_option]
                if choice == "JOGAR":
                    self.state = "SELECT"
                elif choice == "SETTINGS":
                    self.state = "SETTINGS"
                elif choice == "SAIR":
                    return "SAIR"

        elif self.state == "SETTINGS":
            if event.key == pygame.K_ESCAPE:
                self.state = "MAIN"
            elif event.key in (pygame.K_UP, pygame.K_w):
                self.settings_cursor = (self.settings_cursor - 1) % SETTINGS_ROWS
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.settings_cursor = (self.settings_cursor + 1) % SETTINGS_ROWS
            elif event.key in (pygame.K_LEFT, pygame.K_a):
                self._change_setting(-1)
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self._change_setting(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.settings_cursor == SETTINGS_ROWS - 1:
                self.state = "MAIN"

        elif self.state == "SELECT":
            if event.key == pygame.K_ESCAPE:
                self.state = "MAIN"
            elif event.key in (pygame.K_UP, pygame.K_w):
                self.select_cursor = (self.select_cursor - 1) % SELECT_ROWS
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.select_cursor = (self.select_cursor + 1) % SELECT_ROWS
            elif event.key in (pygame.K_LEFT, pygame.K_a):
                self._change_selection(-1)
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self._change_selection(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.select_cursor == SELECT_ROWS - 1:
                return "START_GAME"
        return None

    def _change_setting(self, direction):
        if self.settings_cursor == 0:
            total = len(config.RESOLUTION_OPTIONS)
            index = config.VIDEO_SETTINGS["resolution_index"]
            config.VIDEO_SETTINGS["resolution_index"] = (index + direction) % total
        elif self.settings_cursor == 1:
            current = config.HZ_OPTIONS.index(config.VIDEO_SETTINGS["hz"])
            config.VIDEO_SETTINGS["hz"] = config.HZ_OPTIONS[(current + direction) % len(config.HZ_OPTIONS)]
        elif self.settings_cursor == 2:
            config.VIDEO_SETTINGS["fullscreen"] = not config.VIDEO_SETTINGS["fullscreen"]
        elif self.settings_cursor == 3:
            value = config.VIDEO_SETTINGS["gamma"] + direction * 10
            config.VIDEO_SETTINGS["gamma"] = max(70, min(130, value))
        elif self.settings_cursor == 4:
            config.VIDEO_SETTINGS["debug_console"] = not config.VIDEO_SETTINGS["debug_console"]
        elif self.settings_cursor == 5:
            config.VIDEO_SETTINGS["volume"] = max(0, min(100, config.VIDEO_SETTINGS["volume"] + direction * 10))
            if self.sound_manager:
                self.sound_manager.set_volume(config.VIDEO_SETTINGS["volume"])
        elif self.settings_cursor == 6:
            config.VIDEO_SETTINGS["music"] = not config.VIDEO_SETTINGS.get("music", True)
        else:
            return
        if self.settings_cursor <= 3:
            config.apply_display_settings()
        else:
            config.save_video_settings()

    def _change_selection(self, direction):
        if self.select_cursor == 0:
            self.p1_choices[0] = (self.p1_choices[0] + direction) % len(self.styles_list)
        elif self.select_cursor == 1:
            self.p1_choices[1] = (self.p1_choices[1] + direction) % len(self.weapons_list)
        elif self.select_cursor == 2:
            self.p2_choices[0] = (self.p2_choices[0] + direction) % len(self.styles_list)
        elif self.select_cursor == 3:
            self.p2_choices[1] = (self.p2_choices[1] + direction) % len(self.weapons_list)
        elif self.select_cursor == 4:
            self.stage_choice = (self.stage_choice + direction) % len(STAGES)

    def get_selections(self):
        return (
            self.styles_list[self.p1_choices[0]], self.weapons_list[self.p1_choices[1]],
            self.styles_list[self.p2_choices[0]], self.weapons_list[self.p2_choices[1]],
        )

    def get_stage(self):
        return STAGES[self.stage_choice]

    # ------------------------------------------------------------------ atualização
    def update(self):
        self.anim_timer += 0.05
        for showcase in self._intro:
            showcase.tick()
        for showcase in self._showcases.values():
            showcase.tick()

    # ------------------------------------------------------------------ desenho
    def _stage_for(self, surface, name):
        size = surface.get_size()
        if size != self._size:
            self._stages.clear()
            self._size = size
        stage = self._stages.get(name)
        if stage is None:
            stage = self._stages[name] = Stage(name, size[0], size[1])
        return stage

    def draw(self, surface):
        name = self.get_stage() if self.state == "SELECT" else "NEON" if self.state == "SETTINGS" else "DOJO"
        stage = self._stage_for(surface, name)
        stage.update()
        stage.draw(surface)
        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 80 if self.state == "MAIN" else 140))
        surface.blit(dim, (0, 0))
        if self.state == "MAIN":
            self._draw_main_menu(surface, stage)
        elif self.state == "SETTINGS":
            self._draw_settings(surface)
        else:
            self._draw_select_menu(surface, stage)

    def _title(self, surface, text, center, font, color, glow):
        width = center[0]
        pulse = 0.5 + 0.5 * math.sin(self.anim_timer * 2)
        big = font.get_height() > 55
        for offset, alpha in (((6, 40), (3, 70)) if big else ((2, 30),)):
            halo = font.render(text, True, glow)
            halo.set_alpha(int(alpha + 30 * pulse))
            for dx, dy in ((-offset, 0), (offset, 0), (0, -offset), (0, offset)):
                surface.blit(halo, halo.get_rect(center=(center[0] + dx, center[1] + dy)))
        shadow = font.render(text, True, BLACK)
        surface.blit(shadow, shadow.get_rect(center=(center[0] + 4, center[1] + 5)))
        surface.blit(font.render(text, True, color), font.render(text, True, color).get_rect(center=center))

    def _draw_main_menu(self, surface, stage):
        width, height = surface.get_size()
        self._title(surface, "MORTAL STICK", (width // 2, 120), self.title_font, (255, 70, 60), (255, 120, 40))
        subtitle = self.sub_font.render("A R E N A   D E   D U E L O S", True, YELLOW)
        surface.blit(subtitle, subtitle.get_rect(center=(width // 2, 178)))
        for index, option in enumerate(self.options):
            selected = index == self.selected_option
            rect = pygame.Rect(0, 0, 300, 50)
            rect.center = (width // 2 + (math.sin(self.anim_timer * 3) * 6 if selected else 0), 262 + index * 64)
            body = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(body, (255, 220, 0, 55) if selected else (20, 22, 40, 190), body.get_rect(), border_radius=12)
            surface.blit(body, rect)
            pygame.draw.rect(surface, YELLOW if selected else (90, 98, 135), rect, 3 if selected else 2, border_radius=12)
            label = self.font.render(option, True, YELLOW if selected else WHITE)
            surface.blit(label, label.get_rect(center=rect.center))
        # Dois lutadores de vitrine duelando sobre o chão do cenário.
        floor = stage.floor_y
        left, right = self._intro
        for showcase, x in ((left, width * 0.27), (right, width * 0.73 - 40)):
            showcase.player.x, showcase.player.y = x, floor - 100
            showcase.player.floor_override = floor
            showcase.draw(surface)
        hint = self.small_font.render("W/S ou setas navegam  ·  ENTER confirma", True, LIGHT_GRAY)
        surface.blit(hint, hint.get_rect(center=(width // 2, height - 22)))

    def _draw_settings(self, surface):
        width, height = surface.get_size()
        self._title(surface, "SETTINGS", (width // 2, 80), self.panel_title_font, YELLOW, (255, 200, 40))
        resolution = config.RESOLUTION_OPTIONS[config.VIDEO_SETTINGS["resolution_index"]]
        values = [
            ("Resolução", f"{resolution[0]} x {resolution[1]}"),
            ("Taxa de atualização", f"{config.VIDEO_SETTINGS['hz']} Hz"),
            ("Tela cheia", "ATIVADA" if config.VIDEO_SETTINGS["fullscreen"] else "DESATIVADA"),
            ("Gamma / brilho", f"{config.VIDEO_SETTINGS['gamma']}%"),
            ("Console de debug", "LIBERADO" if config.VIDEO_SETTINGS["debug_console"] else "BLOQUEADO"),
            ("Volume", f"{config.VIDEO_SETTINGS['volume']}%"),
            ("Música", "LIGADA" if config.VIDEO_SETTINGS.get("music", True) else "DESLIGADA"),
            ("Voltar", "ENTER"),
        ]
        panel = pygame.Rect(0, 0, min(620, width - 60), 8 * 50 + 30)
        panel.center = (width // 2, height // 2 + 10)
        body = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(body, (14, 16, 30, 215), body.get_rect(), border_radius=16)
        surface.blit(body, panel)
        pygame.draw.rect(surface, (90, 98, 135), panel, 2, border_radius=16)
        for index, (label, value) in enumerate(values):
            selected = index == self.settings_cursor
            y = panel.y + 40 + index * 50
            if selected:
                bar = pygame.Surface((panel.w - 24, 40), pygame.SRCALPHA)
                pygame.draw.rect(bar, (255, 220, 0, 40), bar.get_rect(), border_radius=10)
                surface.blit(bar, (panel.x + 12, y - 20))
            color = YELLOW if selected else WHITE
            surface.blit(self.font.render(label, True, color), (panel.x + 34, y - 11))
            value_img = self.font.render(f"< {value} >" if selected and index < 7 else value, True, color)
            surface.blit(value_img, value_img.get_rect(midright=(panel.right - 34, y)))
        hint = self.small_font.render("W/S navega  ·  A/D altera  ·  ENTER confirma  ·  ESC volta", True, LIGHT_GRAY)
        surface.blit(hint, hint.get_rect(center=(width // 2, height - 22)))

    def _showcase(self, style, weapon, x, floor, facing, offset):
        key = (style, weapon, facing)
        showcase = self._showcases.get(key)
        if showcase is None:
            showcase = self._showcases[key] = Showcase(style, weapon, x, floor, facing, 110, offset)
        showcase.player.x, showcase.player.y = x, floor - 100
        showcase.player.floor_override = floor
        return showcase

    def _draw_select_menu(self, surface, stage):
        width, height = surface.get_size()
        self._title(surface, "ESCOLHA SEUS LUTADORES", (width // 2, 34), self.panel_title_font, YELLOW, (255, 200, 40))
        styles, weapons = load_content()
        panel_w = min(330, (width - 90) // 2)
        gap = min(60, width - 2 * panel_w - 40)
        left = (width - (2 * panel_w + gap)) // 2
        self._draw_player_panel(surface, left, 66, panel_w, "JOGADOR 1", BLUE, self.p1_choices, [0, 1], styles, weapons, 1)
        self._draw_player_panel(surface, left + panel_w + gap, 66, panel_w, "JOGADOR 2", RED, self.p2_choices, [2, 3], styles, weapons, -1)

        # Seletor de cenário
        selected = self.select_cursor == 4
        stage_name = STAGES[self.stage_choice]
        rect = pygame.Rect(0, 0, 330, 40)
        rect.center = (width // 2, height - 128)
        body = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(body, (255, 220, 0, 55) if selected else (20, 22, 40, 200), body.get_rect(), border_radius=10)
        surface.blit(body, rect)
        pygame.draw.rect(surface, YELLOW if selected else (90, 98, 135), rect, 2, border_radius=10)
        label = self.small_font.render(f"CENÁRIO  <  {STAGE_INFO[stage_name].upper()}  >", True, YELLOW if selected else WHITE)
        surface.blit(label, label.get_rect(center=rect.center))

        start_selected = self.select_cursor == 5
        button = pygame.Rect(0, 0, 300, 50)
        button.center = (width // 2, height - 70)
        pygame.draw.rect(surface, GREEN if start_selected else (60, 66, 90), button, border_radius=10)
        pygame.draw.rect(surface, WHITE, button, 3, border_radius=10)
        text = self.font.render(">>> INICIAR LUTA <<<" if start_selected else "INICIAR LUTA", True,
                                BLACK if start_selected else WHITE)
        surface.blit(text, text.get_rect(center=button.center))
        hint = self.small_font.render("W/S muda a linha  ·  A/D troca a opção  ·  ESC volta", True, LIGHT_GRAY)
        surface.blit(hint, hint.get_rect(center=(width // 2, height - 22)))

    def _stat_bar(self, surface, x, y, w, label, fraction, color):
        surface.blit(self.small_font.render(label, True, LIGHT_GRAY), (x, y - 2))
        bar = pygame.Rect(x + 90, y, w - 90, 12)
        pygame.draw.rect(surface, (34, 36, 56), bar, border_radius=6)
        fill = bar.copy()
        fill.width = max(4, int(bar.width * max(0.0, min(1.0, fraction))))
        pygame.draw.rect(surface, color, fill, border_radius=6)

    def _draw_player_panel(self, surface, x, y, w, title, color, choices, cursor_indices, styles, weapons, facing):
        height = surface.get_height()
        ph = height - 66 - 150
        body = pygame.Surface((w, ph), pygame.SRCALPHA)
        pygame.draw.rect(body, (*PANEL_BG, 225), body.get_rect(), border_radius=14)
        surface.blit(body, (x, y))
        pygame.draw.rect(surface, color, (x, y, w, ph), 3, border_radius=14)
        title_img = self.panel_title_font.render(title, True, color)
        surface.blit(title_img, title_img.get_rect(midtop=(x + w // 2, y + 6)))

        style_name = self.styles_list[choices[0]]
        style_info = styles[style_name]
        weapon_name = self.weapons_list[choices[1]]
        weapon_info = weapons[weapon_name]
        sel_style = self.select_cursor == cursor_indices[0]
        sel_weapon = self.select_cursor == cursor_indices[1]
        surface.blit(self.font.render(f"Estilo: < {style_name} >", True, YELLOW if sel_style else WHITE), (x + 14, y + 52))
        surface.blit(self.small_font.render(style_info["desc"], True, LIGHT_GRAY), (x + 14, y + 80))
        surface.blit(self.font.render(f"Arma: < {weapon_name} >", True, YELLOW if sel_weapon else WHITE), (x + 14, y + 104))
        surface.blit(self.small_font.render(weapon_info["desc"], True, LIGHT_GRAY), (x + 14, y + 132))

        # Vitrine animada do lutador escolhido, no chão do painel.
        floor = y + ph - 110
        showcase = self._showcase(style_name, weapon_name, x + w // 2 - 20, floor, facing, 0 if facing > 0 else 55)
        pygame.draw.line(surface, (70, 76, 110), (x + 14, floor), (x + w - 14, floor), 2)
        showcase.draw(surface)

        # Atributos (relativos aos maiores valores do conteúdo).
        max_hp = max(v["hp"] for v in styles.values())
        max_speed = max(v["speed"] for v in styles.values())
        max_dmg = max(v["damage"] for v in weapons.values())
        max_range = max(v["range"] for v in weapons.values())
        cds = [v["cooldown"] for v in weapons.values()]
        speed_rating = 1.0 - (weapon_info["cooldown"] - min(cds)) / max(1, max(cds) - min(cds)) * 0.85
        by = y + ph - 98
        rows = (("VIDA", style_info["hp"] / max_hp, (70, 225, 120)),
                ("VELOC.", style_info["speed"] / max_speed, CYAN),
                ("DANO", weapon_info["damage"] / max_dmg, (255, 90, 80)),
                ("ALCANCE", weapon_info["range"] / max_range, (255, 190, 60)),
                ("AGILIDADE", speed_rating, (190, 120, 255)))
        for i, (label, fraction, bar_color) in enumerate(rows):
            self._stat_bar(surface, x + 14, by + i * 19, w - 28, label, fraction, bar_color)
