"""
Avisos no Telegram sempre que um gasto entra, muda ou sai (qualquer usuario), mais dois alertas
proativos derivados dos mesmos eventos: orcamento estourado e gasto de valor alto.

Como funciona: gatilhos (triggers) do SQLite registram cada mudanca em `eventos_lancamento`; ao fim de cada requisicao que
altera dados, o middleware chama `enviar_pendentes`, que junta os eventos numa mensagem e a envia em segundo plano.
Uma falha aqui NUNCA atrapalha o cadastro. Sem token/chat configurados, o recurso fica desligado.

Configuracao (Docker secrets, ver docker-compose.yml): /run/secrets/telegram_token e /run/secrets/telegram_chat
(ou TELEGRAM_TOKEN / TELEGRAM_CHAT_ID). NOTIFICAR_DETALHES=0 manda so o resumo, sem valor nem descricao.
GASTO_ALTO define o valor a partir do qual um lancamento novo dispara aviso extra (0 desliga; padrao 500).

Os outros dois avisos (lembrete de conta pendente perto do vencimento e resumo do fechamento do mes) sao
scripts a parte, chamados 1x por dia por uma tarefa agendada: ver app/lembretes.py e app/resumo.py.
"""
import json
import os
import sqlite3
import threading
import urllib.request
from collections import defaultdict
from pathlib import Path

from app import database

LOTE_MAX_INDIVIDUAIS = 3   # acima disso vira uma mensagem-resumo (importacoes, "gerar recorrentes"...)

TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS trg_ev_lanc_novo AFTER INSERT ON lancamentos WHEN NEW.validado = 1
BEGIN INSERT INTO eventos_lancamento (tipo, lancamento_id, data, valor, categoria, descricao, forma)
      VALUES ('novo', NEW.id, NEW.data, NEW.valor, (SELECT nome FROM categorias WHERE id = NEW.categoria_id), NEW.descricao, NEW.forma_pagamento); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_ev_lanc_confirmado AFTER UPDATE OF validado ON lancamentos WHEN OLD.validado = 0 AND NEW.validado = 1
BEGIN INSERT INTO eventos_lancamento (tipo, lancamento_id, data, valor, categoria, descricao, forma)
      VALUES ('novo', NEW.id, NEW.data, NEW.valor, (SELECT nome FROM categorias WHERE id = NEW.categoria_id), NEW.descricao, NEW.forma_pagamento); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_ev_lanc_editado AFTER UPDATE ON lancamentos
WHEN OLD.validado = 1 AND NEW.validado = 1 AND (OLD.valor IS NOT NEW.valor OR OLD.data IS NOT NEW.data
     OR OLD.categoria_id IS NOT NEW.categoria_id OR OLD.descricao IS NOT NEW.descricao
     OR OLD.forma_pagamento IS NOT NEW.forma_pagamento OR OLD.status IS NOT NEW.status)
BEGIN INSERT INTO eventos_lancamento (tipo, lancamento_id, data, valor, valor_antes, categoria, descricao, forma)
      VALUES ('editado', NEW.id, NEW.data, NEW.valor, OLD.valor, (SELECT nome FROM categorias WHERE id = NEW.categoria_id), NEW.descricao, NEW.forma_pagamento); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_ev_lanc_excluido AFTER DELETE ON lancamentos WHEN OLD.validado = 1
