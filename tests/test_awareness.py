"""Testes da consciência do jogo em tempo real: protocolo estendido, eventos, resumo e tática."""

from __future__ import annotations

import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import PlayerTwoSession, describe_event, summarize_state  # noqa: E402
from src.bridge import BridgeServer, parse_state  # noqa: E402
from src.tactics import ReflexController  # noqa: E402


def entity(x, **extra):
    base = {"x": x, "y": 300, "w": 40, "h": 100, "hp": 100, "max_hp": 100, "vx": 0, "vy": 0,
            "grounded": True, "attacking": False, "hurt": False, "facing": 1, "reach": 90}
    base.update(extra)
    return base


def raw_state(**extra):
    state = {"arena": {"w": 800, "h": 600}, "self": entity(100), "opponent": entity(300),
             "over": False, "paused": False}
    state.update(extra)
    return state


class ProtocolTests(unittest.TestCase):
    def test_basic_state_still_valid_and_gets_defaults(self):
        state = parse_state(raw_state())
        self.assertEqual(state["phase"], "fight")
        self.assertEqual(state["events"], [])
        self.assertEqual(state["match"], {})

    def test_over_implies_phase_over(self):
        self.assertEqual(parse_state(raw_state(over=True))["phase"], "over")

    def test_extended_fields_are_validated_and_clamped(self):
        state = parse_state(raw_state(
            phase="countdown",
            self=entity(100, cooldown=5, jumps=1, weapon="ESPADA\x00", style="NINJA", invulnerable=True),
            match={"time": 12.5, "hits_self": 3, "dmg_self": "x", "combo_self": 2},
        ))
        me = state["self"]
        self.assertEqual(me["cooldown"], 1.0)           # limitado à faixa
        self.assertEqual(me["weapon"], "ESPADA")        # controle removido
        self.assertTrue(me["invulnerable"])
        self.assertEqual(state["phase"], "countdown")
        self.assertEqual(state["match"], {"time": 12.5, "hits_self": 3.0, "combo_self": 2.0})

    def test_invalid_optional_fields_are_ignored_not_fatal(self):
        state = parse_state(raw_state(self=entity(100, cooldown="abc", speed=float("nan"))))
        self.assertIsNotNone(state)
        self.assertNotIn("cooldown", state["self"])
        self.assertNotIn("speed", state["self"])

    def test_events_are_whitelisted_and_limited(self):
        events = [{"k": "hit", "who": "self", "v": 20}, {"k": "rm -rf", "who": "self"},
                  {"k": "ko", "who": "alguem"}, "texto", {"k": "combo", "who": "opponent", "v": 3}]
        events += [{"k": "land", "who": "self"}] * 50
        state = parse_state(raw_state(events=events))
        kinds = [e["k"] for e in state["events"]]
        self.assertEqual(kinds[:2], ["hit", "combo"])
        self.assertLessEqual(len(kinds), 12)

    def test_bad_phase_falls_back(self):
        self.assertEqual(parse_state(raw_state(phase="hack"))["phase"], "fight")

    def test_events_not_a_list(self):
        self.assertEqual(parse_state(raw_state(events={"k": "hit"}))["events"], [])


class MessageTests(unittest.TestCase):
    def test_say_and_status_messages_sent_to_game(self):
        server = BridgeServer(lambda s: None)
        sent = []
        server.send = lambda message: sent.append(message) or True  # type: ignore[method-assign]
        server.say("Olá!\x07", "Duo\n")
        server.status("Duo", "aggressive")
        server.status("", "invalida")
        self.assertEqual(sent[0], {"type": "say", "text": "Olá!", "name": "Duo"})
        self.assertEqual(sent[1], {"type": "status", "name": "Duo", "strategy": "aggressive"})
        self.assertEqual(len(sent), 2)       # status sem dados úteis não é enviado


