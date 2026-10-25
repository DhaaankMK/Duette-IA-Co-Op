"""Página de jogos: catálogo, instalação de mods e início do jogo de teste."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .. import mod_installer
from ..mod_installer import GameEntry, InstallCancelled, InstallError
from . import theme
from .widgets import HeroBanner, hover_glow, pulse_button


class GameCard(ttk.Frame):
    def __init__(self, parent: tk.Misc, app, entry: GameEntry):
        super().__init__(parent, style="Card.TFrame", padding=20)
        self.app = app
        self.entry = entry
        self._offered = False
        self._cancel = threading.Event()
        self._busy = False

        top = ttk.Frame(self, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text=entry.name, style="Card.TLabel", font=theme.FONT_H2).pack(side="left")
        self.badge = ttk.Label(top, text="", style="Card.TLabel", font=theme.FONT_BOLD)
        self.badge.pack(side="right")

        ttk.Label(self, text=entry.description, style="CardMuted.TLabel", wraplength=720, justify="left").pack(anchor="w", pady=(6, 0))
        self.detail = ttk.Label(self, text="", style="CardMuted.TLabel", wraplength=720, justify="left")
        self.detail.pack(anchor="w", pady=(6, 0))

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress_label = ttk.Label(self, text="", style="CardMuted.TLabel")

        self.actions = ttk.Frame(self, style="Card.TFrame")
        self.actions.pack(fill="x", pady=(14, 0))
        self.refresh()

    # ------------------------------------------------------------------ estado
    def _saved_path(self) -> str | None:
        return self.app.storage.get("app_preferences", "game_paths").get(self.entry.id)

    def game_dir(self) -> Path | None:
        return mod_installer.find_game_dir(self.entry, self._saved_path())

    def refresh(self) -> None:
        for child in self.actions.winfo_children():
            child.destroy()
        entry = self.entry

        if entry.kind == "builtin":
            self.badge.configure(text="Pronto", foreground=theme.OK)
            self.detail.configure(
                text="Controles do Jogador 1: A/D movem, W pula (duplo), E ataca. "
                     "A IA controla o outro lutador."
            )
            play = ttk.Button(self.actions, text="▶  Jogar com a IA", style="Accent.TButton", command=self._play)
            play.pack(side="left")
            pulse_button(play)
            return

        directory = self.game_dir()
        status = mod_installer.check_installation(entry, directory)
        receipt = directory is not None and (directory / mod_installer.RECEIPT_NAME).is_file()

        if directory is None:
            self.badge.configure(text="Pasta não encontrada", foreground=theme.WARN)
            self.detail.configure(text="Selecione a pasta onde o jogo está instalado.")
        elif status.installed:
            self.badge.configure(text="Integração instalada", foreground=theme.OK)
            self.detail.configure(text=f"Pasta: {directory}")
        elif not status.bundle_available:
            self.badge.configure(text="Mods indisponíveis", foreground=theme.WARN)
            self.detail.configure(
                text=f"Pasta: {directory}\nO pacote de mods deste jogo ainda não está disponível nesta versão do Duette."
            )
        else:
            self.badge.configure(text="Mods ausentes", foreground=theme.WARN)
            self.detail.configure(text=f"Pasta: {directory}\nFaltando: {', '.join(status.missing)}")

        ttk.Button(self.actions, text="Selecionar pasta…", command=self._choose_dir).pack(side="left")
        if directory is not None and not status.installed and status.bundle_available:
            ttk.Button(self.actions, text="Instalar mods", style="Accent.TButton",
                       command=lambda: self._install(directory)).pack(side="left", padx=(10, 0))
        if directory is not None and receipt:
            ttk.Button(self.actions, text="Remover mods", style="Danger.TButton",
                       command=lambda: self._uninstall(directory)).pack(side="left", padx=(10, 0))

    def on_show(self) -> None:
        """Ao abrir a página: oferece a instalação automática, uma vez por sessão."""
        if self.entry.kind != "mod" or self._offered or self._busy:
            return
        directory = self.game_dir()
        if directory is None or not self.app.storage.get("app_preferences", "auto_launch_mods"):
            return
        status = mod_installer.check_installation(self.entry, directory)
        if not status.installed and status.bundle_available:
            self._offered = True
            self._install(directory)

    # ------------------------------------------------------------------ ações
    def _play(self) -> None:
        self.app.click()
        self.app.launch_game(self.entry.name)

    def _choose_dir(self) -> None:
        self.app.click()
        chosen = filedialog.askdirectory(title=f"Pasta do jogo: {self.entry.name}")
        if not chosen:
            return
        directory = Path(chosen)
        if not mod_installer.is_valid_game_dir(self.entry, directory):
            messagebox.showerror("Duette", f"Esta pasta não contém o executável do jogo ({self.entry.executable}).")
            return
        paths = dict(self.app.storage.get("app_preferences", "game_paths"))
        paths[self.entry.id] = str(directory)
        self.app.storage.update("app_preferences", game_paths=paths)
        self.refresh()
        self.on_show()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.progress.pack(fill="x", pady=(12, 0), before=self.actions)
            self.progress_label.pack(anchor="w", pady=(4, 0), before=self.actions)
        else:
            self.progress.pack_forget()
            self.progress_label.pack_forget()

    def _install(self, directory: Path) -> None:
        if self._busy:
            return
        if not messagebox.askyesno(
            "Instalar mods",
            f"O Duette vai instalar a integração da IA em:\n\n{directory}\n\n"
            "Arquivos existentes que forem substituídos receberão cópia de segurança. Continuar?",
        ):
            return
        self.app.click()
        self._cancel.clear()
        self._set_busy(True)
        for child in self.actions.winfo_children():
            child.destroy()
        ttk.Button(self.actions, text="Cancelar", command=self._cancel.set).pack(side="left")

        def progress(fraction: float, message: str) -> None:
            self.app.post(self._on_progress, fraction, message)

        self.app.run_async(
            lambda: mod_installer.install(self.entry, directory, progress, self._cancel),
            self._on_install_done,
        )

    def _on_progress(self, fraction: float, message: str) -> None:
        if self.winfo_exists():
            self.progress["value"] = fraction * 100
            self.progress_label.configure(text=message)

    def _on_install_done(self, result: Any, error: Exception | None) -> None:
        if not self.winfo_exists():
            return
        self._set_busy(False)
        self.refresh()
        if isinstance(error, InstallCancelled):
            messagebox.showinfo("Duette", "Instalação cancelada. Nenhuma alteração foi mantida.")
        elif isinstance(error, InstallError):
            messagebox.showerror("Duette", str(error))
        elif error is not None:
            messagebox.showerror("Duette", f"Erro inesperado na instalação ({type(error).__name__}).")
        else:
            messagebox.showinfo("Duette", "Integração instalada com sucesso.")

    def _uninstall(self, directory: Path) -> None:
        if not messagebox.askyesno("Remover mods", "Remover os arquivos instalados pelo Duette neste jogo?"):
            return
        self.app.click()
        try:
            removed = mod_installer.uninstall(directory)
        except InstallError as exc:
            messagebox.showerror("Duette", str(exc))
        else:
            messagebox.showinfo("Duette", f"{removed} arquivo(s) removido(s).")
        self.refresh()


class GamesPage(ttk.Frame):
    def __init__(self, parent: tk.Misc, app, dashboard):
        super().__init__(parent)
        ttk.Label(self, text="Jogos", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Escolha onde a sua IA vai jogar com você.", style="Muted.TLabel").pack(anchor="w", pady=(2, 12))
        self.banner = HeroBanner(self, app)
        self.banner.pack(fill="x", pady=(0, 16))
        self.cards: list[GameCard] = []
        entries = mod_installer.load_catalog()
        if not entries:
            ttk.Label(self, text="Nenhum jogo no catálogo (mods_bundle/games.json ausente ou inválido).",
                      style="Warn.TLabel").pack(anchor="w")
        for entry in entries:
            holder = tk.Frame(self, background=theme.BORDER, padx=1, pady=1)   # borda que brilha no hover
            holder.pack(fill="x", pady=(0, 14))
            card = GameCard(holder, app, entry)
            card.pack(fill="x")
            hover_glow(holder)
            self.cards.append(card)

    def on_show(self) -> None:
        self.banner.refresh_identity()
        for card in self.cards:
            card.on_show()
