"""Testes automatizados dos módulos centrais do Duette (sem rede real, sem interface)."""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ai_engine, mod_installer, storage  # noqa: E402
from src.ai_engine import KeyStatus  # noqa: E402
from src.bridge import BridgeServer, parse_state  # noqa: E402
from src.tactics import Command, ReflexController  # noqa: E402

VALID_KEY = "sk-test-0123456789abcdef"


def make_state(gap=300.0, foe_attacking=False, me_x=100.0):
    entity = {"y": 300, "w": 40, "h": 100, "hp": 100, "max_hp": 100, "grounded": True, "reach": 90}
    return {
        "arena": {"w": 800, "h": 600},
        "self": {**entity, "x": me_x},
        "opponent": {**entity, "x": me_x + gap, "attacking": foe_attacking},
    }


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def store(self):
        return storage.Storage(self.dir, use_keyring=False)

    def test_defaults_on_first_run(self):
        s = self.store()
        self.assertFalse(s.terms_accepted)
        self.assertFalse(s.has_api_key())
        self.assertEqual(s.get("ai_profile", "personality"), "zueiro")

    def test_terms_acceptance_persists(self):
        self.store().accept_terms()
        again = self.store()
        self.assertTrue(again.terms_accepted)
        self.assertIsNotNone(again.get("settings", "accepted_terms_at"))

    def test_api_key_roundtrip_and_clear(self):
        s = self.store()
        s.set_api_key(f"  {VALID_KEY}\n", provider="openai")
        again = self.store()
        self.assertEqual(again.get_api_key(), VALID_KEY)
        self.assertEqual(again.get("ai_profile", "provider"), "openai")
        again.clear_api_key()
        self.assertEqual(self.store().get_api_key(), "")

    def test_rejects_malformed_keys(self):
        s = self.store()
        for bad in ("", "curta", "com espaço no meio 12345", "chave\nquebra\r\nHeader: x", "ç" * 20):
            with self.assertRaises(ValueError, msg=repr(bad)):
                s.set_api_key(bad)

    def test_snapshot_never_contains_key(self):
        s = self.store()
        s.set_api_key(VALID_KEY)
        self.assertNotIn(VALID_KEY, json.dumps(s.snapshot()))

    @unittest.skipUnless(os.name == "posix", "permissões POSIX")
    def test_config_file_is_private(self):
        s = self.store()
        s.set_api_key(VALID_KEY)
        self.assertEqual(oct((self.dir / "config.json").stat().st_mode & 0o777), "0o600")

    def test_sanitizes_garbage_values(self):
        (self.dir / "config.json").write_text(json.dumps({
            "settings": {"accepted_terms": "yes"},
            "ai_profile": {"provider": "evil", "bot_name": "x" * 500, "personality": 7, "api_key": 123},
            "app_preferences": {"sound_volume": 9999, "theme": "pink", "game_paths": {"a": 1, "b": "ok"}},
        }), encoding="utf-8")
        s = self.store()
        snap = s.snapshot()
        self.assertFalse(snap["settings"]["accepted_terms"])
        self.assertEqual(snap["ai_profile"]["provider"], "anthropic")
        self.assertLessEqual(len(snap["ai_profile"]["bot_name"]), ai_engine.MAX_BOT_NAME)
        self.assertEqual(snap["ai_profile"]["personality"], "zueiro")
        self.assertEqual(snap["app_preferences"]["sound_volume"], 70)
        self.assertEqual(snap["app_preferences"]["theme"], "dark")
        self.assertEqual(snap["app_preferences"]["game_paths"], {"b": "ok"})

    def test_corrupt_file_recovers_from_backup(self):
        s = self.store()
        s.accept_terms()
        s.update("ai_profile", bot_name="Khyros")   # cria .bak com a versão anterior
        (self.dir / "config.json").write_text("{ isto não é json", encoding="utf-8")
        recovered = self.store()
        self.assertIsNotNone(recovered.recovery_notice)
        self.assertTrue(recovered.terms_accepted)
        self.assertTrue(any(p.name.startswith("config.json.corrupt-") for p in self.dir.iterdir()))

    def test_corrupt_without_backup_uses_defaults(self):
        (self.dir / "config.json").write_text("\x00\x01", encoding="utf-8")
        s = self.store()
        self.assertFalse(s.terms_accepted)
        self.assertIsNotNone(s.recovery_notice)

    def test_concurrent_updates_keep_file_valid(self):
        s = self.store()

        def worker(i):
            for n in range(20):
                s.update("ai_profile", bot_name=f"Bot{i}-{n}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        json.loads((self.dir / "config.json").read_text(encoding="utf-8"))


class HealthCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = storage.Storage(Path(self.tmp.name), use_keyring=False)

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, status):
        result = ai_engine.ApiValidation(status, "msg")
        with mock.patch.object(storage, "validate_api_key", return_value=result):
            return storage.run_startup_health_check(self.s)

    def test_no_key_goes_to_api_config(self):
        self.assertEqual(storage.run_startup_health_check(self.s).route, storage.StartupRoute.API_CONFIG)

    def test_valid_key_goes_to_dashboard(self):
        self.s.set_api_key(VALID_KEY)
        r = self.run_check(KeyStatus.VALID)
        self.assertEqual(r.route, storage.StartupRoute.DASHBOARD)
        self.assertTrue(self.s.has_api_key())

    def test_invalid_key_is_discarded(self):
        self.s.set_api_key(VALID_KEY)
        r = self.run_check(KeyStatus.INVALID)
        self.assertEqual(r.route, storage.StartupRoute.API_CONFIG)
        self.assertFalse(self.s.has_api_key())

    def test_network_failure_keeps_key_and_opens_offline(self):
        self.s.set_api_key(VALID_KEY)
        r = self.run_check(KeyStatus.NETWORK_ERROR)
        self.assertEqual(r.route, storage.StartupRoute.DASHBOARD)
        self.assertTrue(r.offline)
        self.assertTrue(self.s.has_api_key())

    def test_rate_limit_keeps_key(self):
        self.s.set_api_key(VALID_KEY)
        self.assertEqual(self.run_check(KeyStatus.RATE_LIMITED).route, storage.StartupRoute.DASHBOARD)
        self.assertTrue(self.s.has_api_key())


