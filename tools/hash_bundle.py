"""Imprime o SHA-256 de um pacote de mods para ser colocado em mods_bundle/games.json."""
import hashlib
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python tools/hash_bundle.py <arquivo.zip>")
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print("Arquivo não encontrado.")
        return 1
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    print(digest.hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
