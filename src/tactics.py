"""Controlador de reflexos do Player 2.

A IA (LLM) leva de centenas de milissegundos a vários segundos para responder, o que é lento
demais para controlar um personagem quadro a quadro. Por isso a divisão de responsabilidades é:

  * LLM  ➜ decide a ESTRATÉGIA (agressiva, defensiva, recuar...) a cada poucos segundos e fala.
  * Este controlador local ➜ executa a estratégia em tempo real (movimento, pulo, ataque),
    com um pequeno atraso de reação aleatório para parecer humano.

Funciona mesmo sem rede: sem estratégia nova, mantém a última (ou ``balanced``).
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Any

from .ai_engine import STRATEGIES


@dataclass(frozen=True)
class Command:
    move: int = 0        # -1 esquerda, 0 parado, 1 direita
    jump: bool = False
    attack: bool = False

    def to_message(self) -> dict[str, Any]:
        return {"type": "command", "move": self.move, "jump": self.jump, "attack": self.attack}


IDLE = Command()


def _center_x(entity: dict[str, Any]) -> float:
    return entity["x"] + entity["w"] / 2.0


class ReflexController:
    def __init__(self, rng: random.Random | None = None, reaction_range_ms: tuple[int, int] = (80, 220)):
        self._rng = rng or random.Random()
        self._reaction_range = reaction_range_ms
        self._strategy = "balanced"
        self._lock = threading.Lock()
        self._next_decision = 0.0
        self._last = IDLE

    @property
    def strategy(self) -> str:
        with self._lock:
            return self._strategy

    def set_strategy(self, strategy: str) -> None:
        if strategy in STRATEGIES:
            with self._lock:
                self._strategy = strategy

    def decide(self, state: dict[str, Any], now: float | None = None) -> Command:
        """Devolve o comando atual. Reavalia a situação apenas após o atraso de reação."""
        now = time.monotonic() if now is None else now
        if state.get("over") or state.get("paused") or state.get("phase") == "countdown":
            self._last = IDLE
            return IDLE
        if now < self._next_decision:
            return self._last

        low, high = self._reaction_range
        self._next_decision = now + self._rng.uniform(low, high) / 1000.0
        self._last = self._think(state, self.strategy)
        return self._last

    # ---------------------------------------------------------------------------------
    def _think(self, state: dict[str, Any], strategy: str) -> Command:
        me, foe = state["self"], state["opponent"]
        gap = _center_x(foe) - _center_x(me)
        dist = abs(gap)
        toward = 1 if gap >= 0 else -1
        reach = max(40.0, me.get("reach", 80.0))
        arena_w = state["arena"]["w"]
        # Encurralado: encostado em uma parede, com o oponente do lado oposto.
        cornered = (me["x"] < 40 and toward == 1) or (me["x"] + me["w"] > arena_w - 40 and toward == -1)
        can_attack = not me.get("attacking") and not me.get("hurt")
        foe_attacking = bool(foe.get("attacking"))
        foe_above = (foe["y"] + foe["h"]) < (me["y"] - 25)
        grounded = me.get("grounded", True)
        wants_jump = grounded and (foe_above and dist < reach * 2.0) and self._rng.random() < 0.5
        # Leitura em tempo real do oponente: quem está na recuperação de um golpe está aberto;
        # quem está invulnerável (após ser atingido) não adianta golpear.
        foe_invulnerable = bool(foe.get("invulnerable"))
        foe_open = foe_attacking and foe.get("cooldown", 0.0) > 0.6 and not foe_invulnerable
        can_attack = can_attack and not foe_invulnerable
        panic = me["hp"] / me["max_hp"] < 0.2 and foe["hp"] / foe["max_hp"] > 0.3

        if strategy == "idle":
            return IDLE

        if foe_open and strategy in ("aggressive", "balanced") and dist <= reach * 1.7 and not panic:
            # Janela de punição: avança e golpeia assim que estiver ao alcance.
            if dist > reach * 0.85:
                return Command(move=toward, jump=wants_jump)
            return Command(move=0, attack=can_attack)

        if strategy == "aggressive":
            if dist > reach * 0.85:
                return Command(move=toward, jump=wants_jump)
            return Command(move=0, jump=wants_jump, attack=can_attack)

        if strategy == "defensive":
            danger = foe_attacking and dist < reach * 1.4
            if danger:
                return Command(move=-toward, jump=me.get("grounded", True) and self._rng.random() < 0.4)
            if dist <= reach and not foe_attacking:
                return Command(move=0, attack=can_attack)
            if dist < reach * 1.6:
                return Command(move=-toward)
            if dist > reach * 2.4:
                return Command(move=toward)
            return IDLE

        if strategy == "retreat":
            if cornered and dist <= reach:
                return Command(move=0, jump=me.get("grounded", True), attack=can_attack)
            if cornered:
                return IDLE
            return Command(move=-toward, jump=me.get("grounded", True) and dist < reach * 1.2 and self._rng.random() < 0.3)

        # balanced
        if panic and foe_attacking and dist < reach * 1.5:
            return Command(move=-toward, jump=grounded and self._rng.random() < 0.5)
        if dist > reach * 1.05:
            return Command(move=toward, jump=wants_jump)
        if dist < reach * 0.45 and self._rng.random() < 0.35:
            return Command(move=-toward)
        return Command(move=0, jump=wants_jump, attack=can_attack)
