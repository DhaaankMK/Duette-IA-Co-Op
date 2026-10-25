"""Conversa de texto com a IA."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from ..ai_engine import AIError
from . import theme


class ChatPage(ttk.Frame):
    def __init__(self, parent: tk.Misc, app, dashboard):
        super().__init__(parent)
        self.app, self.dashboard = app, dashboard
        self._waiting = False

        ttk.Label(self, text="Conversa", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Converse com a sua IA. Durante uma partida, as respostas também aparecem no jogo.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 16))

        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True)
        self.log = tk.Text(holder, state="disabled")
        theme.style_text(self.log)
        self.log.tag_configure("me", foreground=theme.ACCENT_HOVER, spacing1=8, font=theme.FONT_BOLD)
        self.log.tag_configure("bot", foreground=theme.TEXT, spacing1=8)
        self.log.tag_configure("info", foreground=theme.MUTED, font=theme.FONT_SMALL, spacing1=6)
        self.log.tag_configure("err", foreground=theme.ERR, spacing1=6)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        row = ttk.Frame(self)
        row.pack(fill="x", pady=(12, 0))
        self.var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.var)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self._send())
        self.send_button = ttk.Button(row, text="Enviar", style="Accent.TButton", command=self._send)
        self.send_button.pack(side="left", padx=(10, 0))

        self._append("Dica: a IA só responde se houver uma chave de API válida configurada.", "info")

    # ------------------------------------------------------------------ utilidades
    def _bot_name(self) -> str:
        return self.app.storage.snapshot()["ai_profile"]["bot_name"]

    def _append(self, text: str, tag: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.configure(state="disabled")
        self.log.see("end")

    def on_show(self) -> None:
        self.entry.focus_set()

    # ------------------------------------------------------------------ envio
    def _send(self) -> None:
        text = self.var.get().strip()
        if not text or self._waiting:
            return
        if not self.app.storage.has_api_key():
            self._append("Configure uma chave de API em Configurações para conversar.", "err")
            return
        session = self.app.get_session()
        if session.ai is None:
            self._append("A IA não está disponível. Verifique a chave de API em Configurações.", "err")
            return
        self.app.click()
        self.var.set("")
        self._append(f"Você: {text}", "me")
        self._waiting = True
        self.send_button.configure(state="disabled")
        self._model_before = session.ai.model
        self._append("A IA está pensando...", "info")
        self.app.run_async(lambda: session.chat(text), self._on_reply)

    def _on_reply(self, reply: str | None, error: Exception | None) -> None:
        self._waiting = False
        if not self.winfo_exists():
            return
        self.send_button.configure(state="normal")
        if error is not None:
            self.app.sound.play("error")
        elif reply:
            self.app.sound.play("notify")
        if isinstance(error, AIError):
            self._append(f"{error}\nDetalhes técnicos em Configurações > Logs e diagnóstico.", "err")
        elif error is not None:
            self._append(f"Erro inesperado ({type(error).__name__}).", "err")
        elif reply:
            self._append(f"{self._bot_name()}: {reply}", "bot")
        session = self.app.session
        if session is not None and session.ai is not None and getattr(self, "_model_before", None) not in (None, session.ai.model):
            self._append(f"Modelo trocado automaticamente: {self._model_before} → {session.ai.model} "
                         "(o anterior estava indisponível ou sobrecarregado).", "info")
        self.entry.focus_set()

    # ------------------------------------------------------------------ eventos do jogo
    def on_session_event(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "connected":
            self._append(f"🎮 Jogo conectado: {data.get('game', 'jogo')}.", "info")
        elif kind == "disconnected":
            self._append("🎮 Jogo desconectado.", "info")
        elif kind == "say":
            self._append(f"{self._bot_name()} (no jogo): {data.get('text', '')}", "bot")
        elif kind == "ai_error":
            self._append(f"Falha da IA durante a partida: {data.get('message', '')}\n"
                         "Detalhes técnicos em Configurações > Logs e diagnóstico.", "err")
