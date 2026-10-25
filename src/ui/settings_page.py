"""Página de configurações: chave de API, modelo, som e informações."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .. import APP_NAME, APP_VERSION, ai_engine
from ..ai_engine import KeyStatus, PROVIDERS, mask_key
from . import theme


class SettingsPage(ttk.Frame):
    def __init__(self, parent: tk.Misc, app, dashboard):
        super().__init__(parent)
        self.app, self.dashboard = app, dashboard

        ttk.Label(self, text="Configurações", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Chave de API, modelo de IA, som e informações do aplicativo.", style="Muted.TLabel").pack(anchor="w", pady=(2, 16))

        # ---- IA
        ai_card = ttk.Frame(self, style="Card.TFrame", padding=20)
        ai_card.pack(fill="x", pady=(0, 14))
        ttk.Label(ai_card, text="Inteligência artificial", style="Card.TLabel", font=theme.FONT_H2).pack(anchor="w")
        self.ai_info = ttk.Label(ai_card, text="", style="CardMuted.TLabel", justify="left")
        self.ai_info.pack(anchor="w", pady=(6, 10))
        row = ttk.Frame(ai_card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Alterar chave de API…", command=self._change_key).pack(side="left")
        self.revalidate = ttk.Button(row, text="Revalidar chave", command=self._revalidate)
        self.revalidate.pack(side="left", padx=(10, 0))
        self.detect_button = ttk.Button(row, text="Detectar modelo", command=self._detect_model)
        self.detect_button.pack(side="left", padx=(10, 0))
        ttk.Button(row, text="Remover chave", style="Danger.TButton", command=self._remove_key).pack(side="left", padx=(10, 0))
        self.validation = ttk.Label(ai_card, text="", style="Card.TLabel")
        self.validation.pack(anchor="w", pady=(10, 0))

        # ---- som
        sound_card = ttk.Frame(self, style="Card.TFrame", padding=20)
        sound_card.pack(fill="x", pady=(0, 14))
        ttk.Label(sound_card, text="Som e instalação", style="Card.TLabel", font=theme.FONT_H2).pack(anchor="w")
        prefs = app.storage.snapshot()["app_preferences"]
        self.sound_var = tk.BooleanVar(value=prefs["sound_enabled"])
        ttk.Checkbutton(sound_card, text="Efeitos sonoros da interface", variable=self.sound_var,
                        style="Card.TCheckbutton", command=self._save_prefs).pack(anchor="w", pady=(8, 0))
        self.music_var = tk.BooleanVar(value=prefs.get("music_enabled", True))
        ttk.Checkbutton(sound_card, text="Música de fundo", variable=self.music_var,
                        style="Card.TCheckbutton", command=self._save_prefs).pack(anchor="w", pady=(4, 0))
        volume_row = ttk.Frame(sound_card, style="Card.TFrame")
        volume_row.pack(fill="x", pady=(6, 0))
        ttk.Label(volume_row, text="Volume", style="Card.TLabel").pack(side="left")
        self.volume_var = tk.IntVar(value=prefs["sound_volume"])
        scale = ttk.Scale(volume_row, from_=0, to=100, variable=self.volume_var, length=220,
                          command=lambda _v: None)
        scale.pack(side="left", padx=12)
        scale.bind("<ButtonRelease-1>", lambda _e: self._save_prefs())
        self.auto_var = tk.BooleanVar(value=prefs["auto_launch_mods"])
        ttk.Checkbutton(sound_card, text="Oferecer a instalação de mods automaticamente ao abrir a lista de jogos",
                        variable=self.auto_var, style="Card.TCheckbutton", command=self._save_prefs).pack(anchor="w", pady=(10, 0))

        # ---- sobre
        about = ttk.Frame(self, style="Card.TFrame", padding=20)
        about.pack(fill="x")
        ttk.Label(about, text="Sobre", style="Card.TLabel", font=theme.FONT_H2).pack(anchor="w")
        ttk.Label(about, text=f"{APP_NAME} {APP_VERSION}  •  Dados em: {app.storage.data_dir}",
                  style="CardMuted.TLabel", wraplength=780, justify="left").pack(anchor="w", pady=(6, 0))
        buttons = ttk.Frame(about, style="Card.TFrame")
        buttons.pack(anchor="w", pady=(10, 0))
        ttk.Button(buttons, text="Logs e diagnóstico", style="Accent.TButton", command=self._show_logs).pack(side="left")
        ttk.Button(buttons, text="Ver Termos de Licença", command=self._show_license).pack(side="left", padx=(10, 0))

        self.refresh_info()

    # ------------------------------------------------------------------ exibição
    def on_show(self) -> None:
        self.refresh_info()

    def refresh_info(self) -> None:
        snap = self.app.storage.snapshot()["ai_profile"]
        spec = PROVIDERS[snap["provider"]]
        key = self.app.storage.get_api_key()
        detected = self.app.storage.get_detected_model(snap["provider"])
        if snap["model"]:
            model = f"{snap['model']} (definido por você)"
        elif detected:
            model = f"{detected} (detectado automaticamente)"
        else:
            model = "será detectado automaticamente na primeira conversa"
        shown = mask_key(key) if key else "nenhuma"
        self.ai_info.configure(
            text=f"Provedor: {spec.label}\nChave: {shown}  (guardada em: {self.app.storage.storage_mode()})\nModelo: {model}"
        )

    # ------------------------------------------------------------------ ações
    def _change_key(self) -> None:
        self.app.click()
        self.app.show_api_config(can_cancel=True)

    def _remove_key(self) -> None:
        if not messagebox.askyesno("Remover chave", "Remover a chave de API salva? Você precisará informar uma nova para usar a IA."):
            return
        self.app.click()
        self.app.storage.clear_api_key()
        self.app.refresh_ai()
        self.dashboard.update_status()
        self.refresh_info()
        self.validation.configure(text="Chave removida.", style="CardMuted.TLabel")

    def _detect_model(self) -> None:
        """Consulta o provedor e adota o melhor modelo disponível para a chave (zera o modelo manual)."""
        key = self.app.storage.get_api_key()
        provider = self.app.storage.get("ai_profile", "provider")
        if not key:
            self.validation.configure(text="Nenhuma chave configurada.", style="CardWarn.TLabel")
            return
        self.app.click()
        self.detect_button.configure(state="disabled")
        self.validation.configure(text="Procurando o melhor modelo disponível...", style="CardMuted.TLabel")
        self.app.run_async(
            lambda: ai_engine.pick_best_model(provider, ai_engine.list_models(provider, key)),
            lambda model, error: self._on_detected(provider, model, error),
        )

    def _on_detected(self, provider: str, model: str | None, error: Exception | None) -> None:
        if not self.winfo_exists():
            return
        self.detect_button.configure(state="normal")
        if error is not None or not model:
            detail = str(error) if isinstance(error, ai_engine.AIError) else "nenhum modelo de chat encontrado"
            self.validation.configure(text=f"Não foi possível detectar o modelo: {detail}", style="CardErr.TLabel")
            return
        self.app.storage.update("ai_profile", model="")
        self.app.storage.set_detected_model(provider, model)
        self.app.refresh_ai()
        self.refresh_info()
        self.validation.configure(text=f"✔ Modelo selecionado: {model}", style="CardOk.TLabel")

    def _revalidate(self) -> None:
        key = self.app.storage.get_api_key()
        provider = self.app.storage.get("ai_profile", "provider")
        if not key:
            self.validation.configure(text="Nenhuma chave configurada.", style="CardWarn.TLabel")
            return
        self.app.click()
        self.revalidate.configure(state="disabled")
        self.validation.configure(text="Testando...", style="CardMuted.TLabel")
        self.app.run_async(lambda: ai_engine.validate_api_key(key, provider), self._on_validated)

    def _on_validated(self, result: Any, error: Exception | None) -> None:
        if not self.winfo_exists():
            return
        self.revalidate.configure(state="normal")
        if error is not None or result is None:
            self.validation.configure(text="Erro inesperado ao testar a chave.", style="CardErr.TLabel")
        elif result.ok:
            self.dashboard.offline = False
            self.dashboard.update_status()
            self.validation.configure(text=f"✔ {result.message}", style="CardOk.TLabel")
        elif result.status in (KeyStatus.NETWORK_ERROR, KeyStatus.SERVER_ERROR):
            self.validation.configure(text=result.message, style="CardWarn.TLabel")
        else:
            self.validation.configure(text=f"✖ {result.message} Use \"Alterar chave de API\".", style="CardErr.TLabel")

    def _save_prefs(self) -> None:
        try:
            self.app.storage.update(
                "app_preferences",
                sound_enabled=bool(self.sound_var.get()),
                music_enabled=bool(self.music_var.get()),
                sound_volume=int(self.volume_var.get()),
                auto_launch_mods=bool(self.auto_var.get()),
            )
        except OSError:
            return
        self.app.sound.configure(bool(self.sound_var.get()), int(self.volume_var.get()), bool(self.music_var.get()))
        if self.music_var.get() and self.sound_var.get():
            self.app.sound.start_music()
        if self.app.dashboard is not None:
            self.app.dashboard._refresh_music_button()
        self.app.click()

    def _show_logs(self) -> None:
        self.app.click()
        from .log_window import LogWindow
        LogWindow(self, self.app)

    def _show_license(self) -> None:
        self.app.click()
        window = tk.Toplevel(self)
        window.title("Termos de Licença")
        window.geometry("760x520")
        window.configure(background=theme.BG)
        text = tk.Text(window)
        theme.style_text(text)
        text.configure(font=theme.FONT_MONO)
        text.insert("1.0", self.app.storage.license_text() or "LICENSE.txt não encontrado.")
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=12, pady=12)
