"""
Resumo do fechamento do mês anterior, mandado no Telegram. Roda 1x por dia, mas só age no dia 1º
(passe --forcar para testar em qualquer dia). Chamado de fora do container:

    docker compose exec backend python -m app.resumo

Sem token/chat configurados, não faz nada (mesmo esquema de app/avisos.py).
"""
import sqlite3
import sys
from datetime import date

from app import avisos, database
from app.relatorios import dados_relatorios


def _mes_anterior(hoje: date) -> str:
    ano, mes = hoje.year, hoje.month - 1
    if mes == 0:
        ano, mes = ano - 1, 12
    return f"{ano:04d}-{mes:02d}"


def montar_mensagem(con, mes: str) -> str:
    r = dados_relatorios(con, mes, n_meses=1)
    c = r["cards"]
    linhas = [f"📊 Fechamento de {mes}: {avisos._brl(c['total_mes'])}"]
    if c["variacao_pct"] is not None:
        seta = "🔺" if c["variacao"] > 0 else "🔻"
        linhas.append(f"{seta} {avisos._brl(abs(c['variacao']))} ({abs(c['variacao_pct']):.1f}%) vs mês anterior")
    if c["orcamento_pct"] is not None:
        linhas.append(f"Orçamento: {c['orcamento_pct']:.1f}% de {avisos._brl(c['orcamento_mes'])}")
    if r["estouros"]:
        piores = sorted(r["estouros"], key=lambda e: e["excesso"], reverse=True)[:3]
        linhas.append("Estourou: " + ", ".join(f"{e['nome']} (+{avisos._brl(e['excesso'])})" for e in piores))
    if r["top"]:
        linhas.append("Maiores gastos: " + ", ".join(f"{t['nome']} {avisos._brl(t['total'])}" for t in r["top"][:3]))
    return "\n".join(linhas)


def main() -> None:
    hoje = date.today()
    if hoje.day != 1 and "--forcar" not in sys.argv:
        return
    token = avisos._segredo("telegram_token", "TELEGRAM_TOKEN")
    chat = avisos._segredo("telegram_chat", "TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    mes = _mes_anterior(hoje)
    con = sqlite3.connect(database.DATABASE_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        texto = montar_mensagem(con, mes)
    finally:
        con.close()
    avisos._enviar(token, chat, texto)


if __name__ == "__main__":
    main()
