import json
from pathlib import Path
import pygame

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60

RESOLUTION_OPTIONS = [(800, 600), (1024, 768), (1280, 720)]
HZ_OPTIONS = [30, 60, 75, 120]
VIDEO_SETTINGS = {
    "resolution_index": 0,
    "hz": 60,
    "fullscreen": False,
    "gamma": 100,
    "debug_console": False,
    "volume": 70,
    "music": True,
}

SETTINGS_FILE = Path(__file__).resolve().parents[3] / "content" / "video_settings.json"


def load_video_settings():
    if not SETTINGS_FILE.exists():
        return
    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as file:
            saved = json.load(file)
        for key in VIDEO_SETTINGS:
            if key in saved:
                VIDEO_SETTINGS[key] = saved[key]
    except (OSError, ValueError):
        pass


def save_video_settings():
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with SETTINGS_FILE.open("w", encoding="utf-8") as file:
            json.dump(VIDEO_SETTINGS, file, ensure_ascii=False, indent=2)
    except OSError:
        pass


load_video_settings()


def apply_display_settings():
    """Aplica as opções atuais e retorna a nova superfície da janela."""
    global SCREEN_WIDTH, SCREEN_HEIGHT, FPS
    SCREEN_WIDTH, SCREEN_HEIGHT = RESOLUTION_OPTIONS[VIDEO_SETTINGS["resolution_index"]]
    FPS = VIDEO_SETTINGS["hz"]
    flags = pygame.FULLSCREEN if VIDEO_SETTINGS["fullscreen"] else 0
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), flags)
    try:
        gamma = max(0.5, VIDEO_SETTINGS["gamma"] / 100.0)
        pygame.display.set_gamma(gamma, gamma, gamma)
    except (pygame.error, AttributeError):
        # Alguns drivers (e algumas plataformas) não permitem gamma via SDL.
        pass
    save_video_settings()
    return screen

# Cores
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (230, 50, 50)
BLUE = (50, 120, 255)
GREEN = (50, 255, 100)
GRAY = (120, 120, 120)
DARK_GRAY = (18, 18, 24)
LIGHT_GRAY = (180, 180, 180)
YELLOW = (255, 220, 0)
ORANGE = (255, 140, 0)
PURPLE = (160, 32, 240)
CYAN = (0, 225, 255)

# Padrões caso o json não exista
DEFAULT_STYLES = {
    "STICK": {"color": [255, 255, 255], "hp": 100, "speed": 7.0, "desc": "Equilibrado."},
    "TANK": {"color": [80, 180, 100], "hp": 150, "speed": 5.0, "desc": "Tanque."}
}

DEFAULT_WEAPONS = {
    "PUNHO": {"damage": 12, "range": 50, "cooldown": 14, "desc": "Rápido."},
    "ESPADA": {"damage": 28, "range": 85, "cooldown": 28, "desc": "Pesado."}
}

CONTENT_FILE = Path(__file__).resolve().parents[3] / "content" / "content.json"


def load_content():
    if CONTENT_FILE.exists():
        try:
            with CONTENT_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("styles", DEFAULT_STYLES), data.get("weapons", DEFAULT_WEAPONS)
        except Exception as e:
            print("Erro ao ler content.json, usando padrão:", e)
    return DEFAULT_STYLES, DEFAULT_WEAPONS

STYLES, WEAPONS = load_content()
