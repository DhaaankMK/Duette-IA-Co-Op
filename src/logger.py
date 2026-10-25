"""Registro (log) detalhado do Duette.

* Arquivo rotativo em ``<dados do usuário>/logs/duette.log`` (1 MB x 5 arquivos), sempre em nível DEBUG.
* Console somente com ``DUETTE_DEBUG=1`` (ou ``python Run.py --debug``).
* Privacidade: chaves de API são mascaradas automaticamente (padrões conhecidos + segredos registrados),
  e o conteúdo das conversas NÃO é gravado, apenas tamanhos. Para depurar o conteúdo, defina
  ``DUETTE_LOG_CONTENT=1``.
* Exceções não tratadas (threads, interface e processo) são sempre gravadas com traceback.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import re
import sys
import threading
from pathlib import Path

ROOT_NAME = "duette"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5

_SECRETS: set[str] = set()
_secrets_lock = threading.Lock()
_log_dir: Path | None = None

_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bAQ\.[0-9A-Za-z_\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)((?:x-api-key|x-goog-api-key|authorization)['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]{8,}"),
    re.compile(r"(?i)([?&]key=)[^&\s]{8,}"),
)


def register_secret(secret: str | None) -> None:
    """Garante que ``secret`` seja sempre mascarado nos logs (ex.: a chave de API em uso)."""
    if secret and len(secret) >= 8:
        with _secrets_lock:
            _SECRETS.add(secret)


def redact(text: str) -> str:
    with _secrets_lock:
        secrets = sorted(_SECRETS, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, "***")
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + "***", text)
        else:
            text = pattern.sub("***", text)
    return text


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def log_content_enabled() -> bool:
    return os.environ.get("DUETTE_LOG_CONTENT") == "1"


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_NAME}.{name}")


def log_dir() -> Path | None:
    return _log_dir


def log_file() -> Path | None:
    return _log_dir / "duette.log" if _log_dir else None


def setup_logging(data_dir: Path, debug: bool | None = None) -> Path:
    """Configura (ou reconfigura) o log. Devolve o caminho do arquivo."""
    global _log_dir
    _log_dir = Path(data_dir) / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger(ROOT_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = _RedactingFormatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)-16s | %(threadName)-14s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_file(), maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    if debug is None:
        debug = os.environ.get("DUETTE_DEBUG") == "1"
    if debug:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.setLevel(logging.DEBUG)
        root.addHandler(console)
    return log_file()  # type: ignore[return-value]


def read_tail(lines: int = 400) -> str:
    """Últimas ``lines`` linhas do log atual (já mascaradas)."""
    path = log_file()
    if path is None or not path.is_file():
        return "(nenhum log ainda)"
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 400_000))
            data = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"(não foi possível ler o log: {exc})"
    return redact("\n".join(data.splitlines()[-lines:]))


def install_exception_hooks() -> None:
    """Registra no log qualquer exceção não tratada (processo e threads)."""
    log = get_logger("crash")

    def process_hook(exc_type, exc, tb):
        log.critical("Exceção não tratada", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def thread_hook(args):
        log.critical("Exceção não tratada na thread %s", getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = process_hook
    threading.excepthook = thread_hook


def log_startup_banner(app_version: str, data_dir: Path) -> None:
    log = get_logger("app")
    log.info("=" * 70)
    log.info("Duette %s iniciando", app_version)
    log.info("Python %s | %s | %s", platform.python_version(), platform.platform(), platform.machine())
    log.info("Dados: %s | Log: %s", data_dir, log_file())
    for name in ("PIL", "pygame", "keyring"):
        try:
            module = __import__(name)
            log.info("Dependência opcional %-8s presente (versão %s)", name, getattr(module, "__version__", "?"))
        except Exception:
            log.info("Dependência opcional %-8s ausente", name)
    try:
        import tkinter
        log.info("tkinter %s", tkinter.TkVersion)
    except Exception as exc:
        log.error("tkinter indisponível: %s", exc)
    proxies = [k for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY") if os.environ.get(k)]
    log.info("Proxy configurado por variável de ambiente: %s", ", ".join(proxies) if proxies else "nenhum")
