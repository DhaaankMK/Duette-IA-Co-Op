"""Diagnóstico de ambiente e de rede, para localizar a causa de falhas de conexão com a IA."""

from __future__ import annotations

import os
import platform
import socket
import ssl
import sys
import time
import urllib.request
from dataclasses import dataclass

from . import APP_NAME, APP_VERSION
from .ai_engine import PROVIDERS, KeyStatus, explain_network_error, mask_key, validate_api_key
from .logger import get_logger, log_file, read_tail, redact

log = get_logger("diag")


@dataclass
class ProbeStep:
    name: str
    ok: bool
    detail: str
    ms: int | None = None

    def line(self) -> str:
        mark = "OK  " if self.ok else "FALHA"
        timing = f" ({self.ms} ms)" if self.ms is not None else ""
        return f"[{mark}] {self.name}{timing}: {self.detail}"


def _timed(func):
    start = time.monotonic()
    try:
        value = func()
        return True, value, int((time.monotonic() - start) * 1000)
    except Exception as exc:  # o objetivo é justamente descrever a falha
        return False, exc, int((time.monotonic() - start) * 1000)


def network_probe(provider: str, api_key: str = "", timeout: float = 10.0) -> list[ProbeStep]:
    """Testa, etapa por etapa, o caminho até o provedor: DNS, TCP, TLS e a própria API."""
    spec = PROVIDERS[provider]
    host = spec.host
    steps: list[ProbeStep] = []

    ok, value, ms = _timed(lambda: socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
    if ok:
        addresses = sorted({info[4][0] for info in value})
        steps.append(ProbeStep("DNS", True, f"{host} -> {', '.join(addresses[:3])}", ms))
    else:
        steps.append(ProbeStep("DNS", False, explain_network_error(value), ms))
        return _finish(provider, steps)

    sock_holder: dict[str, socket.socket] = {}

    def connect():
        sock_holder["s"] = socket.create_connection((host, 443), timeout=timeout)

    ok, value, ms = _timed(connect)
    steps.append(ProbeStep("Conexão TCP (porta 443)", ok, "conectado" if ok else explain_network_error(value), ms))
    if not ok:
        return _finish(provider, steps)

    def handshake():
        context = ssl.create_default_context()
        with context.wrap_socket(sock_holder["s"], server_hostname=host) as tls:
            cert = tls.getpeercert() or {}
            issuer = dict(x[0] for x in cert.get("issuer", ())).get("organizationName", "?")
            return f"{tls.version()}, emissor do certificado: {issuer}"

    ok, value, ms = _timed(handshake)
    steps.append(ProbeStep("Handshake TLS", ok, value if ok else explain_network_error(value), ms))
    try:
        sock_holder["s"].close()
    except OSError:
        pass
    if not ok:
        return _finish(provider, steps)

    if api_key:
        start = time.monotonic()
        result = validate_api_key(api_key, provider, timeout=timeout)
        ms = int((time.monotonic() - start) * 1000)
        healthy = result.status in (KeyStatus.VALID, KeyStatus.RATE_LIMITED)
        steps.append(ProbeStep("Chamada à API (listar modelos)", healthy,
                               f"{result.status.value}: {result.message}", ms))
    else:
        steps.append(ProbeStep("Chamada à API", False, "sem chave configurada; etapa ignorada"))
    return _finish(provider, steps)


def _finish(provider: str, steps: list[ProbeStep]) -> list[ProbeStep]:
    for step in steps:
        (log.info if step.ok else log.warning)("probe %s | %s", provider, step.line())
    return steps


def proxy_summary() -> str:
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        proxies = {}
    shown = {k: redact(v) for k, v in proxies.items() if k in ("http", "https", "all")}
    return ", ".join(f"{k}={v}" for k, v in shown.items()) if shown else "nenhum"


def build_report(storage, probe: list[ProbeStep] | None = None, log_lines: int = 150) -> str:
    """Relatório completo e seguro (sem chaves) para anexar em um pedido de suporte."""
    snap = storage.snapshot()
    profile = snap["ai_profile"]
    key = storage.get_api_key()
    lines = [
        f"== {APP_NAME} {APP_VERSION} - relatório de diagnóstico ==",
        f"Python {platform.python_version()} | {platform.platform()}",
        f"Pasta de dados: {storage.data_dir}",
        f"Arquivo de log: {log_file()}",
        f"Proxy do sistema: {proxy_summary()}",
        "",
        "-- Configuração --",
        f"Provedor: {profile['provider']}",
        f"Modelo definido pelo usuário: {profile['model'] or '(automático)'}",
        f"Modelo detectado: {storage.get_detected_model(profile['provider']) or '(nenhum)'}",
        f"Chave: {mask_key(key) if key else '(nenhuma)'} (guardada em: {storage.storage_mode()})",
        f"Termos aceitos: {snap['settings']['accepted_terms']}",
        f"Perfil: nome={profile['bot_name']!r} personalidade={profile['personality']}",
        "",
    ]
    if probe:
        lines += ["-- Teste de rede --"] + [s.line() for s in probe] + [""]
    lines += [f"-- Últimas {log_lines} linhas do log --", read_tail(log_lines)]
    return redact("\n".join(lines))


def open_in_file_manager(path) -> None:
    """Abre uma pasta no gerenciador de arquivos do sistema."""
    import subprocess

    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