class AIEngineTests(unittest.TestCase):
    def validate(self, status_code, provider="anthropic"):
        with mock.patch.object(ai_engine, "_http_json", return_value=(status_code, {})):
            return ai_engine.validate_api_key(VALID_KEY, provider)

    def test_status_mapping(self):
        self.assertEqual(self.validate(200).status, KeyStatus.VALID)
        self.assertEqual(self.validate(401).status, KeyStatus.INVALID)
        self.assertEqual(self.validate(403).status, KeyStatus.INVALID)
        self.assertEqual(self.validate(429).status, KeyStatus.RATE_LIMITED)
        self.assertEqual(self.validate(503).status, KeyStatus.SERVER_ERROR)
        self.assertEqual(self.validate(400, "gemini").status, KeyStatus.INVALID)
        self.assertEqual(self.validate(404).status, KeyStatus.SERVER_ERROR)

    def test_network_error_status(self):
        with mock.patch.object(ai_engine, "_http_json", side_effect=ai_engine.AIError("x", retryable=True)):
            self.assertEqual(ai_engine.validate_api_key(VALID_KEY, "openai").status, KeyStatus.NETWORK_ERROR)

    def test_bad_input_never_reaches_network(self):
        with mock.patch.object(ai_engine, "_http_json") as http:
            self.assertEqual(ai_engine.validate_api_key("", "openai").status, KeyStatus.EMPTY)
            self.assertEqual(ai_engine.validate_api_key("a b c d e f g h", "openai").status, KeyStatus.MALFORMED)
            self.assertEqual(ai_engine.validate_api_key(VALID_KEY, "inexistente").status, KeyStatus.MALFORMED)
            http.assert_not_called()

    def test_http_layer_blocks_foreign_hosts_and_plain_http(self):
        for url in ("https://evil.example.com/v1/models", "http://api.openai.com/v1/models"):
            with self.assertRaises(ai_engine.AIError):
                ai_engine._http_json("GET", url, {})

    def test_key_never_leaks_in_repr(self):
        ai = ai_engine.CompanionAI("openai", VALID_KEY, model="m")
        self.assertNotIn(VALID_KEY, repr(ai))
        self.assertNotIn(VALID_KEY, ai_engine.mask_key(VALID_KEY))

    def test_system_prompt_injects_profile(self):
        profile = ai_engine.CompanionProfile("Khyros", "custom", "Aja como um herói sarcástico.")
        prompt = ai_engine.build_system_prompt(profile, "Mortal Stick", "strategy")
        self.assertIn("Khyros", prompt)
        self.assertIn("herói sarcástico", prompt)
        self.assertIn("strategy", prompt)

    def test_custom_prompt_is_sanitized_and_limited(self):
        profile = ai_engine.CompanionProfile("Bot\x00", "custom", "a\x07" + "x" * 9000)
        norm = profile.normalized()
        self.assertNotIn("\x00", norm.bot_name)
        self.assertLessEqual(len(norm.custom_prompt), ai_engine.MAX_CUSTOM_PROMPT)
        self.assertNotIn("\x07", norm.custom_prompt)

    def test_parse_strategy_is_strict(self):
        self.assertEqual(ai_engine.parse_strategy('{"strategy":"aggressive","say":"Vamos!"}'),
                         {"strategy": "aggressive", "say": "Vamos!"})
        self.assertEqual(ai_engine.parse_strategy('Claro! {"strategy":"defensive"} ok')["strategy"], "defensive")
        for garbage in ("", "sem json", '{"strategy":"apagar_tudo"}', '{"strategy": 5}', "[1,2]", '{"strategy":'):
            self.assertEqual(ai_engine.parse_strategy(garbage)["strategy"], "balanced", garbage)
        self.assertLessEqual(len(ai_engine.parse_strategy('{"say":"' + "a" * 999 + '"}')["say"]), ai_engine.MAX_SAY_CHARS)

    def test_chat_builds_history_and_extracts_text(self):
        ai = ai_engine.CompanionAI("anthropic", VALID_KEY, model="m")
        payload = {"content": [{"type": "text", "text": "Fala, parceiro!"}]}
        with mock.patch.object(ai_engine, "_http_json", return_value=(200, payload)) as http:
            self.assertEqual(ai.chat("oi"), "Fala, parceiro!")
            body = http.call_args.args[3]
            self.assertIn("Duo", body["system"])
        self.assertEqual(len(ai._history), 2)

    def test_chat_extracts_openai_and_gemini(self):
        with mock.patch.object(ai_engine, "_http_json", return_value=(200, {"choices": [{"message": {"content": "oi!"}}]})):
            self.assertEqual(ai_engine.CompanionAI("openai", VALID_KEY, model="m").chat("x"), "oi!")
        gem = {"candidates": [{"content": {"parts": [{"text": "e aí"}]}}]}
        with mock.patch.object(ai_engine, "_http_json", return_value=(200, gem)):
            self.assertEqual(ai_engine.CompanionAI("gemini", VALID_KEY, model="m").chat("x"), "e aí")

    def test_chat_errors_are_user_friendly_and_retry_once(self):
        ai = ai_engine.CompanionAI("openai", VALID_KEY, model="m")
        with mock.patch.object(ai_engine, "_http_json", return_value=(429, {})) as http, \
             mock.patch.object(ai_engine.time, "sleep"):
            with self.assertRaises(ai_engine.AIError) as ctx:
                ai.chat("oi")
            posts = [c for c in http.call_args_list if c.args[0] == "POST"]
            self.assertEqual(len(posts), 2)      # 1 tentativa + 1 repetição, sem alternativa de modelo
            self.assertNotIn(VALID_KEY, str(ctx.exception))
        with mock.patch.object(ai_engine, "_http_json", return_value=(401, {})) as http:
            with self.assertRaises(ai_engine.AIError):
                ai.chat("oi")
            self.assertEqual(http.call_count, 1)

    def test_history_is_capped(self):
        ai = ai_engine.CompanionAI("openai", VALID_KEY, model="m")
        with mock.patch.object(ai_engine, "_http_json", return_value=(200, {"choices": [{"message": {"content": "ok"}}]})):
            for i in range(60):
                ai.chat(f"msg {i}")
        self.assertLessEqual(len(ai._history), ai_engine.MAX_HISTORY_TURNS * 2)


