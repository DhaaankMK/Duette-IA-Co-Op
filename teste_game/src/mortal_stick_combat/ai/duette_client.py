"""Cliente da ponte do Duette (somente biblioteca padrão).

Quando o jogo é iniciado pelo Duette, as variáveis de ambiente DUETTE_BRIDGE_* estão
definidas e este cliente conecta em 127.0.0.1, envia o estado da partida e recebe os
comandos do Player 2 (IA). Sem as variáveis, o jogo funciona normalmente, só com humanos.

Toda a rede roda em uma thread própria: o laço do jogo nunca bloqueia.
"""

import json
import math
import os
import socket
import threading
import time
from collections import deque

PROTOCOL_VERSION = 1
SEND_INTERVAL = 1.0 / 20.0     # no máximo 20 estados por segundo
COMMAND_TTL = 0.5              # comando "velho" é descartado (IA parada = personagem parado)
SAY_DURATION = 3.5
MAX_EVENTS = 12
VALID_EVENTS = ("hit", "whiff", "ko", "low_hp", "combo", "round", "land", "jump")
MAX_LINE = 16 * 1024
GAME_NAME = "Mortal Stick Combat"

_client = None
_client_resolved = False
LOG_PATH = os.environ.get("DUETTE_GAME_LOG", "")
MAX_LOG_BYTES = 500 * 1024


