"""Ponto de entrada do MiScale Analytics Desktop."""

import logging

import uvicorn

from app.config import load_config
from app.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = create_app()

if __name__ == "__main__":
    config = load_config()
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
