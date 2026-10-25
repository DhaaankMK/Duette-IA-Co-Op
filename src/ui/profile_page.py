"""Página de personalização da IA (nome, avatar e personalidade)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import ai_engine, avatar
from ..ai_engine import PERSONALITIES
from . import theme


class ProfilePage(ttk.Frame):
    def __init__(self, parent: tk.Misc, app, dashboard):
        super().__init__(parent)
        self.app, self.dashboard = app, dashboard
        profile = app.storage.snapshot()["ai_profile"]
        self._avatar_name = profile["avatar"]

        ttk.Label(self, text="Perfil da IA", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Dê um nome, uma foto e uma personalidade à sua IA.", style="Muted.TLabel").pack(anchor="w", pady=(2, 16))

        card = ttk.Frame(self, style="Card.TFrame", padding=22)
        card.pack(fill="both", expand=True)
        card.columnconfigure(1, weight=1)

        # ---- identidade
        self.avatar_view = theme.Avatar(card, size=96, background=theme.CARD)
        self.avatar_view.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 22))

        ttk.Label(card, text="Nome", style="Card.TLabel", font=theme.FONT_BOLD).grid(row=0, column=1, sticky="w")
        self.name_var = tk.StringVar(value=profile["bot_name"])
        self.name_var.trace_add("write", lambda *_: self._redraw_avatar())
        ttk.Entry(card, textvariable=self.name_var, width=34).grid(row=1, column=1, sticky="nw", pady=(4, 0))

        avatar_buttons = ttk.Frame(card, style="Card.TFrame")
        avatar_buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(avatar_buttons, text="Escolher foto…", command=self._choose_avatar).pack(side="left")
        ttk.Button(avatar_buttons, text="Remover foto", command=self._remove_avatar).pack(side="left", padx=(8, 0))
        if not avatar.pillow_available():
            ttk.Label(avatar_buttons, text="  (instale o Pillow para usar fotos)", style="CardMuted.TLabel").pack(side="left")

        # ---- personalidade
        ttk.Label(card, text="Personalidade", style="Card.TLabel", font=theme.FONT_BOLD).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(22, 6))
        self.personality = tk.StringVar(value=profile["personality"])
        radios = ttk.Frame(card, style="Card.TFrame")
        radios.grid(row=4, column=0, columnspan=2, sticky="w")
        for key, data in PERSONALITIES.items():
            ttk.Radiobutton(radios, text=data["label"], value=key, variable=self.personality,
                            style="Card.TRadiobutton", command=self._on_personality).pack(anchor="w", pady=2)
        self.persona_hint = ttk.Label(card, text="", style="CardMuted.TLabel", wraplength=640, justify="left")
        self.persona_hint.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Label(card, text="Instruções personalizadas (opcional)", style="Card.TLabel", font=theme.FONT_BOLD).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(18, 6))
        self.custom = tk.Text(card, height=5)
        theme.style_text(self.custom, background=theme.BG)
        self.custom.grid(row=7, column=0, columnspan=2, sticky="nsew")
        self.custom.insert("1.0", profile["custom_prompt"])
        self.custom.bind("<<Modified>>", self._on_custom_modified)
        self.counter = ttk.Label(card, text="", style="CardMuted.TLabel")
        self.counter.grid(row=8, column=1, sticky="e")
        card.rowconfigure(7, weight=1)

        footer = ttk.Frame(card, style="Card.TFrame")
        footer.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.status = ttk.Label(footer, text="", style="Card.TLabel")
        self.status.pack(side="left")
        ttk.Button(footer, text="Salvar perfil", style="Accent.TButton", command=self._save).pack(side="right")

        self._redraw_avatar()
        self._on_personality()
        self._update_counter()

    # ------------------------------------------------------------------ avatar
    def _redraw_avatar(self) -> None:
        photo = None
        path = avatar.resolve_avatar(self.app.avatars_dir, self._avatar_name)
        if path is not None:
            photo = avatar.load_photo(path, 96)
        self.avatar_view.show(self.name_var.get().strip() or "D", photo)

    def _choose_avatar(self) -> None:
        self.app.click()
        chosen = filedialog.askopenfilename(
            title="Escolher foto de perfil",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"), ("Todos os arquivos", "*.*")],
        )
        if not chosen:
            return
        try:
            self._avatar_name = avatar.import_avatar(chosen, self.app.avatars_dir)
        except avatar.AvatarError as exc:
            messagebox.showerror("Duette", str(exc))
            return
        self._redraw_avatar()

    def _remove_avatar(self) -> None:
        self.app.click()
        self._avatar_name = ""
        self._redraw_avatar()

    # ------------------------------------------------------------------ personalidade
    def _on_personality(self) -> None:
        key = self.personality.get()
        prompt = PERSONALITIES[key]["prompt"]
        self.persona_hint.configure(
            text=prompt if prompt else "Descreva abaixo como a sua IA deve se comportar."
        )

    def _on_custom_modified(self, _event=None) -> None:
        if self.custom.edit_modified():
            text = self.custom.get("1.0", "end-1c")
            if len(text) > ai_engine.MAX_CUSTOM_PROMPT:
                self.custom.delete("1.0", "end")
                self.custom.insert("1.0", text[: ai_engine.MAX_CUSTOM_PROMPT])
            self._update_counter()
            self.custom.edit_modified(False)

    def _update_counter(self) -> None:
        used = len(self.custom.get("1.0", "end-1c"))
        self.counter.configure(text=f"{used}/{ai_engine.MAX_CUSTOM_PROMPT}")

    # ------------------------------------------------------------------ salvar
    def _save(self) -> None:
        self.app.click()
        name = ai_engine.sanitize_text(self.name_var.get(), ai_engine.MAX_BOT_NAME)
        if not name:
            self.status.configure(text="Informe um nome para a sua IA.", style="CardErr.TLabel")
            return
        personality = self.personality.get()
        custom = ai_engine.sanitize_text(self.custom.get("1.0", "end-1c"), ai_engine.MAX_CUSTOM_PROMPT)
        if personality == "custom" and not custom:
            self.status.configure(text="Descreva a personalidade personalizada.", style="CardErr.TLabel")
            return
        try:
            self.app.storage.update(
                "ai_profile", bot_name=name, avatar=self._avatar_name, personality=personality, custom_prompt=custom
            )
        except OSError:
            self.status.configure(text="Não foi possível salvar o perfil.", style="CardErr.TLabel")
            return
        self.name_var.set(name)
        self.app.refresh_ai()
        self.dashboard.update_identity()
        self.status.configure(text="✔ Perfil salvo.", style="CardOk.TLabel")
