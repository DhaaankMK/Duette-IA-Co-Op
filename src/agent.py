"""Sessão do Player 2: une ponte com o jogo, reflexos locais e a IA.

``PlayerTwoSession`` é independente da interface gráfica: comunica-se com ela apenas pelo
callback ``on_event`` (que será chamado de threads secundárias).
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any, Callable

from .ai_engine import AIError, CompanionAI
from .bridge import BridgeServer
from .logger import get_logger
from .tactics import Command, ReflexController

log = get_logger("agent")

EventCallback = Callable[[str, dict[str, Any]], None]


EVENT_MEMORY_SECONDS = 10.0
MAX_REMEMBERED_EVENTS = 24
URGENT_MIN_GAP = 3.0          # intervalo mínimo entre decisões disparadas por eventos
HP_HISTORY_SECONDS = 6.0


def describe_event(event: dict[str, Any]) -> str:
    """Frase curta em português para um evento do jogo (usada no contexto do modelo)."""
    mine = event["who"] == "self"
    kind, value = event["k"], int(round(event.get("v", 0)))
    if kind == "hit":
        return f"acertei um golpe (-{value} de vida do oponente)" if mine else f"o oponente me acertou (-{value} de vida)"
    if kind == "whiff":
        return "errei um golpe" if mine else "o oponente errou um golpe"
    if kind == "ko":
        return "fui nocauteada" if mine else "nocauteei o oponente"
    if kind == "low_hp":
        return "minha vida está crítica" if mine else "a vida do oponente está crítica"
    if kind == "combo":
        return f"fiz um combo de {value} golpes" if mine else f"o oponente fez um combo de {value} golpes"
    if kind == "round":
        return "uma nova luta começou"
    if kind == "jump":
        return "pulei" if mine else "o oponente pulou"
    if kind == "land":
        return "aterrissei" if mine else "o oponente aterrissou"
    return kind


def _is_urgent(event: dict[str, Any]) -> bool:
    kind, mine = event["k"], event["who"] == "self"
    if kind == "hit":
        return not mine or event.get("v", 0) >= 25
    return kind in ("ko", "low_hp", "round") or (kind == "combo" and event.get("v", 0) >= 3)


def summarize_state(state: dict[str, Any] | None) -> str | None:
    """Resumo curto do estado para o chat (a IA responde sabendo como está a partida)."""
    if not state:
        return None
    return json.dumps(PlayerTwoSession._brief(state, []), ensure_ascii=False, separators=(",", ":"))


class PlayerTwoSession:
    def __init__(
        self,
        ai: CompanionAI | None,
        on_event: EventCallback | None = None,
        strategy_interval: float = 2.5,
    ):
        self.ai = ai
        self._emit = on_event or (lambda kind, data: None)
        self._interval = max(0.5, strategy_interval)
        self.controller = ReflexController()
        self.server = BridgeServer(self._on_state, self._on_bridge_event)
        self._latest: dict[str, Any] | None = None
        self._latest_time = 0.0
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._error_streak = 0
        self._last_error_event = 0.0
        self._last_decision = 0.0
        self._started = False
        self._events: deque[tuple[float, dict[str, Any]]] = deque(maxlen=MAX_REMEMBERED_EVENTS)
        self._hp_history: deque[tuple[float, float]] = deque(maxlen=64)
        self._urgent = False

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> dict[str, str]:
        """Inicia a ponte e a thread de estratégia (idempotente). Devolve o ambiente para o jogo."""
        if self._started:
            return self.server.environment()
        self._started = True
        log.info("Sessão iniciada (IA %s)", "disponível" if self.ai is not None else "indisponível: só reflexos locais")
        self.server.start()
        if self.ai is not None:
            self._worker = threading.Thread(target=self._strategy_loop, name="duette-strategy", daemon=True)
            self._worker.start()
        return self.server.environment()

    def stop(self) -> None:
        log.info("Sessão encerrada")
        self._stop.set()
        self._wake.set()
        self.server.stop()
        if self._worker:
            self._worker.join(timeout=3.0)

    @property
    def started(self) -> bool:
        return self._started

    @property
    def game_connected(self) -> bool:
        return self.server.connected

    @property
    def bot_name(self) -> str:
        return self.ai.profile.normalized().bot_name if self.ai is not None else "IA"

    # ------------------------------------------------------------------ chat
    def chat(self, text: str) -> str:
        if self.ai is None:
            raise AIError("A IA não está disponível (sem chave válida).")
        with self._state_lock:
            context = summarize_state(self._latest) if time.monotonic() - self._latest_time < 10 else None
        reply = self.ai.chat(text, context)
        self.server.say(reply, self.bot_name)
        return reply

    # ------------------------------------------------------------------ interno
    def _on_state(self, state: dict[str, Any]) -> Command:
        now = time.monotonic()
        urgent = False
        with self._state_lock:
            self._latest = state
            self._latest_time = now
            for event in state.get("events", ()):
                if event["k"] in ("jump", "land"):
                    continue  # ruído: serve só para reflexos, não para o modelo
                self._events.append((now, event))
                urgent = urgent or _is_urgent(event)
            me = state["self"]
            self._hp_history.append((now, 100.0 * me["hp"] / me["max_hp"]))
        if urgent and self.ai is not None:
            self._urgent = True
            self._wake.set()
        return self.controller.decide(state)

    def _on_bridge_event(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "connected":
            self.server.status(self.bot_name, self.controller.strategy)
        if kind == "disconnected":
            with self._state_lock:
                self._latest = None
                self._events.clear()
                self._hp_history.clear()
        self._emit(kind, data)

    def _strategy_loop(self) -> None:
        assert self.ai is not None
        while not self._stop.is_set():
            self._wake.wait(self._interval + min(self._error_streak, 5) * 2.0)
            if self._stop.is_set():
                break
            urgent, self._urgent = self._urgent, False
            self._wake.clear()
            now = time.monotonic()
            if urgent:
                # Decisão disparada por evento: respeita um intervalo mínimo (limites de taxa
                # do provedor) e é ignorada se a IA estiver falhando.
                if self._error_streak or now - self._last_decision < URGENT_MIN_GAP:
                    continue
            with self._state_lock:
                state, age = self._latest, now - self._latest_time
                recent = [(now - t, e) for t, e in self._events if now - t <= EVENT_MEMORY_SECONDS]
                trend = self._hp_trend(now)
            if state is None or age > 3.0 or state["over"] or state["paused"] or state.get("phase") == "countdown":
                continue
            self._last_decision = now
            brief = self._brief(state, recent)
            brief["tendencia_da_minha_vida"] = trend
            try:
                decision = self.ai.choose_strategy(brief)
            except AIError as exc:
                self._error_streak += 1
                log.warning("Falha ao obter estratégia (sequência de %d): %s", self._error_streak, exc)
                now = time.monotonic()
                if now - self._last_error_event > 15.0:
                    self._last_error_event = now
                    self._emit("ai_error", {"message": str(exc)})
                continue
            if self._error_streak:
                log.info("IA voltou a responder após %d falha(s)", self._error_streak)
            self._error_streak = 0
            if decision["strategy"] != self.controller.strategy:
                log.info("Estratégia: %s -> %s%s", self.controller.strategy, decision["strategy"],
                         " (disparada por evento)" if urgent else "")
                self.server.status(self.bot_name, decision["strategy"])
            self.controller.set_strategy(decision["strategy"])
            self._emit("strategy", {"strategy": decision["strategy"]})
            if decision["say"]:
                self.server.say(decision["say"], self.bot_name)
                self._emit("say", {"text": decision["say"]})

    def _hp_trend(self, now: float) -> str:
        """Compara a vida atual com a de alguns segundos atrás (chamado com o lock tomado)."""
        old = [hp for t, hp in self._hp_history if now - t >= HP_HISTORY_SECONDS - 1.5]
        if not old or not self._hp_history:
            return "estavel"
        delta = self._hp_history[-1][1] - old[0]
        return "caindo" if delta < -8 else "subindo" if delta > 8 else "estavel"

    @staticmethod
    def _brief(state: dict[str, Any], recent: list[tuple[float, dict[str, Any]]]) -> dict[str, Any]:
        """Resumo compacto e em português do que está acontecendo, para o modelo."""
        me, foe = state["self"], state["opponent"]
        match = state.get("match", {})
        gap = (foe["x"] + foe["w"] / 2) - (me["x"] + me["w"] / 2)
        arena_w = state["arena"]["w"]
        brief: dict[str, Any] = {
            "fase": {"countdown": "contagem", "fight": "luta", "over": "fim"}.get(state.get("phase", "fight"), "luta"),
            "minha_vida_pct": round(100 * me["hp"] / me["max_hp"]),
            "vida_oponente_pct": round(100 * foe["hp"] / foe["max_hp"]),
            "distancia": round(abs(gap)),
            "alcance_do_meu_golpe": round(me["reach"]),
            "alcance_do_oponente": round(foe["reach"]),
            "oponente_atacando": foe["attacking"],
            "estou_atacando": me["attacking"],
            "oponente_esta_" + ("a_direita" if gap > 0 else "a_esquerda"): True,
            "meu_golpe_pronto": me.get("cooldown", 0.0) <= 0.05 and not me["attacking"],
            "oponente_vulneravel": bool(foe["hurt"] or (foe["attacking"] and foe.get("cooldown", 0.0) > 0.6)),
            "oponente_invulneravel": bool(foe.get("invulnerable")),
            "estou_no_ar": not me["grounded"],
            "encurralada": (me["x"] < 50 and gap > 0) or (me["x"] + me["w"] > arena_w - 50 and gap < 0),
        }
        for key, source in (("minha_arma", me), ("arma_do_oponente", foe)):
            if source.get("weapon"):
                brief[key] = source["weapon"]
        if match:
            brief["placar"] = {
                "tempo_s": round(match.get("time", 0)),
                "meus_golpes": round(match.get("hits_self", 0)),
                "golpes_do_oponente": round(match.get("hits_opponent", 0)),
                "meu_combo": round(match.get("combo_self", 0)),
                "combo_do_oponente": round(match.get("combo_opponent", 0)),
            }
        if recent:
            brief["eventos_recentes"] = [
                {"ha_s": round(age, 1), "o_que": describe_event(event)} for age, event in recent[-6:]
            ]
        return brief