class ModelDetectionTests(unittest.TestCase):
    def test_pick_gemini_prefers_stable_current_flash(self):
        models = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview", "gemini-2.5-pro"]
        self.assertEqual(ai_engine.pick_best_model("gemini", models), "gemini-2.5-flash")
        self.assertEqual(ai_engine.pick_best_model("gemini", models, {"gemini-2.5-flash"}), "gemini-2.0-flash")
        self.assertEqual(ai_engine.pick_best_model("gemini", models, {"gemini-2.5-flash", "gemini-2.0-flash"}),
                         "gemini-2.5-flash-lite")
        self.assertIsNone(ai_engine.pick_best_model("gemini", []))

    def test_pick_anthropic_prefers_fast_alias(self):
        models = ["claude-sonnet-4-5", "claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-3-5-haiku-20241022"]
        self.assertEqual(ai_engine.pick_best_model("anthropic", models), "claude-haiku-4-5")
        self.assertEqual(ai_engine.pick_best_model("anthropic", ["claude-sonnet-4-5"]), "claude-sonnet-4-5")

    def test_pick_openai_prefers_non_reasoning_mini(self):
        self.assertEqual(ai_engine.pick_best_model("openai", ["gpt-4o", "gpt-5-mini", "gpt-4o-mini"]), "gpt-4o-mini")
        self.assertEqual(ai_engine.pick_best_model("openai", ["gpt-4o", "gpt-5-mini"]), "gpt-5-mini")

    def test_list_models_filters_non_chat_models(self):
        gem = {"models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
        ]}
        with mock.patch.object(ai_engine, "_http_json", return_value=(200, gem)):
            self.assertEqual(ai_engine.list_models("gemini", VALID_KEY), ["gemini-2.5-flash"])
        oa = {"data": [{"id": "gpt-4o-mini"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"},
                       {"id": "gpt-4o-audio-preview"}, {"id": "o3-mini"}]}
        with mock.patch.object(ai_engine, "_http_json", return_value=(200, oa)):
            self.assertEqual(ai_engine.list_models("openai", VALID_KEY), ["gpt-4o-mini", "o3-mini"])

    def test_list_models_failure_raises(self):
        with mock.patch.object(ai_engine, "_http_json", return_value=(403, {})):
            with self.assertRaises(ai_engine.AIError):
                ai_engine.list_models("openai", VALID_KEY)

    @staticmethod
    def fake_gemini(retired):
        calls = []

        def fake(method, url, headers, body=None, timeout=0):
            calls.append((method, url, body))
            if method == "GET":
                return 200, {"models": [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]}
                                        for m in ("gemini-2.0-flash", "gemini-2.5-flash")]}
            if retired in url:
                return 404, {"error": {"message": "model no longer available"}}
            return 200, {"candidates": [{"content": {"parts": [{"text": "Fala!"}]}}]}

        return fake, calls

    def test_404_triggers_redetection_and_retry(self):
        fake, calls = self.fake_gemini(retired="gemini-2.5-flash:")
        resolved = []
        ai = ai_engine.CompanionAI("gemini", VALID_KEY, model="gemini-2.5-flash", on_model_resolved=resolved.append)
        with mock.patch.object(ai_engine, "_http_json", side_effect=fake):
            self.assertEqual(ai.chat("oi"), "Fala!")
        self.assertEqual(ai.model, "gemini-2.0-flash")
        self.assertEqual(resolved, ["gemini-2.0-flash"])
        self.assertEqual([c[0] for c in calls], ["POST", "GET", "POST", "POST"])   # falha, lista, teste, resposta

    def test_detects_model_on_first_call_when_none_configured(self):
        fake, calls = self.fake_gemini(retired="nenhum-modelo")
        resolved = []
        ai = ai_engine.CompanionAI("gemini", VALID_KEY, on_model_resolved=resolved.append)
        with mock.patch.object(ai_engine, "_http_json", side_effect=fake):
            ai.chat("oi")
        self.assertEqual(resolved, ["gemini-2.5-flash"])
        self.assertIn("gemini-2.5-flash:generateContent", calls[1][1])

    def test_overloaded_model_falls_back_to_next_and_is_remembered(self):
        """Caso real: o modelo mais novo respondia 503 'high demand'. Deve trocar sozinho para outro."""
        models = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash"]
        seen = []

        def fake(method, url, headers, body=None, timeout=0):
            if method == "GET":
                return 200, {"models": [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]} for m in models]}
            seen.append(url)
            if "gemini-3.8-flash" in url or "gemini-3.7-flash" in url:
                return 503, {"error": {"message": "This model is currently experiencing high demand."}}
            return 200, {"candidates": [{"content": {"parts": [{"text": "Fala!"}]}}]}

        resolved = []
        ai = ai_engine.CompanionAI("gemini", VALID_KEY, model="gemini-3.8-flash", on_model_resolved=resolved.append)
        with mock.patch.object(ai_engine, "_http_json", side_effect=fake):
            self.assertEqual(ai.chat("oi"), "Fala!")
        self.assertEqual(ai.model, "gemini-2.5-flash")
        self.assertEqual(resolved[-1], "gemini-2.5-flash")
        self.assertIn("gemini-3.8-flash", ai._unavailable())

    def test_timeout_is_treated_as_model_failure_but_connection_errors_are_not(self):
        models = ["gemini-2.5-flash", "gemini-2.0-flash"]
        state = {"first": True}

        def timeout_then_ok(method, url, headers, body=None, timeout=0):
            if method == "GET":
                return 200, {"models": [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]} for m in models]}
            if "gemini-2.5-flash" in url and state["first"]:
                state["first"] = False
                raise ai_engine.AIError("Tempo esgotado", retryable=True)
            return 200, {"candidates": [{"content": {"parts": [{"text": "ok!"}]}}]}

        ai = ai_engine.CompanionAI("gemini", VALID_KEY, model="gemini-2.5-flash")
        with mock.patch.object(ai_engine, "_http_json", side_effect=timeout_then_ok):
            self.assertEqual(ai.chat("oi"), "ok!")

        down = ai_engine.AIError("DNS", retryable=True, network=True)
        calls = []

        def offline(method, url, headers, body=None, timeout=0):
            calls.append(method)
            raise down

        ai = ai_engine.CompanionAI("gemini", VALID_KEY, model="gemini-2.5-flash")
        with mock.patch.object(ai_engine, "_http_json", side_effect=offline):
            with self.assertRaises(ai_engine.AIError):
                ai.chat("oi")
        self.assertEqual(calls, ["POST"])                  # sem rede: não adianta trocar de modelo
        self.assertEqual(ai._unavailable(), set())         # e nenhum modelo é marcado como ruim

    def test_rank_prefers_proven_model_over_newest(self):
        real_list = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash", "gemini-3-flash-preview",
                     "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-2.5-pro"]
        ranked = ai_engine.rank_models("gemini", real_list)
        self.assertEqual(ranked[0], "gemini-2.5-flash")
        self.assertEqual(ranked[1], "gemini-3.8-flash")
        self.assertEqual(ranked[:3], ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.7-flash"])
        self.assertEqual(len(ranked), len(set(ranked)))

    def test_remembered_model_skips_detection(self):
        fake, calls = self.fake_gemini(retired="nenhum-modelo")
        ai = ai_engine.CompanionAI("gemini", VALID_KEY, detected_model="gemini-2.5-flash")
        with mock.patch.object(ai_engine, "_http_json", side_effect=fake):
            ai.chat("oi")
        self.assertEqual([c[0] for c in calls], ["POST"])

    def test_404_with_no_alternative_gives_clear_error(self):
        def fake(method, url, headers, body=None, timeout=0):
            return (200, {"models": []}) if method == "GET" else (404, {})
        ai = ai_engine.CompanionAI("gemini", VALID_KEY, model="gemini-x")
        with mock.patch.object(ai_engine, "_http_json", side_effect=fake):
            with self.assertRaises(ai_engine.AIError) as ctx:
                ai.chat("oi")
        self.assertIn("gemini-x", str(ctx.exception))

    def test_error_detail_is_shown_but_key_is_redacted(self):
        payload = {"error": {"message": f"API key {VALID_KEY} expired \x07 or bad request"}}
        ai = ai_engine.CompanionAI("openai", VALID_KEY, model="m")
        with mock.patch.object(ai_engine, "_http_json", return_value=(400, payload)):
            with self.assertRaises(ai_engine.AIError) as ctx:
                ai.chat("oi")
        self.assertIn("HTTP 400", str(ctx.exception))
        self.assertIn("***", str(ctx.exception))
        self.assertNotIn(VALID_KEY, str(ctx.exception))
        self.assertNotIn("\x07", str(ctx.exception))

    def test_gemini_25_flash_disables_thinking_and_has_token_headroom(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        ai = ai_engine.CompanionAI("gemini", VALID_KEY, model="gemini-2.5-flash")
        with mock.patch.object(ai_engine, "_http_json", return_value=(200, payload)) as http:
            ai.chat("oi")
        config = http.call_args.args[3]["generationConfig"]
        self.assertEqual(config["thinkingConfig"], {"thinkingBudget": 0})
        self.assertGreaterEqual(config["maxOutputTokens"], 1024)

    def test_storage_remembers_detected_model_and_resets_on_new_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = storage.Storage(Path(tmp), use_keyring=False)
            s.set_api_key(VALID_KEY, "gemini")
            s.set_detected_model("gemini", "gemini-2.5-flash")
            self.assertEqual(storage.Storage(Path(tmp), use_keyring=False).get_detected_model("gemini"), "gemini-2.5-flash")
            s.set_detected_model("evil", "x")
            self.assertEqual(s.get_detected_model("evil"), "")
            s.set_api_key(VALID_KEY + "2", "gemini")
            self.assertEqual(s.get_detected_model("gemini"), "")

    def test_gemini_tutorial_and_wording(self):
        steps = " ".join(ai_engine.PROVIDERS["gemini"].tutorial)
        for expected in ("aistudio.google.com", "Get API key", "Create API key", "novo projeto", "Copy"):
            self.assertIn(expected, steps)
        prompt = ai_engine.build_system_prompt(ai_engine.CompanionProfile(), None, "chat")
        self.assertIn("IA", prompt)
        for personality in ai_engine.PERSONALITIES.values():
            self.assertNotIn("parceiro", personality["prompt"].lower())


class TacticsTests(unittest.TestCase):
    def controller(self, strategy):
        c = ReflexController(reaction_range_ms=(0, 0))
        c.set_strategy(strategy)
        return c

    def test_aggressive_approaches_then_attacks(self):
        c = self.controller("aggressive")
        self.assertEqual(c.decide(make_state(gap=400), now=1.0).move, 1)
        close = c.decide(make_state(gap=40), now=2.0)
        self.assertTrue(close.attack)

    def test_retreat_moves_away(self):
        c = self.controller("retreat")
        self.assertEqual(c.decide(make_state(gap=100, me_x=400), now=1.0).move, -1)

    def test_defensive_backs_off_from_attacks(self):
        c = self.controller("defensive")
        self.assertEqual(c.decide(make_state(gap=80, foe_attacking=True, me_x=300), now=1.0).move, -1)

    def test_idle_and_game_over(self):
        self.assertEqual(self.controller("idle").decide(make_state(), now=1.0), Command())
        over = make_state()
        over["over"] = True
        self.assertEqual(self.controller("aggressive").decide(over, now=1.0), Command())

    def test_reaction_delay_holds_previous_command(self):
        c = ReflexController(reaction_range_ms=(500, 500))
        c.set_strategy("aggressive")
        first = c.decide(make_state(gap=400), now=10.0)
        held = c.decide(make_state(gap=-400), now=10.1)   # situação mudou, mas ainda reagindo
        self.assertEqual(first, held)

    def test_invalid_strategy_is_ignored(self):
        c = self.controller("aggressive")
        c.set_strategy("rm -rf")
        self.assertEqual(c.strategy, "aggressive")


def _connect(port):
    return socket.create_connection(("127.0.0.1", port), timeout=3)


def _send(sock, obj):
    sock.sendall((json.dumps(obj) + "\n").encode())


def _recv_line(sock):
    data = b""
    while b"\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        data += chunk
    return json.loads(data.split(b"\n")[0])


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.server = BridgeServer(lambda state: Command(move=1, attack=True), lambda k, d: self.events.append(k))
        self.port = self.server.start()

    def tearDown(self):
        self.server.stop()

    def hello(self, sock, token=None):
        _send(sock, {"type": "hello", "token": token or self.server.token, "game": "Teste", "protocol": 1})

    def wire_state(self):
        return {"type": "state", **make_state()}

    def test_listens_on_loopback_only(self):
        self.assertEqual(self.server._server.getsockname()[0], "127.0.0.1")
        with self.assertRaises(ValueError):
            BridgeServer(lambda s: None, host="0.0.0.0")

    def test_valid_session_gets_commands(self):
        with _connect(self.port) as sock:
            self.hello(sock)
            _send(sock, self.wire_state())
            reply = _recv_line(sock)
            self.assertEqual(reply, {"type": "command", "move": 1, "jump": False, "attack": True})
            time.sleep(0.1)
            self.assertTrue(self.server.connected)
            self.assertTrue(self.server.say("Boa jogada!"))
            self.assertEqual(_recv_line(sock), {"type": "say", "text": "Boa jogada!"})
        time.sleep(0.3)
        self.assertFalse(self.server.connected)
        self.assertEqual(self.events, ["connected", "disconnected"])

    def test_wrong_token_is_rejected(self):
        with _connect(self.port) as sock:
            self.hello(sock, token="x" * 43)
            _send(sock, self.wire_state())
            self.assertIsNone(_recv_line(sock))
        self.assertNotIn("connected", self.events)

    def test_state_before_hello_is_rejected(self):
        with _connect(self.port) as sock:
            _send(sock, self.wire_state())
            self.assertIsNone(_recv_line(sock))

    def test_second_client_is_refused(self):
        with _connect(self.port) as first:
            self.hello(first)
            _send(first, self.wire_state())
            _recv_line(first)
            with _connect(self.port) as second:
                self.hello(second)
                _send(second, self.wire_state())
                self.assertIsNone(_recv_line(second))
            _send(first, self.wire_state())
            self.assertIsNotNone(_recv_line(first))

    def test_oversized_line_drops_connection(self):
        with _connect(self.port) as sock:
            self.hello(sock)
            _send(sock, self.wire_state())
            _recv_line(sock)
            try:
                sock.sendall(b"A" * 40000 + b"\n")
            except OSError:
                pass
            self.assertIsNone(_recv_line(sock))

    def test_malformed_states_are_ignored_not_fatal(self):
        with _connect(self.port) as sock:
            self.hello(sock)
            bad = make_state()
            bad["self"]["x"] = float("nan")
            for payload in ({"type": "state"}, {"type": "state", **bad}, {"type": "state", "arena": 5}):
                sock.sendall((json.dumps(payload) + "\n").encode())
            _send(sock, self.wire_state())
            self.assertEqual(_recv_line(sock)["type"], "command")

    def test_parse_state_clamps_and_validates(self):
        good = make_state()
        good["self"]["x"] = 10 ** 9
        parsed = parse_state(good)
        self.assertEqual(parsed["self"]["x"], 5000.0)
        self.assertIsNone(parse_state({"arena": {"w": 800, "h": 600}, "self": {}, "opponent": {}}))
        self.assertIsNone(parse_state("texto"))
        weird = make_state()
        weird["self"]["hp"] = "100"
        self.assertIsNone(parse_state(weird))


class ModInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.game = self.root / "game"
        self.bundles = self.root / "bundles"
        self.game.mkdir()
        self.bundles.mkdir()
        (self.game / "Game.exe").write_bytes(b"MZ")

    def tearDown(self):
        self.tmp.cleanup()

    def make_bundle(self, files, name="pack.zip"):
        path = self.bundles / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, data in files.items():
                z.writestr(rel, data)
        return path

    def entry(self, bundle_path=None, sha=None):
        return mod_installer.GameEntry(
            id="g", name="G", description="", kind="mod", executable="Game.exe",
            required_files=("Mods/mod.dll",), bundle=bundle_path.name if bundle_path else None,
            bundle_sha256=sha or (mod_installer.sha256_file(bundle_path) if bundle_path else None),
        )

    def test_install_and_uninstall(self):
        bundle = self.make_bundle({"Mods/mod.dll": b"dll", "MelonLoader/ml.dll": b"ml"})
        entry = self.entry(bundle)
        self.assertFalse(mod_installer.check_installation(entry, self.game, self.bundles).installed)
        progress = []
        files = mod_installer.install(entry, self.game, lambda f, m: progress.append(f), bundles=self.bundles)
        self.assertEqual(sorted(files), ["MelonLoader/ml.dll", "Mods/mod.dll"])
        self.assertTrue(mod_installer.check_installation(entry, self.game, self.bundles).installed)
        self.assertEqual(progress[-1], 1.0)
        self.assertEqual(mod_installer.uninstall(self.game), 2)
        self.assertFalse((self.game / "Mods" / "mod.dll").exists())

    def test_tampered_bundle_is_refused(self):
        bundle = self.make_bundle({"Mods/mod.dll": b"dll"})
        with self.assertRaises(mod_installer.InstallError):
            mod_installer.install(self.entry(bundle, sha="0" * 64), self.game, bundles=self.bundles)
        self.assertFalse((self.game / "Mods").exists())

    def test_missing_hash_is_refused(self):
        bundle = self.make_bundle({"Mods/mod.dll": b"dll"})
        entry = self.entry(bundle)
        entry = mod_installer.GameEntry(**{**entry.__dict__, "bundle_sha256": None})
        with self.assertRaises(mod_installer.InstallError):
            mod_installer.install(entry, self.game, bundles=self.bundles)

    def test_zip_slip_and_absolute_paths_are_refused(self):
        for evil in ("../escape.txt", "/etc/duette_evil", "Mods/../../escape.txt", "C:/Windows/x.dll", "a\\b.dll"):
            bundle = self.make_bundle({"ok.txt": b"ok", evil: b"evil"}, name="evil.zip")
            with self.assertRaises(mod_installer.InstallError, msg=evil):
                mod_installer.install(self.entry(bundle), self.game, bundles=self.bundles)
            self.assertFalse((self.root / "escape.txt").exists())
            self.assertFalse((self.game / "ok.txt").exists(), "nada deve ser mantido após falha")

    def test_symlink_entries_are_refused(self):
        path = self.bundles / "link.zip"
        with zipfile.ZipFile(path, "w") as z:
            info = zipfile.ZipInfo("Mods/link")
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
        with self.assertRaises(mod_installer.InstallError):
            mod_installer.install(self.entry(path), self.game, bundles=self.bundles)

    def test_overwritten_files_are_restored_on_failure(self):
        (self.game / "Mods").mkdir()
        (self.game / "Mods" / "mod.dll").write_bytes(b"ORIGINAL")
        bundle = self.make_bundle({"Mods/mod.dll": b"novo", "Mods": b"conflito"})
        with self.assertRaises(mod_installer.InstallError):
            mod_installer.install(self.entry(bundle), self.game, bundles=self.bundles)
        self.assertEqual((self.game / "Mods" / "mod.dll").read_bytes(), b"ORIGINAL")

    def test_cancel_rolls_back(self):
        bundle = self.make_bundle({"a.txt": b"1", "b.txt": b"2"})
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(mod_installer.InstallCancelled):
            mod_installer.install(self.entry(bundle), self.game, cancel=cancel, bundles=self.bundles)
        self.assertFalse((self.game / "a.txt").exists())

    def test_wrong_game_folder_is_refused(self):
        bundle = self.make_bundle({"a.txt": b"1"})
        other = self.root / "outra"
        other.mkdir()
        with self.assertRaises(mod_installer.InstallError):
            mod_installer.install(self.entry(bundle), other, bundles=self.bundles)

    def test_catalog_skips_invalid_entries(self):
        (self.bundles / "games.json").write_text(json.dumps({"games": [
            {"id": "ok", "name": "OK", "kind": "builtin"},
            {"id": "../mau", "name": "Mau"},
            {"id": "traversal", "name": "T", "required_files": ["../../x"]},
            {"id": "badzip", "name": "B", "bundle": "../x.zip"},
            {"name": "sem id"},
        ]}), encoding="utf-8")
        self.assertEqual([g.id for g in mod_installer.load_catalog(self.bundles)], ["ok"])

    def test_catalog_missing_or_corrupt_is_empty(self):
        self.assertEqual(mod_installer.load_catalog(self.bundles), [])
        (self.bundles / "games.json").write_text("{{{", encoding="utf-8")
        self.assertEqual(mod_installer.load_catalog(self.bundles), [])

    def test_shipped_catalog_is_valid(self):
        games = mod_installer.load_catalog()
        self.assertEqual({g.id for g in games}, {"mortal_stick", "bonelab"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
