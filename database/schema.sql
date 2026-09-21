-- ============================================================================
-- Controle de Gastos - Schema inicial (SQLite)
-- Espelha a estrutura normalizada da planilha (Config, Recorrentes, Lançamentos)
-- ============================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE titulares (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL UNIQUE,
    orcamento_mensal REAL NOT NULL DEFAULT 0       -- orçamento do mês só deste titular (0 = sem orçamento)
);

-- Parâmetros gerais (chave/valor): meta de economia e teto mensal da aba Config.
CREATE TABLE parametros (
    chave           TEXT PRIMARY KEY,
    valor           TEXT NOT NULL
);

CREATE TABLE categorias (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                TEXT NOT NULL UNIQUE,
    grupo               TEXT NOT NULL,
    essencial           INTEGER NOT NULL DEFAULT 0 CHECK (essencial IN (0,1)),
    orcamento_mensal    REAL NOT NULL DEFAULT 0,
    ativa               INTEGER NOT NULL DEFAULT 1 CHECK (ativa IN (0,1)),
    observacao          TEXT,
    contabiliza         INTEGER NOT NULL DEFAULT 1 CHECK (contabiliza IN (0,1))  -- 0 = não soma nos gastos (ex.: aplicações)
);

CREATE TABLE cartoes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    identificador   TEXT NOT NULL UNIQUE,          -- ex.: "Maria - Nubank"
    titular_id      INTEGER NOT NULL REFERENCES titulares(id),
    banco           TEXT NOT NULL,
    ativo           INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    observacao      TEXT,
    palavra_chave   TEXT                           -- termos (vírgula) que identificam o cartão numa fatura/extrato, ex.: final 1234
);

CREATE TABLE recorrentes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria_id        INTEGER NOT NULL REFERENCES categorias(id),
    descricao           TEXT NOT NULL,
    dia_vencimento      INTEGER CHECK (dia_vencimento BETWEEN 1 AND 31),
    valor_estimado      REAL NOT NULL DEFAULT 0,
    forma_pagamento     TEXT NOT NULL CHECK (forma_pagamento IN
                            ('Dinheiro','PIX','Débito','Cartão de crédito','Boleto',
                             'Débito automático','Transferência / TED')),
    titular_id          INTEGER REFERENCES titulares(id),
    cartao_id           INTEGER REFERENCES cartoes(id),
    ativo               INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    palavra_chave       TEXT                         -- termos (separados por vírgula) que identificam este gasto em faturas/extratos
);

CREATE TABLE lancamentos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    data                TEXT NOT NULL,              -- ISO 8601 (YYYY-MM-DD)
    categoria_id        INTEGER NOT NULL REFERENCES categorias(id),
    descricao           TEXT,
    titular_id          INTEGER REFERENCES titulares(id),
    forma_pagamento     TEXT NOT NULL CHECK (forma_pagamento IN
                            ('Dinheiro','PIX','Débito','Cartão de crédito','Boleto',
                             'Débito automático','Transferência / TED')),
    cartao_id           INTEGER REFERENCES cartoes(id),
    valor               REAL NOT NULL CHECK (valor >= 0),
    tipo                TEXT NOT NULL CHECK (tipo IN ('Recorrente','Variável','Extra / Eventual')),
    status              TEXT NOT NULL DEFAULT 'Pago' CHECK (status IN ('Pago','Pendente','Agendado')),
    parcela             TEXT,                        -- ex.: "3/12"
    observacoes         TEXT,
    criado_em           TEXT NOT NULL DEFAULT (datetime('now')),
    -- Importação (extrato/faturas). Bancos antigos recebem estas colunas em app/database.py (migrar_db).
    validado            INTEGER NOT NULL DEFAULT 1 CHECK (validado IN (0,1)),  -- 0 = importado, aguardando revisão
    origem              TEXT,                        -- 'extrato' | 'fatura' | NULL (digitado)
    id_externo          TEXT,                        -- identificação da linha no arquivo importado (evita duplicar)
    alerta              TEXT,                        -- aviso de possível duplicidade (fatura de cartão, transferência)
    sugestao_id         INTEGER,                     -- lançamento pendente que este parece concluir
    recorrente_id       INTEGER REFERENCES recorrentes(id) ON DELETE SET NULL
);

-- Regras aprendidas na validação: descrição normalizada -> categoria/titular/forma.
CREATE TABLE regras (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    padrao          TEXT NOT NULL UNIQUE,
    categoria_id    INTEGER NOT NULL REFERENCES categorias(id),
    titular_id      INTEGER REFERENCES titulares(id),
    forma_pagamento TEXT,
    atualizado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX idx_lancamentos_id_externo ON lancamentos(id_externo) WHERE id_externo IS NOT NULL;

-- Linhas de extrato que o usuário excluiu na validação: não voltam se o extrato for importado de novo.
CREATE TABLE ignorados_importacao (
    id_externo      TEXT PRIMARY KEY
);

-- Autenticação: usuários e sessões no servidor (só o hash do token fica no banco).
CREATE TABLE usuarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nome            TEXT NOT NULL,
    senha_hash      TEXT NOT NULL,
    ativo           INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    falhas          INTEGER NOT NULL DEFAULT 0,          -- tentativas de login erradas seguidas
    bloqueado_ate   TEXT,                                -- UTC; preenchido após muitas falhas
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    ultimo_login    TEXT
);

CREATE TABLE sessoes (
    token_hash      TEXT PRIMARY KEY,
    usuario_id      INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    expira_em       TEXT NOT NULL,
    ip              TEXT,
    agente          TEXT
);
CREATE INDEX idx_sessoes_usuario ON sessoes(usuario_id);

-- Pares que o usuário marcou como "gastos diferentes" na tela de duplicidades (a < b).
CREATE TABLE duplicidades_ignoradas (
    a               INTEGER NOT NULL,
    b               INTEGER NOT NULL,
    PRIMARY KEY (a, b)
);

CREATE INDEX idx_lancamentos_data      ON lancamentos(data);
CREATE INDEX idx_lancamentos_categoria ON lancamentos(categoria_id);
CREATE INDEX idx_lancamentos_titular   ON lancamentos(titular_id);
CREATE INDEX idx_lancamentos_cartao    ON lancamentos(cartao_id);

-- View de conveniência: lançamento já com nome de categoria, grupo, titular, cartão e banco.
-- Substitui os SUMIFS/INDEX-MATCH que a planilha fazia em Lançamentos e Resumo Mensal.
CREATE VIEW vw_lancamentos AS
SELECT
    l.id, l.data, c.nome AS categoria, c.grupo, c.essencial, c.contabiliza,
    l.descricao, t.nome AS titular, l.forma_pagamento,
    ca.identificador AS cartao, ca.banco,
    l.valor, l.tipo, l.status, l.parcela, l.observacoes,
    l.validado, l.origem, l.alerta,
    -- A fatura do cartão é a fonte do gasto no cartão: compras lançadas à mão com "Cartão de crédito" (fora da categoria
    -- da fatura) NÃO entram nos totais (conta = 0), para não contar duas vezes.
    CASE WHEN c.contabiliza = 0 THEN 0
         WHEN l.forma_pagamento = 'Cartão de crédito' AND COALESCE(l.origem, '') != 'fatura' AND c.nome != 'Cartões de crédito'
         THEN 0 ELSE 1 END AS conta
FROM lancamentos l
JOIN categorias c        ON c.id = l.categoria_id
LEFT JOIN titulares t    ON t.id = l.titular_id
LEFT JOIN cartoes ca     ON ca.id = l.cartao_id;
