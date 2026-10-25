"""Tema escuro do Duette e widgets reutilizáveis."""

from __future__ import annotations

import math
import sys
import time
import tkinter as tk
from tkinter import ttk

BG = "#0f1117"
PANEL = "#151821"
CARD = "#1c202b"
CARD_HOVER = "#232838"
BORDER = "#2a3042"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#9279ff"
TEXT = "#e8eaf0"
MUTED = "#8b92a5"
OK = "#3ddc97"
ERR = "#ff5d6c"
WARN = "#ffc857"

_FAMILY = "Segoe UI" if sys.platform == "win32" else ("SF Pro Text" if sys.platform == "darwin" else "DejaVu Sans")
FONT = (_FAMILY, 10)
FONT_SMALL = (_FAMILY, 9)
FONT_BOLD = (_FAMILY, 10, "bold")
FONT_TITLE = (_FAMILY, 20, "bold")
FONT_H2 = (_FAMILY, 13, "bold")
FONT_MONO = ("Consolas" if sys.platform == "win32" else "DejaVu Sans Mono", 9)


def apply_theme(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=BG)

    style.configure(".", background=BG, foreground=TEXT, font=FONT, bordercolor=BORDER,
                    lightcolor=BG, darkcolor=BG, troughcolor=PANEL, focuscolor=ACCENT)
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Card.TFrame", background=CARD)

    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Panel.TLabel", background=PANEL)
    style.configure("Card.TLabel", background=CARD)
    style.configure("Title.TLabel", font=FONT_TITLE)
    style.configure("H2.TLabel", font=FONT_H2)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
    style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Ok.TLabel", foreground=OK)
    style.configure("Err.TLabel", foreground=ERR)
    style.configure("Warn.TLabel", foreground=WARN)
    style.configure("CardOk.TLabel", background=CARD, foreground=OK)
    style.configure("CardErr.TLabel", background=CARD, foreground=ERR)
    style.configure("CardWarn.TLabel", background=CARD, foreground=WARN)

    for name, bg, hover, fg in (
        ("TButton", CARD, CARD_HOVER, TEXT),
        ("Accent.TButton", ACCENT, ACCENT_HOVER, "#ffffff"),
        ("Danger.TButton", "#3a2027", "#52272f", ERR),
        ("Nav.TButton", PANEL, CARD, MUTED),
        ("NavActive.TButton", CARD, CARD, TEXT),
    ):
        style.configure(name, background=bg, foreground=fg, padding=(14, 8), borderwidth=0, relief="flat")
        style.map(name,
                  background=[("disabled", PANEL), ("pressed", hover), ("active", hover)],
                  foreground=[("disabled", "#555c70")])
    style.configure("Nav.TButton", anchor="w", padding=(16, 10))
    style.configure("NavActive.TButton", anchor="w", padding=(16, 10), foreground=ACCENT_HOVER)

    style.configure("TEntry", fieldbackground=CARD, foreground=TEXT, insertcolor=TEXT, padding=6, bordercolor=BORDER)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=TEXT,
                    arrowcolor=TEXT, padding=6, selectbackground=CARD, selectforeground=TEXT)
    style.map("TCombobox", fieldbackground=[("readonly", CARD)], bordercolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=BG, foreground=TEXT, indicatorcolor=CARD)
        style.map(name, background=[("active", BG)], indicatorcolor=[("selected", ACCENT)],
                  foreground=[("disabled", "#555c70")])
    style.configure("Card.TRadiobutton", background=CARD)
    style.map("Card.TRadiobutton", background=[("active", CARD)])
    style.configure("Card.TCheckbutton", background=CARD)
    style.map("Card.TCheckbutton", background=[("active", CARD)])

    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL, borderwidth=0, thickness=10)
    style.configure("Horizontal.TScale", background=BG, troughcolor=PANEL)
    style.configure("Vertical.TScrollbar", background=CARD, troughcolor=PANEL, arrowcolor=MUTED, borderwidth=0)


def style_text(widget: tk.Text, background: str = CARD) -> None:
    widget.configure(background=background, foreground=TEXT, insertbackground=TEXT, relief="flat",
                     borderwidth=0, highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT, font=FONT, padx=10, pady=8, wrap="word",
                     selectbackground=ACCENT, selectforeground="#ffffff")


