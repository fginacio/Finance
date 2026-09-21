"""
Gerenciamento de usuários pelo terminal (o primeiro usuário só pode ser criado aqui: o app começa fechado).

    python -m app.usuarios criar joao --nome "João Silva"
    python -m app.usuarios criar maria --nome "Maria Souza"
    python -m app.usuarios senha joao             # redefine a senha (e encerra as sessões abertas)
    python -m app.usuarios listar
    python -m app.usuarios desativar maria        # / ativar maria

A senha é digitada sem aparecer na tela. Para automação, use --senha-env NOME_DA_VARIAVEL.
No Docker:  docker compose exec backend python -m app.usuarios criar joao --nome "João Silva"
"""
import argparse
import getpass
import os
import sqlite3
import sys

from app.database import DATABASE_PATH, init_db
from app.seguranca import hash_senha, validar_senha


def _conectar() -> sqlite3.Connection:
    init_db()  # garante as tabelas mesmo num banco antigo
    con = sqlite3.connect(DATABASE_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _ler_senha(args, usuario: str) -> str:
    if args.senha_env:
        senha = os.environ.get(args.senha_env, "")
        if not senha:
            sys.exit(f"A variável de ambiente {args.senha_env} está vazia ou não existe.")
    else:
        senha = getpass.getpass(f"Senha de {usuario}: ")
        if senha != getpass.getpass("Repita a senha: "):
            sys.exit("As senhas não conferem. Nada foi alterado.")
    problema = validar_senha(senha, usuario)
    if problema:
        sys.exit(problema + " Nada foi alterado.")
    return senha


def _achar(con, usuario: str) -> sqlite3.Row:
    u = con.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    if u is None:
        sys.exit(f"Usuário '{usuario}' não encontrado. Use 'listar' para ver os existentes.")
    return u


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.usuarios", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    for nome in ("criar", "senha", "ativar", "desativar"):
        s = sub.add_parser(nome)
        s.add_argument("usuario")
        if nome == "criar":
            s.add_argument("--nome", help="nome exibido (padrão: o próprio usuário)")
        if nome in ("criar", "senha"):
            s.add_argument("--senha-env", metavar="VARIAVEL", help="lê a senha desta variável de ambiente")
    sub.add_parser("listar")
    args = p.parse_args(argv)

    con = _conectar()
    if args.comando == "listar":
        linhas = con.execute("SELECT usuario, nome, ativo, ultimo_login FROM usuarios ORDER BY nome").fetchall()
        if not linhas:
            print("Nenhum usuário cadastrado. O app está fechado: crie o primeiro com 'criar'.")
        for u in linhas:
            print(f"{u['usuario']:<16} {u['nome']:<28} {'ativo' if u['ativo'] else 'INATIVO':<8} último acesso: {u['ultimo_login'] or '-'}")
        return

    usuario = args.usuario.strip()
    if args.comando == "criar":
        if not usuario or " " in usuario:
            sys.exit("O usuário não pode ter espaços (ex.: fabiano).")
        if con.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone():
            sys.exit(f"O usuário '{usuario}' já existe. Para trocar a senha: python -m app.usuarios senha {usuario}")
        senha = _ler_senha(args, usuario)
        con.execute("INSERT INTO usuarios (usuario, nome, senha_hash) VALUES (?, ?, ?)", (usuario, args.nome or usuario, hash_senha(senha)))
        con.commit()
        print(f"Usuário '{usuario}' criado.")
    elif args.comando == "senha":
        u = _achar(con, usuario)
        senha = _ler_senha(args, usuario)
        con.execute("UPDATE usuarios SET senha_hash = ?, falhas = 0, bloqueado_ate = NULL WHERE id = ?", (hash_senha(senha), u["id"]))
        con.execute("DELETE FROM sessoes WHERE usuario_id = ?", (u["id"],))
        con.commit()
        print(f"Senha de '{usuario}' redefinida; as sessões abertas foram encerradas.")
    else:
        u = _achar(con, usuario)
        ativar = args.comando == "ativar"
        if not ativar and con.execute("SELECT COUNT(*) FROM usuarios WHERE ativo = 1 AND id != ?", (u["id"],)).fetchone()[0] == 0:
            sys.exit("É preciso manter pelo menos um usuário ativo.")
        con.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (1 if ativar else 0, u["id"]))
        if not ativar:
            con.execute("DELETE FROM sessoes WHERE usuario_id = ?", (u["id"],))
        con.commit()
        print(f"Usuário '{usuario}' {'reativado' if ativar else 'desativado'}.")


if __name__ == "__main__":
    main()