BEGIN INSERT INTO eventos_lancamento (tipo, lancamento_id, data, valor, categoria, descricao, forma)
      VALUES ('excluido', OLD.id, OLD.data, OLD.valor, (SELECT nome FROM categorias WHERE id = OLD.categoria_id), OLD.descricao, OLD.forma_pagamento); END""",
]

TABELA = """CREATE TABLE IF NOT EXISTS eventos_lancamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, lancamento_id INTEGER, data TEXT, valor REAL, valor_antes REAL,
    categoria TEXT, descricao TEXT, forma TEXT, criado_em TEXT NOT NULL DEFAULT (datetime('now')), enviado INTEGER NOT NULL DEFAULT 0)"""


def criar_estrutura(con) -> None:
    con.execute(TABELA)
    for t in TRIGGERS:
        con.execute(t)


def _segredo(arquivo: str, variavel: str) -> str:
    try:
        return Path(f"/run/secrets/{arquivo}").read_text(encoding="utf-8").strip()
    except OSError:
        return os.environ.get(variavel, "").strip()


def _brl(v) -> str:
    return "R$ " + f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dia(d) -> str:
    return f"{d[8:]}/{d[5:7]}" if d and len(d) >= 10 else "?"


def _linha(e, detalhes: bool) -> str:
    marca = {"novo": "➕", "editado": "✏️", "excluido": "\U0001f5d1️"}[e["tipo"]]
    if not detalhes:
        return f"{marca} {e['categoria'] or 'sem categoria'}"
    valor = _brl(e["valor"])
    if e["tipo"] == "editado" and e["valor_antes"] is not None and e["valor_antes"] != e["valor"]:
        valor += f" (antes {_brl(e['valor_antes'])})"
    partes = [valor, e["categoria"] or "sem categoria", (e["descricao"] or "sem descrição")[:60], _dia(e["data"]), e["forma"] or ""]
    return f"{marca} " + " · ".join(p for p in partes if p)


def alertas_orcamento(con, eventos: list) -> list[str]:
    """Uma linha por categoria/mês que passou a estourar o orçamento por causa destes eventos.

    Olha a mudança líquida de cada categoria no lote (soma de novos, +/- edições, -excluídos) e só avisa
    quando ela empurrou o total do mês de "dentro do orçamento" para "fora" — não repete a cada compra nova
    já estourada, e não avisa por causa de uma exclusão.
    """
    deltas: dict[tuple[str, str], float] = defaultdict(float)
    for e in eventos:
        mes = (e["data"] or "")[:7]
        if not e["categoria"] or not mes:
            continue
        chave = (e["categoria"], mes)
        if e["tipo"] == "novo":
            deltas[chave] += e["valor"] or 0
        elif e["tipo"] == "editado":
            deltas[chave] += (e["valor"] or 0) - (e["valor_antes"] or 0)
        elif e["tipo"] == "excluido":
            deltas[chave] -= e["valor"] or 0

    linhas = []
    for (categoria, mes), delta in deltas.items():
        if delta <= 0:
            continue
        orc = con.execute("SELECT orcamento_mensal FROM categorias WHERE nome = ?", (categoria,)).fetchone()
        orcado = orc[0] if orc else 0
        if not orcado:
            continue
        total_atual = con.execute(
            "SELECT COALESCE(SUM(valor), 0) FROM vw_lancamentos WHERE categoria = ? AND substr(data, 1, 7) = ? AND conta = 1",
            (categoria, mes),
        ).fetchone()[0]
        total_antes = total_atual - delta
        if total_antes <= orcado < total_atual:
            linhas.append(f"⚠️ {categoria} passou do orçamento do mês: {_brl(total_atual)} de {_brl(orcado)}.")
    return linhas


def alertas_gasto_alto(eventos: list, limiar: float) -> list[str]:
    """Uma linha por lançamento NOVO com valor >= limiar (0 desliga)."""
    if limiar <= 0:
        return []
    linhas = []
    for e in eventos:
        if e["tipo"] != "novo" or (e["valor"] or 0) < limiar:
            continue
        descricao = f" ({e['descricao'][:40]})" if e["descricao"] else ""
        linhas.append(f"💰 Gasto alto: {_brl(e['valor'])} em {e['categoria'] or 'sem categoria'}{descricao}.")
    return linhas


def montar_mensagem(quem: str, eventos: list, detalhes: bool) -> str | None:
    if not eventos:
        return None
    if len(eventos) <= LOTE_MAX_INDIVIDUAIS:
        rotulo = {"novo": "cadastrou", "editado": "alterou", "excluido": "excluiu"}
        tipos = {e["tipo"] for e in eventos}
        cab = f"{quem} " + (rotulo[eventos[0]["tipo"]] if len(tipos) == 1 else "mexeu em lançamentos") + ":"
        return cab + "\n" + "\n".join(_linha(e, detalhes) for e in eventos)
    nomes = (("novo", "novos"), ("editado", "alterados"), ("excluido", "excluídos"))
    partes = [f"{n} {nome}" for t, nome in nomes if (n := sum(1 for e in eventos if e["tipo"] == t))]
    texto = f"{quem} registrou {len(eventos)} mudanças em lançamentos ({', '.join(partes)})."
    novos = [e for e in eventos if e["tipo"] == "novo"]
    if detalhes and novos:
        texto += f" Total dos novos: {_brl(sum(e['valor'] or 0 for e in novos))}."
    return texto


def _enviar(token: str, chat: str, texto: str) -> None:
    try:
        corpo = json.dumps({"chat_id": chat, "text": texto}).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=corpo,
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        urllib.request.urlopen(req, timeout=6).read()
    except Exception:  # aviso e acessorio: nunca derruba nada
        pass


def enviar_pendentes(quem: str) -> None:
    """Chamado depois de uma requisicao que alterou dados. Junta os eventos ainda nao enviados e manda a mensagem."""
    token, chat = _segredo("telegram_token", "TELEGRAM_TOKEN"), _segredo("telegram_chat", "TELEGRAM_CHAT_ID")
    try:
        con = sqlite3.connect(database.DATABASE_PATH, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            eventos = con.execute("UPDATE eventos_lancamento SET enviado = 1 WHERE enviado = 0 RETURNING *").fetchall()
            con.execute("DELETE FROM eventos_lancamento WHERE enviado = 1 AND criado_em < datetime('now', '-30 days')")
            con.commit()
            eventos = sorted(eventos, key=lambda e: e["id"])
            alertas = alertas_orcamento(con, eventos) if eventos else []
        finally:
            con.close()
    except sqlite3.Error:
        return
    if not (token and chat and eventos):
        return
    limiar = float(os.environ.get("GASTO_ALTO", "500") or 0)
    alertas += alertas_gasto_alto(eventos, limiar)
    texto = montar_mensagem(quem, eventos, os.environ.get("NOTIFICAR_DETALHES", "1") != "0")
    if alertas:
        texto = "\n\n".join(p for p in (texto, "\n".join(alertas)) if p)
    if texto:
        threading.Thread(target=_enviar, args=(token, chat, texto), daemon=True).start()
