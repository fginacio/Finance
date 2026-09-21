"""Cifra (ou decifra) um arquivo de backup do banco, para guardar no OneDrive sem expor os dados.

Chave derivada da senha em %USERPROFILE%\\.controle-gastos\\backup.senha (fora do OneDrive, nunca sincronizada)
com scrypt + sal aleatório por arquivo. Cifra com Fernet (AES-128-CBC + HMAC-SHA256, da lib `cryptography`,
já usada pelo app para PDFs com senha). O sal fica nos primeiros 16 bytes do arquivo .enc.

Uso:
    python scripts/cifrar_backup.py cifrar   caminho/backup.db       # -> caminho/backup.db.enc, remove o .db
    python scripts/cifrar_backup.py decifrar caminho/backup.db.enc   # -> caminho/backup.db
"""
import base64
import hashlib
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ARQUIVO_SENHA = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".controle-gastos" / "backup.senha"
_N, _R, _P, _TAM = 2 ** 14, 8, 1, 32  # mais leve que o login (é rodado num script de backup, não numa tentativa de invasão)


def _senha() -> str:
    if not ARQUIVO_SENHA.exists():
        sys.exit(f"Senha de backup não encontrada em {ARQUIVO_SENHA}. Rode primeiro: python scripts/gerar_senha_backup.py")
    return ARQUIVO_SENHA.read_text(encoding="utf-8").strip()


def _chave(sal: bytes) -> bytes:
    h = hashlib.scrypt(_senha().encode("utf-8"), salt=sal, n=_N, r=_R, p=_P, dklen=_TAM)
    return base64.urlsafe_b64encode(h)


def cifrar(origem: Path) -> Path:
    sal = os.urandom(16)
    token = Fernet(_chave(sal)).encrypt(origem.read_bytes())
    destino = origem.with_suffix(origem.suffix + ".enc")
    destino.write_bytes(sal + token)
    origem.unlink()  # não deixa a cópia sem cifrar
    return destino


def decifrar(origem: Path) -> Path:
    dados = origem.read_bytes()
    sal, token = dados[:16], dados[16:]
    texto = Fernet(_chave(sal)).decrypt(token)
    destino = origem.with_suffix("")  # tira o ".enc"
    destino.write_bytes(texto)
    return destino


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("cifrar", "decifrar"):
        sys.exit(__doc__)
    caminho = Path(sys.argv[2])
    if not caminho.exists():
        sys.exit(f"Arquivo não encontrado: {caminho}")
    resultado = cifrar(caminho) if sys.argv[1] == "cifrar" else decifrar(caminho)
    print(f"OK: {resultado}")
