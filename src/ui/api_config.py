"""Tela de configuração e validação da chave de API."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from .. import ai_engine
from ..ai_engine import ApiValidation, KeyStatus, PROVIDERS
from . import theme


class ApiConfigFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, app, notice: str = "", expired: bool = False, can_cancel: bool = False):
        super().__init__(parent, padding=(40, 28))
        self.app = app
        self._validated: tuple[str, str] | None = None
        self._request_id = 0

        ttk.Label(self, text="Conectar sua IA", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self,
            text="O Duette usa a sua própria chave de API. Ela fica guardada somente neste computador.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        if notice:
            banner = tk.Frame(self, background="#3a2f12" if not expired else "#3a1b22", highlightthickness=0)
            banner.pack(fill="x", pady=(0, 14))
            tk.Label(banner, text=notice, background=banner["background"],
                     foreground=theme.WARN if not expired else theme.ERR, font=theme.FONT_BOLD,
                     wraplength=900, justify="left", padx=14, pady=10).pack(anchor="w")

        columns = self.columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=3, uniform="c")
        columns.columnconfigure(1, weight=2, uniform="c")
        columns.rowconfigure(0, weight=1)
        self._guide_visible = True

        # ---- formulário
        form = ttk.Frame(columns, style="Card.TFrame", padding=22)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        ttk.Label(form, text="Provedor de IA", style="Card.TLabel", font=theme.FONT_BOLD).pack(anchor="w")
        self.provider_var = tk.StringVar()
        self.provider_box = ttk.Combobox(form, state="readonly", textvariable=self.provider_var,
                                         values=[p.label for p in PROVIDERS.values()])
        self.provider_box.pack(fill="x", pady=(6, 16))
        current = app.storage.get("ai_profile", "provider")
        self.provider_box.current(list(PROVIDERS).index(current))
        self.provider_box.bind("<<ComboboxSelected>>", self._on_provider_change)

        ttk.Label(form, text="Chave de API", style="Card.TLabel", font=theme.FONT_BOLD).pack(anchor="w")
        self.hint = ttk.Label(form, text="", style="CardMuted.TLabel")
        self.hint.pack(anchor="w", pady=(2, 6))
        key_row = ttk.Frame(form, style="Card.TFrame")
        key_row.pack(fill="x")
        self.key_var = tk.StringVar()
        self.key_var.trace_add("write", lambda *_: self._on_key_edit())
        self.key_entry = ttk.Entry(key_row, textvariable=self.key_var, show="•")
        self.key_entry.pack(side="left", fill="x", expand=True)
        self.show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(key_row, text="Mostrar", variable=self.show_var, style="Card.TCheckbutton",
                        command=lambda: self.key_entry.configure(show="" if self.show_var.get() else "•")
                        ).pack(side="left", padx=(10, 0))
        self.key_entry.bind("<Return>", lambda _e: self._test())

        self.model_label = ttk.Label(form, text="", style="CardMuted.TLabel")
        self.model_label.pack(anchor="w", pady=(16, 6))
        self.model_var = tk.StringVar(value=app.storage.get("ai_profile", "model"))
        ttk.Entry(form, textvariable=self.model_var).pack(fill="x")

        self.status = ttk.Label(form, text="", style="Card.TLabel", wraplength=520, justify="left")
        self.status.pack(anchor="w", pady=(18, 0))

        actions = ttk.Frame(form, style="Card.TFrame")
        actions.pack(fill="x", side="bottom", pady=(18, 0))
        if can_cancel:
            ttk.Button(actions, text="Voltar", command=self._cancel).pack(side="left")
        self.test_button = ttk.Button(actions, text="Testar conexão", command=self._test)
        self.test_button.pack(side="left", padx=(0 if not can_cancel else 10, 0))
        self.help_button = ttk.Button(actions, text="Ocultar tutorial", command=self._toggle_guide)
        self.help_button.pack(side="left", padx=(10, 0))
        self.continue_button = ttk.Button(actions, text="Salvar e continuar", style="Accent.TButton",
                                          command=self._save, state="disabled")
        self.continue_button.pack(side="right")

        # ---- tutorial
        guide = self.guide = ttk.Frame(columns, style="Panel.TFrame", padding=22)
        guide.grid(row=0, column=1, sticky="nsew")
        ttk.Label(guide, text="Como obter sua chave", style="Panel.TLabel", font=theme.FONT_H2).pack(anchor="w")
        self.steps = ttk.Label(guide, text="", style="Panel.TLabel", wraplength=340, justify="left")
        self.steps.pack(anchor="w", pady=(12, 14))
        self.open_button = ttk.Button(guide, text="Abrir página de chaves", command=self._open_console)
        self.open_button.pack(anchor="w")
        ttk.Label(
            guide,
            text="Dica: trate sua chave como uma senha. Nunca a compartilhe e revogue-a se suspeitar de vazamento.",
            style="PanelMuted.TLabel", wraplength=340, justify="left",
        ).pack(anchor="w", side="bottom")

        self._on_provider_change()
        if can_cancel:      # quem já tem chave raramente precisa do tutorial
            self._toggle_guide(False)
        self.key_entry.focus_set()

    # ------------------------------------------------------------------ helpers
    @property
    def provider_id(self) -> str:
        return list(PROVIDERS)[self.provider_box.current()]

    def _set_status(self, text: str, style: str = "Card.TLabel") -> None:
        self.status.configure(text=text, style=style)

    def _on_provider_change(self, _event=None) -> None:
        spec = PROVIDERS[self.provider_id]
        self.hint.configure(text=spec.key_hint)
        self.model_label.configure(text="Modelo (opcional). Em branco = detecção automática.")
        self.steps.configure(text="\n\n".join(f"{i}. {step}" for i, step in enumerate(spec.tutorial, 1)))
        self._invalidate()

    def _toggle_guide(self, show: bool | None = None) -> None:
        """Mostra/oculta o passo a passo para obter a chave."""
        show = (not self._guide_visible) if show is None else show
        if show == self._guide_visible:
            return
        self._guide_visible = show
        if show:
            self.guide.grid()
            self.columns.columnconfigure(0, weight=3, uniform="c")
            self.columns.columnconfigure(1, weight=2, uniform="c")
            self.help_button.configure(text="Ocultar tutorial")
        else:
            self.guide.grid_remove()
            self.columns.columnconfigure(0, weight=1, uniform="")
            self.columns.columnconfigure(1, weight=0, uniform="")
            self.help_button.configure(text="Como obter a chave?")

    def _on_key_edit(self) -> None:
        self._invalidate()

    def _invalidate(self) -> None:
        self._validated = None
        self._request_id += 1
        self.continue_button.configure(state="disabled")
        self.test_button.configure(state="normal")
        self._set_status("")

    def _open_console(self) -> None:
        self.app.click()
        webbrowser.open(PROVIDERS[self.provider_id].console_url)  # URL fixa, vinda da lista de provedores

    # ------------------------------------------------------------------ ações
    def _test(self) -> None:
        key = ai_engine.normalize_key(self.key_var.get())
        provider = self.provider_id
        problem = ai_engine.check_key_format(key)
        if problem:
            self._set_status(problem, "CardErr.TLabel")
            return
        self.app.click()
        self._request_id += 1
        request = self._request_id
        self.test_button.configure(state="disabled")
        self.continue_button.configure(state="disabled")
        self._set_status("Testando conexão...", "CardMuted.TLabel")
        self.app.run_async(
            lambda: ai_engine.validate_api_key(key, provider),
            lambda result, error: self._on_result(request, key, provider, result, error),
        )

    def _on_result(self, request: int, key: str, provider: str, result: ApiValidation | None, error: Exception | None) -> None:
        if request != self._request_id or not self.winfo_exists():
            return  # o usuário alterou a chave/provedor durante o teste
        self.test_button.configure(state="normal")
        if error is not None or result is None:
            self._set_status("Erro inesperado ao testar a chave.", "CardErr.TLabel")
            return
        if result.ok:
            self._validated = (key, provider)
            suffix = " (limite de uso momentâneo atingido)" if result.status is KeyStatus.RATE_LIMITED else ""
            self._set_status(f"✔ Chave válida{suffix}. Você já pode continuar.", "CardOk.TLabel")
            self.app.sound.play("success")
            self.continue_button.configure(state="normal")
        elif result.status in (KeyStatus.NETWORK_ERROR, KeyStatus.SERVER_ERROR):
            self._set_status(f"{result.message}\nVerifique sua conexão e tente novamente.", "CardWarn.TLabel")
        else:
            self._set_status(f"✖ {result.message}", "CardErr.TLabel")
            self.app.sound.play("error")

    def _save(self) -> None:
        if self._validated is None:
            return
        key, provider = self._validated
        if (ai_engine.normalize_key(self.key_var.get()), self.provider_id) != (key, provider):
            self._invalidate()
            return
        self.app.click()
        try:
            self.app.storage.set_api_key(key, provider)
            self.app.storage.update("ai_profile", model=ai_engine.sanitize_text(self.model_var.get(), 100))
        except (ValueError, OSError) as exc:
            self._set_status(f"Não foi possível salvar: {exc}", "CardErr.TLabel")
            return
        self.key_var.set("")          # não mantém a chave na memória da interface
        self.app.refresh_ai()
        self.app.storage.record_login()
        self.app.show_dashboard()

    def _cancel(self) -> None:
        self.app.click()
        self.app.show_dashboard()
