"""
Lembrete no Telegram de contas pendentes (recorrentes gerados, ainda com status "Pendente") perto do
vencimento ou já vencidas. Roda 1x por dia, chamado de fora do container:

    docker compose exec backend python -m app.lembretes

Avisa 3 dias antes, 1 dia antes, no dia, e todo dia enquanto estiver vencida (até ser paga/excluída).
Sem token/chat configurados, não faz nada (mesmo esquema de app/avisos.py).
"""
import sqlite3
from datetime import date, datetime

from app import avisos, database

DIAS_AVISO_ANTES = (3, 1, 0)


def _pendentes(con) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT l.data, l.valor, c.nome AS categoria, l.descricao
           FROM lancamentos l JOIN categorias c ON c.id = l.categoria_id
           WHERE l.status = 'Pendente' ORDER BY l.data"""
    ).fetchall()


def montar_mensagem(pendentes: list[sqlite3.Row], hoje: date) -> str | None:
    linhas = []
    for p in pendentes:
        try:
            venc = datetime.strptime(p["data"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        dias = (venc - hoje).days
        if dias not in DIAS_AVISO_ANTES and dias >= 0:
            continue
        def _dias(n: int) -> str:
            return "1 dia" if n == 1 else f"{n} dias"
        quando = "hoje" if dias == 0 else (f"em {_dias(dias)}" if dias > 0 else f"venceu há {_dias(-dias)}")
        nome = p["descricao"] or p["categoria"] or "conta"
        linhas.append(f"📅 {nome}: {avisos._brl(p['valor'])} ({quando})")
    if not linhas:
        return None
    return "Contas pendentes:\n" + "\n".join(linhas)


def main() -> None:
    token = avisos._segredo("telegram_token", "TELEGRAM_TOKEN")
    chat = avisos._segredo("telegram_chat", "TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    con = sqlite3.connect(database.DATABASE_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        pendentes = _pendentes(con)
    finally:
        con.close()
    texto = montar_mensagem(pendentes, date.today())
    if texto:
        avisos._enviar(token, chat, texto)


if __name__ == "__main__":
    main()