class Avatar(tk.Canvas):
    """Avatar circular: foto (se houver) ou robozinho vetorial padrão.

    O robô pode ser animado (``start_animation``): pisca, a antena pulsa, a boca mexe ao falar
    (``talk``) e ele pula quando clicado (``bounce``).
    """

    PALETTE = ("#7c5cff", "#ff6b9d", "#3ddc97", "#ffb84d", "#4dc3ff", "#ff7a59")

    def __init__(self, parent: tk.Misc, size: int = 56, background: str = PANEL):
        super().__init__(parent, width=size, height=size, highlightthickness=0, background=background)
        self._size = size
        self._photo = None
        self._eyes: list[int] = []
        self._ant = None
        self._mouth: list[int] = []
        self._animating = False
        self._t = 0.0
        self._talk_until = 0.0
        self._dy = 0.0

    def show(self, name: str = "", photo=None) -> None:
        """Mostra a foto da IA; sem foto, mostra o robozinho padrão."""
        self.delete("all")
        self._eyes, self._mouth, self._ant, self._dy = [], [], None, 0.0
        size = self._size
        if photo is not None:
            self._photo = photo  # mantém referência
            self.create_image(size // 2, size // 2, image=photo)
            self.create_oval(1, 1, size - 1, size - 1, outline=BORDER, width=2)
            return
        self._draw_robot()

    def _round_rect(self, x1: float, y1: float, x2: float, y2: float, r: float, **options) -> None:
        points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                  x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        self.create_polygon(points, smooth=True, **options)

    def _draw_robot(self) -> None:
        """Robozinho desenhado em vetor (nítido em qualquer tamanho, sem arquivos de imagem)."""
        u = self._size / 100.0
        self.create_oval(1, 1, self._size - 1, self._size - 1, fill="#232842", outline=BORDER, width=max(1, int(2 * u)))
        # antena
        self.create_line(50 * u, 17 * u, 50 * u, 30 * u, fill="#9aa4ff", width=max(2, 3 * u))
        self._ant = self.create_oval(43 * u, 9 * u, 57 * u, 23 * u, fill=ACCENT_HOVER, outline="")
        # orelhas
        self._round_rect(18 * u, 47 * u, 28 * u, 65 * u, 3 * u, fill="#6f78c2", outline="")
        self._round_rect(72 * u, 47 * u, 82 * u, 65 * u, 3 * u, fill="#6f78c2", outline="")
        # cabeça e visor
        self._round_rect(25 * u, 28 * u, 75 * u, 80 * u, 12 * u, fill="#dfe4ff", outline="")
        self._round_rect(31 * u, 38 * u, 69 * u, 62 * u, 8 * u, fill="#151a2e", outline="")
        # olhos
        self._eyes = [self.create_oval(37 * u, 44 * u, 47 * u, 56 * u, fill="#4dffd8", outline=""),
                      self.create_oval(53 * u, 44 * u, 63 * u, 56 * u, fill="#4dffd8", outline="")]
        # boca (grade)
        self._mouth = [self.create_line(x * u, 68 * u, x * u, 73 * u, fill="#7c86c9", width=max(1.5, 2.5 * u))
                       for x in (40, 46, 52, 58)]

    # ------------------------------------------------------------------ animação
    def start_animation(self) -> None:
        if self._animating:
            return
        self._animating = True
        self.after(70, self._tick)

    def talk(self, ms: int = 1000) -> None:
        self._talk_until = max(self._talk_until, time.monotonic() + ms / 1000.0)

    def bounce(self) -> None:
        """Pulinho de alegria (o avatar sobe e volta com ease)."""
        start = time.monotonic()
        height = self._size * 0.16

        def tick() -> None:
            try:
                if not self.winfo_exists():
                    return
                u = min(1.0, (time.monotonic() - start) / 0.45)
                target = -abs(math.sin(u * math.pi * 2)) * height * (1 - u)
                self.move("all", 0, target - self._dy)
                self._dy = target
                if u < 1.0:
                    self.after(16, tick)
                else:
                    self.move("all", 0, -self._dy)
                    self._dy = 0.0
            except tk.TclError:
                return

        tick()

    def _tick(self) -> None:
        try:
            if not self.winfo_exists():
                return
            self._t += 0.07
            u = self._size / 100.0
            if self._ant is not None:
                pulse = (math.sin(self._t * 3) + 1) / 2
                self.itemconfigure(self._ant, fill="#%02x%02x%02x" % (
                    int(0x92 + (0x4d - 0x92) * pulse), int(0x79 + (0xff - 0x79) * pulse), int(0xff + (0xd8 - 0xff) * pulse)))
            if self._eyes:
                blinking = (self._t % 3.9) < 0.14
                top, bottom = (49.5, 50.5) if blinking else (44, 56)
                for item, (x1, x2) in zip(self._eyes, ((37, 47), (53, 63))):
                    self.coords(item, x1 * u, top * u + self._dy, x2 * u, bottom * u + self._dy)
            if self._mouth:
                talking = time.monotonic() < self._talk_until
                for i, line in enumerate(self._mouth):
                    x = (40, 46, 52, 58)[i] * u
                    amp = (2.5 + 5.5 * abs(math.sin(self._t * 9 + i * 1.3))) if talking else 2.5
                    self.coords(line, x, 68 * u + self._dy, x, (68 + 2.5 + amp) * u + self._dy)
            self.after(70, self._tick)
        except tk.TclError:
            return


class StatusDot(ttk.Frame):
    """Indicador com bolinha colorida e texto (pulsa quando está "ok")."""

    def __init__(self, parent: tk.Misc, text: str = "", color: str = MUTED, style: str = "Panel.TFrame"):
        super().__init__(parent, style=style)
        bg = PANEL if style == "Panel.TFrame" else BG
        self._bg = bg
        self._color = color
        self._t = 0.0
        self._canvas = tk.Canvas(self, width=16, height=16, highlightthickness=0, background=bg)
        self._canvas.pack(side="left", padx=(0, 6))
        self._ring = self._canvas.create_oval(8, 8, 8, 8, outline="", width=2)
        self._dot = self._canvas.create_oval(4, 4, 12, 12, fill=color, outline="")
        self._label = ttk.Label(self, text=text, style="PanelMuted.TLabel" if bg == PANEL else "Muted.TLabel")
        self._label.pack(side="left")
        self.after(80, self._tick)

    def set(self, text: str, color: str) -> None:
        self._color = color
        self._canvas.itemconfigure(self._dot, fill=color)
        self._label.configure(text=text)

    def _mix(self, a: str, b: str, t: float) -> str:
        ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
        cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
        return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))

    def _tick(self) -> None:
        try:
            if not self.winfo_exists():
                return
            self._t += 0.08
            if self._color == OK:
                phase = (self._t % 1.6) / 1.6
                radius = 4 + 4 * phase
                self._canvas.coords(self._ring, 8 - radius, 8 - radius, 8 + radius, 8 + radius)
                self._canvas.itemconfigure(self._ring, outline=self._mix(OK, self._bg, phase))
            else:
                self._canvas.coords(self._ring, 8, 8, 8, 8)
                self._canvas.itemconfigure(self._ring, outline="")
            self.after(80, self._tick)
        except tk.TclError:
            return
