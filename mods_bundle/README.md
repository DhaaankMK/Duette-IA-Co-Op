# mods_bundle

Pacotes de mods embutidos no Duette e o catálogo de jogos (`games.json`).

Para cada jogo do tipo `mod`, coloque aqui um `.zip` e preencha no catálogo:

- `bundle`: nome do arquivo `.zip` (somente letras, números, `_`, `-`, `.` e espaço);
- `bundle_sha256`: hash SHA-256 do `.zip` (a instalação é recusada sem ele);
- `required_files`: caminhos relativos à pasta do jogo que indicam que a integração já está instalada.

Gerar o hash:  `python tools/hash_bundle.py mods_bundle/MeuPacote.zip`

Os `.zip` devem usar `/` como separador, sem caminhos absolutos, `..` ou links simbólicos.
O pacote do BONELAB (MelonLoader + mod `DuetteBridge.dll`) ainda NÃO existe: é a próxima etapa.
