"""Ponte local entre o Duette e o jogo.

Protocolo: JSON delimitado por quebra de linha (NDJSON) sobre TCP em 127.0.0.1.

Segurança:
  * Escuta somente em loopback, em porta aleatória; nunca aceita conexões da rede.
  * Autenticação por token aleatório (passado ao jogo por variável de ambiente), comparado em
    tempo constante; o handshake precisa ocorrer em poucos segundos.
  * Apenas um cliente por vez; linhas e taxa de mensagens limitadas; todo número recebido é
    validado, limitado a faixas seguras e rejeitado se não for finito.

Mensagens do jogo ➜ Duette:
  {"type":"hello","token":"...","game":"nome","protocol":1}
  {"type":"state", "arena":{"w","h"}, "self":{...}, "opponent":{...}, "over":bool, "paused":bool,
   "phase":"countdown|fight|over", "match":{...}, "events":[{"k":"hit","who":"self|opponent","v":n}]}
Mensagens do Duette ➜ jogo:
  {"type":"command","move":-1|0|1,"jump":bool,"attack":bool}
  {"type":"say","text":"...","name":"..."}
  {"type":"status","name":"...","strategy":"..."}

Campos extras (todos opcionais, para manter compatibilidade com jogos que enviam o básico):
  entidade: cooldown (0..1), jumps, damage, speed, invulnerable, weapon, style
  match:    time, hits_self, hits_opponent, dmg_self, dmg_opponent, combo_self, combo_opponent
  eventos:  hit, whiff, ko, low_hp, combo, round, land, jump (limitados a 12 por mensagem)
"""

from __future__ import annotations

import hmac
import json
import math
import secrets
import socket
import threading
import time
from typing import Any, Callable

from .ai_engine import MAX_SAY_CHARS, STRATEGIES, sanitize_text
from .logger import get_logger
from .tactics import Command

log = get_logger("bridge")

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 16 * 1024
HANDSHAKE_TIMEOUT = 5.0
IDLE_TIMEOUT = 15.0
MAX_MESSAGES_PER_SECOND = 60

_ENTITY_FIELDS = {
    # campo: (mínimo, máximo)
    "x": (-5000.0, 5000.0),
    "y": (-5000.0, 5000.0),
    "w": (1.0, 2000.0),
    "h": (1.0, 2000.0),
    "hp": (0.0, 100000.0),
    "max_hp": (1.0, 100000.0),
    "vx": (-1000.0, 1000.0),
    "vy": (-1000.0, 1000.0),
    "reach": (0.0, 2000.0),
}
_ENTITY_OPTIONAL = {
    "cooldown": (0.0, 1.0),
    "jumps": (0.0, 20.0),
    "damage": (0.0, 100000.0),
    "speed": (0.0, 1000.0),
}
_ENTITY_BOOLS = ("grounded", "attacking", "hurt", "invulnerable")
_ENTITY_TEXT = {"weapon": 24, "style": 24}
_MATCH_FIELDS = {
    "time": (0.0, 86400.0),
    "hits_self": (0.0, 100000.0),
    "hits_opponent": (0.0, 100000.0),
    "dmg_self": (0.0, 10000000.0),
    "dmg_opponent": (0.0, 10000000.0),
    "combo_self": (0.0, 1000.0),
    "combo_opponent": (0.0, 1000.0),
}
PHASES = ("countdown", "fight", "over")
EVENT_KINDS = ("hit", "whiff", "ko", "low_hp", "combo", "round", "land", "jump")
EVENT_WHO = ("self", "opponent")
MAX_EVENTS_PER_STATE = 12


