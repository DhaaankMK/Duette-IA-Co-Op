"""Widgets animados do Duette: tela de carregamento, logo, faixa de boas-vindas e efeitos de hover.

Todas as animações usam ``after`` do tkinter (sem threads), param sozinhas quando o widget é
destruído e têm baixo custo (poucos itens de canvas por quadro).
"""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable

from .. import APP_NAME
from . import theme

TEAL = "#4dffd8"


# ---------------------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------------------

def ease_out(u: float) -> float:
    return 1.0 - (1.0 - max(0.0, min(1.0, u))) ** 3


def lerp_color(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))


def tween(widget: tk.Misc, duration_ms: int, step: Callable[[float], None],
          done: Callable[[], None] | None = None, easing: Callable[[float], float] = ease_out) -> None:
    """Executa ``step(progresso_suavizado)`` a ~60 quadros/s por ``duration_ms``."""
    start = time.monotonic()

    def tick() -> None:
        try:
            if not widget.winfo_exists():
                return
            u = min(1.0, (time.monotonic() - start) * 1000.0 / max(1, duration_ms))
            step(easing(u))
            if u < 1.0:
                widget.after(16, tick)
            elif done:
                done()
        except tk.TclError:
            return

    tick()


def loop(widget: tk.Misc, interval_ms: int, func: Callable[[], None]) -> None:
    """Repete ``func`` até o widget ser destruído."""
    def tick() -> None:
        try:
            if not widget.winfo_exists():
                return
            func()
            widget.after(interval_ms, tick)
        except tk.TclError:
            return

    widget.after(interval_ms, tick)


# ---------------------------------------------------------------------------------------
# Logo animado
# ---------------------------------------------------------------------------------------

class AnimatedLogo(tk.Canvas):
    """Nome do app com brilho que percorre as letras."""

    def __init__(self, parent: tk.Misc, text: str = APP_NAME, size: int = 20, background: str = theme.PANEL):
        font = (theme.FONT_TITLE[0], size, "bold")
        measure = tkfont.Font(family=font[0], size=size, weight="bold")
        super().__init__(parent, width=measure.measure(text) + 6, height=measure.metrics("linespace") + 6,
                         highlightthickness=0, background=background)
        self._letters = []
        x = 3
        for char in text:
            self._letters.append(self.create_text(x, 3, text=char, anchor="nw", font=font, fill=theme.TEXT))
            x += measure.measure(char)
        self._t = 0.0
        loop(self, 50, self._tick)

    def _tick(self) -> None:
        self._t += 0.05
        for i, item in enumerate(self._letters):
            glow = (math.sin(self._t * 2.4 - i * 0.7) + 1) / 2
            self.itemconfigure(item, fill=lerp_color(theme.TEXT, TEAL if glow > 0.5 else theme.ACCENT_HOVER, glow ** 2 * 0.9))


# ---------------------------------------------------------------------------------------
# Tela de carregamento
# ---------------------------------------------------------------------------------------