def _log(message):
    """Registra em DUETTE_GAME_LOG (definido pelo Duette); nunca interrompe o jogo."""
    if not LOG_PATH:
        return
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write("%s | jogo | %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass


def get_client():
    """Cliente único do processo (ou None se o jogo não foi iniciado pelo Duette)."""
    global _client, _client_resolved
    if not _client_resolved:
        _client_resolved = True
        _client = DuetteClient.from_env()
    return _client


class AIKeys:
    """Substitui ``pygame.key.get_pressed()`` para o personagem controlado pela IA."""

    def __init__(self, real_keys, overrides):
        self._real = real_keys
        self._overrides = overrides

    def __getitem__(self, key):
        if key in self._overrides:
            return self._overrides[key]
        return self._real[key]


class DuetteClient:
    def __init__(self, host, port, token):
        self._addr = (host, port)
        self._token = token
        self._lock = threading.Lock()
        self._command = {"move": 0, "jump": False, "attack": False}
        self._command_time = 0.0
        self._say = ""
        self._say_until = 0.0
        self._says = deque(maxlen=6)       # histórico: dicts com texto, nome e instante
        self._name = "IA"
        self._strategy = ""
        self._events = deque(maxlen=32)
        self._outbox = None
        self._connected = False
        self._last_submit = 0.0
        self._last_error = ""
        self._stop = threading.Event()
        self._wake = threading.Event()
        threading.Thread(target=self._run, name="duette-client", daemon=True).start()

    @classmethod
    def from_env(cls):
        host = os.environ.get("DUETTE_BRIDGE_HOST", "")
        port = os.environ.get("DUETTE_BRIDGE_PORT", "")
        token = os.environ.get("DUETTE_BRIDGE_TOKEN", "")
        if host != "127.0.0.1" or not port.isdigit() or not token:
            _log("Ponte do Duette não configurada (variáveis ausentes ou inválidas): jogo roda sem IA")
            return None
        port = int(port)
        if not 1024 <= port <= 65535:
            _log("Porta da ponte fora da faixa permitida: %d" % port)
            return None
        _log("Cliente criado; ponte em %s:%d" % (host, port))
        return cls(host, port, token)

    # ------------------------------------------------------------------ API do jogo
    @property
    def connected(self):
        return self._connected

    def submit_state(self, state):
        """Enfileira o estado mais recente (descarta o anterior não enviado)."""
        now = time.monotonic()
        if now - self._last_submit < SEND_INTERVAL:
            return
        self._last_submit = now
        with self._lock:
            self._outbox = state
        self._wake.set()

    def build_keys(self, real_keys, controls):
        """Chaves efetivas do personagem da IA, com base no último comando recebido."""
        with self._lock:
            fresh = time.monotonic() - self._command_time < COMMAND_TTL
            cmd = self._command if fresh else {"move": 0, "jump": False, "attack": False}
            move, jump, attack = cmd["move"], cmd["jump"], cmd["attack"]
        return AIKeys(real_keys, {
            controls["left"]: move < 0,
            controls["right"]: move > 0,
            controls["jump"]: jump,
            controls["punch"]: attack,
        })

    def push_event(self, kind, who, value=0.0):
        """Registra um evento discreto (golpe, KO...) que irá junto do próximo estado enviado."""
        if kind in VALID_EVENTS and who in ("self", "opponent"):
            with self._lock:
                self._events.append({"k": kind, "who": who, "v": round(float(value), 1)})

    def messages(self):
        """Falas recentes da IA (mais antigas primeiro), com a idade em segundos."""
        now = time.monotonic()
        with self._lock:
            return [{"text": m["text"], "name": m["name"], "age": now - m["time"]} for m in self._says]

    @property
    def ai_name(self):
        with self._lock:
            return self._name

    @property
    def strategy(self):
        with self._lock:
            return self._strategy

    def current_say(self):
        with self._lock:
            return self._say if time.monotonic() < self._say_until else ""

    def close(self):
        self._stop.set()
        self._wake.set()

    # ------------------------------------------------------------------ rede
    def _run(self):
        while not self._stop.is_set():
            try:
                with socket.create_connection(self._addr, timeout=3) as sock:
                    self._session(sock)
            except OSError as exc:
                if str(exc) != self._last_error:
                    self._last_error = str(exc)
                    _log("Erro de conexão com a ponte: %s" % exc)
            if self._connected:
                _log("Desconectado da ponte")
            self._connected = False
            self._stop.wait(1.5)

    def _session(self, sock):
        sock.settimeout(0.2)
        self._send(sock, {"type": "hello", "token": self._token, "game": GAME_NAME,
                          "protocol": PROTOCOL_VERSION})
        self._connected = True
        self._last_error = ""
        with self._lock:
            self._events.clear()
        _log("Conectado à ponte; handshake enviado")
        buffer = b""
        while not self._stop.is_set():
            self._wake.wait(0.1)
            self._wake.clear()
            with self._lock:
                state, self._outbox = self._outbox, None
            if state is not None:
                with self._lock:
                    events = [self._events.popleft() for _ in range(min(MAX_EVENTS, len(self._events)))]
                self._send(sock, dict(state, type="state", events=events))
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                buffer += chunk
            except socket.timeout:
                pass
            if len(buffer) > MAX_LINE:
                return
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                self._handle(line)

    @staticmethod
    def _send(sock, message):
        sock.sendall((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))

    def _handle(self, line):
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        if kind == "command":
            move = message.get("move")
            move = move if move in (-1, 0, 1) and not isinstance(move, bool) else 0
            with self._lock:
                self._command = {"move": move, "jump": message.get("jump") is True,
                                 "attack": message.get("attack") is True}
                self._command_time = time.monotonic()
        elif kind == "say":
            text = message.get("text")
            if isinstance(text, str):
                text = "".join(ch for ch in text if ch.isprintable())[:140]
                name = message.get("name")
                with self._lock:
                    if isinstance(name, str) and name.strip():
                        self._name = "".join(ch for ch in name if ch.isprintable())[:24]
                    now = time.monotonic()
                    self._say = text
                    self._say_until = now + SAY_DURATION
                    if text:
                        self._says.append({"text": text, "name": self._name, "time": now})
        elif kind == "status":
            name, strategy = message.get("name"), message.get("strategy")
            with self._lock:
                if isinstance(name, str) and name.strip():
                    self._name = "".join(ch for ch in name if ch.isprintable())[:24]
                if strategy in ("aggressive", "balanced", "defensive", "retreat", "idle"):
                    self._strategy = strategy


def entity_snapshot(player):
    """Dados de um personagem no formato do protocolo (somente números e booleanos)."""
    def num(value):
        value = float(value)
        return value if math.isfinite(value) else 0.0
    return {
        "x": num(player.x), "y": num(player.y), "w": num(player.width), "h": num(player.height),
        "hp": num(player.health), "max_hp": num(max(1.0, player.max_health)),
        "vx": num(player.vel_x), "vy": num(player.vel_y),
        "grounded": bool(player.is_grounded), "attacking": bool(player.punching),
        "hurt": bool(player.hurt_timer > 0), "facing": -1 if player.facing < 0 else 1,
        "reach": num(player.weapon_info["range"] + 24),
        "cooldown": num(max(0.0, min(1.0, player.attack_cooldown_fraction))),
        "jumps": int(max(0, player.jumps_left)),
        "damage": num(player.weapon_info["damage"]), "speed": num(player.MAX_SPEED_X),
        "invulnerable": bool(player.invulnerable_timer > 0 or player.admin_invulnerable),
        "weapon": str(player.weapon_name)[:24], "style": str(player.style_name)[:24],
    }
