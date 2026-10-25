import pygame
import sys
from .config.settings import *
from .config import settings as config
from .audio.sound_manager import SoundManager
from .ui.menu import Menu
from .core.game import Game
from .ai.duette_client import get_client

def main():
    pygame.init()
    screen = config.apply_display_settings()
    pygame.display.set_caption("Mortal Stick Combat" + (" - IA ativa" if get_client() else " - Áudio & Pulo Duplo"))
    clock = pygame.time.Clock()

    sound_mgr = SoundManager()
    state = "MENU"
    menu = Menu(sound_manager=sound_mgr)
    game = None

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if state == "MENU":
                action = menu.handle_input(event)
                if action == "SAIR":
                    pygame.quit()
                    sys.exit()
                elif action == "START_GAME":
                    p1_s, p1_w, p2_s, p2_w = menu.get_selections()
                    game = Game(p1_s, p1_w, p2_s, p2_w, sound_manager=sound_mgr, stage=menu.get_stage())
                    state = "GAME"

            elif state == "GAME":
                action = game.handle_events(event)
                if action == "MENU":
                    state = "MENU"
                if game.game_over and event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                    state = "MENU"
                if state == "MENU":
                    sound_mgr.stop_music()

        screen = pygame.display.get_surface()
        if state == "MENU":
            menu.update()
            menu.draw(screen)
        elif state == "GAME":
            game.update()
            game.draw(screen)

        pygame.display.flip()
        clock.tick(config.FPS)

if __name__ == "__main__":
    main()
