"""
Camada de acesso ao banco - SQLite puro, sem ORM.

schema.sql e seed.sql são a fonte única de verdade da estrutura do banco.
Na primeira execução (arquivo .db ainda não existe), este módulo os roda
na ordem para criar e popular o banco. Em execuções seguintes o arquivo .db
é preservado (inclusive pelo volume Docker em produção) e apenas passa por
migrar_db(), que acrescenta o que faltar de versões novas do schema.
"""
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "data" / "controle-gastos.db"))
SCHEMA_SQL = BASE_DIR / "database" / "schema.sql"
SEED_SQL = BASE_DIR / "database" / "seed.sql"

CATEGORIA_PENDENTE = "A classificar"
CATEGORIA_INVESTIMENTOS = "Investimentos"  # poupança/aplicações: nasce fora dos totais de gastos (contabiliza = 0)

# Colunas incluídas depois da primeira versão do schema (mesmas definições do schema.sql).
_COLUNAS_NOVAS = {
    "categorias": [
        ("contabiliza", "INTEGER NOT NULL DEFAULT 1 CHECK (contabiliza IN (0,1))"),
    ],
    "titulares": [
        ("orcamento_mensal", "REAL NOT NULL DEFAULT 0"),
    ],
    "cartoes": [
        ("palavra_chave", "TEXT"),
    ],
    "recorrentes": [
        ("palavra_chave", "TEXT"),
    ],
    "lancamentos": [
        ("validado", "INTEGER NOT NULL DEFAULT 1 CHECK (validado IN (0,1))"),
        ("origem", "TEXT"),
        ("id_externo", "TEXT"),
        ("alerta", "TEXT"),
        ("sugestao_id", "INTEGER"),
        ("recorrente_id", "INTEGER REFERENCES recorrentes(id) ON DELETE SET NULL"),
    ],
}

_VIEW_LANCAMENTOS = """
CREATE VIEW vw_lancamentos AS
SELECT
    l.id, l.data, c.nome AS categoria, c.grupo, c.essencial, c.contabiliza,
    l.descricao, t.nome AS titular, l.forma_pagamento,
    ca.identificador AS cartao, ca.banco,
    l.valor, l.tipo, l.status, l.parcela, l.observacoes,
    l.validado, l.origem, l.alerta,
    -- A fatura do cartão é a fonte do gasto no cartão: compras lançadas à mão com "Cartão de crédito" (fora da categoria
    -- da fatura) NÃO entram nos totais (conta = 0), para não contar duas vezes.
    -- Categorias com contabiliza = 0 (ex.: aplicações) também ficam fora dos totais de gastos.
    CASE WHEN c.contabiliza = 0 THEN 0
         WHEN l.forma_pagamento = 'Cartão de crédito' AND COALESCE(l.origem, '') != 'fatura' AND c.nome != 'Cartões de crédito'
         THEN 0 ELSE 1 END AS conta
FROM lancamentos l
JOIN categorias c        ON c.id = l.categoria_id
LEFT JOIN titulares t    ON t.id = l.titular_id
LEFT JOIN cartoes ca     ON ca.id = l.cartao_id
"""


def migrar_db(con: sqlite3.Connection) -> None:
    """Leva um banco criado por uma versão anterior do schema até a versão atual. Idempotente."""
    for tabela, colunas in _COLUNAS_NOVAS.items():
        existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
        for nome, definicao in colunas:
            if nome not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {definicao}")

    con.execute("""CREATE TABLE IF NOT EXISTS regras (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        padrao          TEXT NOT NULL UNIQUE,
        categoria_id    INTEGER NOT NULL REFERENCES categorias(id),
        titular_id      INTEGER REFERENCES titulares(id),
        forma_pagamento TEXT,
        atualizado_em   TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    con.execute("CREATE TABLE IF NOT EXISTS ignorados_importacao (id_externo TEXT PRIMARY KEY)")
    con.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario         TEXT NOT NULL UNIQUE COLLATE NOCASE,
        nome            TEXT NOT NULL,
        senha_hash      TEXT NOT NULL,
        ativo           INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
        falhas          INTEGER NOT NULL DEFAULT 0,
        bloqueado_ate   TEXT,
        criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
        ultimo_login    TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS sessoes (
        token_hash      TEXT PRIMARY KEY,
        usuario_id      INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
        expira_em       TEXT NOT NULL,
        ip              TEXT,
        agente          TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_sessoes_usuario ON sessoes(usuario_id)")
    # Leitura de QR de nota fiscal: local (CNPJ) -> categoria aprendida, e notas já consultadas (evita ler/cadastrar duas vezes)
    con.execute("""CREATE TABLE IF NOT EXISTS notas_locais (
        cnpj            TEXT PRIMARY KEY,
        categoria_id    INTEGER NOT NULL REFERENCES categorias(id),
        estabelecimento TEXT,
        atualizado_em   TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS notas_lidas (
        chave           TEXT PRIMARY KEY,
        lida_em         TEXT NOT NULL DEFAULT (datetime('now')),
        data            TEXT,
        valor           REAL,
        estabelecimento TEXT
    )""")
    from app import avisos, beneficios  # import tardio: avisos importa este módulo
    beneficios.criar_estrutura(con)  # cartões vale alimentação/refeição (fora dos totais de gastos)
    avisos.criar_estrutura(con)  # eventos + gatilhos dos avisos no Telegram
    con.execute("CREATE TABLE IF NOT EXISTS duplicidades_ignoradas (a INTEGER NOT NULL, b INTEGER NOT NULL, PRIMARY KEY (a, b))")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lancamentos_id_externo "
                "ON lancamentos(id_externo) WHERE id_externo IS NOT NULL")

    # Categoria provisória para o que vem de importação e ainda não foi classificado.
    con.execute("INSERT OR IGNORE INTO categorias (nome, grupo, essencial, orcamento_mensal, ativa, observacao) "
                "VALUES (?, 'Outros', 0, 0, 1, 'Provisória: lançamentos importados aguardando classificação.')",
                (CATEGORIA_PENDENTE,))

    # A view precisa expor as colunas novas.
    con.execute("INSERT OR IGNORE INTO categorias (nome, grupo, essencial, orcamento_mensal, ativa, observacao, contabiliza) "
                "VALUES (?, 'Financeiro', 0, 0, 1, 'Economias/aplicações. Não soma nos gastos (marque \"Soma nos gastos\" em Cadastros para passar a somar).', 0)",
                (CATEGORIA_INVESTIMENTOS,))
    colunas_view = {r[1] for r in con.execute("PRAGMA table_info(vw_lancamentos)")}
    if "conta" not in colunas_view or "contabiliza" not in colunas_view:
        con.execute("DROP VIEW IF EXISTS vw_lancamentos")
        con.execute(_VIEW_LANCAMENTOS)
    con.commit()


def init_db() -> None:
    """Cria o banco a partir de schema.sql + seed.sql, se ainda não existir, e o migra."""
    os.umask(0o077)  # banco, journal e backups criados só com acesso do dono (nada legível por "outros")
    novo = not DATABASE_PATH.exists()
    if novo:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATABASE_PATH)
    try:
        if novo:
            con.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
            con.executescript(SEED_SQL.read_text(encoding="utf-8"))
            con.commit()
        migrar_db(con)
    finally:
        con.close()


def get_db() -> sqlite3.Connection:
    """Dependency do FastAPI: uma conexão por request, fechada ao final."""
    # check_same_thread=False: o FastAPI pode abrir a dependência e rodar a rota em threads diferentes
    # do pool; a conexão é de uso exclusivo do request, então não há acesso concorrente.
    con = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
    finally:
        con.close()
