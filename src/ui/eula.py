"""Tela de aceite dos Termos de Licença e Uso (EULA)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import APP_NAME
from . import theme


class EulaFrame(ttk.Frame):
    """Bloqueia o aplicativo até que o usuário role até o fim e aceite os termos."""

    def __init__(self, parent: tk.Misc, app):
        super().__init__(parent, padding=(40, 28))
        self.app = app
        self._read_to_end = False

        ttk.Label(self, text="Termos de Licença e Uso", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self,
            text=f"Para usar o {APP_NAME}, leia os termos até o final e aceite para continuar.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True)
        self.text = tk.Text(holder, font=theme.FONT_MONO, wrap="word")
        theme.style_text(self.text)
        self.text.configure(font=theme.FONT_MONO)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self._on_scroll(scroll))
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        license_text = app.storage.license_text() or (
            "Não foi possível carregar o arquivo LICENSE.txt. Reinstale o aplicativo para continuar."
        )
        self.has_license = license_text.strip() != "" and app.storage.license_text() != ""
        self.text.insert("1.0", license_text)
        self.text.configure(state="disabled")

        self.hint = ttk.Label(self, text="Role até o final do texto para habilitar o aceite.", style="Warn.TLabel")
        self.hint.pack(anchor="w", pady=(10, 4))

        self.accepted = tk.BooleanVar(value=False)
        self.check = ttk.Checkbutton(
            self, text="Li e aceito os Termos de Licença e Uso", variable=self.accepted,
            command=self._refresh, state="disabled",
        )
        self.check.pack(anchor="w")

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Recusar e sair", command=self._decline).pack(side="left")
        self.accept_button = ttk.Button(buttons, text="Aceitar e continuar", style="Accent.TButton",
                                        command=self._accept, state="disabled")
        self.accept_button.pack(side="right")

        self._after_id = self.after(200, self._check_scroll_needed)

    def destroy(self) -> None:
        try:
            self.after_cancel(self._after_id)
        except (tk.TclError, AttributeError):
            pass
        super().destroy()

    def _on_scroll(self, scrollbar: ttk.Scrollbar):
        def handler(first: str, last: str) -> None:
            scrollbar.set(first, last)
            if float(last) >= 0.995:
                self._mark_read()
        return handler

    def _check_scroll_needed(self) -> None:
        first, last = self.text.yview()
        if float(last) >= 0.995:
            self._mark_read()

    def _mark_read(self) -> None:
        if self._read_to_end or not self.has_license:
            return
        self._read_to_end = True
        self.check.configure(state="normal")
        self.hint.configure(text="Obrigado. Agora você pode aceitar os termos.", style="Ok.TLabel")

    def _refresh(self) -> None:
        enabled = self._read_to_end and self.accepted.get() and self.has_license
        self.accept_button.configure(state="normal" if enabled else "disabled")

    def _accept(self) -> None:
        if not (self._read_to_end and self.accepted.get() and self.has_license):
            return
        self.app.click()
        self.app.on_terms_accepted()

    def _decline(self) -> None:
        self.app.click()
        self.app.on_terms_declined()
