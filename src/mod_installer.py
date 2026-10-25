"""Gerenciador e instalador de mods do Duette.

Fluxo: catálogo de jogos (``mods_bundle/games.json``) ➜ localizar a pasta do jogo ➜ verificar
dependências ➜ instalar o pacote embutido (``.zip``) com barra de progresso.

Segurança da instalação:
  * Integridade: o SHA-256 do pacote é conferido contra o catálogo antes de extrair.
  * Extração segura: bloqueia caminhos absolutos, ``..`` (zip-slip), links simbólicos, arquivos
    gigantes, taxas de compressão suspeitas (zip-bomb) e excesso de arquivos.
  * Reversível: arquivos sobrescritos são salvos em ``.duette_backup`` e restaurados se algo
    falhar; um registro ``.duette_install.json`` permite desinstalar.
  * Nunca escreve fora da pasta do jogo escolhida.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from .logger import get_logger
from .paths import mods_bundle_dir

log = get_logger("mods")

CATALOG_NAME = "games.json"
RECEIPT_NAME = ".duette_install.json"
BACKUP_DIR = ".duette_backup"

MAX_FILES = 5000
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_FILE_BYTES = 300 * 1024 * 1024
MAX_RATIO = 200

ProgressCallback = Callable[[float, str], None]


class InstallError(Exception):
    """Falha de instalação com mensagem apropriada para o usuário."""


class InstallCancelled(InstallError):
    pass


@dataclass(frozen=True)
class GameEntry:
    id: str
    name: str
    description: str
    kind: str                       # "builtin" (não precisa de mods) ou "mod"
    executable: str = ""
    steam_app_folder: str = ""      # nome da pasta em steamapps/common
    required_files: tuple[str, ...] = ()
    bundle: str | None = None       # nome do .zip dentro de mods_bundle
    bundle_sha256: str | None = None


@dataclass
class InstallStatus:
    game_dir: Path | None
    missing: list[str] = field(default_factory=list)
    bundle_available: bool = False

    @property
    def installed(self) -> bool:
        return self.game_dir is not None and not self.missing


# ======================================================================================
# Catálogo
# ======================================================================================

_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def _safe_relative(path_text: str) -> bool:
    if not path_text or "\\" in path_text or "\x00" in path_text:
        return False
    posix = PurePosixPath(path_text)
    return not posix.is_absolute() and ".." not in posix.parts and not re.match(r"^[A-Za-z]:", path_text)


def load_catalog(directory: Path | None = None) -> list[GameEntry]:
    """Lê o catálogo de jogos. Entradas inválidas são ignoradas (nunca derrubam o app)."""
    path = (directory or mods_bundle_dir()) / CATALOG_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries: list[GameEntry] = []
    for item in raw.get("games", []) if isinstance(raw, dict) else []:
        try:
            game_id = str(item["id"])
            if not _ID_RE.match(game_id):
                continue
            required = tuple(str(f) for f in item.get("required_files", []))
            if not all(_safe_relative(f) for f in required):
                continue
            bundle = item.get("bundle")
            if bundle is not None and (not isinstance(bundle, str) or not re.match(r"^[\w.\- ]+\.zip$", bundle)):
                continue
            sha = item.get("bundle_sha256")
            entries.append(
                GameEntry(
                    id=game_id,
                    name=str(item["name"])[:80],
                    description=str(item.get("description", ""))[:300],
                    kind="builtin" if item.get("kind") == "builtin" else "mod",
                    executable=str(item.get("executable", ""))[:120],
                    steam_app_folder=str(item.get("steam_app_folder", ""))[:120],
                    required_files=required,
                    bundle=bundle,
                    bundle_sha256=sha.lower() if isinstance(sha, str) else None,
                )
            )
        except (KeyError, TypeError):
            continue
    return entries


# ======================================================================================
# Localização do jogo
# ======================================================================================

def _steam_roots() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = []
    if sys.platform == "win32":
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "Steam")
    elif sys.platform == "darwin":
        candidates.append(home / "Library" / "Application Support" / "Steam")
    else:
        candidates += [home / ".steam" / "steam", home / ".local" / "share" / "Steam"]

    roots = [c for c in candidates if c.is_dir()]
    for root in list(roots):
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', text):
            library = Path(match.group(1).replace("\\\\", "\\"))
            if library.is_dir() and library not in roots:
                roots.append(library)
    return roots


def is_valid_game_dir(entry: GameEntry, directory: Path) -> bool:
    return bool(entry.executable) and directory.is_dir() and (directory / entry.executable).is_file()


def find_game_dir(entry: GameEntry, hint: str | None = None) -> Path | None:
    """Procura a pasta do jogo: primeiro o caminho salvo, depois as bibliotecas do Steam."""
    if hint:
        candidate = Path(hint)
        if is_valid_game_dir(entry, candidate):
            return candidate
    if entry.steam_app_folder:
        for root in _steam_roots():
            candidate = root / "steamapps" / "common" / entry.steam_app_folder
            if is_valid_game_dir(entry, candidate):
                return candidate
    return None


def check_installation(entry: GameEntry, game_dir: Path | None, bundles: Path | None = None) -> InstallStatus:
    bundle_ok = bool(entry.bundle) and (((bundles or mods_bundle_dir()) / (entry.bundle or "")).is_file())
    if entry.kind == "builtin":
        return InstallStatus(game_dir=game_dir or Path("."), missing=[], bundle_available=True)
    if game_dir is None:
        return InstallStatus(None, list(entry.required_files), bundle_ok)
    missing = [rel for rel in entry.required_files if not (game_dir / rel).exists()]
    return InstallStatus(game_dir, missing, bundle_ok)


# ======================================================================================
# Instalação
# ======================================================================================

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > MAX_FILES:
        raise InstallError("O pacote de mods contém arquivos demais e foi recusado.")
    total = 0
    result: list[zipfile.ZipInfo] = []
    for info in members:
        name = info.filename
        if not _safe_relative(name.rstrip("/")):
            raise InstallError("O pacote contém um caminho inseguro e foi recusado.")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise InstallError("O pacote contém links simbólicos e foi recusado.")
        if info.is_dir():
            continue
        if info.file_size > MAX_FILE_BYTES:
            raise InstallError("O pacote contém um arquivo grande demais e foi recusado.")
        if info.compress_size > 0 and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 10 * 1024 * 1024:
            raise InstallError("O pacote tem uma taxa de compressão suspeita e foi recusado.")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise InstallError("O pacote descompactado excede o tamanho máximo permitido.")
        result.append(info)
    return result


def install(
    entry: GameEntry,
    game_dir: Path,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    bundles: Path | None = None,
) -> list[str]:
    """Instala o pacote do jogo. Devolve a lista de arquivos instalados (relativos)."""
    report = progress or (lambda fraction, message: None)
    log.info("Instalação solicitada: jogo=%s pasta=%s pacote=%s", entry.id, game_dir, entry.bundle)
    if entry.kind == "builtin":
        return []
    if not is_valid_game_dir(entry, game_dir):
        raise InstallError("A pasta selecionada não parece ser a do jogo (executável não encontrado).")
    if not entry.bundle:
        raise InstallError("O pacote de mods deste jogo ainda não está disponível nesta versão do Duette.")
    bundle_path = (bundles or mods_bundle_dir()) / entry.bundle
    if not bundle_path.is_file():
        raise InstallError("O pacote de mods embutido não foi encontrado.")

    report(0.02, "Verificando integridade do pacote...")
    if not entry.bundle_sha256:
        raise InstallError("O catálogo não informa o SHA-256 do pacote; instalação recusada por segurança.")
    if sha256_file(bundle_path) != entry.bundle_sha256:
        raise InstallError("O pacote de mods está corrompido ou foi alterado (SHA-256 não confere).")

    root = game_dir.resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = root / BACKUP_DIR / stamp
    created: list[Path] = []
    backed_up: list[tuple[Path, Path]] = []   # (destino original, cópia no backup)
    installed: list[str] = []

    try:
        with zipfile.ZipFile(bundle_path) as archive:
            members = _validated_members(archive)
            total = max(1, sum(m.file_size for m in members))
            done = 0
            for info in members:
                if cancel is not None and cancel.is_set():
                    raise InstallCancelled("Instalação cancelada.")
                relative = PurePosixPath(info.filename)
                target = (root / Path(*relative.parts)).resolve()
                if root not in target.parents:
                    raise InstallError("Caminho de destino fora da pasta do jogo; instalação interrompida.")
                report(0.05 + 0.9 * done / total, f"Instalando {relative.name}...")

                if target.exists():
                    if target.is_dir():
                        raise InstallError(f"Conflito: {relative} é uma pasta no jogo.")
                    backup = backup_root / Path(*relative.parts)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                    backed_up.append((target, backup))
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)

                temp = target.with_name(target.name + ".duette_tmp")
                with archive.open(info) as source, temp.open("wb") as out:
                    shutil.copyfileobj(source, out, 1024 * 1024)
                os.replace(temp, target)
                if all(target != original for original, _ in backed_up):
                    created.append(target)
                installed.append(relative.as_posix())
                done += info.file_size

        receipt = {"game": entry.id, "installed_at": stamp, "files": installed}
        (root / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        log.info("Instalação concluída: %d arquivo(s), backup em %s", len(installed), backup_root)
        report(1.0, "Instalação concluída.")
        return installed
    except BaseException as exc:
        log.error("Instalação falhou (%s: %s). Desfazendo %d criado(s) e %d sobrescrito(s)",
                  type(exc).__name__, exc, len(created), len(backed_up))
        _rollback(created, backed_up)
        if isinstance(exc, (InstallError, KeyboardInterrupt)):
            raise
        if isinstance(exc, (OSError, zipfile.BadZipFile)):
            raise InstallError(f"Falha durante a instalação: {type(exc).__name__}. Nenhuma alteração foi mantida.") from exc
        raise


def _rollback(created: list[Path], backed_up: list[tuple[Path, Path]]) -> None:
    for path in created:
        try:
            path.unlink()
        except OSError:
            pass
    for original, backup in backed_up:
        try:
            shutil.copy2(backup, original)
        except OSError:
            pass


def uninstall(game_dir: Path) -> int:
    """Remove os arquivos instalados pelo Duette (conforme o recibo). Devolve a quantidade."""
    root = game_dir.resolve()
    receipt_path = root / RECEIPT_NAME
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        files = receipt["files"]
    except (OSError, ValueError, KeyError, TypeError):
        raise InstallError("Nenhuma instalação do Duette foi encontrada nesta pasta.") from None

    log.info("Desinstalação: %d arquivo(s) no recibo (%s)", len(files), root)
    removed = 0
    for relative in files:
        if not isinstance(relative, str) or not _safe_relative(relative):
            continue
        target = (root / Path(*PurePosixPath(relative).parts)).resolve()
        if root in target.parents and target.is_file():
            try:
                target.unlink()
                removed += 1
            except OSError:
                pass
    try:
        receipt_path.unlink()
    except OSError:
        pass
    return removed
