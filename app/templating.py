"""Instância única de templates, compartilhada por main.py e pelos routers."""
import sqlite3
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app import database
from app.duplicidades import pares_suspeitos
from app.versao import VERSAO

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


def _contar_a_validar() -> int:
    """Usado no menu: quantos lançamentos importados aguardam revisão."""
    try:
        con = sqlite3.connect(database.DATABASE_PATH)
        try:
            return con.execute("SELECT COUNT(*) FROM lancamentos WHERE validado = 0").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def _contar_duplicidades() -> int:
    """Usado no menu: pares suspeitos de duplicidade (inclui lançamentos já validados)."""
    try:
        con = sqlite3.connect(database.DATABASE_PATH)
        con.row_factory = sqlite3.Row
        try:
            return len(pares_suspeitos(con))
        finally:
            con.close()
    except sqlite3.Error:
        return 0


templates.env.globals["contar_a_validar"] = _contar_a_validar
templates.env.globals["contar_duplicidades"] = _contar_duplicidades
templates.env.globals["versao_app"] = VERSAO
