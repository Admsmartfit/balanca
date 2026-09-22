"""Ponto de entrada do MiScale Analytics Desktop.

Uso normal (sobe o servidor):
    python main.py

Criar o primeiro administrador (não sobe o servidor, só cadastra e sai):
    python main.py --create-admin
"""

import argparse
import getpass
import logging

import uvicorn

from app.config import load_config
from app.db import Database, InvalidAdmin
from app.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _create_admin_cli() -> None:
    print("Criar administrador do MiScale Analytics Desktop")
    email = input("E-mail: ").strip()
    password = getpass.getpass("Senha (mínimo 8 caracteres — não aparece na tela): ")
    confirm = getpass.getpass("Confirme a senha: ")

    if password != confirm:
        print("As senhas não coincidem. Nada foi criado.")
        raise SystemExit(1)

    db = Database()
    try:
        admin = db.create_admin(email=email, password=password)
    except InvalidAdmin as exc:
        print(f"Erro: {exc}")
        raise SystemExit(1) from exc
    finally:
        db.close()
    print(f"Administrador '{admin.email}' criado. Use /admin para entrar.")


def main() -> None:
    parser = argparse.ArgumentParser(description="MiScale Analytics Desktop")
    parser.add_argument(
        "--create-admin", action="store_true", help="cria um administrador e sai, sem subir o servidor"
    )
    args = parser.parse_args()

    if args.create_admin:
        _create_admin_cli()
        return

    config = load_config()
    app = create_app()
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
