import math
import random

import pygame

from ..config.settings import *
from ..config import settings as config
from ..entities.player import Player
from ..ai.duette_client import get_client, entity_snapshot
from ..ui.hud import HUD
from .effects import Effects
from .stage import Stage, STAGES

COUNTDOWN_FRAMES = 150
SWING_SOUNDS = {"ESPADA": "swing_blade", "KATANA": "swing_blade", "MACHADO": "whoosh_heavy",
                "MARTELO": "whoosh_heavy", "BASTÃO": "whoosh_heavy", "LANCA": "whoosh_light",
                "ARCO": "bow", "CHAKRAM": "whirl", "PUNHO": "whoosh_light"}
BLADES = ("ESPADA", "KATANA", "MACHADO", "LANCA")


class _NoKeys:
    """Teclas todas soltas (contagem regressiva e pós-KO)."""

    def __getitem__(self, key):
        return False


NO_KEYS = _NoKeys()


class Game:
    def __init__(self, p1_style="STICK", p1_weapon="PUNHO", p2_style="STICK", p2_weapon="PUNHO",
                 sound_manager=None, stage=None):
        self.sound_manager = sound_manager
        self.match_config = (p1_style, p1_weapon, p2_style, p2_weapon)
        self.stage_name = stage if stage in STAGES else random.choice(STAGES)
        self.stage = Stage(self.stage_name)
        self.effects = Effects()
        self.hud = HUD()
        self.p1 = Player(200, 300, p1_style, p1_weapon, {
            'left': pygame.K_a,
            'right': pygame.K_d,
            'jump': pygame.K_w,
            'punch': pygame.K_e
        }, sound_manager=self.sound_manager)

        self.p2 = Player(560, 300, p2_style, p2_weapon, {
            'left': pygame.K_LEFT,
            'right': pygame.K_RIGHT,
            'jump': pygame.K_UP,
            'punch': pygame.K_k
        }, sound_manager=self.sound_manager)
        self.p1.facing, self.p2.facing = 1, -1

        self.font = pygame.font.SysFont(None, 24)
        self.big_font = pygame.font.SysFont(None, 48, bold=True)
        self.game_over = False
        self.winner_text = ""
        self.screen_shake = 0
        self.console_open = False
        self.console_input = ""
        self.admin_mode = False
        self.admin_notice = ""
        self.admin_notice_timer = 0
        self.trainer_open = False
        self.trainer_cursor = 0
        self.trainer_options = [
            "TRANSFORMAR EM HULK",
            "VIDA +50",
            "DANO +10",
            "VELOCIDADE +1",
            "PULO +1",
            "INVULNERABILIDADE",
            "RESTAURAR ATRIBUTOS",
        ]
        self.paused = False
        self.hit_stop = 0
        # Estado da luta
        self.frame = 0
        self.phase = "countdown"          # countdown -> fight (game_over marca o KO)
        self.phase_timer = 0
        self.match_time = 0.0
        self.stats = {"hits": [0, 0], "damage": [0.0, 0.0], "best_combo": [0, 0]}
        self.combo_count = [0, 0]
        self.combo_timer = [0, 0]
        self.combo_show = [(0, 0), (0, 0)]
        self.low_hp_warned = [False, False]
        self.ko_timer = 0
        self.slowmo = 0
        self.flash = 0
        self.ko_focus = (config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2)
        self.loser = None
        # Quando iniciado pelo Duette, o Jogador 2 passa a ser controlado pela IA.
        self.ai = get_client()
        if self.ai:
            self.ai.push_event("round", "self", 0)
        if self.sound_manager:
            self.sound_manager.start_music()

    # ------------------------------------------------------------------ rótulos
    @property
    def label_p1(self):
        return f"P1 · {self.p1.style_name}"

    @property
    def label_p2(self):
        if self.ai:
            return f"IA · {self.ai.ai_name} · {self.p2.style_name}"
        return f"P2 · {self.p2.style_name}"

    def _play(self, name, volume=1.0):
        if self.sound_manager:
            self.sound_manager.play(name, volume)

    def handle_events(self, event):
        if event.type != pygame.KEYDOWN:
            return None

        quote_key = getattr(pygame, "K_QUOTE", None)
        if event.key == quote_key and config.VIDEO_SETTINGS["debug_console"]:
            self.console_open = not self.console_open
            if self.console_open:
                self.console_input = ""
            return None

        if self.console_open:
            if event.key == pygame.K_ESCAPE:
                self.console_open = False
                self.console_input = ""
            elif event.key == pygame.K_BACKSPACE:
                self.console_input = self.console_input[:-1]
            elif event.key == pygame.K_RETURN:
                self._submit_console_command()
            else:
                character = getattr(event, "unicode", "")
                if character and character.isprintable() and len(self.console_input) < 48:
                    self.console_input += character.lower()
            return None

        if event.key == pygame.K_p and not self.game_over:
            self.paused = not self.paused
            if self.sound_manager:
                self.sound_manager.play("pause" if self.paused else "unpause")
                self.sound_manager.duck_music(self.paused)
            return None

        if event.key == pygame.K_m:
            if self.sound_manager:
                self.sound_manager.toggle_music()
            return None

        if self.paused:
            if event.key == pygame.K_ESCAPE:
                self.paused = False
                if self.sound_manager:
                    self.sound_manager.duck_music(False)
                return "MENU"
            return None

        if event.key == pygame.K_ESCAPE:
            return "MENU"

        if self.game_over and event.key == pygame.K_r:
            self.restart()
            return None

        if self.admin_mode:
            if event.key == pygame.K_t:
                self.trainer_open = not self.trainer_open
                return None
            if self.trainer_open:
                self._handle_trainer(event)
            else:
                self._handle_admin_power(event)
        return None

    def _handle_trainer(self, event):
        if event.key == pygame.K_ESCAPE:
            self.trainer_open = False
        elif event.key in (pygame.K_UP, pygame.K_w):
            self.trainer_cursor = (self.trainer_cursor - 1) % len(self.trainer_options)
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.trainer_cursor = (self.trainer_cursor + 1) % len(self.trainer_options)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self._apply_trainer_option()

    def _apply_trainer_option(self):
        actions = [
            (self.p1.transform_hulk, "HULK ATIVADO PELO TRAINER"),
            (lambda: self.p1.increase_max_health(50), "VIDA MÁXIMA AUMENTADA"),
            (lambda: self.p1.increase_damage(10), "DANO AUMENTADO"),
            (lambda: self.p1.increase_speed(1), "VELOCIDADE AUMENTADA"),
            (lambda: self.p1.increase_jump(), "FORÇA DE PULO AUMENTADA"),
            (self._toggle_trainer_invulnerability, "INVULNERABILIDADE ALTERADA"),
            (self.p1.reset_trainer_modifiers, "ATRIBUTOS RESTAURADOS"),
        ]
        action, notice = actions[self.trainer_cursor]
        action()
        self.admin_notice = notice
        self.admin_notice_timer = 120

    def _toggle_trainer_invulnerability(self):
        self.p1.admin_invulnerable = not self.p1.admin_invulnerable

    def _submit_console_command(self):
        command = self.console_input.strip().lower()
        self.console_input = ""
        self.console_open = False
        if command == "starting debug":
            self.admin_mode = True
            self.admin_notice = "MODO ADMINISTRADOR ATIVADO"
            self.admin_notice_timer = 180
        else:
            self.admin_notice = "COMANDO NEGADO"
            self.admin_notice_timer = 90

    def _handle_admin_power(self, event):
        powers = {
            pygame.K_h: (self._transform_hulk, "TRANSFORMAÇÃO HULK ATIVADA"),
            pygame.K_1: (self._admin_heal, "VIDA RESTAURADA"),
            pygame.K_2: (self._admin_super_jump, "SUPER PULO ATIVADO"),
            pygame.K_3: (self._admin_super_speed, "VELOCIDADE AUMENTADA"),
            pygame.K_4: (self._admin_god_mode, "INVULNERABILIDADE ATIVADA"),
            pygame.K_5: (self._admin_damage, "DANO MÁXIMO APLICADO"),
        }
        action = powers.get(event.key)
        if action:
            action[0]()
            self.admin_notice = action[1]
            self.admin_notice_timer = 120

    def _transform_hulk(self):
        self.p1.transform_hulk()

    def _admin_heal(self):
        self.p1.health = self.p1.max_health
        self.p2.health = self.p2.max_health

    def _admin_super_jump(self):
        self.p1.JUMP_FORCE = -22.0
        self.p1.max_jumps = 3
        self.p1.jumps_left = 3

    def _admin_super_speed(self):
        self.p1.MAX_SPEED_X = max(self.p1.MAX_SPEED_X, 13.0)

    def _admin_god_mode(self):
        self.p1.admin_invulnerable = not self.p1.admin_invulnerable
        self.admin_notice = "INVULNERABILIDADE " + ("ATIVADA" if self.p1.admin_invulnerable else "DESATIVADA")

    def _admin_damage(self):
        self.p1.weapon_info["damage"] = 999

    # ------------------------------------------------------------------ lógica
    def update(self):
        self.frame += 1
        if self.console_open or self.trainer_open or self.paused:
            return
        if self.game_over:
            self._update_ko()
            return
        if self.hit_stop > 0:
            self.hit_stop -= 1
            return

        self.hud.update(self)
        self.stage.update()
        self.effects.update()
        self.flash = max(0, self.flash - 1)
        if self.screen_shake > 0:
            self.screen_shake -= 1
        self.admin_notice_timer = max(0, self.admin_notice_timer - 1)
        self._tick_combos()

        keys = pygame.key.get_pressed()
        if self.ai:
            self.ai.submit_state(self._ai_state())

        if self.phase == "countdown":
            self._update_countdown()
            return

        self.match_time += 1.0 / max(1, config.FPS)
        self.p1.handle_input(keys)
        if self.ai:
            self.p2.handle_input(self.ai.build_keys(keys, self.p2.controls))
        else:
            self.p2.handle_input(keys)

        self.p1.update()
        self.p2.update()
        self._process_events()

        # Os personagens se encaram automaticamente e cada golpe só pode
        # acertar uma vez durante a sua janela de impacto.
        self.p1.face_toward(self.p2.x)
        self.p2.face_toward(self.p1.x)
        self._resolve_attack(self.p1, self.p2, 0)
        self._resolve_attack(self.p2, self.p1, 1)
        self._separate_players()

        # Condição de vitória
        if self.p1.health <= 0:
            self._ko(0)
        elif self.p2.health <= 0:
            self._ko(1)

    def _update_countdown(self):
        for player in (self.p1, self.p2):
            player.handle_input(NO_KEYS)
            player.update()
        self._process_events(silent=True)
        self.p1.face_toward(self.p2.x)
        self.p2.face_toward(self.p1.x)
        if self.phase_timer in (0, 40, 80):
            self._play("beep")
        elif self.phase_timer == 120:
            self._play("gong")
            self.screen_shake = 8
        self.phase_timer += 1
        if self.phase_timer >= COUNTDOWN_FRAMES:
            self.phase = "fight"

    def _update_ko(self):
        """Animação pós-KO: câmera lenta, partículas e queda do perdedor."""
        self.ko_timer += 1
        if self.slowmo > 0:
            self.slowmo -= 1
            if self.frame % 3:
                return
        self.hud.update(self)
        self.stage.update()
        self.effects.update()
        self.flash = max(0, self.flash - 1)
        if self.screen_shake > 0:
            self.screen_shake -= 1
        if self.hit_stop > 0:
            self.hit_stop -= 1
            return
        for player in (self.p1, self.p2):
            player.handle_input(NO_KEYS)
            player.update()
        self._process_events(silent=True)
        if self.ko_timer == 50:
            self._play("win")

    def _tick_combos(self):
        for i in (0, 1):
            if self.combo_timer[i] > 0:
                self.combo_timer[i] -= 1
                if self.combo_timer[i] == 0:
                    self.combo_count[i] = 0
            count, timer = self.combo_show[i]
            self.combo_show[i] = (count, max(0, timer - 1))

    def _process_events(self, silent=False):
        """Converte eventos dos personagens em sons, poeira e avisos para a IA."""
        for index, player in enumerate((self.p1, self.p2)):
            who = "self" if index == 1 else "opponent"
            for name, x, y, power in player.events:
                if name == "jump":
                    self._play("jump", 0.8)
                    self.effects.dust(x, y, 3)
                elif name == "double_jump":
                    self._play("double_jump", 0.8)
                    self.effects.jump_ring(x, y - 30)
                elif name == "land":
                    self._play("land", 0.35 + 0.65 * power)
                    self.effects.land(x, y, power)
                elif name == "step":
                    self._play("step", 0.45 * power)
                    if random.random() < 0.5:
                        self.effects.dust(x, y, 1, size=5)
                elif name == "attack_start":
                    self._play(SWING_SOUNDS.get(player.weapon_name, "whoosh_light"))
                elif name == "attack_whiff":
                    if not silent:
                        self._play("whiff", 0.6)
                        if self.ai:
                            self.ai.push_event("whiff", who, 0)
            player.events.clear()

    def _ai_state(self):
        """Estado da partida do ponto de vista do Jogador 2 (IA), no protocolo do Duette."""
        phase = "over" if self.game_over else ("countdown" if self.phase == "countdown" else "fight")
        hits, damage = self.stats["hits"], self.stats["damage"]
        return {
            "arena": {"w": config.SCREEN_WIDTH, "h": config.SCREEN_HEIGHT},
            "self": entity_snapshot(self.p2),
            "opponent": entity_snapshot(self.p1),
            "over": bool(self.game_over),
            "paused": bool(self.paused or self.console_open or self.trainer_open),
            "phase": phase,
            "match": {
                "time": round(self.match_time, 1),
                "hits_self": hits[1], "hits_opponent": hits[0],
                "dmg_self": round(damage[1]), "dmg_opponent": round(damage[0]),
                "combo_self": self.combo_count[1], "combo_opponent": self.combo_count[0],
            },
        }

    def _resolve_attack(self, attacker, defender, index):
        if not attacker.attack_active or attacker.attack_hit:
            return
        if abs(attacker.y - defender.y) >= 68:
            return
        if not attacker.get_attack_rect().colliderect(defender.hurtbox):
            return
        base = attacker.weapon_info["damage"]
        counter = defender.punching and not defender.attack_active     # pegou no início/fim do golpe
        crit = random.random() < 0.08
        damage = int(round(base * (1.25 if counter else 1.0) * (1.5 if crit else 1.0)))
        if not defender.take_damage(damage, attacker.facing * (8.0 + damage * 0.08), -5.5):
            return
        attacker.register_attack_hit()
        self._on_hit(attacker, defender, index, damage, crit, counter)

    def _on_hit(self, attacker, defender, index, damage, crit, counter):
        power = min(1.0, damage / 45.0)
        px, py = defender.x + defender.width / 2, defender.y + 40
        self.stats["hits"][index] += 1
        self.stats["damage"][index] += damage
        self.screen_shake = min(18, 7 + damage // 10 + (4 if crit else 0))
        self.hit_stop = 4 + (3 if crit else 0)
        self.flash = 5 if crit else 2
        self.effects.hit(px, py, attacker.facing, power + (0.4 if crit else 0), attacker.color)
        color = (255, 230, 80) if crit else (255, 255, 255)
        self.effects.text(px, defender.y - 6, f"-{damage}", color, 40 if crit else 30)
        if crit:
            self.effects.text(px, defender.y - 38, "CRÍTICO!", (255, 90, 60), 30, 56)
            self._play("crit")
        elif counter:
            self.effects.text(px, defender.y - 38, "CONTRA-ATAQUE!", (0, 225, 255), 26, 56)
            self._play("counter")
        name = "hit_blade" if attacker.weapon_name in BLADES else ("hit_heavy" if damage >= 35 else "hit_light")
        self._play(name)

        # Combos: acertos seguidos do mesmo lutador antes de o outro reagir.
        other = 1 - index
        self.combo_count[other] = 0
        self.combo_show[other] = (0, 0)
        self.combo_count[index] = self.combo_count[index] + 1 if self.combo_timer[index] > 0 else 1
        self.combo_timer[index] = 110
        count = self.combo_count[index]
        self.stats["best_combo"][index] = max(self.stats["best_combo"][index], count)
        self.combo_show[index] = (count, 100)
        who = "self" if index == 1 else "opponent"
        if self.ai:
            self.ai.push_event("hit", who, damage)
        if count >= 2:
            self.effects.text(attacker.x + attacker.width / 2, attacker.y - 30, f"COMBO x{count}", (255, 220, 0), 30, 50)
            self._play("combo")
            if self.ai:
                self.ai.push_event("combo", who, count)

        # Vida crítica (uma vez por luta para cada lutador).
        didx = 1 - index
        if defender.health > 0 and defender.health / defender.max_health < 0.25 and not self.low_hp_warned[didx]:
            self.low_hp_warned[didx] = True
            self._play("heartbeat")
            if self.ai:
                self.ai.push_event("low_hp", "self" if didx == 1 else "opponent", defender.health)

    def _ko(self, loser_index):
        loser = self.p1 if loser_index == 0 else self.p2
        winner = self.p2 if loser_index == 0 else self.p1
        loser.health = 0
        self.game_over = True
        self.loser = loser_index
        if loser_index == 0:
            self.winner_text = f"IA {self.ai.ai_name.upper()} VENCEU!" if self.ai else "JOGADOR 2 VENCEU!"
        else:
            self.winner_text = "JOGADOR 1 VENCEU!"
        loser.set_ko()
        winner.punching = False
        self.slowmo = 80
        self.ko_timer = 0
        self.hit_stop = 6
        self.flash = 7
        self.screen_shake = 16
        self.ko_focus = (int(loser.x + loser.width / 2), int(loser.y + 50))
        self.effects.ko_burst(self.ko_focus[0], self.ko_focus[1], loser.color)
        self._play("ko")
        if self.ai:
            self.ai.push_event("ko", "self" if loser_index == 1 else "opponent", 0)

    def _separate_players(self):
        if not self.p1.hurtbox.colliderect(self.p2.hurtbox):
            return
        overlap = self.p1.hurtbox.clip(self.p2.hurtbox).width
        if overlap <= 0:
            return
        direction = -1 if self.p1.x < self.p2.x else 1
        shift = overlap / 2 + 0.5
        self.p1.x = max(0, min(config.SCREEN_WIDTH - self.p1.width, self.p1.x - direction * shift))
        self.p2.x = max(0, min(config.SCREEN_WIDTH - self.p2.width, self.p2.x + direction * shift))
        self.p1.vel_x *= 0.65
        self.p2.vel_x *= 0.65

    def restart(self):
        """Reinicia a luta atual sem voltar ao menu de seleção."""
        p1_style, p1_weapon, p2_style, p2_weapon = self.match_config
        self.__init__(p1_style, p1_weapon, p2_style, p2_weapon, self.sound_manager, self.stage_name)

    # ------------------------------------------------------------------ desenho
    def draw(self, surface):
        width, height = config.SCREEN_WIDTH, config.SCREEN_HEIGHT
        canvas = getattr(self, "_canvas", None)
        if canvas is None or canvas.get_size() != (width, height):
            canvas = self._canvas = pygame.Surface((width, height))
        self.stage.draw(canvas)

        # O perdedor é desenhado primeiro para o vencedor ficar à frente.
        order = (self.p2, self.p1) if self.loser == 1 else (self.p1, self.p2)
        for player in order:
            player.draw(canvas)
        self.effects.draw(canvas)

        self.hud.draw_top(canvas, self)
        if self.ai:
            self.hud.draw_ai_panel(canvas, self)
        else:
            self.hud.draw_floor_hint(canvas, self)

        if self.admin_mode:
            admin_label = self.font.render("ADMIN: T Trainer | H Hulk | 1 Vida | 2 Pulo | 3 Velocidade | 4 Deus | 5 Dano", True, GREEN)
            canvas.blit(admin_label, (40, 128))
            if self.admin_notice_timer > 0:
                notice = self.font.render(self.admin_notice, True, YELLOW)
                canvas.blit(notice, notice.get_rect(center=(width // 2, 105)))

        if self.phase == "countdown" and not self.game_over:
            self.hud.draw_countdown(canvas, self)
        if self.game_over:
            if self.ko_timer < 90:
                self.hud.draw_ko(canvas, self)
            if self.ko_timer > 70:
                self.hud.draw_result(canvas, self)
        if self.paused:
            self.hud.draw_pause(canvas, self)

        if self.console_open:
            console = pygame.Surface((width - 80, 125), pygame.SRCALPHA)
            console.fill((4, 8, 12, 238))
            pygame.draw.rect(console, GREEN, console.get_rect(), 2)
            title = self.font.render("DEBUG CONSOLE  |  ESC fecha", True, GREEN)
            prompt = self.font.render("> " + self.console_input + "_", True, WHITE)
            hint = self.font.render("Digite o comando de acesso e pressione ENTER", True, LIGHT_GRAY)
            console.blit(title, (16, 12))
            console.blit(prompt, (16, 48))
            console.blit(hint, (16, 84))
            canvas.blit(console, (40, height // 2 - 60))

        if self.trainer_open:
            self._draw_trainer(canvas)

        if self.flash > 0:
            flash = pygame.Surface((width, height), pygame.SRCALPHA)
            flash.fill((255, 255, 255, min(150, self.flash * 28)))
            canvas.blit(flash, (0, 0))

        view = canvas
        if self.game_over and self.ko_timer < 100:
            # Zoom suave sobre o nocaute (entra em 24 quadros e relaxa antes do resultado).
            grow = min(1.0, self.ko_timer / 24.0) if self.ko_timer < 70 else max(0.0, 1 - (self.ko_timer - 70) / 30.0)
            zoom = 1.0 + 0.07 * (1 - (1 - grow) ** 2)
            if zoom > 1.005:
                size = (int(width * zoom), int(height * zoom))
                big = pygame.transform.smoothscale(canvas, size)
                fx, fy = self.ko_focus
                ox = max(width - size[0], min(0, int(fx - fx * zoom)))
                oy = max(height - size[1], min(0, int(fy - fy * zoom)))
                view = pygame.Surface((width, height))
                view.blit(big, (ox, oy))

        shake = self.screen_shake
        offset_x = random.randint(-shake, shake) if shake > 0 else 0
        offset_y = random.randint(-shake, shake) if shake > 0 else 0
        if offset_x or offset_y:
            surface.fill((0, 0, 0))
        surface.blit(view, (offset_x, offset_y))

    def _draw_trainer(self, surface):
        width, height = surface.get_size()
        panel_width, panel_height = min(620, width - 50), 410
        panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel.fill((8, 12, 18, 245))
        pygame.draw.rect(panel, GREEN, panel.get_rect(), 3)
        title = self.big_font.render("ADMIN TRAINER", True, GREEN)
        panel.blit(title, title.get_rect(center=(panel_width // 2, 38)))
        subtitle = self.font.render("Jogador 1 • ENTER aplica • T/ESC fecha", True, LIGHT_GRAY)
        panel.blit(subtitle, subtitle.get_rect(center=(panel_width // 2, 78)))
        for index, option in enumerate(self.trainer_options):
            selected = index == self.trainer_cursor
            color = YELLOW if selected else WHITE
            prefix = "> " if selected else "  "
            text = self.font.render(prefix + option, True, color)
            panel.blit(text, (38, 108 + index * 37))
        stats = self.font.render(
            f"HP {int(self.p1.health)}/{int(self.p1.max_health)}  DANO {self.p1.weapon_info['damage']}  VEL {self.p1.MAX_SPEED_X:.1f}",
            True, CYAN,
        )
        panel.blit(stats, (38, panel_height - 32))
        surface.blit(panel, panel.get_rect(center=(width // 2, height // 2)))
