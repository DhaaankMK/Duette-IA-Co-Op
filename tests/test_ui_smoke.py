"""Teste de fumaça da interface: percorre o fluxo completo com rede simulada.

Requer tkinter e um display (no Linux sem tela: ``xvfb-run python -m unittest tests.test_ui_smoke``).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import tkinter
    HAVE_TK = True
except ImportError:
    HAVE_TK = False

SCREENSHOT_DIR = os.environ.get("DUETTE_SCREENSHOT_DIR")
KEY = "sk-ant-test-0123456789abcdef"


def pump(app, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def wait_for(app, predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def shot(app, name):
    if not SCREENSHOT_DIR:
        return
    try:
        from PIL import ImageGrab
        app.update()
        x, y, w, h = app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ.get("DISPLAY")).save(
            Path(SCREENSHOT_DIR) / f"{name}.png")
    except Exception as exc:  # captura é opcional
        print("screenshot falhou:", exc)


@unittest.skipUnless(HAVE_TK and os.environ.get("DISPLAY"), "requer tkinter e um display")
class UiFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DUETTE_DATA_DIR"] = self.tmp.name
        from src import ai_engine, storage
        from src.ui.app import DuetteApp
        self.ai_engine, self.storage_mod = ai_engine, storage
        from src import logger
        logger.setup_logging(Path(self.tmp.name), debug=False)
        self.store = storage.Storage(Path(self.tmp.name), use_keyring=False)
        self.app = DuetteApp(self.store)
        self.app.geometry("1080x700+0+0")
        self.app.splash_min_seconds = 0   # sem espera artificial da tela de carregamento
        pump(self.app, 0.15)   # deixa o fluxo inicial (EULA) terminar antes de cada teste

    def tearDown(self):
        self.app.on_close()
        self.tmp.cleanup()
        os.environ.pop("DUETTE_DATA_DIR", None)

    def test_full_flow(self):
        from src.ui.api_config import ApiConfigFrame
        from src.ui.dashboard import DashboardFrame
        from src.ui.eula import EulaFrame

        # 1) EULA bloqueia até ler e aceitar
        pump(self.app)
        eula = self.app._current
        self.assertIsInstance(eula, EulaFrame)
        self.assertTrue(eula.has_license)
        self.assertEqual(str(eula.accept_button["state"]), "disabled")
        shot(self.app, "1_eula")
        eula.accepted.set(True)
        eula._refresh()
        self.assertEqual(str(eula.accept_button["state"]), "disabled", "não deve aceitar sem rolar até o fim")
        eula.text.yview_moveto(1.0)
        pump(self.app, 0.2)
        eula._check_scroll_needed()
        self.assertEqual(str(eula.check["state"]), "normal")
        eula.accepted.set(True)
        eula._refresh()
        self.assertEqual(str(eula.accept_button["state"]), "normal")
        shot(self.app, "2_eula_pronta")

        # 2) aceite persiste; sem chave -> tela de API
        eula._accept()
        self.assertTrue(wait_for(self.app, lambda: isinstance(self.app._current, ApiConfigFrame)))
        self.assertTrue(self.store.terms_accepted)
        api = self.app._current
        shot(self.app, "3_api_config")

        # 3) chave recusada não libera o app
        bad = self.ai_engine.ApiValidation(self.ai_engine.KeyStatus.INVALID, "O provedor recusou a chave.", 401)
        with mock.patch.object(self.ai_engine, "validate_api_key", return_value=bad):
            api.key_var.set(KEY)
            api._test()
            self.assertTrue(wait_for(self.app, lambda: "recusou" in api.status["text"]))
        self.assertEqual(str(api.continue_button["state"]), "disabled")
        shot(self.app, "4_api_invalida")

        # 4) chave válida libera o dashboard
        good = self.ai_engine.ApiValidation(self.ai_engine.KeyStatus.VALID, "Chave válida.", 200)
        with mock.patch.object(self.ai_engine, "validate_api_key", return_value=good):
            api.key_var.set(KEY + "x")
            api._test()
            self.assertTrue(wait_for(self.app, lambda: str(api.continue_button["state"]) == "normal"))
            shot(self.app, "5_api_valida")
            api._save()
        self.assertIsInstance(self.app._current, DashboardFrame)
        self.assertEqual(self.store.get_api_key(), KEY + "x")
        dash = self.app._current
        pump(self.app)
        shot(self.app, "6_dashboard_jogos")

        # 5) perfil
        dash.show_page("profile")
        page = dash.pages["profile"]
        page.name_var.set("Khyros")
        page.personality.set("custom")
        page._on_personality()
        page.custom.insert("1.0", "Aja como um herói sarcástico.")
        page._save()
        self.assertEqual(self.store.get("ai_profile", "bot_name"), "Khyros")
        self.assertEqual(self.store.get("ai_profile", "personality"), "custom")
        self.assertEqual(dash.name_label["text"], "Khyros")
        pump(self.app)
        shot(self.app, "7_perfil")

        # 6) chat com IA simulada
        dash.show_page("chat")
        chat = dash.pages["chat"]
        payload = {"content": [{"type": "text", "text": "Meu nome é Khyros, parceiro!"}]}
        with mock.patch.object(self.ai_engine, "_http_json", return_value=(200, payload)) as http:
            chat.var.set("Qual é o seu nome?")
            chat._send()
            self.assertTrue(wait_for(self.app, lambda: "Khyros, parceiro" in chat.log.get("1.0", "end")))
            sent_system = http.call_args.args[3]["system"]
            self.assertIn("Khyros", sent_system)
            self.assertIn("herói sarcástico", sent_system)
        shot(self.app, "8_chat")

        # 7) configurações não exibem a chave completa
        dash.show_page("settings")
        pump(self.app)
        info = dash.pages["settings"].ai_info["text"]
        self.assertNotIn(KEY + "x", info)
        shot(self.app, "9_configuracoes")

        # 8) janela de logs e diagnóstico
        from unittest import mock as _mock
        from src import diagnostics
        from src.ui.log_window import LogWindow
        window = LogWindow(self.app, self.app)
        pump(self.app, 0.2)
        content = window.text.get("1.0", "end")
        self.assertIn("Duette", content + "Duette")
        self.assertNotIn(KEY + "x", content)
        steps = [diagnostics.ProbeStep("DNS", True, "ok", 5), diagnostics.ProbeStep("Conexão TCP (porta 443)", False, "Tempo esgotado", 10000)]
        with _mock.patch.object(diagnostics, "network_probe", return_value=steps):
            window.run_probe()
            self.assertTrue(wait_for(self.app, lambda: "Teste de rede" in window.text.get("1.0", "end")))
        self.assertIn("Falha em: Conexão TCP", window.status["text"])
        report = window.text.get("1.0", "end")
        self.assertNotIn(KEY + "x", report)
        shot(self.app, "11_logs_diagnostico")
        window.copy_all()
        self.assertIn("relatório de diagnóstico", window.clipboard_get())
        window.destroy()

    def test_expired_key_routes_to_api_screen(self):
        from src.ui.api_config import ApiConfigFrame
        self.store.accept_terms()
        self.store.set_api_key(KEY)
        invalid = self.ai_engine.ApiValidation(self.ai_engine.KeyStatus.INVALID, "recusada", 401)
        with mock.patch.object(self.storage_mod, "validate_api_key", return_value=invalid):
            self.app.begin_health_check()
            self.assertTrue(wait_for(self.app, lambda: isinstance(self.app._current, ApiConfigFrame)))
        self.assertFalse(self.store.has_api_key())
        self.assertIn("expirou", self.app._current.winfo_children()[2].winfo_children()[0]["text"])
        shot(self.app, "10_chave_expirada")

    def test_valid_key_skips_straight_to_dashboard_and_eula_not_shown_again(self):
        from src.ui.dashboard import DashboardFrame
        self.store.accept_terms()
        self.store.set_api_key(KEY)
        ok = self.ai_engine.ApiValidation(self.ai_engine.KeyStatus.VALID, "ok", 200)
        with mock.patch.object(self.storage_mod, "validate_api_key", return_value=ok):
            self.app.start_flow()
            self.assertTrue(wait_for(self.app, lambda: isinstance(self.app._current, DashboardFrame)))

    def test_offline_opens_dashboard_with_notice(self):
        from src.ui.dashboard import DashboardFrame
        self.store.accept_terms()
        self.store.set_api_key(KEY)
        net = self.ai_engine.ApiValidation(self.ai_engine.KeyStatus.NETWORK_ERROR, "Sem conexão.")
        with mock.patch.object(self.storage_mod, "validate_api_key", return_value=net):
            self.app.start_flow()
            self.assertTrue(wait_for(self.app, lambda: isinstance(self.app._current, DashboardFrame)))
        self.assertTrue(self.store.has_api_key())
        self.assertTrue(self.app.dashboard.offline)


if __name__ == "__main__":
    unittest.main(verbosity=2)
