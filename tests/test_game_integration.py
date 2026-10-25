"""Teste de integração ponta a ponta: jogo de teste (headless) <-> ponte <-> reflexos do Duette."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import PlayerTwoSession  # noqa: E402

# Roda dentro do processo do jogo: simula alguns segundos de partida sem janela.
GAME_SCRIPT = textwrap.dedent(
    """
    import os, sys, time, json
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    sys.path.insert(0, os.getcwd())
    import pygame
    pygame.init()
    pygame.display.set_mode((800, 600))
    from src.mortal_stick_combat.core.game import Game
    game = Game("STICK", "PUNHO", "STICK", "PUNHO")
    assert game.ai is not None, "cliente do Duette não foi criado"
    surface = pygame.display.get_surface()
    start_x = game.p2.x
    max_hp_lost = 0.0
    moved = attacked = False
    deadline = time.time() + 12
    while time.time() < deadline and not game.game_over:
        pygame.event.pump()
        game.update()
        game.draw(surface)
        moved |= abs(game.p2.x - start_x) > 30
        attacked |= game.p2.punching
        time.sleep(1 / 60)
    print(json.dumps({"moved": moved, "attacked": attacked, "connected": bool(game.ai and game.ai.connected)}))
    """
)


EVENT_SCRIPT = textwrap.dedent(
    """
    import os, sys, time, json
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    sys.path.insert(0, os.getcwd())
    import pygame
    pygame.init()
    pygame.display.set_mode((800, 600))
    from src.mortal_stick_combat.core.game import Game
    game = Game("STICK", "ESPADA", "STICK", "PUNHO", stage="DOJO")
    surface = pygame.display.get_surface()
    for _ in range(170):                      # contagem regressiva
        game.update()
    assert game.phase == "fight", game.phase
    game.p1.x = game.p2.x - 55
    game.p1.start_attack()
    for _ in range(90):
        game.update()
        game.draw(surface)
        time.sleep(1 / 60)
    time.sleep(0.3)
    print(json.dumps({"hits": game.stats["hits"], "damage": game.stats["damage"]}))
    """
)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame não instalado")
class GameIntegrationTests(unittest.TestCase):
    def test_ai_controls_player_two(self):
        events = []
        session = PlayerTwoSession(ai=None, on_event=lambda kind, data: events.append(kind))
        session.controller.set_strategy("aggressive")
        import tempfile
        game_log = Path(tempfile.mkdtemp()) / "game.log"
        env = {**os.environ, **session.start(), "DUETTE_GAME_LOG": str(game_log)}
        try:
            result = subprocess.run(
                [sys.executable, "-c", GAME_SCRIPT],
                cwd=str(ROOT / "teste_game"),
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
        finally:
            session.stop()
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        import json

        outcome = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(outcome["connected"])
        self.assertTrue(outcome["moved"], "o Player 2 deveria ter se movido")
        self.assertTrue(outcome["attacked"], "o Player 2 deveria ter atacado")
        self.assertIn("connected", events)
        text = game_log.read_text(encoding="utf-8")
        self.assertIn("Conectado à ponte", text)

    def test_game_events_reach_the_session(self):
        session = PlayerTwoSession(ai=None)
        session.controller.set_strategy("idle")
        env = {**os.environ, **session.start()}
        try:
            result = subprocess.run([sys.executable, "-c", EVENT_SCRIPT], cwd=str(ROOT / "teste_game"), env=env,
                                    capture_output=True, text=True, timeout=60)
        finally:
            events = [event for _t, event in list(session._events)]
            latest = session._latest
            session.stop()
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn(("hit", "opponent"), [(e["k"], e["who"]) for e in events])
        self.assertIn(latest["phase"], ("fight", "over"))
        self.assertIn("weapon", latest["opponent"])
        self.assertIn("time", latest["match"])

    def test_game_without_duette_runs_normally(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("DUETTE_BRIDGE")}
        script = GAME_SCRIPT.replace('assert game.ai is not None, "cliente do Duette não foi criado"', "assert game.ai is None")
        result = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT / "teste_game"), env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
