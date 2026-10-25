"""Testes do log detalhado, da redação de segredos e do diagnóstico de rede."""

from __future__ import annotations

import io
import logging
import socket
import ssl
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ai_engine, diagnostics, logger, storage  # noqa: E402

KEY = "AIzaSyD-test-0123456789abcdefghijkl"


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log_path = logger.setup_logging(self.dir, debug=False)

    def tearDown(self):
        root = logging.getLogger(logger.ROOT_NAME)
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        logger._SECRETS.clear()
        self.tmp.cleanup()

    def text(self):
        for handler in logging.getLogger(logger.ROOT_NAME).handlers:
            handler.flush()
        return self.log_path.read_text(encoding="utf-8")

    def test_log_file_created_with_expected_format(self):
        logger.get_logger("teste").info("olá %s", "mundo")
        line = self.text().strip().splitlines()[-1]
        self.assertRegex(line, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} \| INFO    \| duette\.teste +\| MainThread +\| olá mundo$")

    def test_redacts_known_key_patterns_and_registered_secrets(self):
        logger.register_secret("segredo-super-especial-123")
        log = logger.get_logger("teste")
        log.info("gemini %s", KEY)
        log.info("openai sk-proj-abcdefghijklmnop1234567890")
        log.info("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
        log.info("url https://x/y?key=%s&a=1", KEY)
        log.info("header x-api-key: sk-ant-api03-abcdefghijklmnop")
        log.info("custom segredo-super-especial-123")
        content = self.text()
        for leaked in (KEY, "sk-proj-abcdefghijklmnop", "abcdefghijklmnopqrstuvwxyz", "sk-ant-api03", "segredo-super-especial"):
            self.assertNotIn(leaked, content)
        self.assertIn("***", content)

    def test_exception_tracebacks_are_logged_and_redacted(self):
        logger.register_secret(KEY)
        try:
            raise RuntimeError(f"falhou com {KEY}")
        except RuntimeError:
            logger.get_logger("teste").exception("quebrou")
        content = self.text()
        self.assertIn("Traceback", content)
        self.assertIn("RuntimeError", content)
        self.assertNotIn(KEY, content)

    def test_read_tail_limits_lines_and_is_redacted(self):
        for i in range(50):
            logger.get_logger("teste").info("linha %d %s", i, KEY)
        tail = logger.read_tail(10)
        self.assertEqual(len(tail.splitlines()), 10)
        self.assertNotIn(KEY, tail)

    def test_reconfiguring_does_not_duplicate_handlers(self):
        logger.setup_logging(self.dir, debug=False)
        logger.setup_logging(self.dir, debug=False)
        self.assertEqual(len(logging.getLogger(logger.ROOT_NAME).handlers), 1)

    def test_thread_exceptions_reach_the_log(self):
        import threading
        previous = threading.excepthook
        logger.install_exception_hooks()
        try:
            def boom():
                raise ValueError("erro na thread")
            t = threading.Thread(target=boom, name="thread-teste")
            t.start()
            t.join()
        finally:
            threading.excepthook = previous
            sys.excepthook = sys.__excepthook__
        content = self.text()
        self.assertIn("thread-teste", content)
        self.assertIn("ValueError", content)

    # ------------------------------------------------------------ camada de rede
    def test_network_failure_is_logged_with_cause_and_user_message(self):
        error = urllib.error.URLError(socket.timeout("timed out"))
        with mock.patch.object(ai_engine._OPENER, "open", side_effect=error):
            with self.assertRaises(ai_engine.AIError) as ctx:
                ai_engine._http_json("GET", "https://generativelanguage.googleapis.com/v1beta/models", {})
        self.assertIn("Tempo esgotado", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable)
        content = self.text()
        self.assertIn("FALHA de rede", content)
        self.assertIn("generativelanguage.googleapis.com/v1beta/models", content)

    def test_http_error_logs_status_timing_and_redacted_body(self):
        body = ('{"error":{"message":"key %s invalid"}}' % KEY).encode()
        err = urllib.error.HTTPError("https://api.openai.com/v1/models", 503, "x", {}, io.BytesIO(body))
        with mock.patch.object(ai_engine._OPENER, "open", side_effect=err):
            status, payload = ai_engine._http_json("GET", "https://api.openai.com/v1/models", {"Authorization": "Bearer " + KEY})
        self.assertEqual(status, 503)
        content = self.text()
        self.assertRegex(content, r"HTTP 503 em \d+ ms")
        self.assertIn("corpo do erro", content)
        self.assertNotIn(KEY, content)

    def test_explain_network_errors(self):
        cases = {
            socket.gaierror(11001, "getaddrinfo failed"): "DNS",
            TimeoutError("x"): "Tempo esgotado",
            ssl.SSLCertVerificationError("bad cert"): "Certificado",
            ConnectionRefusedError("x"): "recusada",
            ConnectionResetError("x"): "derrubada",
        }
        for exc, expected in cases.items():
            self.assertIn(expected, ai_engine.explain_network_error(urllib.error.URLError(exc)))

    def test_full_chat_failure_leaves_a_useful_trail(self):
        ai = ai_engine.CompanionAI("gemini", KEY, model="gemini-2.5-flash")
        with mock.patch.object(ai_engine._OPENER, "open", side_effect=urllib.error.URLError(TimeoutError("t"))), \
             mock.patch.object(ai_engine.time, "sleep"):
            with self.assertRaises(ai_engine.AIError):
                ai.chat("oi")
        content = self.text()
        for expected in ("IA criada", "chat: mensagem de 2 caractere(s)", "FALHA de rede", "Sem alternativa; tentando o mesmo modelo", "Chamada ao modelo"):
            self.assertIn(expected, content)
        self.assertNotIn(KEY, content)
        self.assertNotIn("| oi", content)   # conteúdo da conversa não é gravado por padrão

    def test_chat_content_only_logged_when_opted_in(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "resposta secreta"}]}}]}
        ai = ai_engine.CompanionAI("gemini", KEY, model="gemini-2.5-flash")
        with mock.patch.object(ai_engine, "_http_json", return_value=(200, payload)):
            ai.chat("pergunta privada")
        self.assertNotIn("pergunta privada", self.text())
        with mock.patch.dict("os.environ", {"DUETTE_LOG_CONTENT": "1"}), \
             mock.patch.object(ai_engine, "_http_json", return_value=(200, payload)):
            ai.chat("pergunta liberada")
        self.assertIn("pergunta liberada", self.text())

    def test_storage_events_are_logged_without_the_key(self):
        store = storage.Storage(self.dir / "dados", use_keyring=False)
        store.accept_terms()
        store.set_api_key(KEY, "gemini")
        store.clear_api_key()
        content = self.text()
        for expected in ("Abrindo armazenamento", "primeira execução", "Termos de licença aceitos", "Chave de API salva", "Chave de API removida"):
            self.assertIn(expected, content)
        self.assertNotIn(KEY, content)

    # ------------------------------------------------------------ diagnóstico
    def test_probe_stops_at_dns_failure_with_hint(self):
        with mock.patch.object(diagnostics.socket, "getaddrinfo", side_effect=socket.gaierror(11001, "getaddrinfo failed")):
            steps = diagnostics.network_probe("gemini", KEY)
        self.assertEqual([s.name for s in steps], ["DNS"])
        self.assertFalse(steps[0].ok)
        self.assertIn("DNS", steps[0].detail)

    def test_probe_reports_tcp_timeout(self):
        fake_info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.0.1", 443))]
        with mock.patch.object(diagnostics.socket, "getaddrinfo", return_value=fake_info), \
             mock.patch.object(diagnostics.socket, "create_connection", side_effect=socket.timeout("timed out")):
            steps = diagnostics.network_probe("gemini", KEY)
        self.assertEqual([s.ok for s in steps], [True, False])
        self.assertIn("Tempo esgotado", steps[1].detail)

    def test_probe_full_success_path(self):
        fake_info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.0.1", 443))]
        tls = mock.MagicMock()
        tls.__enter__.return_value = tls
        tls.version.return_value = "TLSv1.3"
        tls.getpeercert.return_value = {"issuer": ((("organizationName", "Google Trust Services"),),)}
        context = mock.MagicMock()
        context.wrap_socket.return_value = tls
        valid = ai_engine.ApiValidation(ai_engine.KeyStatus.VALID, "Chave válida.", 200)
        with mock.patch.object(diagnostics.socket, "getaddrinfo", return_value=fake_info), \
             mock.patch.object(diagnostics.socket, "create_connection", return_value=mock.MagicMock()), \
             mock.patch.object(diagnostics.ssl, "create_default_context", return_value=context), \
             mock.patch.object(diagnostics, "validate_api_key", return_value=valid):
            steps = diagnostics.network_probe("gemini", KEY)
        self.assertTrue(all(s.ok for s in steps), [s.line() for s in steps])
        self.assertEqual(len(steps), 4)
        self.assertIn("Google Trust Services", steps[2].detail)

    def test_report_has_environment_and_never_the_key(self):
        store = storage.Storage(self.dir / "dados", use_keyring=False)
        store.set_api_key(KEY, "gemini")
        logger.get_logger("teste").info("algo com %s", KEY)
        steps = [diagnostics.ProbeStep("DNS", True, "ok", 12), diagnostics.ProbeStep("TCP", False, "Tempo esgotado", 10000)]
        report = diagnostics.build_report(store, steps)
        for expected in ("relatório de diagnóstico", "Provedor: gemini", "Teste de rede", "[FALHA] TCP", "Últimas"):
            self.assertIn(expected, report)
        self.assertNotIn(KEY, report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
