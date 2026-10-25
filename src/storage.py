"""Armazenamento persistente do Duette e health-check da chave de API.

Características:
  * Escrita atômica (arquivo temporário + ``os.replace``) com cópia de segurança ``.bak``.
  * Recuperação automática: arquivo corrompido é preservado como ``.corrupt-<data>`` e o
    ``.bak`` é usado; na ausência dele, são aplicados os valores padrão.
  * Dados sempre validados e normalizados na leitura (tipos, tamanhos e valores permitidos).
  * Chave de API guardada no chaveiro do sistema quando o pacote ``keyring`` está disponível;
    caso contrário, no ``config.json`` com permissão 0600 (POSIX). Atenção: nesse caso a chave
    NÃO é criptografada; a proteção depende das permissões da conta do usuário.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from . import ai_engine
from .ai_engine import ApiValidation, KeyStatus
from .logger import get_logger, register_secret
from .paths import license_path, user_data_dir

log = get_logger("storage")

SCHEMA_VERSION = 1
MAX_CONFIG_BYTES = 1024 * 1024
KEYRING_SERVICE = "Duette"
KEYRING_USER = "api_key"

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "settings": {
        "accepted_terms": False,
        "accepted_terms_at": None,
        "accepted_license_sha256": None,
        "last_login": None,
    },
    "ai_profile": {
        "provider": ai_engine.DEFAULT_PROVIDER,
        "model": "",
        "detected_models": {},
        "api_key": "",
        "key_in_keyring": False,
        "bot_name": "Duo",
        "avatar": "",
        "personality": ai_engine.DEFAULT_PERSONALITY,
        "custom_prompt": "",
    },
    "app_preferences": {
        "theme": "dark",
        "auto_launch_mods": True,
        "sound_enabled": True,
        "music_enabled": True,
        "sound_volume": 70,
        "game_paths": {},
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _as_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_str(value: Any, default: str, limit: int) -> str:
    return ai_engine.sanitize_text(value, limit) if isinstance(value, str) else default


def sanitize_config(raw: Any) -> dict[str, Any]:
    """Mescla com os padrões e força tipos e valores válidos. Nunca lança exceção."""
    merged = _deep_merge(DEFAULT_CONFIG, raw if isinstance(raw, dict) else {})
    d = DEFAULT_CONFIG

    s, ds = merged["settings"], d["settings"]
    if not isinstance(s, dict):
        s = copy.deepcopy(ds)
    s["accepted_terms"] = _as_bool(s.get("accepted_terms"), False)
    s["accepted_terms_at"] = _as_str(s.get("accepted_terms_at"), "", 40) or None
    s["accepted_license_sha256"] = _as_str(s.get("accepted_license_sha256"), "", 64) or None
    s["last_login"] = _as_str(s.get("last_login"), "", 40) or None

    a, da = merged["ai_profile"], d["ai_profile"]
    if not isinstance(a, dict):
        a = copy.deepcopy(da)
    a["provider"] = a.get("provider") if a.get("provider") in ai_engine.PROVIDERS else da["provider"]
    a["model"] = _as_str(a.get("model"), "", 100)
    detected = a.get("detected_models")
    a["detected_models"] = (
        {k: v[:100] for k, v in detected.items() if k in ai_engine.PROVIDERS and isinstance(v, str) and v.strip()}
        if isinstance(detected, dict)
        else {}
    )
    a["api_key"] = a["api_key"].strip() if isinstance(a.get("api_key"), str) else ""
    a["key_in_keyring"] = _as_bool(a.get("key_in_keyring"), False)
    a["bot_name"] = _as_str(a.get("bot_name"), da["bot_name"], ai_engine.MAX_BOT_NAME) or da["bot_name"]
    a["avatar"] = _as_str(a.get("avatar"), "", 300)
    a["personality"] = a.get("personality") if a.get("personality") in ai_engine.PERSONALITIES else da["personality"]
    a["custom_prompt"] = _as_str(a.get("custom_prompt"), "", ai_engine.MAX_CUSTOM_PROMPT)

    p, dp = merged["app_preferences"], d["app_preferences"]
    if not isinstance(p, dict):
        p = copy.deepcopy(dp)
    p["theme"] = p.get("theme") if p.get("theme") in ("dark", "light") else "dark"
    p["auto_launch_mods"] = _as_bool(p.get("auto_launch_mods"), True)
    p["sound_enabled"] = _as_bool(p.get("sound_enabled"), True)
    p["music_enabled"] = _as_bool(p.get("music_enabled"), True)
    volume = p.get("sound_volume")
    p["sound_volume"] = volume if isinstance(volume, int) and not isinstance(volume, bool) and 0 <= volume <= 100 else 70
    paths = p.get("game_paths")
    p["game_paths"] = (
        {k[:60]: v[:500] for k, v in paths.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(paths, dict)
        else {}
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "settings": s,
        "ai_profile": a,
        "app_preferences": p,
    }


def _import_keyring():
    try:
        import keyring  # type: ignore

        return keyring
    except Exception:  # pacote ausente ou backend indisponível
        return None


class Storage:
    """Gerencia o ``config.json`` do usuário com segurança de concorrência e de dados."""

    def __init__(self, data_dir: Path | None = None, use_keyring: bool = True):
        self.data_dir = Path(data_dir) if data_dir else user_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "config.json"
        self.backup_path = self.data_dir / "config.json.bak"
        self._lock = threading.RLock()
        self._use_keyring = use_keyring
        self.recovery_notice: str | None = None
        log.info("Abrindo armazenamento em %s (keyring solicitado=%s)", self.data_dir, use_keyring)
        self._data: dict[str, Any] = self._load()
        existing = self._data["ai_profile"]
        log.info("Configuração carregada: termos=%s provedor=%s modelo_usuario=%r chave=%s",
                 self._data["settings"]["accepted_terms"], existing["provider"], existing["model"],
                 "no keyring" if existing["key_in_keyring"] else ("no arquivo" if existing["api_key"] else "ausente"))
        if existing["api_key"]:
            register_secret(existing["api_key"])

    # ---------------------------------------------------------------- leitura / escrita
    def _read_file(self, path: Path) -> dict[str, Any] | None:
        try:
            if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
                return None
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            log.info("config.json inexistente: primeira execução, usando valores padrão")
            return sanitize_config({})

        data = self._read_file(self.path)
        if data is not None:
            return sanitize_config(data)
        log.error("config.json ilegível ou grande demais; tentando recuperar do backup")

        # Arquivo principal ilegível: preserva o original e tenta o backup.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            self.path.replace(self.data_dir / f"config.json.corrupt-{stamp}")
        except OSError:
            pass
        backup = self._read_file(self.backup_path)
        if backup is not None:
            log.warning("Configuração restaurada a partir do backup")
            self.recovery_notice = "A configuração estava corrompida e foi restaurada a partir do backup."
            return sanitize_config(backup)
        log.error("Backup também indisponível: configuração reiniciada com padrões")
        self.recovery_notice = "A configuração estava corrompida e foi reiniciada com os valores padrão."
        return sanitize_config({})

    def save(self) -> None:
        """Grava a configuração de forma atômica."""
        with self._lock:
            payload = json.dumps(self._data, ensure_ascii=False, indent=2)
            if self.path.exists():
                try:
                    data = self.path.read_bytes()
                    self._atomic_write(self.backup_path, data)
                except OSError:
                    pass
            try:
                self._atomic_write(self.path, payload.encode("utf-8"))
            except OSError as exc:
                log.error("Falha ao gravar config.json: %s", exc)
                raise
            log.debug("config.json gravado (%d bytes)", len(payload))

    def _atomic_write(self, target: Path, content: bytes) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "posix":
                os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ---------------------------------------------------------------- acesso a dados
    def snapshot(self) -> dict[str, Any]:
        """Cópia dos dados SEM a chave de API."""
        with self._lock:
            data = copy.deepcopy(self._data)
        data["ai_profile"]["api_key"] = ""
        return data

    def get(self, section: str, key: str) -> Any:
        with self._lock:
            return copy.deepcopy(self._data[section][key])

    def update(self, section: str, **values: Any) -> None:
        """Atualiza valores de uma seção, revalida tudo e persiste."""
        with self._lock:
            if section not in self._data:
                raise KeyError(f"Seção desconhecida: {section}")
            candidate = copy.deepcopy(self._data)
            candidate[section].update(values)
            self._data = sanitize_config(candidate)
            self.save()

    # ---------------------------------------------------------------- EULA
    @staticmethod
    def license_text() -> str:
        try:
            return license_path().read_text(encoding="utf-8")
        except OSError:
            return ""

    @staticmethod
    def license_hash() -> str:
        return hashlib.sha256(Storage.license_text().encode("utf-8")).hexdigest()

    @property
    def terms_accepted(self) -> bool:
        return bool(self.get("settings", "accepted_terms"))

    def accept_terms(self) -> None:
        log.info("Termos de licença aceitos (sha256 da licença: %s)", self.license_hash()[:12])
        self.update(
            "settings",
            accepted_terms=True,
            accepted_terms_at=_utc_now(),
            accepted_license_sha256=self.license_hash(),
        )

    # ---------------------------------------------------------------- chave de API
    def get_api_key(self) -> str:
        with self._lock:
            profile = self._data["ai_profile"]
            if profile["key_in_keyring"]:
                keyring = _import_keyring()
                if keyring is not None:
                    try:
                        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
                    except Exception:
                        return ""
                return ""
            return profile["api_key"]

    def set_api_key(self, key: str, provider: str | None = None) -> None:
        key = ai_engine.normalize_key(key)
        problem = ai_engine.check_key_format(key)
        if problem:
            raise ValueError(problem)
        with self._lock:
            in_keyring = False
            keyring = _import_keyring() if self._use_keyring else None
            if keyring is not None:
                try:
                    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
                    in_keyring = True
                except Exception:
                    in_keyring = False
            register_secret(key)
            log.info("Chave de API salva: provedor=%s armazenamento=%s",
                     provider or self._data["ai_profile"]["provider"], "keyring" if in_keyring else "arquivo local")
            values: dict[str, Any] = {"api_key": "" if in_keyring else key, "key_in_keyring": in_keyring}
            if provider:
                values["provider"] = provider
            # Outra chave/conta pode ter acesso a outros modelos: força nova detecção.
            values["detected_models"] = {}
            self.update("ai_profile", **values)

    def clear_api_key(self) -> None:
        log.info("Chave de API removida")
        with self._lock:
            if self._data["ai_profile"]["key_in_keyring"]:
                keyring = _import_keyring()
                if keyring is not None:
                    try:
                        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
                    except Exception:
                        pass
            self.update("ai_profile", api_key="", key_in_keyring=False)

    def get_detected_model(self, provider: str) -> str:
        return self.get("ai_profile", "detected_models").get(provider, "")

    def set_detected_model(self, provider: str, model: str) -> None:
        with self._lock:
            detected = dict(self._data["ai_profile"]["detected_models"])
            if provider in ai_engine.PROVIDERS and model and detected.get(provider) != model:
                detected[provider] = model
                log.info("Modelo detectado salvo: %s -> %s", provider, model)
                self.update("ai_profile", detected_models=detected)

    def has_api_key(self) -> bool:
        return bool(self.get_api_key())

    def storage_mode(self) -> str:
        return "keyring" if self.get("ai_profile", "key_in_keyring") else "arquivo local"

    # ---------------------------------------------------------------- perfil
    def get_profile(self) -> ai_engine.CompanionProfile:
        a = self.snapshot()["ai_profile"]
        return ai_engine.CompanionProfile(a["bot_name"], a["personality"], a["custom_prompt"])

    def record_login(self) -> None:
        self.update("settings", last_login=_utc_now())


# ======================================================================================
# Health-check de inicialização
# ======================================================================================

class StartupRoute(str, Enum):
    DASHBOARD = "dashboard"
    API_CONFIG = "api_config"


@dataclass(frozen=True)
class HealthResult:
    route: StartupRoute
    message: str = ""
    offline: bool = False
    validation: ApiValidation | None = None


def validate_api_key(key: str, provider: str) -> ApiValidation:
    """Atalho para ``ai_engine.validate_api_key`` (mantido aqui conforme a especificação)."""
    return ai_engine.validate_api_key(key, provider)


def run_startup_health_check(storage: Storage) -> HealthResult:
    """Decide para onde o aplicativo deve ir ao iniciar.

    * Chave válida ➜ Dashboard.
    * Chave ausente / inválida / expirada ➜ chave descartada e tela de configuração de API.
    * Falha de rede ou indisponibilidade do provedor ➜ a chave NÃO é descartada (ela pode estar
      perfeitamente válida); o app abre em modo offline com aviso.
    """
    key = storage.get_api_key()
    provider = storage.get("ai_profile", "provider")
    log.info("Health-check de inicialização (provedor=%s, chave=%s)", provider, "presente" if key else "ausente")

    if not key:
        return HealthResult(StartupRoute.API_CONFIG, "Nenhuma chave de API configurada.")

    result = validate_api_key(key, provider)
    log.info("Health-check: status=%s http=%s mensagem=%s", result.status.value, result.http_status, result.message)
    if result.status is KeyStatus.VALID:
        return HealthResult(StartupRoute.DASHBOARD, result.message, validation=result)
    if result.status is KeyStatus.RATE_LIMITED:
        return HealthResult(StartupRoute.DASHBOARD, result.message, validation=result)
    if result.definitely_invalid:
        log.warning("Chave descartada pelo health-check (%s)", result.status.value)
        storage.clear_api_key()
        return HealthResult(
            StartupRoute.API_CONFIG,
            "Sua chave de API expirou ou é inválida. Informe uma nova chave para continuar.",
            validation=result,
        )
    log.warning("Abrindo em modo offline: chave preservada (%s)", result.status.value)
    return HealthResult(
        StartupRoute.DASHBOARD,
        "Não foi possível validar a chave agora (" + result.message + ") O Duette abriu em modo offline.",
        offline=True,
        validation=result,
    )
