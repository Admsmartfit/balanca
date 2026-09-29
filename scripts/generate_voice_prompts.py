"""Gera os áudios das orientações faladas do quiosque (voz natural, não robótica).

Ferramenta de desenvolvimento — NÃO roda no quiosque nem é dependência do
servidor (`gTTS` não está em requirements.txt de propósito: precisa de
internet, e o app tem que funcionar 100% offline). Rode isto uma vez, no seu
computador, sempre que o texto de uma orientação mudar, e comite os .mp3
gerados em `web/audio/` — o app só reproduz esses arquivos prontos.

Uso:
    .venv\\Scripts\\python.exe -m pip install gTTS
    .venv\\Scripts\\python.exe scripts/generate_voice_prompts.py
"""

from __future__ import annotations

from pathlib import Path

from gtts import gTTS

AUDIO_DIR = Path(__file__).resolve().parent.parent / "web" / "audio"

# Texto igual ao usado em web/app.js (VOICE_PROMPTS) — mantenha os dois em sincronia.
PROMPTS = {
    "waiting-instruction": (
        "Pode subir na balança, descalço, com um pé em cada par de sensores. "
        "Fique parado até a leitura terminar, por favor."
    ),
    "photo-prompt": (
        "Quer tirar uma foto agora, para acompanhar sua evolução? "
        "Aperte 1 para sim, ou 0 para não."
    ),
}


def main() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for key, text in PROMPTS.items():
        path = AUDIO_DIR / f"{key}.mp3"
        # tld="com.br" pede a voz do Google em português do Brasil — o padrão
        # ("com") tende a sair com sotaque de Portugal.
        gTTS(text=text, lang="pt", tld="com.br", slow=False).save(path)
        print(f"gerado: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
