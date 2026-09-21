"""Gera a senha que protege os backups do OneDrive (scripts/cifrar_backup.py) e grava fora do OneDrive.

Só precisa rodar uma vez (ou de novo para trocar a senha - nesse caso, backups antigos cifrados com a
senha anterior deixam de abrir; guarde a senha antiga em outro lugar seguro se ainda precisar deles).

Uso: python scripts/gerar_senha_backup.py
"""
import os
import secrets
import stat
from pathlib import Path

DESTINO = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".controle-gastos" / "backup.senha"


def main() -> None:
    if DESTINO.exists():
        resposta = input(f"Já existe uma senha em {DESTINO}. Gerar outra e SUBSTITUIR? (digite 'sim'): ")
        if resposta.strip().lower() != "sim":
            print("Nada foi alterado.")
            return
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    senha = secrets.token_urlsafe(24)
    DESTINO.write_text(senha, encoding="utf-8")
    try:
        os.chmod(DESTINO, stat.S_IRUSR | stat.S_IWUSR)  # sem efeito real no Windows, mas não custa nada
    except OSError:
        pass
    print(f"Senha gerada e gravada em {DESTINO} (fora do OneDrive; não aparece na tela nem no chat).")
    print("A partir do próximo backup semanal, os arquivos em backups\\ ficam cifrados (extensão .db.enc).")


if __name__ == "__main__":
    main()
