"""Janela de logs e diagnóstico (ver, copiar, testar a rede e abrir a pasta de logs)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .. import diagnostics
from ..ai_engine import PROVIDERS
from ..logger import get_logger, log_dir, read_tail
from . import theme

log = get_logger("ui")


class LogWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, app):
        super().__init__(parent)
        self.app = app
        self.title("Logs e diagnóstico")
        self.geometry("1020x660")
        self.configure(background=theme.BG)

        bar = ttk.Frame(self, padding=(12, 12, 12, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text="Atualizar", command=self.refresh).pack(side="left")
        self.probe_button = ttk.Button(bar, text="Diagnóstico de rede", style="Accent.TButton", command=self.run_probe)
        self.probe_button.pack(side="left", padx=8)
        ttk.Button(bar, text="Copiar tudo", command=self.copy_all).pack(side="left")
        ttk.Button(bar, text="Abrir pasta de logs", command=self.open_folder).pack(side="left", padx=8)
        self.status = ttk.Label(bar, text="", style="Muted.TLabel")
        self.status.pack(side="right")

        holder = ttk.Frame(self, padding=(12, 0, 12, 12))
        holder.pack(fill="both", expand=True)
        self.text = tk.Text(holder, state="disabled", wrap="none")
        theme.style_text(self.text, background=theme.CARD)
        self.text.configure(font=theme.FONT_MONO, wrap="none")
        self.text.tag_configure("err", foreground=theme.ERR)
        self.text.tag_configure("warn", foreground=theme.WARN)
        self.text.tag_configure("ok", foreground=theme.OK)
        self.text.tag_configure("head", foreground=theme.ACCENT_HOVER)
        y = ttk.Scrollbar(holder, orient="vertical", command=self.text.yview)
        x = ttk.Scrollbar(holder, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        y.pack(side="right", fill="y")
        x.pack(side="bottom", fill="x")
        self.text.pack(side="left", fill="both", expand=True)

        self.refresh()

    # ------------------------------------------------------------------ conteúdo
    def _show(self, content: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for line in content.splitlines():
            tag = ""
            if "| CRITICAL" in line or "| ERROR" in line or "[FALHA]" in line:
                tag = "err"
            elif "| WARNING" in line:
                tag = "warn"
            elif "[OK  ]" in line:
                tag = "ok"
            elif line.startswith("==") or line.startswith("--"):
                tag = "head"
            self.text.insert("end", line + "\n", tag)
        self.text.configure(state="disabled")
        self.text.see("end")

    def refresh(self) -> None:
        self._show(read_tail(600))
        self.status.configure(text="Mostrando as últimas linhas do log")

    # ------------------------------------------------------------------ ações
    def run_probe(self) -> None:
        provider = self.app.storage.get("ai_profile", "provider")
        key = self.app.storage.get_api_key()
        log.info("Diagnóstico de rede solicitado pelo usuário (provedor=%s)", provider)
        self.probe_button.configure(state="disabled")
        self.status.configure(text=f"Testando o caminho até {PROVIDERS[provider].host}...")
        self.app.run_async(lambda: diagnostics.network_probe(provider, key), self._on_probe)

    def _on_probe(self, steps: Any, error: Exception | None) -> None:
        if not self.winfo_exists():
            return
        self.probe_button.configure(state="normal")
        if error is not None:
            log.error("Diagnóstico de rede falhou", exc_info=error)
            self.status.configure(text="O diagnóstico falhou; veja o log")
            return
        self._show(diagnostics.build_report(self.app.storage, steps))
        self.text.see("1.0")
        failed = [s for s in steps if not s.ok]
        self.status.configure(text="Falha em: " + failed[0].name if failed else "Tudo certo até a API")

    def copy_all(self) -> None:
        content = self.text.get("1.0", "end-1c")
        if not any(line.startswith("==") for line in content.splitlines()[:3]):
            content = diagnostics.build_report(self.app.storage)   # junta ambiente + log, sempre sem chaves
        self.clipboard_clear()
        self.clipboard_append(content)
        self.status.configure(text="Copiado para a área de transferência (sem chaves de API)")

    def open_folder(self) -> None:
        folder = log_dir()
        if folder is None:
            messagebox.showinfo("Duette", "O log ainda não foi iniciado.", parent=self)
            return
        try:
            diagnostics.open_in_file_manager(folder)
        except Exception as exc:
            messagebox.showerror("Duette", f"Não foi possível abrir a pasta:\n{folder}\n\n{exc}", parent=self)