def _number(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return max(low, min(high, value))


def _parse_entity(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for name, (low, high) in _ENTITY_FIELDS.items():
        if name in raw:
            number = _number(raw[name], low, high)
            if number is None:
                return None
            out[name] = number
    for required in ("x", "y", "w", "h"):
        if required not in out:
            return None
    for name, (low, high) in _ENTITY_OPTIONAL.items():
        if name in raw:
            number = _number(raw[name], low, high)
            if number is not None:  # campo opcional inválido é apenas ignorado
                out[name] = number
    for name, limit in _ENTITY_TEXT.items():
        value = raw.get(name)
        if isinstance(value, str):
            out[name] = sanitize_text(value, limit)
    for name in _ENTITY_BOOLS:
        out[name] = bool(raw.get(name, False))
    facing = raw.get("facing", 1)
    out["facing"] = -1 if facing == -1 else 1
    out.setdefault("hp", 0.0)
    out.setdefault("max_hp", max(1.0, out["hp"]))
    out.setdefault("reach", 80.0)
    return out


def parse_state(raw: Any) -> dict[str, Any] | None:
    """Valida e normaliza uma mensagem ``state``. Retorna ``None`` se for inválida."""
    if not isinstance(raw, dict):
        return None
    arena = raw.get("arena")
    if not isinstance(arena, dict):
        return None
    width = _number(arena.get("w"), 100.0, 10000.0)
    height = _number(arena.get("h"), 100.0, 10000.0)
    me, foe = _parse_entity(raw.get("self")), _parse_entity(raw.get("opponent"))
    if None in (width, height, me, foe):
        return None
    over = bool(raw.get("over", False))
    phase = raw.get("phase")
    if phase not in PHASES:
        phase = "over" if over else "fight"
    return {
        "arena": {"w": width, "h": height},
        "self": me,
        "opponent": foe,
        "over": over,
        "paused": bool(raw.get("paused", False)),
        "phase": phase,
        "match": _parse_match(raw.get("match")),
        "events": _parse_events(raw.get("events")),
    }


def _parse_match(raw: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(raw, dict):
        for name, (low, high) in _MATCH_FIELDS.items():
            if name in raw:
                number = _number(raw[name], low, high)
                if number is not None:
                    out[name] = number
    return out


def _parse_events(raw: Any) -> list[dict[str, Any]]:
    """Eventos discretos (golpe, KO...). Itens inválidos são descartados; a lista é limitada."""
    events: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return events
    for item in raw[:MAX_EVENTS_PER_STATE]:
        if not isinstance(item, dict) or item.get("k") not in EVENT_KINDS or item.get("who") not in EVENT_WHO:
            continue
        value = _number(item.get("v", 0), 0.0, 1000000.0)
        events.append({"k": item["k"], "who": item["who"], "v": 0.0 if value is None else value})
    return events


class BridgeServer:
    """Servidor TCP local. ``on_state`` recebe o estado validado e devolve o ``Command``."""

    def __init__(
        self,
        on_state: Callable[[dict[str, Any]], Command | None],
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        host: str = "127.0.0.1",
    ):
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("A ponte só pode escutar em loopback.")
        self._on_state = on_state
        self._on_event = on_event or (lambda kind, data: None)
        self._host = "127.0.0.1" if host == "localhost" else host
        self.token = secrets.token_urlsafe(32)
        self.port = 0
        self._server: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: socket.socket | None = None
        self._client_lock = threading.Lock()
        self._send_lock = threading.Lock()

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> int:
        if self._thread:
            return self.port
        self._server = socket.create_server((self._host, 0), family=socket.AF_INET6 if ":" in self._host else socket.AF_INET)
        self._server.settimeout(0.5)
        self.port = self._server.getsockname()[1]
        log.info("Ponte escutando em %s:%d (somente loopback)", self._host, self.port)
        self._thread = threading.Thread(target=self._accept_loop, name="duette-bridge", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        with self._client_lock:
            if self._client:
                self._close(self._client)
        if self._server:
            self._close(self._server)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None

    @property
    def connected(self) -> bool:
        with self._client_lock:
            return self._client is not None

    def environment(self) -> dict[str, str]:
        """Variáveis de ambiente que o jogo precisa para se conectar."""
        return {
            "DUETTE_BRIDGE_HOST": self._host,
            "DUETTE_BRIDGE_PORT": str(self.port),
            "DUETTE_BRIDGE_TOKEN": self.token,
        }

    # ------------------------------------------------------------------ envio
    def send(self, message: dict[str, Any]) -> bool:
        with self._client_lock:
            client = self._client
        if client is None:
            return False
        data = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._send_lock:
                client.sendall(data)
            return True
        except OSError:
            return False

    def say(self, text: str, name: str = "") -> bool:
        text = sanitize_text(text, MAX_SAY_CHARS)
        message: dict[str, Any] = {"type": "say", "text": text}
        name = sanitize_text(name, 24)
        if name:
            message["name"] = name
        return bool(text) and self.send(message)

    def status(self, name: str = "", strategy: str = "") -> bool:
        """Informa ao jogo o nome da IA e a estratégia atual (para exibir no HUD)."""
        message: dict[str, Any] = {"type": "status"}
        name = sanitize_text(name, 24)
        if name:
            message["name"] = name
        if strategy in STRATEGIES:
            message["strategy"] = strategy
        return len(message) > 1 and self.send(message)

    # ------------------------------------------------------------------ interno
    @staticmethod
    def _close(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def _accept_loop(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                conn, _addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._client_lock:
                busy = self._client is not None
            log.debug("Conexão recebida de %s:%s (ocupado=%s)", _addr[0], _addr[1], busy)
            if busy:
                log.warning("Conexão recusada: já existe um jogo conectado")
                self._close(conn)
                continue
            threading.Thread(target=self._serve, args=(conn,), name="duette-bridge-client", daemon=True).start()

    def _read_line(self, conn: socket.socket, buffer: bytearray) -> dict[str, Any] | None:
        """Lê uma linha JSON. Levanta ``ConnectionError`` em violações do protocolo."""
        while b"\n" not in buffer:
            if len(buffer) > MAX_LINE_BYTES:
                raise ConnectionError("linha excede o limite")
            chunk = conn.recv(4096)
            if not chunk:
                raise ConnectionError("conexão encerrada")
            buffer.extend(chunk)
        line, _, rest = bytes(buffer).partition(b"\n")
        buffer[:] = rest
        if len(line) > MAX_LINE_BYTES:
            raise ConnectionError("linha excede o limite")
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ConnectionError("JSON inválido") from None
        if not isinstance(message, dict):
            raise ConnectionError("mensagem inválida")
        return message

    def _serve(self, conn: socket.socket) -> None:
        buffer = bytearray()
        authenticated = False
        game_name = "jogo"
        try:
            conn.settimeout(HANDSHAKE_TIMEOUT)
            hello = self._read_line(conn, buffer)
            token = hello.get("token") if hello else None
            if (
                not hello
                or hello.get("type") != "hello"
                or hello.get("protocol") != PROTOCOL_VERSION
                or not isinstance(token, str)
                or not hmac.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))
            ):
                log.warning("Handshake recusado: tipo=%r protocolo=%r token_ok=%s",
                            (hello or {}).get("type"), (hello or {}).get("protocol"),
                            isinstance(token, str) and hmac.compare_digest(token.encode(), self.token.encode()))
                raise ConnectionError("handshake recusado")
            authenticated = True
            game_name = sanitize_text(hello.get("game", "jogo"), 60) or "jogo"
            with self._client_lock:
                if self._client is not None:
                    raise ConnectionError("já existe um jogo conectado")
                self._client = conn
            log.info("Jogo conectado: %s", game_name)
            self._on_event("connected", {"game": game_name})

            conn.settimeout(1.0)
            last_message = time.monotonic()
            window_start, window_count = time.monotonic(), 0
            stats = {"estados": 0, "invalidos": 0, "descartados": 0}
            stats_time = time.monotonic()
            while not self._stop.is_set():
                try:
                    message = self._read_line(conn, buffer)
                except socket.timeout:
                    if time.monotonic() - last_message > IDLE_TIMEOUT:
                        raise ConnectionError("tempo limite de inatividade")
                    continue
                last_message = time.monotonic()
                if last_message - window_start >= 1.0:
                    window_start, window_count = last_message, 0
                window_count += 1
                if window_count > MAX_MESSAGES_PER_SECOND:
                    stats["descartados"] += 1
                    continue  # excesso: descarta
                if message and message.get("type") == "state":
                    state = parse_state(message)
                    if state is None:
                        stats["invalidos"] += 1
                        if stats["invalidos"] in (1, 10, 100):
                            log.warning("Estado inválido recebido (total %d)", stats["invalidos"])
                        continue
                    stats["estados"] += 1
                    if last_message - stats_time >= 15.0:
                        log.debug("Resumo da ponte (15 s): %s", stats)
                        stats_time = last_message
                    command = self._on_state(state)
                    if command is not None:
                        self.send(command.to_message())
        except (ConnectionError, OSError) as exc:
            log.info("Sessão da ponte encerrada: %s", exc)
        finally:
            was_client = False
            with self._client_lock:
                if self._client is conn:
                    self._client = None
                    was_client = True
            self._close(conn)
            if authenticated and was_client:
                log.info("Jogo desconectado: %s", game_name)
                self._on_event("disconnected", {"game": game_name})
