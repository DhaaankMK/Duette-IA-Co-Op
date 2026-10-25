import math
import random
from collections import deque

import pygame

from ..config.settings import *
from ..config import settings as config
from ..core.effects import Mote


class ImpactParticle:
    def __init__(self, x, y, color, amount=1):
        self.x = float(x)
        self.y = float(y)
        self.vx = random.uniform(-6, 6)
        self.vy = random.uniform(-6, 2)
        self.size = random.randint(2, 6)
        self.color = color
        self.life = random.randint(12, 20)
        self.max_life = self.life
        self.amount = amount

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.4
        self.vx *= 0.97
        self.life -= 1

    def draw(self, surface):
        if self.life <= 0:
            return
        radius = max(1, int(self.size * self.life / self.max_life))
        pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), radius)


WEAPON_TRAIL = {
    "ESPADA": ((210, 230, 255), 46), "KATANA": ((0, 225, 255), 48), "BASTÃO": ((255, 160, 40), 32),
    "MARTELO": ((255, 190, 90), 40), "LANCA": ((255, 245, 190), 62), "MACHADO": ((220, 220, 235), 36),
    "ARCO": ((255, 200, 120), 20), "CHAKRAM": ((0, 225, 255), 22), "PUNHO": ((255, 255, 255), 8),
}
BODY_WIDTH = {"classic": 4, "heavy": 7, "athletic": 5, "slim": 3, "robot": 5}
AMBIENT = {"DEMON": ((255, 90, 20), 0.18), "ANJO": ((255, 245, 170), 0.15), "ROBO": ((0, 225, 255), 0.05),
           "VAMPIRO": ((200, 20, 50), 0.07), "HULK": ((80, 255, 90), 0.2)}


def _ease_out(u):
    return 1.0 - (1.0 - max(0.0, min(1.0, u))) ** 3


