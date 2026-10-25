"""Janela principal do Duette: orquestra o fluxo de inicialização e compartilha serviços."""

from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .. import APP_NAME, APP_VERSION
from ..agent import PlayerTwoSession
from ..ai_engine import AIError, CompanionAI
from ..launcher import LaunchError, launch_test_game
from ..logger import get_logger
from ..sound import SoundManager
from ..storage import Storage, HealthResult, StartupRoute, run_startup_health_check
from . import theme
from .api_config import ApiConfigFrame
from .dashboard import DashboardFrame
from .eula import EulaFrame
from .widgets import SplashFrame


log = get_logger("ui")


class DuetteApp(tk.Tk):
    def __init__(self, storage: Storage | None = None):
        super().__init__()
        self.title(f"{APP_NAME}")
        self.geometry("1080x700")
        self.minsize(940, 620)
        theme.apply_theme(self)

        self.storage = storage or Storage()
        prefs = self.storage.snapshot()["app_preferences"]
        self.sound = SoundManager(prefs["sound_enabled"], prefs["sound_volume"],
                                  music_enabled=prefs.get("music_enabled", True))
        self.splash_min_seconds: float | None = None   # None = padrão do SplashFrame (testes usam 0)
        self.bind_class("TButton", "<Enter>", self._on_button_hover, add="+")

        self.session: PlayerTwoSession | None = None
        self.game_proc: subprocess.Popen | None = None
        self.dashboard: DashboardFrame | None = None
        self._current: tk.Misc | None = None
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._closing = False

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._pump_id = self.after(40, self._pump)
        self._start_id = self.after(20, self.start_flow)
        self._music_id = self.after(500, self.sound.start_music)

    # ------------------------------------------------------------------ infraestrutura
    @property
    def avatars_dir(self):
        return self.storage.data_dir / "avatars"

    def post(self, func: Callable[..., None], *args: Any) -> None:
        """Agenda ``func`` para rodar na thread da interface (seguro para qualquer thread)."""
        self._queue.put(lambda: func(*args))

    def _pump(self) -> None:
        try:
            while True:
                self._queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception:  # um callback com defeito não pode travar a interface
            log.exception("Erro em callback agendado da interface")
        if not self._closing:
            self._pump_id = self.after(40, self._pump)

    def run_async(self, work: Callable[[], Any], done: Callable[[Any, Exception | None], None]) -> None:
        """Executa ``work`` em outra thread e chama ``done(resultado, erro)`` na interface."""
        def runner() -> None:
            try:
                result, error = work(), None
            except Exception as exc:
                # Erros da IA já foram registrados com detalhes; os demais ganham traceback.
                log.warning("Tarefa em segundo plano falhou: %s: %s", type(exc).__name__, exc,
                            exc_info=not isinstance(exc, AIError))
                result, error = None, exc
            self.post(done, result, error)

        threading.Thread(target=runner, name="duette-worker", daemon=True).start()

    def click(self) -> None:
        self.sound.play("click")

    def _on_button_hover(self, event) -> None:
        try:
            if str(event.widget.cget("state")) != "disabled":
                self.sound.play("hover")
        except tk.TclError:
            pass

    def toggle_music(self) -> bool:
        """Liga/desliga a música ambiente e grava a preferência. Devolve o novo estado."""
        enabled = not self.sound.music_enabled
        try:
            self.storage.update("app_preferences", music_enabled=enabled)
        except OSError:
            log.warning("Não foi possível gravar a preferência de música")
        self.sound.configure(self.sound.enabled, self.sound.volume, enabled)
        if enabled:
            self.sound.start_music()
        self.sound.play("confirm")
        return enabled

    def show(self, frame: tk.Misc) -> None:
        log.debug("Tela: %s", type(frame).__name__)
        if self._current is not None:
            self._current.destroy()
        self._current = frame
        if not isinstance(frame, DashboardFrame):
            self.dashboard = None
        frame.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ fluxo de inicialização
    def report_callback_exception(self, exc, val, tb) -> None:
        """Erros dentro de eventos do tkinter (cliques, teclas) vão para o log em vez de sumirem."""
        log.critical("Exceção em evento da interface", exc_info=(exc, val, tb))

    def start_flow(self) -> None:
        if not self.storage.terms_accepted:
            self.show(EulaFrame(self, self))
            return
        self.begin_health_check()

    def begin_health_check(self) -> None:
        splash = SplashFrame(
            self,
            steps=((0.0, "Acordando a IA..."), (0.8, "Verificando sua chave de API..."),
                   (1.7, "Carregando perfil e preferências..."), (2.2, "Preparando a arena...")),
            min_seconds=self.splash_min_seconds,
        )
        self.show(splash)
        self.after(650, lambda: self.sound.play("intro"))
        self.run_async(lambda: run_startup_health_check(self.storage),
                       lambda result, error: self._after_splash(splash, result, error))

    def _after_splash(self, splash: SplashFrame, result: HealthResult | None, error: Exception | None) -> None:
        if self._closing or self._current is not splash or not splash.winfo_exists():
            return
        splash.finish(lambda: self._on_health(result, error))

    def _on_health(self, result: HealthResult | None, error: Exception | None) -> None:
        log.info("Resultado do health-check: rota=%s offline=%s", getattr(result, "route", None), getattr(result, "offline", None))
        if error is not None or result is None:
            self.show_api_config("Não foi possível verificar a chave de API. Informe-a novamente.")
            return
        if self.storage.recovery_notice:
            messagebox.showwarning(APP_NAME, self.storage.recovery_notice)
            self.storage.recovery_notice = None
        if result.route is StartupRoute.API_CONFIG:
            self.show_api_config(result.message, expired=True)
        else:
            self.storage.record_login()
            self.show_dashboard(result.message if result.offline else "")

    def show_api_config(self, notice: str = "", expired: bool = False, can_cancel: bool = False) -> None:
        self.show(ApiConfigFrame(self, self, notice=notice, expired=expired, can_cancel=can_cancel))

    def show_dashboard(self, notice: str = "") -> None:
        frame = DashboardFrame(self, self, notice=notice)
        self.show(frame)
        self.dashboard = frame

    def on_terms_accepted(self) -> None:
        self.storage.accept_terms()
        self.begin_health_check()

    def on_terms_declined(self) -> None:
        self.on_close()

    # ------------------------------------------------------------------ IA e sessão
    def build_ai(self) -> CompanionAI | None:
        key = self.storage.get_api_key()
        if not key:
            return None
        snap = self.storage.snapshot()["ai_profile"]
        provider = snap["provider"]
        try:
            return CompanionAI(
                provider, key, snap["model"], self.storage.get_profile(),
                detected_model=self.storage.get_detected_model(provider),
                on_model_resolved=lambda model: self.storage.set_detected_model(provider, model),
            )
        except AIError:
            return None

    def get_session(self) -> PlayerTwoSession:
        if self.session is None:
            self.session = PlayerTwoSession(self.build_ai(), on_event=lambda kind, data: self.post(self._on_session_event, kind, data))
        return self.session

    def refresh_ai(self) -> None:
        """Aplica mudanças de perfil/chave à sessão existente."""
        if self.session is None:
            return
        if self.session.game_connected and self.session.ai is not None:
            self.session.ai.profile = self.storage.get_profile().normalized()
            return
        self.session.stop()
        self.session = None

    def _on_session_event(self, kind: str, data: dict[str, Any]) -> None:
        if self.dashboard is not None:
            self.dashboard.on_session_event(kind, data)

    def launch_game(self, game_name: str) -> bool:
        """Inicia o jogo de teste com a IA ativa. Devolve ``True`` em caso de sucesso."""
        if self.game_proc is not None and self.game_proc.poll() is None:
            messagebox.showinfo(APP_NAME, "O jogo de teste já está aberto.")
            return False
        log.info("Usuário iniciou o jogo %r", game_name)
        session = self.get_session()
        if session.ai is None:
            log.warning("Jogo iniciado sem IA (sem chave válida): só reflexos locais")
            messagebox.showwarning(
                APP_NAME,
                "Sem uma chave de API válida a IA não conversa nem define estratégias, "
                "mas a IA ainda jogará com os reflexos locais.",
            )
        try:
            env = session.start()
            if session.ai is not None:
                session.ai.game_name = game_name
            self.game_proc = launch_test_game(env)
        except LaunchError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return False
        return True

    # ------------------------------------------------------------------ encerramento
    def on_close(self) -> None:
        if self._closing:
            return
        log.info("Encerrando o aplicativo")
        self._closing = True
        for after_id in (self._pump_id, self._start_id, self._music_id):
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        try:
            self.sound.shutdown()
            if self.session is not None:
                self.session.stop()
            if self.game_proc is not None and self.game_proc.poll() is None:
                self.game_proc.terminate()
        finally:
            self.destroy()

    @property
    def version(self) -> str:
        return APP_VERSION
