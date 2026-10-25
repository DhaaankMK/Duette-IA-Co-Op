"""Resolução centralizada de caminhos do Duette.

- ``resource_root()``: pasta com os recursos empacotados (somente leitura).
- ``user_data_dir()``: pasta de dados do usuário (configuração, avatares, logs).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def resource_root() -> Path:
    """Raiz dos recursos do aplicativo (funciona também empacotado com PyInstaller)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def ensure_private_dir(path: Path) -> Path:
    """Cria o diretório (se necessário) e restringe o acesso ao usuário atual em POSIX."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def user_data_dir() -> Path:
    """Diretório de dados persistentes do usuário.

    Pode ser sobrescrito pela variável de ambiente ``DUETTE_DATA_DIR`` (útil em testes).
    """
    override = os.environ.get("DUETTE_DATA_DIR")
    if override:
        base = Path(override).expanduser()
    elif sys.platform == "win32":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(root) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(root) / APP_NAME.lower()
    return ensure_private_dir(base)


def assets_dir() -> Path:
    return resource_root() / "assets"


def mods_bundle_dir() -> Path:
    return resource_root() / "mods_bundle"


def test_game_dir() -> Path:
    return resource_root() / "teste_game"


def license_path() -> Path:
    return resource_root() / "LICENSE.txt"
