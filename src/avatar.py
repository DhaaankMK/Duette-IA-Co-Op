"""Importação segura de avatares (requer Pillow; sem ele, usa-se o avatar gerado com a inicial)."""

from __future__ import annotations

import hashlib
from pathlib import Path

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
AVATAR_SIZE = 256
ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "WEBP", "BMP"}


class AvatarError(Exception):
    pass


def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401

        return True
    except ImportError:
        return False


def import_avatar(source: str | Path, avatars_dir: Path) -> str:
    """Valida a imagem, recorta em quadrado, reduz para 256x256 e salva como PNG.

    O arquivo original nunca é copiado: a imagem é decodificada e reescrita, o que remove
    metadados e qualquer conteúdo embutido. Devolve o nome do arquivo salvo.
    """
    try:
        from PIL import Image, ImageOps  # type: ignore
    except ImportError:
        raise AvatarError("Para usar fotos de perfil, instale o Pillow: pip install Pillow") from None

    path = Path(source)
    try:
        if not path.is_file():
            raise AvatarError("Arquivo não encontrado.")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise AvatarError("A imagem excede 5 MB.")
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(path) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise AvatarError("Formato não suportado. Use PNG, JPG, GIF, WEBP ou BMP.")
            probe.verify()
        with Image.open(path) as image:
            image.seek(0)
            image = ImageOps.exif_transpose(image).convert("RGBA")
            image = ImageOps.fit(image, (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    except AvatarError:
        raise
    except Exception:
        raise AvatarError("Não foi possível ler a imagem (arquivo inválido ou corrompido).") from None

    avatars_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(image.tobytes()).hexdigest()[:16]
    name = f"avatar_{digest}.png"
    image.save(avatars_dir / name, format="PNG")
    return name


def resolve_avatar(avatars_dir: Path, name: str) -> Path | None:
    """Caminho seguro de um avatar salvo (apenas arquivos dentro da pasta de avatares)."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = (avatars_dir / name).resolve()
    if avatars_dir.resolve() in path.parents and path.is_file():
        return path
    return None


def load_photo(path: Path, size: int):
    """Carrega um avatar como ``ImageTk.PhotoImage`` (ou ``None`` se não for possível)."""
    try:
        from PIL import Image, ImageTk  # type: ignore

        with Image.open(path) as image:
            return ImageTk.PhotoImage(image.convert("RGBA").resize((size, size), Image.LANCZOS))
    except Exception:
        return None