class SplashFrame(tk.Frame):
    """Carregamento animado: estrelas, robô flutuante com órbitas, título com brilho e barra de progresso."""

    MIN_SECONDS = 2.4

    def __init__(self, parent: tk.Misc, message: str = "", steps: tuple[tuple[float, str], ...] = (),
                 min_seconds: float | None = None):
        super().__init__(parent, background=theme.BG)
        self.min_seconds = self.MIN_SECONDS if min_seconds is None else min_seconds
        self._steps = steps or ((0.0, message or "Carregando..."),)
        self._start = time.monotonic()
        self._progress = 0.0
        self._target = 0.0
        self._finish_cb: Callable[[], None] | None = None
        self._finishing = False
        self._message = ""
        self._msg_change = 0.0
        self._t = 0.0
        self._rnd = random.Random()
        self._stars = [[self._rnd.random(), self._rnd.random(), self._rnd.uniform(0.0006, 0.003),
                        self._rnd.uniform(0.6, 2.2), self._rnd.uniform(0, 6.28)] for _ in range(70)]
        self.canvas = tk.Canvas(self, highlightthickness=0, background=theme.BG)
        self.canvas.pack(fill="both", expand=True)
        self.robot = theme.Avatar(self.canvas, size=116, background=theme.BG)
        self.robot.show()
        self.robot.start_animation()
        self._robot_win = self.canvas.create_window(0, 0, window=self.robot)
        self._title_font = (theme.FONT_TITLE[0], 34, "bold")
        self._letters: list[int] = []
        self._orbs = [self.canvas.create_oval(0, 0, 0, 0, fill=c, outline="") for c in (theme.ACCENT_HOVER, TEAL, "#ff6b9d")]
        self._trails = [[self.canvas.create_oval(0, 0, 0, 0, fill="", outline="") for _ in range(5)] for _ in self._orbs]
        self._subtitle = self.canvas.create_text(0, 0, text="sua IA para jogar", fill=theme.MUTED, font=theme.FONT)
        self._track = self.canvas.create_rectangle(0, 0, 0, 0, fill=theme.CARD, outline="")
        self._fill = self.canvas.create_rectangle(0, 0, 0, 0, fill=theme.ACCENT, outline="")
        self._shine = self.canvas.create_rectangle(0, 0, 0, 0, fill=theme.ACCENT_HOVER, outline="")
        self._status = self.canvas.create_text(0, 0, text="", fill=theme.MUTED, font=theme.FONT)
        self._star_items = [self.canvas.create_oval(0, 0, 0, 0, fill=theme.MUTED, outline="") for _ in self._stars]
        for item in self._star_items:
            self.canvas.tag_lower(item)
        self._letter_x: list[float] = []
        loop(self, 33, self._tick)

    # ------------------------------------------------------------------ API
    def set_message(self, text: str) -> None:
        if text != self._message:
            self._message = text
            self._msg_change = self._t
            self.canvas.itemconfigure(self._status, text=text)

    def finish(self, callback: Callable[[], None]) -> None:
        """Conclui o carregamento (respeitando o tempo mínimo) e chama ``callback``."""
        self._finish_cb = callback
        self._finishing = True

    # ------------------------------------------------------------------ quadro
    def _layout_title(self, width: int, cy: int) -> None:
        if not self._letters:
            measure = tkfont.Font(family=self._title_font[0], size=self._title_font[1], weight="bold")
            self._widths = [measure.measure(c) for c in APP_NAME]
            for char in APP_NAME:
                self._letters.append(self.canvas.create_text(0, 0, text=char, font=self._title_font, fill=theme.BG))
        total = sum(self._widths)
        x = width / 2 - total / 2
        self._letter_x = []
        for w in self._widths:
            self._letter_x.append(x + w / 2)
            x += w

    def _tick(self) -> None:
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 50 or height < 50:
            return
        self._t += 0.033
        elapsed = time.monotonic() - self._start
        cx, cy = width / 2, height * 0.38

        # Mensagens por etapa e progresso "otimista" que nunca chega a 100% sozinho.
        current = self._steps[0][1]
        for at, text in self._steps:
            if elapsed >= at:
                current = text
        self.set_message(current)
        creep = 0.9 * (1 - math.exp(-elapsed / 1.6))
        if self._finishing and elapsed >= self.min_seconds:
            self._target = 1.0
        else:
            self._target = min(self._target if self._target > creep else creep, 0.93)
        self._progress += (self._target - self._progress) * (1.0 if self.min_seconds == 0 else 0.12)

        # Estrelas
        for star, item in zip(self._stars, self._star_items):
            star[1] -= star[2]
            if star[1] < 0:
                star[1], star[0] = 1.0, self._rnd.random()
            x, y = star[0] * width, star[1] * height
            size = star[3] * (0.6 + 0.4 * math.sin(self._t * 2 + star[4]))
            self.canvas.coords(item, x - size, y - size, x + size, y + size)
            self.canvas.itemconfigure(item, fill=lerp_color(theme.BG, theme.MUTED, 0.35 + 0.5 * math.sin(self._t + star[4]) ** 2))

        # Robô flutuando e órbitas com rastro
        bob = math.sin(self._t * 2.0) * 7
        self.canvas.coords(self._robot_win, cx, cy + bob)
        for i, (orb, trail) in enumerate(zip(self._orbs, self._trails)):
            for k, dot in enumerate([orb] + trail):
                ang = self._t * (1.4 + i * 0.35) + i * 2.09 - k * 0.11
                rx, ry = 92 + i * 14, 26 + i * 6
                px, py = cx + math.cos(ang) * rx, cy + bob * 0.5 + math.sin(ang) * ry
                r = 5 - k * 0.7 if k else 6
                self.canvas.coords(dot, px - r, py - r, px + r, py + r)
                if k:
                    self.canvas.itemconfigure(dot, fill=lerp_color(theme.BG, self.canvas.itemcget(orb, "fill"), 0.5 - k * 0.09))

        # Título: letras entram uma a uma e brilham
        title_y = cy + 112
        self._layout_title(width, int(title_y))
        for i, (item, lx) in enumerate(zip(self._letters, self._letter_x)):
            appear = max(0.0, min(1.0, (elapsed - 0.15 - i * 0.09) / 0.35))
            glow = (math.sin(self._t * 2.6 - i * 0.7) + 1) / 2
            color = lerp_color(theme.BG, lerp_color(theme.TEXT, TEAL, glow ** 2 * 0.8), ease_out(appear))
            self.canvas.coords(item, lx, title_y + (1 - ease_out(appear)) * 18)
            self.canvas.itemconfigure(item, fill=color)
        sub_alpha = max(0.0, min(1.0, (elapsed - 0.9) / 0.5))
        self.canvas.coords(self._subtitle, cx, title_y + 38)
        self.canvas.itemconfigure(self._subtitle, fill=lerp_color(theme.BG, theme.MUTED, sub_alpha))

        # Barra de progresso com brilho deslizante
        bar_w, bar_h = min(360, width - 80), 10
        bx0, by0 = cx - bar_w / 2, title_y + 78
        self.canvas.coords(self._track, bx0, by0, bx0 + bar_w, by0 + bar_h)
        fill_w = bar_w * self._progress
        self.canvas.coords(self._fill, bx0, by0, bx0 + fill_w, by0 + bar_h)
        shine_x = bx0 + ((self._t * 0.9) % 1.0) * max(1.0, fill_w)
        self.canvas.coords(self._shine, shine_x, by0, min(bx0 + fill_w, shine_x + 36), by0 + bar_h)
        fade = min(1.0, (self._t - self._msg_change) / 0.35)
        self.canvas.coords(self._status, cx, by0 + 32)
        self.canvas.itemconfigure(self._status, fill=lerp_color(theme.BG, theme.MUTED, 0.3 + 0.7 * fade))

        if self._finish_cb and self._progress > 0.985 and elapsed >= self.min_seconds:
            callback, self._finish_cb = self._finish_cb, None
            self.canvas.itemconfigure(self._status, text="Tudo pronto!", fill=theme.OK)
            self.after(0 if self.min_seconds == 0 else 380, callback)


