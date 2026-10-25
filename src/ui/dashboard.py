"""Dashboard principal: navegação lateral, status da IA e páginas."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from .. import APP_NAME
from ..avatar import load_photo, resolve_avatar
from ..logger import get_logger
from . import theme
from .chat_page import ChatPage
from .games_page import GamesPage
from .profile_page import ProfilePage
from .settings_page import SettingsPage
from .widgets import AnimatedLogo, tween

log = get_logger("ui")

PAGES = (
    ("games", "🎮  Jogos", GamesPage),
    ("profile", "🧑  Perfil da IA", ProfilePage),
    ("chat", "💬  Conversa", ChatPage),
    ("settings", "⚙  Configurações", SettingsPage),
)


class DashboardFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, app, notice: str = ""):
        super().__init__(parent)
        self.app = app
        self.offline = bool(notice)
        self._current_key = ""
        self._animate = True

        # ------------------------------------------------------------ barra lateral
        sidebar = ttk.Frame(self, style="Panel.TFrame", width=250)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        AnimatedLogo(sidebar, APP_NAME).pack(anchor="w", padx=19, pady=(19, 0))
        ttk.Label(sidebar, text="sua IA para jogar", style="PanelMuted.TLabel").pack(anchor="w", padx=22, pady=(0, 18))

        identity = ttk.Frame(sidebar, style="Panel.TFrame")
        identity.pack(fill="x", padx=18, pady=(0, 16))
        self.avatar = theme.Avatar(identity, size=48)
        self.avatar.pack(side="left")
        self.avatar.configure(cursor="hand2")
        self.avatar.bind("<Button-1>", self._poke_avatar)
        names = ttk.Frame(identity, style="Panel.TFrame")
        names.pack(side="left", padx=12)
        self.name_label = ttk.Label(names, text="", style="Panel.TLabel", font=theme.FONT_BOLD)
        self.name_label.pack(anchor="w")
        self.persona_label = ttk.Label(names, text="", style="PanelMuted.TLabel")
        self.persona_label.pack(anchor="w")

        self.nav_buttons: dict[str, ttk.Button] = {}
        for key, label, _cls in PAGES:
            button = ttk.Button(sidebar, text=label, style="Nav.TButton", command=lambda k=key: self.show_page(k, click=True))
            button.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = button

        footer = ttk.Frame(sidebar, style="Panel.TFrame")
        footer.pack(side="bottom", fill="x", padx=22, pady=20)
        self.ai_status = theme.StatusDot(footer)
        self.ai_status.pack(anchor="w", pady=2)
        self.game_status = theme.StatusDot(footer)
        self.game_status.pack(anchor="w", pady=2)
        self.music_button = ttk.Button(footer, text="", style="Nav.TButton", command=self._toggle_music)
        self.music_button.pack(fill="x", pady=(10, 0))
        self._refresh_music_button()

        # ------------------------------------------------------------ conteúdo
        main = ttk.Frame(self, padding=(28, 22))
        main.pack(side="left", fill="both", expand=True)

        if notice:
            banner = tk.Frame(main, background="#3a2f12")
            banner.pack(fill="x", pady=(0, 14))
            tk.Label(banner, text=notice, background="#3a2f12", foreground=theme.WARN, font=theme.FONT,
                     wraplength=760, justify="left", padx=14, pady=10).pack(anchor="w")

        self.container = ttk.Frame(main)
        self.container.pack(fill="both", expand=True)
        self.pages: dict[str, Any] = {}
        for key, _label, cls in PAGES:
            page = cls(self.container, app, self)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page

        self.update_identity()
        self.update_status()
        self.show_page("games")

    # ------------------------------------------------------------------ navegação
    def show_page(self, key: str, click: bool = False) -> None:
        if click:
            self.app.click()
        log.debug("Página: %s", key)
        for name, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if name == key else "Nav.TButton")
        page = self.pages[key]
        changed = key != self._current_key
        self._current_key = key
        page.lift()
        if changed and self._animate:
            # Transição: a página desliza suavemente da direita para o lugar.
            page.place_configure(relx=0.04)
            tween(page, 240, lambda u: page.place_configure(relx=0.04 * (1 - u)),
                  done=lambda: page.place_configure(relx=0))
        if hasattr(page, "on_show"):
            page.on_show()

    # ------------------------------------------------------------------ interações
    def _poke_avatar(self, _event=None) -> None:
        """Clicar na IA faz ela pular e responder com um som."""
        self.app.sound.play("pop")
        self.avatar.bounce()
        self.avatar.talk(900)

    def _toggle_music(self) -> None:
        self.app.toggle_music()
        self._refresh_music_button()

    def _refresh_music_button(self) -> None:
        on = self.app.sound.music_enabled and self.app.sound.enabled
        self.music_button.configure(text="🎵  Música: ligada" if on else "🔇  Música: desligada")

    # ------------------------------------------------------------------ identidade e status
    def update_identity(self) -> None:
        profile = self.app.storage.snapshot()["ai_profile"]
        photo = None
        path = resolve_avatar(self.app.avatars_dir, profile["avatar"])
        if path is not None:
            photo = load_photo(path, 48)
        self.avatar.show(profile["bot_name"], photo)
        self.avatar.start_animation()
        self.name_label.configure(text=profile["bot_name"])
        from ..ai_engine import PERSONALITIES
        self.persona_label.configure(text=PERSONALITIES[profile["personality"]]["label"].split(" /")[0])

    def update_status(self) -> None:
        has_key = self.app.storage.has_api_key()
        if not has_key:
            self.ai_status.set("IA: sem chave", theme.ERR)
        elif self.offline:
            self.ai_status.set("IA: offline", theme.WARN)
        else:
            self.ai_status.set("IA: conectada", theme.OK)
        session = self.app.session
        connected = bool(session and session.game_connected)
        self.game_status.set("Jogo: conectado" if connected else "Jogo: aguardando", theme.OK if connected else theme.MUTED)

    def on_session_event(self, kind: str, data: dict[str, Any]) -> None:
        if kind in ("connected", "disconnected"):
            self.update_status()
            self.app.sound.play("success" if kind == "connected" else "notify")
        elif kind == "say":
            self.avatar.talk(1800)
        for page in self.pages.values():
            if hasattr(page, "on_session_event"):
                page.on_session_event(kind, data)