class Player:
    """Personagem com física simples e animação procedural de stickman."""

    def __init__(self, x, y, style_name="STICK", weapon_name="PUNHO", controls=None, sound_manager=None):
        self.x = float(x)
        self.y = float(y)
        self.width = 40
        self.height = 100
        self.controls = controls or {}
        self.sound_manager = sound_manager  # mantido por compatibilidade; sons são tocados pelo Game

        styles, weapons = load_content()
        self.style_name = style_name
        style_info = styles.get(style_name, list(styles.values())[0])
        self.color = tuple(style_info["color"])
        self.accent_color = tuple(style_info.get("accent", self.color))
        self.body_type = style_info.get("body", "classic")
        self.accessory = style_info.get("accessory", "none")
        self.max_health = style_info["hp"]
        self.health = float(self.max_health)

        self.weapon_name = weapon_name
        self.weapon_info = weapons.get(weapon_name, list(weapons.values())[0])
        self._base_max_health = self.max_health
        self._base_speed = style_info["speed"]
        self._base_jump_force = -15.0
        self._base_damage = self.weapon_info["damage"]
        self._base_color = self.color
        self._base_accent_color = self.accent_color
        self._base_body_type = self.body_type
        self._base_accessory = self.accessory

        # Física e controle
        self.vel_x = 0.0
        self.vel_y = 0.0
        self.acc_x = 0.0
        self.ACCEL_GROUND = 1.4
        self.ACCEL_AIR = 0.6
        self.FRICTION_GROUND = 0.80
        self.FRICTION_AIR = 0.95
        self.MAX_SPEED_X = style_info["speed"]
        self.GRAVITY = 0.8
        self.FALL_GRAVITY = 1.2
        self.JUMP_FORCE = -15.0

        self.max_jumps = 2
        self.jumps_left = self.max_jumps
        self.jump_key_pressed = False
        self.is_grounded = False
        self.facing = 1

        # Estados de combate/animação
        self.punching = False
        self.punch_timer = 0
        self.attack_hit = False
        self.state = "idle"
        self.state_time = 0.0
        self.anim_time = random.uniform(0, math.tau)
        self.hurt_timer = 0
        self.invulnerable_timer = 0
        self.flash_timer = 0
        self.admin_invulnerable = False
        self.is_hulk = False
        self.land_timer = 0
        self.particles = []
        self.ko = False
        self.ko_time = 0
        self.blink_timer = random.randint(120, 260)
        self.trail = deque(maxlen=8)
        self.floor_override = None   # permite desenhar em pré-visualizações (menu)
        self.events = []             # eventos para o Game: (nome, x, y, intensidade)
        self._step_sign = 1

    # ------------------------------------------------------------------ propriedades
    @property
    def attack_duration(self):
        return max(1, int(self.weapon_info["cooldown"]))

    @property
    def attack_progress(self):
        if not self.punching:
            return 0.0
        return 1.0 - (self.punch_timer / self.attack_duration)

    @property
    def attack_active(self):
        # A janela curta de impacto deixa o combate mais previsível.
        return self.punching and 0.26 <= self.attack_progress <= 0.62

    @property
    def attack_cooldown_fraction(self):
        """0 = pronto para atacar; 1 = acabou de começar um golpe."""
        return (self.punch_timer / self.attack_duration) if self.punching else 0.0

    @property
    def hurtbox(self):
        return pygame.Rect(int(self.x + 5), int(self.y + 8), self.width - 10, self.height - 8)

    def _emit(self, name, power=1.0):
        if len(self.events) < 32:
            self.events.append((name, self.x + self.width / 2, self.y + self.height, power))

    # ------------------------------------------------------------------ entrada e ações
    def handle_input(self, keys):
        self.acc_x = 0.0
        if self.ko:
            return
        if self.hurt_timer > 0:
            self.jump_key_pressed = keys[self.controls["jump"]]
            return

        accel = self.ACCEL_GROUND if self.is_grounded else self.ACCEL_AIR
        if keys[self.controls["left"]]:
            self.acc_x -= accel
            self.facing = -1
        if keys[self.controls["right"]]:
            self.acc_x += accel
            self.facing = 1

        jump_key = keys[self.controls["jump"]]
        if jump_key and not self.jump_key_pressed and self.jumps_left > 0 and not self.punching:
            self.vel_y = self.JUMP_FORCE
            self._emit("jump" if self.jumps_left == self.max_jumps else "double_jump")
            self.jumps_left -= 1
            self.is_grounded = False
        self.jump_key_pressed = jump_key

        if keys[self.controls["punch"]] and not self.punching:
            self.start_attack()

    def start_attack(self):
        if self.ko or self.hurt_timer > 0 or self.punching:
            return False
        self.punching = True
        self.punch_timer = self.attack_duration
        self.attack_hit = False
        self.state_time = 0.0
        self.trail.clear()
        self._emit("attack_start")
        return True

    def get_attack_rect(self):
        """Hitbox retangular que acompanha o lado para o qual o jogador olha."""
        if not self.attack_active:
            return pygame.Rect(0, 0, 0, 0)
        reach = int(self.weapon_info["range"] + 24)
        if self.facing > 0:
            return pygame.Rect(int(self.x + self.width // 2), int(self.y + 22), reach, 58)
        return pygame.Rect(int(self.x + self.width // 2 - reach), int(self.y + 22), reach, 58)

    def register_attack_hit(self):
        self.attack_hit = True

    def take_damage(self, damage, force_x, force_y):
        if self.admin_invulnerable or self.invulnerable_timer > 0 or self.health <= 0:
            return False
        self.health = max(0, self.health - damage)
        self.vel_x = force_x
        self.vel_y = force_y
        self.is_grounded = False
        self.punching = False
        self.punch_timer = 0
        self.hurt_timer = 18
        self.invulnerable_timer = 24
        self.flash_timer = 6
        self.state_time = 0.0
        for _ in range(4):
            self.particles.append(ImpactParticle(self.x + self.width // 2, self.y + 42, RED))
        return True

    def set_ko(self):
        """Derrubada final: o personagem é lançado para trás e cai."""
        if self.ko:
            return
        self.ko = True
        self.ko_time = 0
        self.punching = False
        self.hurt_timer = 0
        self.vel_x = -self.facing * 6.5
        self.vel_y = -9.0
        self.is_grounded = False
        self.state = "ko"

    def transform_hulk(self):
        """Ativa uma forma administrativa forte, verde e visualmente maior."""
        self.is_hulk = True
        self.color = (65, 205, 75)
        self.accent_color = (20, 95, 35)
        self.body_type = "heavy"
        self.accessory = "none"
        self.max_health = max(self.max_health, 300)
        self.health = self.max_health
        self.width = 52
        self.height = 112
        self.MAX_SPEED_X = max(self.MAX_SPEED_X, 8.5)
        self.JUMP_FORCE = min(self.JUMP_FORCE, -17.5)
        self.weapon_info = dict(self.weapon_info)
        self.weapon_info["damage"] = max(45, self.weapon_info["damage"], self._base_damage * 2)
        self.admin_invulnerable = True
        self.invulnerable_timer = 0
        self.state_time = 0.0
        for _ in range(22):
            self.particles.append(ImpactParticle(self.x + self.width // 2, self.y + 48, GREEN))

    def increase_max_health(self, amount):
        self.max_health += amount
        self.health = min(self.max_health, self.health + amount)

    def increase_damage(self, amount):
        self.weapon_info = dict(self.weapon_info)
        self.weapon_info["damage"] += amount

    def increase_speed(self, amount):
        self.MAX_SPEED_X += amount

    def increase_jump(self):
        self.JUMP_FORCE -= 1.5
        self.max_jumps += 1
        self.jumps_left = self.max_jumps

    def reset_trainer_modifiers(self):
        self.is_hulk = False
        self.color = self._base_color
        self.accent_color = self._base_accent_color
        self.body_type = self._base_body_type
        self.accessory = self._base_accessory
        self.max_health = self._base_max_health
        self.health = self.max_health
        self.width = 40
        self.height = 100
        self.MAX_SPEED_X = self._base_speed
        self.JUMP_FORCE = self._base_jump_force
        self.max_jumps = 2
        self.jumps_left = self.max_jumps
        self.weapon_info = dict(self.weapon_info)
        self.weapon_info["damage"] = self._base_damage
        self.admin_invulnerable = False

    def apply_impulse(self, force_x, force_y):
        self.vel_x += force_x
        self.vel_y += force_y
        self.is_grounded = False
        for _ in range(8):
            self.particles.append(ImpactParticle(self.x + self.width // 2, self.y + 40, RED))

    def _set_animation_state(self):
        if self.ko:
            new_state = "ko"
        elif self.hurt_timer > 0:
            new_state = "hurt"
        elif self.punching:
            new_state = "attack"
        elif not self.is_grounded and self.vel_y < 0:
            new_state = "jump"
        elif not self.is_grounded:
            new_state = "fall"
        elif abs(self.vel_x) > 0.65:
            new_state = "run"
        else:
            new_state = "idle"
        if new_state != self.state:
            self.state = new_state
            self.state_time = 0.0

    def update(self):
        self.anim_time += 0.22
        self.state_time += 1 / FPS
        self.hurt_timer = max(0, self.hurt_timer - 1)
        self.invulnerable_timer = max(0, self.invulnerable_timer - 1)
        self.flash_timer = max(0, self.flash_timer - 1)
        self.land_timer = max(0, self.land_timer - 1)
        self.blink_timer = self.blink_timer - 1 if self.blink_timer > 0 else random.randint(120, 260)
        if self.ko:
            self.ko_time += 1
            self.acc_x = 0.0

        was_grounded = self.is_grounded
        self.vel_x += self.acc_x
        self.vel_x *= self.FRICTION_GROUND if self.is_grounded else self.FRICTION_AIR
        self.vel_x = max(-self.MAX_SPEED_X, min(self.MAX_SPEED_X, self.vel_x))

        self.vel_y += self.FALL_GRAVITY if self.vel_y > 0 else self.GRAVITY
        self.x += self.vel_x
        self.y += self.vel_y

        floor_y = config.SCREEN_HEIGHT - 120
        if self.y + self.height >= floor_y:
            self.y = floor_y - self.height
            if not was_grounded and self.vel_y > 5:
                self.land_timer = 8
                self._emit("land", min(1.0, self.vel_y / 18.0))
            self.vel_y = 0.0
            self.is_grounded = True
            self.jumps_left = self.max_jumps
        else:
            self.is_grounded = False

        if self.x < 0:
            self.x, self.vel_x = 0, 0
        elif self.x + self.width > config.SCREEN_WIDTH:
            self.x, self.vel_x = config.SCREEN_WIDTH - self.width, 0

        if self.punching:
            self.punch_timer -= 1
            if self.punch_timer <= 0:
                self.punching = False
                if not self.attack_hit:
                    self._emit("attack_whiff")
                self.attack_hit = False

        # Passos (um evento a cada troca de perna) e partículas ambientes do estilo.
        if self.state == "run" and self.is_grounded:
            sign = 1 if math.sin(self.anim_time * 1.8) >= 0 else -1
            if sign != self._step_sign:
                self._emit("step", min(1.0, abs(self.vel_x) / max(1.0, self.MAX_SPEED_X)))
            self._step_sign = sign
        self._ambient()

        for particle in self.particles[:]:
            particle.update()
            if particle.life <= 0:
                self.particles.remove(particle)
        self._set_animation_state()

    def _ambient(self):
        if self.ko or len(self.particles) > 40:
            return
        color, chance = AMBIENT.get("HULK" if self.is_hulk else self.style_name, (None, 0))
        if color and random.random() < chance:
            self.particles.append(Mote(self.x + self.width / 2 + random.uniform(-14, 14),
                                       self.y + random.uniform(20, 90), color))
        if self.health > 0 and self.health / self.max_health < 0.25 and random.random() < 0.12:
            self.particles.append(Mote(self.x + self.width / 2 + random.uniform(-10, 10), self.y + 10, (255, 60, 40)))

    def preview_tick(self):
        """Avança somente a animação (usado nas pré-visualizações do menu)."""
        self.anim_time += 0.22
        self.state_time += 1 / 60
        self.blink_timer = self.blink_timer - 1 if self.blink_timer > 0 else random.randint(120, 260)
        if self.punching:
            self.punch_timer -= 1
            if self.punch_timer <= 0:
                self.punching = False

    def face_toward(self, target_x):
        if not self.punching and self.hurt_timer <= 0 and not self.ko:
            self.facing = 1 if target_x > self.x else -1

    # ------------------------------------------------------------------ desenho
    def _point(self, x, y):
        return int(x), int(y)

    def _draw_limb(self, surface, start, end, color=None, width=4):
        pygame.draw.line(surface, color or self.color, self._point(*start), self._point(*end), width)
        pygame.draw.circle(surface, color or self.color, self._point(*end), max(2, width // 2))

    def _draw_limb2(self, surface, a, b, c, color, width):
        """Membro com articulação (cotovelo/joelho)."""
        pygame.draw.line(surface, color, self._point(*a), self._point(*b), width)
        pygame.draw.line(surface, color, self._point(*b), self._point(*c), width)
        pygame.draw.circle(surface, color, self._point(*b), max(2, width // 2))
        pygame.draw.circle(surface, color, self._point(*c), max(2, width // 2))

    def _swing_curve(self):
        """Curva do golpe: recuo (antecipação), investida rápida e recuperação suave."""
        p = self.attack_progress
        if p < 0.26:
            return -0.45 * _ease_out(p / 0.26)
        if p < 0.62:
            return -0.45 + 1.45 * _ease_out((p - 0.26) / 0.36)
        return 1.0 - _ease_out((p - 0.62) / 0.38)

    def draw(self, surface, floor_y=None):
        if floor_y is None:
            floor_y = self.floor_override if self.floor_override is not None else config.SCREEN_HEIGHT - 120
        for particle in self.particles:
            particle.draw(surface)

        f, t, state = self.facing, self.anim_time, self.state
        k = self.height / 100.0
        cx = self.x + self.width / 2
        feet_y = self.y + self.height
        lift = max(0.0, floor_y - feet_y)

        # Aura do Hulk, brilho de fúria (vida baixa) e sombra.
        if self.is_hulk:
            aura = pygame.Surface((110, 145), pygame.SRCALPHA)
            pygame.draw.ellipse(aura, (80, 255, 90, 28), aura.get_rect(), 5)
            surface.blit(aura, (int(cx - 55), int(self.y - 8)))
        if not self.ko and self.health > 0 and self.health / self.max_health < 0.25:
            pulse = 0.5 + 0.5 * math.sin(t * 0.9)
            rage = pygame.Surface((90, 130), pygame.SRCALPHA)
            pygame.draw.ellipse(rage, (255, 40, 30, int(26 + 34 * pulse)), rage.get_rect())
            surface.blit(rage, (int(cx - 45), int(self.y - 6)))
        shadow_width = max(12, int(30 - min(lift * 0.12, 16)))
        shadow = pygame.Surface((shadow_width * 2 + 4, 10), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 95), shadow.get_rect())
        surface.blit(shadow, (int(cx - shadow_width - 2), int(floor_y - 5)))

        # Escala (squash/stretch) e inclinação do corpo em torno dos pés.
        land_t = self.land_timer / 8.0
        sy = 1.0 - 0.13 * land_t
        if not self.is_grounded and not self.ko:
            sy += min(0.08, abs(self.vel_y) * 0.005)
        sx = 1.0 / sy if sy else 1.0
        angle = max(-0.2, min(0.2, self.vel_x * 0.02))
        bob = math.sin(t * 1.7) * 1.5 if state == "idle" else 0.0
        phase, cyc = math.sin(t * 1.8), math.cos(t * 1.8)
        speed = min(1.0, abs(self.vel_x) / max(1.0, self.MAX_SPEED_X))

        head = [angle * 18, 15 + bob]
        neck = [angle * 14, 27 + bob]
        shoulder = [angle * 10, 36 + bob]
        hip = [0.0, 65.0 + bob * 0.5]
        bend = 3.0
        arm_back = [-f * 18, 52 + phase * 3]
        arm_front = [f * 15, 56]
        s = 0.0

        if state == "run":
            foot1 = [phase * 18 * speed, 100 - 8 * max(0.0, cyc)]
            foot2 = [-phase * 18 * speed, 100 - 8 * max(0.0, -cyc)]
            bend = 6 + 8 * speed
            arm_back = [-f * 12 - phase * 10 * speed * f, 52 + 2]
            arm_front = [f * 14 + phase * 10 * speed * f, 54]
        elif state == "jump":
            foot1, foot2, bend = [-16 * f, 87], [15 * f, 78], 12
            neck[1], head[1] = 28, 17
            arm_front, arm_back = [f * 16, 28], [-f * 17, 34]
        elif state == "fall":
            foot1, foot2, bend = [-20 * f, 98], [20 * f, 92], 7
            arm_front, arm_back = [f * 24, 40], [-f * 24, 42]
        elif state == "hurt":
            angle = -f * 0.28
            head, neck, shoulder = [-f * 10, 14], [-f * 7, 25], [-f * 6, 34]
            foot1, foot2, bend = [-14 * f, 95], [18 * f, 88], 6
            arm_front, arm_back = [-f * 22, 22], [f * 14, 28]
        elif state == "ko":
            u = _ease_out(self.ko_time / 22.0)
            angle = -f * (math.pi / 2 - 0.12) * u
            foot1, foot2, bend = [-10 * f, 100], [12 * f, 100], 4 + 4 * u
            arm_front, arm_back = [f * 26, 30 - 10 * u], [-f * 26, 34 - 10 * u]
            sy = sx = 1.0
        elif state == "attack":
            s = self._swing_curve()
            lunge, windup = max(0.0, s), max(0.0, -s)
            angle += f * (0.2 * lunge - 0.3 * windup)
            hip[1] += 3 * lunge
            foot1, foot2, bend = [f * (10 + 12 * lunge), 100], [-f * (12 + 4 * lunge), 100], 5
            arm_back = [-f * (10 + 10 * lunge), 48]
        else:
            foot1, foot2 = [6 + phase * 1.5, 100], [-6 - phase * 1.5, 100]

        ca, sa = math.cos(angle), math.sin(angle)

        def tx(p):
            x, y = p[0] * k * sx, (p[1] - 100) * k * sy
            return (cx + x * ca - y * sa, feet_y + x * sa + y * ca)

        def knee(a, b):
            return ((a[0] + b[0]) / 2 + f * bend, (a[1] + b[1]) / 2)

        draw_color = self.color
        if self.flash_timer > 0:
            draw_color = WHITE
        elif self.invulnerable_timer > 0 and (self.invulnerable_timer // 3) % 2 == 0:
            draw_color = tuple(min(255, int(c * 0.55 + 115)) for c in self.color)
        width = 7 if self.is_hulk else BODY_WIDTH.get(self.body_type, 4)

        head_s, neck_s, hip_s, sh_s = tx(head), tx(neck), tx(hip), tx(shoulder)
        head_radius = 16 if self.is_hulk else 12
        pygame.draw.circle(surface, draw_color, self._point(*head_s), head_radius)
        pygame.draw.circle(surface, BLACK, self._point(*head_s), head_radius, 2)
        self._draw_face(surface, head_s, head_radius, draw_color)
        self._draw_accessory(surface, head_s[0], head_s[1], head_radius, cx, hip_s)

        self._draw_limb(surface, neck_s, hip_s, draw_color, width)
        for foot in (foot1, foot2):
            self._draw_limb2(surface, hip_s, tx(knee(hip, foot)), tx(foot), draw_color, width)
        self._draw_limb2(surface, sh_s, tx(((shoulder[0] + arm_back[0]) / 2, (shoulder[1] + arm_back[1]) / 2 + 4)),
                         tx(arm_back), draw_color, width)

        if state == "attack":
            raw = -0.9 + s * 2.0
            arm_len = self.weapon_info["range"] * (0.72 + 0.28 * max(0.0, s))
            hand = (sh_s[0] + math.cos(raw) * arm_len * f, sh_s[1] + math.sin(raw) * arm_len * 0.55)
            elbow = ((sh_s[0] + hand[0]) / 2, (sh_s[1] + hand[1]) / 2 + 6)
            self._draw_limb2(surface, sh_s, elbow, hand, draw_color, width + 1)
            self._draw_trail(surface, sh_s, hand, f)
            self._draw_weapon(surface, hand[0], hand[1], max(0.0, s))
        else:
            if self.trail:
                self.trail.clear()
            hand = tx(arm_front)
            elbow = tx(((shoulder[0] + arm_front[0]) / 2 + f * 2, (shoulder[1] + arm_front[1]) / 2 + 3))
            self._draw_limb2(surface, sh_s, elbow, hand, draw_color, width)

        if self.is_hulk:
            label = pygame.font.SysFont(None, 18, bold=True).render("HULK", True, GREEN)
            surface.blit(label, label.get_rect(center=(int(cx), int(self.y - 12))))

    def _draw_face(self, surface, head, radius, color):
        hx, hy = head
        f = self.facing
        r = radius / 12.0
        luminance = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        ink = BLACK if luminance > 110 else WHITE
        eyes = ((hx + f * 3 * r, hy - 2 * r), (hx + f * 8 * r, hy - 2 * r))
        if self.state in ("hurt", "ko"):
            for ex, ey in eyes:
                pygame.draw.line(surface, ink, (ex - 2, ey - 2), (ex + 2, ey + 2), 2)
                pygame.draw.line(surface, ink, (ex - 2, ey + 2), (ex + 2, ey - 2), 2)
            pygame.draw.line(surface, ink, (hx + f * 3 * r, hy + 6 * r), (hx + f * 9 * r, hy + 7 * r), 2)
            return
        if self.blink_timer < 6:
            for ex, ey in eyes:
                pygame.draw.line(surface, ink, (ex - 2, ey), (ex + 2, ey), 2)
        else:
            for ex, ey in eyes:
                pygame.draw.circle(surface, ink, (int(ex), int(ey)), max(2, int(2 * r)))
        if self.state == "attack":
            pygame.draw.line(surface, ink, (hx + f * 1 * r, hy - 7 * r), (hx + f * 10 * r, hy - 4 * r), 2)
            pygame.draw.circle(surface, ink, (int(hx + f * 7 * r), int(hy + 6 * r)), max(2, int(2.5 * r)))
        elif self.health > 0 and self.health / self.max_health < 0.25:
            pygame.draw.line(surface, ink, (hx + f * 3 * r, hy + 7 * r), (hx + f * 9 * r, hy + 5 * r), 2)

    def _draw_trail(self, surface, shoulder, hand, f):
        color, length = WEAPON_TRAIL.get(self.weapon_name, ((255, 255, 255), 24))
        dx, dy = hand[0] - shoulder[0], hand[1] - shoulder[1]
        norm = math.hypot(dx, dy) or 1.0
        tip = (hand[0] + dx / norm * length, hand[1] + dy / norm * length - 6)
        if 0.18 <= self.attack_progress <= 0.8:
            self.trail.append((hand, tip))
        elif self.trail:
            self.trail.popleft()
        pts = list(self.trail)
        for i in range(1, len(pts)):
            (h0, t0), (h1, t1) = pts[i - 1], pts[i]
            poly = [h0, t0, t1, h1]
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            left, top = int(min(xs)) - 2, int(min(ys)) - 2
            w, h = int(max(xs)) - left + 4, int(max(ys)) - top + 4
            if w <= 0 or h <= 0 or w > 600 or h > 600:
                continue
            layer = pygame.Surface((w, h), pygame.SRCALPHA)
            alpha = int(120 * (i / len(pts)) ** 2)
            pygame.draw.polygon(layer, (*color, alpha), [(p[0] - left, p[1] - top) for p in poly])
            surface.blit(layer, (left, top))

    def _draw_weapon(self, surface, hand_x, hand_y, swing):
        if "ESPADA" in self.weapon_name or "KATANA" in self.weapon_name:
            blade_color = CYAN if "KATANA" in self.weapon_name else WHITE
            tip_x = hand_x + (34 + swing * 10) * self.facing
            tip_y = hand_y - 14 - swing * 8
            pygame.draw.line(surface, blade_color, self._point(hand_x, hand_y), self._point(tip_x, tip_y), 5)
            pygame.draw.line(surface, ORANGE,
                             self._point(hand_x - 4 * self.facing, hand_y + 3),
                             self._point(hand_x + 5 * self.facing, hand_y - 3), 3)
        elif "BASTÃO" in self.weapon_name:
            tip_x = hand_x + (24 + swing * 8) * self.facing
            pygame.draw.line(surface, ORANGE, self._point(hand_x, hand_y), self._point(tip_x, hand_y - 4), 6)
        elif "MARTELO" in self.weapon_name:
            tip_x = hand_x + 35 * self.facing
            pygame.draw.line(surface, GRAY, self._point(hand_x, hand_y), self._point(tip_x, hand_y - 8), 7)
            pygame.draw.rect(surface, GRAY, (int(tip_x - 14), int(hand_y - 20), 28, 22), border_radius=4)
            pygame.draw.rect(surface, BLACK, (int(tip_x - 14), int(hand_y - 20), 28, 22), 2, border_radius=4)
        elif "LANCA" in self.weapon_name:
            tip_x = hand_x + 58 * self.facing
            pygame.draw.line(surface, ORANGE,
                             self._point(hand_x, hand_y), self._point(tip_x, hand_y - 5), 4)
            pygame.draw.polygon(surface, WHITE, [self._point(tip_x, hand_y - 5),
                                                  self._point(tip_x - 14 * self.facing, hand_y - 13),
                                                  self._point(tip_x - 12 * self.facing, hand_y + 4)])
        elif "MACHADO" in self.weapon_name:
            tip_x = hand_x + 30 * self.facing
            pygame.draw.line(surface, ORANGE, self._point(hand_x, hand_y), self._point(tip_x, hand_y - 4), 5)
            pygame.draw.polygon(surface, GRAY, [self._point(tip_x, hand_y - 22),
                                                 self._point(tip_x + 18 * self.facing, hand_y - 12),
                                                 self._point(tip_x, hand_y + 4)])
        elif "ARCO" in self.weapon_name:
            bow_x = hand_x + 18 * self.facing
            pygame.draw.arc(surface, ORANGE, (int(bow_x - 17), int(hand_y - 26), 34, 52),
                            math.pi / 2 if self.facing > 0 else -math.pi / 2,
                            3 * math.pi / 2 if self.facing > 0 else math.pi / 2, 4)
            pygame.draw.line(surface, WHITE, self._point(bow_x, hand_y - 24), self._point(bow_x, hand_y + 24), 2)
        elif "CHAKRAM" in self.weapon_name:
            pygame.draw.circle(surface, CYAN, self._point(hand_x + 18 * self.facing, hand_y - 4), 13, 4)
        else:
            pygame.draw.circle(surface, YELLOW, self._point(hand_x, hand_y), 8)

    def _draw_accessory(self, surface, head_x, head_y, head_radius, center_x, body_bottom):
        """Desenha acessórios simples sem depender de imagens externas."""
        accent = self.accent_color
        accessory = self.accessory
        if accessory == "horns":
            pygame.draw.polygon(surface, accent, [self._point(head_x - 9, head_y - 8),
                                                  self._point(head_x - 15, head_y - 25),
                                                  self._point(head_x - 2, head_y - 12)])
            pygame.draw.polygon(surface, accent, [self._point(head_x + 9, head_y - 8),
                                                  self._point(head_x + 15, head_y - 25),
                                                  self._point(head_x + 2, head_y - 12)])
        elif accessory == "bandana":
            pygame.draw.line(surface, accent, self._point(head_x - head_radius, head_y - 1),
                             self._point(head_x + head_radius, head_y - 1), 5)
            pygame.draw.line(surface, accent, self._point(head_x - 8, head_y - 2),
                             self._point(head_x - 25, head_y + 8), 4)
        elif accessory == "visor":
            pygame.draw.rect(surface, accent, (int(head_x - 11), int(head_y - 3), 22, 7), border_radius=3)
            pygame.draw.line(surface, CYAN, self._point(head_x - 6, head_y), self._point(head_x + 6, head_y), 2)
        elif accessory == "helmet":
            pygame.draw.arc(surface, accent, (int(head_x - 15), int(head_y - 15), 30, 25), math.pi, math.tau, 5)
            pygame.draw.line(surface, accent, self._point(head_x - 14, head_y - 2), self._point(head_x + 14, head_y - 2), 3)
        elif accessory == "cape":
            pygame.draw.polygon(surface, accent, [self._point(head_x - 10, head_y + 18),
                                                   self._point(head_x - 30 * self.facing, body_bottom[1] + 18),
                                                   self._point(head_x + 3, body_bottom[1] + 5)])
        elif accessory == "wings":
            pygame.draw.line(surface, accent, self._point(center_x, head_y + 28),
                             self._point(center_x - 32, head_y + 3), 5)
            pygame.draw.line(surface, accent, self._point(center_x, head_y + 35),
                             self._point(center_x + 32, head_y + 3), 5)
        elif accessory == "armor":
            pygame.draw.circle(surface, accent, self._point(center_x - 8, head_y + 26), 7)
            pygame.draw.circle(surface, accent, self._point(center_x + 8, head_y + 26), 7)