# ---------------------------------------------------------------------------------------
# Faixa de boas-vindas interativa
# ---------------------------------------------------------------------------------------

class HeroBanner(tk.Canvas):
    """Faixa com ondas animadas, avatar e fala com efeito de digitação. Clique para ouvir outra dica."""

    def __init__(self, parent: tk.Misc, app, height: int = 104):
        super().__init__(parent, height=height, highlightthickness=1, highlightbackground=theme.BORDER,
                         background=theme.CARD, cursor="hand2")
        self.app = app
        self._h = height
        self._t = 0.0
        self._tip = 0
        self._text = ""
        self._typed = 0.0
        self._last_tip_change = time.monotonic()
        self._waves = [self.create_line(0, 0, 0, 0, smooth=True, width=2, fill=theme.CARD) for _ in range(4)]
        self.avatar = theme.Avatar(self, size=68, background=theme.CARD)
        self.avatar.pack_forget()
        self._avatar_win = self.create_window(52, height // 2, window=self.avatar)
        self._title = self.create_text(100, 30, anchor="w", fill=theme.TEXT, font=theme.FONT_H2, text="")
        self._line = self.create_text(100, 62, anchor="nw", fill=theme.MUTED, font=theme.FONT, text="", width=600)
        self._cursor = self.create_text(0, 0, anchor="w", text="▌", fill=theme.ACCENT_HOVER, font=theme.FONT)
        self.bind("<Button-1>", lambda _e: self.next_tip(user=True))
        self.avatar.bind("<Button-1>", lambda _e: self.next_tip(user=True))
        self.bind("<Configure>", self._on_configure)
        self.refresh_identity()
        self._set_tip(0)
        loop(self, 40, self._tick)

    def refresh_identity(self) -> None:
        from ..avatar import load_photo, resolve_avatar

        profile = self.app.storage.snapshot()["ai_profile"]
        photo = None
        path = resolve_avatar(self.app.avatars_dir, profile["avatar"])
        if path is not None:
            photo = load_photo(path, 68)
        self.avatar.show(profile["bot_name"], photo)
        self.avatar.start_animation()
        self.itemconfigure(self._title, text=f"Olá! Eu sou {profile['bot_name']}.")

    def _tips(self) -> list[str]:
        name = self.app.storage.snapshot()["ai_profile"]["bot_name"]
        return [
            "Escolha um jogo abaixo e eu entro na partida como Player 2.",
            f"Dica: no Perfil da IA você muda o meu nome, a foto e a minha personalidade.",
            "Na aba Conversa você fala comigo, e eu respondo dentro do jogo também.",
            "Eu leio a partida em tempo real: vida, distância, golpes e combos.",
            f"Pode me chamar de {name} a qualquer hora. Clique aqui para outra dica!",
        ]

    def _set_tip(self, index: int) -> None:
        tips = self._tips()
        self._tip = index % len(tips)
        self._text = tips[self._tip]
        self._typed = 0.0
        self._last_tip_change = time.monotonic()
        self.itemconfigure(self._line, text="")

    def next_tip(self, user: bool = False) -> None:
        self._set_tip(self._tip + 1)
        if user:
            self.app.sound.play("pop")
            self.avatar.bounce()
            self.avatar.talk(1200)

    def _on_configure(self, _event=None) -> None:
        self.itemconfigure(self._line, width=max(200, self.winfo_width() - 130))

    def _tick(self) -> None:
        self._t += 0.04
        width = max(100, self.winfo_width())
        # Ondas
        for i, wave in enumerate(self._waves):
            pts = []
            for x in range(0, width + 40, 40):
                y = self._h * (0.80 + 0.05 * i) + math.sin(x * 0.012 + self._t * (1.0 + i * 0.4) + i) * (5 + i * 2)
                pts.extend((x, y))
            self.coords(wave, *pts)
            self.itemconfigure(wave, fill=lerp_color(theme.CARD, theme.ACCENT, 0.12 + i * 0.1))
        # Digitação
        if self._typed < len(self._text):
            self._typed = min(len(self._text), self._typed + 1.1)
            if int(self._typed) % 3 == 0:
                self.avatar.talk(160)
        shown = self._text[: int(self._typed)]
        self.itemconfigure(self._line, text=shown)
        bbox = self.bbox(self._line)
        if bbox:
            self.coords(self._cursor, bbox[2] + 2, bbox[3] - 9)
        self.itemconfigure(self._cursor, state="normal" if int(self._t * 2.5) % 2 == 0 else "hidden")
        if self._typed >= len(self._text) and time.monotonic() - self._last_tip_change > 9.0:
            self._set_tip(self._tip + 1)


# ---------------------------------------------------------------------------------------
# Hover e pulso
# ---------------------------------------------------------------------------------------

def hover_glow(holder: tk.Frame, base: str = theme.BORDER, glow: str = theme.ACCENT) -> None:
    """Anima a cor da borda de ``holder`` (tk.Frame com padding de 1-2 px) ao passar o mouse."""
    state = {"u": 0.0, "target": 0.0, "running": False}

    def inside() -> bool:
        try:
            px, py = holder.winfo_pointerxy()
            x, y = holder.winfo_rootx(), holder.winfo_rooty()
            return x <= px < x + holder.winfo_width() and y <= py < y + holder.winfo_height()
        except tk.TclError:
            return False

    def run() -> None:
        if state["running"]:
            return
        state["running"] = True

        def tick() -> None:
            try:
                if not holder.winfo_exists():
                    return
                diff = state["target"] - state["u"]
                state["u"] += max(-0.18, min(0.18, diff))
                holder.configure(background=lerp_color(base, glow, state["u"]))
                if abs(diff) > 0.01:
                    holder.after(16, tick)
                else:
                    state["running"] = False
            except tk.TclError:
                return

        tick()

    def enter(_e=None) -> None:
        state["target"] = 1.0
        run()

    def leave(_e=None) -> None:
        holder.after(30, lambda: (state.update(target=0.0) if not inside() else None, run()))

    for widget in (holder, *_descendants(holder)):
        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")


def _descendants(widget: tk.Misc):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def pulse_button(button: ttk.Button, base_style: str = "Accent.TButton", name: str = "Pulse.Accent.TButton") -> None:
    """Faz o botão principal respirar suavemente entre duas cores."""
    style = ttk.Style(button)
    style.configure(name, background=theme.ACCENT, foreground="#ffffff", padding=(14, 8), borderwidth=0, relief="flat")
    style.map(name, background=[("disabled", theme.PANEL), ("pressed", theme.ACCENT_HOVER), ("active", theme.ACCENT_HOVER)])
    button.configure(style=name)
    state = {"t": 0.0}

    def tick() -> None:
        state["t"] += 0.12
        if str(button.cget("state")) == "normal":
            style.configure(name, background=lerp_color(theme.ACCENT, "#a592ff", (math.sin(state["t"]) + 1) / 2 * 0.7))

    loop(button, 70, tick)
