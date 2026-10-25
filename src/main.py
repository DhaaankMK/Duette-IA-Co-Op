"""Ponto de entrada do Duette.

Fluxo: EULA (primeira vez) ➜ health-check da chave de API ➜ Dashboard (ou tela de API).
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print(
            "O Duette precisa do tkinter, que não está instalado neste Python.\n"
            "  Windows/macOS: reinstale o Python marcando a opção 'tcl/tk'.\n"
            "  Linux (Debian/Ubuntu): sudo apt install python3-tk",
            file=sys.stderr,
        )
        return 1

    from . import APP_VERSION
    from .logger import get_logger, install_exception_hooks, log_startup_banner, setup_logging
    from .paths import user_data_dir

    data_dir = user_data_dir()
    log_path = setup_logging(data_dir, debug="--debug" in sys.argv)
    install_exception_hooks()
    log_startup_banner(APP_VERSION, data_dir)
    print(f"[Duette] log detalhado em: {log_path}")

    from .ui.app import DuetteApp

    try:
        app = DuetteApp()
        app.mainloop()
    except Exception:
        get_logger("app").critical("Erro fatal na interface", exc_info=True)
        raise
    get_logger("app").info("Duette encerrado normalmente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
