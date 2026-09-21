"""
Cartões de benefício (vale alimentação/refeição).

Não é dinheiro: o valor cai no cartão todo mês, acumula com o saldo anterior e só serve para pagar compras. Por isso os usos
ficam em `beneficio_usos`, separados de `lancamentos`, e nunca entram nos totais de gastos (painel, relatórios, orçamento).

Saldo = saldo inicial + recargas até a data - usos até a data. Uma recarga acontece no `dia_recarga` de cada mês (limitado
ao último dia do mês), a partir da data de `inicio` do cartão.
"""
import calendar
from datetime import date

FORMA_PAGAMENTO = "Vale alimentação/refeição"
TITULAR_FAMILIA = "Família (compartilhado)"  # todo gasto no vale é da família, qualquer que seja o dono do cartão


def criar_estrutura(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS beneficios (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        titular_id      INTEGER NOT NULL REFERENCES titulares(id),
        nome            TEXT NOT NULL,
        valor_mensal    REAL NOT NULL DEFAULT 0 CHECK (valor_mensal >= 0),
        dia_recarga     INTEGER NOT NULL CHECK (dia_recarga BETWEEN 1 AND 31),
        inicio          TEXT NOT NULL,              -- ISO: recargas contam a partir desta data
        saldo_inicial   REAL NOT NULL DEFAULT 0,    -- saldo que o cartão já tinha em `inicio`
        ativo           INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
        UNIQUE (titular_id, nome)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS beneficio_usos (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        beneficio_id    INTEGER NOT NULL REFERENCES beneficios(id) ON DELETE CASCADE,
        data            TEXT NOT NULL,
        valor           REAL NOT NULL CHECK (valor > 0),
        descricao       TEXT,
        categoria_id    INTEGER REFERENCES categorias(id),
        titular_id      INTEGER REFERENCES titulares(id)   -- sempre a família; o dono do cartão está em `beneficios`
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_beneficio_usos ON beneficio_usos(beneficio_id, data)")


def _dia_no_mes(ano: int, mes: int, dia: int) -> date:
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def recargas(b, ate: date, desde: date | None = None) -> float:
    """Soma das recargas com data entre `desde` (padrão: início do cartão) e `ate`, inclusive."""
    inicio = date.fromisoformat(b["inicio"])
    piso = max(inicio, desde) if desde else inicio
    total, ano, mes = 0.0, inicio.year, inicio.month
    while (ano, mes) <= (ate.year, ate.month):
        d = _dia_no_mes(ano, mes, b["dia_recarga"])
        if inicio <= d and piso <= d <= ate:
            total += b["valor_mensal"]
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return total


def _usos(db, beneficio_id: int, ate: date, desde: date | None = None) -> float:
    return db.execute(
        "SELECT COALESCE(SUM(valor), 0) FROM beneficio_usos WHERE beneficio_id = ? AND data <= ? AND data >= ?",
        (beneficio_id, ate.isoformat(), desde.isoformat() if desde else "0000-00-00")).fetchone()[0]


def saldo_em(db, b, ate: date) -> float:
    # o saldo inicial já é o que sobrava em `inicio`: usos anteriores a essa data não contam
    return b["saldo_inicial"] + recargas(b, ate) - _usos(db, b["id"], ate, desde=date.fromisoformat(b["inicio"]))


def resumo_do_mes(db, mes: str) -> dict:
    """Para o painel: por cartão ativo, saldo que veio do mês anterior, recarga, uso e saldo restante ao fim do mês."""
    ano, m = int(mes[:4]), int(mes[5:7])
    primeiro = date(ano, m, 1)
    ultimo = date(ano, m, calendar.monthrange(ano, m)[1])
    anterior = date.fromordinal(primeiro.toordinal() - 1)
    limite = min(ultimo, date.today()) if primeiro <= date.today() else ultimo  # mês em curso: só o que já caiu até hoje
    lista = []
    for b in db.execute("""SELECT b.*, t.nome AS titular FROM beneficios b JOIN titulares t ON t.id = b.titular_id
                           WHERE b.ativo = 1 ORDER BY t.nome, b.nome"""):
        if date.fromisoformat(b["inicio"]) > ultimo:
            continue  # cartão que só começa depois deste mês
        recarga = recargas(b, limite, desde=primeiro)
        usado = _usos(db, b["id"], ultimo, desde=max(primeiro, date.fromisoformat(b["inicio"])))
        saldo_ant = saldo_em(db, b, anterior) if anterior >= date.fromisoformat(b["inicio"]) else b["saldo_inicial"]
        disponivel = saldo_ant + recarga
        lista.append({"id": b["id"], "nome": b["nome"], "titular": b["titular"], "saldo_anterior": saldo_ant,
                      "recarga": recarga, "disponivel": disponivel, "usado": usado, "restante": disponivel - usado,
                      "pct_usado": (usado / disponivel * 100) if disponivel > 0 else 0.0})
    return {"lista": lista, "usado": sum(x["usado"] for x in lista), "restante": sum(x["restante"] for x in lista),
            "disponivel": sum(x["disponivel"] for x in lista)}