class AgentAwarenessTests(unittest.TestCase):
    def test_describe_event(self):
        self.assertIn("me acertou", describe_event({"k": "hit", "who": "opponent", "v": 20}))
        self.assertIn("nocauteei", describe_event({"k": "ko", "who": "opponent", "v": 0}))
        self.assertIn("combo de 3", describe_event({"k": "combo", "who": "self", "v": 3}))

    def test_brief_contains_readable_context(self):
        state = parse_state(raw_state(
            opponent=entity(180, attacking=True, cooldown=0.8, weapon="MARTELO"),
            match={"time": 30, "hits_self": 2, "hits_opponent": 4}))
        brief = PlayerTwoSession._brief(state, [(1.2, {"k": "hit", "who": "opponent", "v": 30})])
        self.assertTrue(brief["oponente_vulneravel"])
        self.assertEqual(brief["arma_do_oponente"], "MARTELO")
        self.assertEqual(brief["placar"]["golpes_do_oponente"], 4)
        self.assertEqual(brief["eventos_recentes"][0]["ha_s"], 1.2)
        self.assertIn("oponente_esta_a_direita", brief)

    def test_summary_for_chat_is_json_with_life(self):
        text = summarize_state(parse_state(raw_state()))
        self.assertIn("minha_vida_pct", text)
        self.assertIsNone(summarize_state(None))

    def test_hit_event_wakes_strategy_loop_and_is_remembered(self):
        class FakeAI:
            profile = None
        session = PlayerTwoSession(ai=FakeAI())  # type: ignore[arg-type]
        state = parse_state(raw_state(events=[{"k": "hit", "who": "opponent", "v": 30}]))
        session._on_state(state)
        self.assertTrue(session._wake.is_set())
        self.assertTrue(session._urgent)
        self.assertEqual(len(session._events), 1)

    def test_land_and_jump_events_are_noise(self):
        class FakeAI:
            profile = None
        session = PlayerTwoSession(ai=FakeAI())  # type: ignore[arg-type]
        session._on_state(parse_state(raw_state(events=[{"k": "land", "who": "self", "v": 1}])))
        self.assertFalse(session._wake.is_set())
        self.assertEqual(len(session._events), 0)

    def test_without_ai_events_do_not_wake(self):
        session = PlayerTwoSession(ai=None)
        session._on_state(parse_state(raw_state(events=[{"k": "ko", "who": "self", "v": 0}])))
        self.assertFalse(session._wake.is_set())

    def test_hp_trend(self):
        session = PlayerTwoSession(ai=None)
        now = time.monotonic()
        session._hp_history.extend([(now - 5, 100.0), (now - 3, 80.0), (now, 55.0)])
        self.assertEqual(session._hp_trend(now), "caindo")


class TacticsAwarenessTests(unittest.TestCase):
    def controller(self, strategy="balanced"):
        c = ReflexController(random.Random(3), (0, 0))
        c.set_strategy(strategy)
        return c

    def state(self, **foe):
        return parse_state(raw_state(opponent=entity(210, **foe)))

    def test_countdown_is_idle(self):
        state = parse_state(raw_state(phase="countdown"))
        command = self.controller("aggressive").decide(state, 1.0)
        self.assertEqual((command.move, command.attack), (0, False))

    def test_punishes_opponent_recovering_from_attack(self):
        command = self.controller().decide(self.state(attacking=True, cooldown=0.8), 1.0)
        self.assertEqual(command.move, 1)            # avança sobre o oponente aberto

    def test_does_not_attack_invulnerable_opponent(self):
        state = parse_state(raw_state(self=entity(160), opponent=entity(210, invulnerable=True)))
        command = self.controller("aggressive").decide(state, 1.0)
        self.assertFalse(command.attack)

    def test_panic_dodges_when_low_health_and_threatened(self):
        state = parse_state(raw_state(self=entity(160, hp=10), opponent=entity(210, attacking=True, cooldown=0.1)))
        command = self.controller("balanced").decide(state, 1.0)
        self.assertEqual(command.move, -1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
