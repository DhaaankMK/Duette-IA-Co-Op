"""Inicialização do jogo de teste integrado (Mortal Stick Combat)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import threading

from .logger import get_logger
from .paths import test_game_dir

log = get_logger("launcher")


class LaunchError(Exception):
    """Falha ao iniciar o jogo, com mensagem apropriada para o usuário."""


def pygame_available() -> bool:
    return importlib.util.find_spec("pygame") is not None


def launch_test_game(bridge_env: dict[str, str]) -> subprocess.Popen:
    """Inicia o jogo de teste como processo separado, já apontando para a ponte do Duette.

    A chave de API nunca é repassada: o jogo recebe apenas o endereço local da ponte e o token
    da sessão.
    """
    game_dir = test_game_dir()
    entry = game_dir / "main.py"
    if not entry.is_file():
        raise LaunchError("Os arquivos do jogo de teste não foram encontrados.")
    if getattr(sys, "frozen", False):
        raise LaunchError("O jogo de teste ainda não é suportado na versão empacotada do Duette.")
    if not pygame_available():
        raise LaunchError("O jogo de teste requer o pacote 'pygame'. Instale com: pip install pygame")

    env = {k: v for k, v in os.environ.items() if not k.upper().endswith(("API_KEY", "_TOKEN", "_SECRET"))}
    env.update(bridge_env)
    from .logger import log_dir
    if log_dir() is not None:
        env["DUETTE_GAME_LOG"] = str(log_dir() / "game.log")
    log.info("Iniciando jogo de teste: %s %s (cwd=%s, ponte na porta %s)", sys.executable, entry, game_dir,
             bridge_env.get("DUETTE_BRIDGE_PORT"))
    try:
        process = subprocess.Popen([sys.executable, str(entry)], cwd=str(game_dir), env=env)
    except OSError as exc:
        log.error("Falha ao iniciar o jogo: %s", exc)
        raise LaunchError(f"Não foi possível iniciar o jogo ({type(exc).__name__}).") from exc
    log.info("Jogo iniciado (pid %d)", process.pid)

    def watch() -> None:
        code = process.wait()
        (log.info if code == 0 else log.error)("Jogo encerrado (pid %d) com código %s", process.pid, code)

    threading.Thread(target=watch, name="duette-game-watch", daemon=True).start()
    return process
