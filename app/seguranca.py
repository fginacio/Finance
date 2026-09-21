"""
Primitivas de segurança: hash de senha (scrypt, biblioteca padrão), token de sessão e regras de senha.

Nada aqui conhece HTTP ou banco de dados.
"""
import base64
import hashlib
import hmac
import os
import secrets

# scrypt no nível recomendado pela OWASP (N=2^15, r=8, p=3: 32 MiB e ~0,2 s por verificação). Os parâmetros ficam
# gravados no hash: dá para aumentá-los depois, e hashes antigos (mais fracos) são refeitos no próximo login.
_N, _R, _P, _TAM = 2 ** 15, 8, 3, 32


def _scrypt(senha: str, sal: bytes, n: int, r: int, p: int, tamanho: int) -> bytes:
    memoria = 128 * n * r + 128 * r * p
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=tamanho, maxmem=2 * memoria + (1 << 20))
SENHA_MIN = 8


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_senha(senha: str) -> str:
    sal = os.urandom(16)
    h = _scrypt(senha, sal, _N, _R, _P, _TAM)
    return f"scrypt${_N}${_R}${_P}${_b64(sal)}${_b64(h)}"


def verificar_senha(senha: str, guardado: str) -> bool:
    """Compara em tempo constante. Formato inválido nunca autentica."""
    try:
        alg, n, r, p, sal, esperado = guardado.split("$")
        if alg != "scrypt":
            return False
        calculado = _scrypt(senha, base64.b64decode(sal), int(n), int(r), int(p), len(base64.b64decode(esperado)))
        return hmac.compare_digest(calculado, base64.b64decode(esperado))
    except (ValueError, TypeError):
        return False


def precisa_refazer_hash(guardado: str) -> bool:
    """True se o hash foi gerado com parâmetros mais fracos que os atuais (refazer após um login correto)."""
    try:
        _, n, r, p, _, _ = guardado.split("$")
        return (int(n), int(r), int(p)) < (_N, _R, _P)
    except ValueError:
        return True


# Verificação "de mentira" para quando o usuário não existe: gasta o mesmo tempo e não revela quem existe.
HASH_FALSO = hash_senha(secrets.token_urlsafe(16))


def novo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """No banco fica só o hash: quem lê o arquivo do banco não consegue usar as sessões."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validar_senha(senha: str, usuario: str = "") -> str | None:
    """Mensagem de erro se a senha for fraca, ou None se estiver aceitável."""
    if len(senha) < SENHA_MIN:
        return f"A senha precisa ter pelo menos {SENHA_MIN} caracteres."
    if usuario and senha.lower() == usuario.lower():
        return "A senha não pode ser igual ao nome de usuário."
    if senha.isdigit() or len(set(senha)) < 4:
        return "Escolha uma senha menos previsível (misture letras e números, ou use uma frase)."
    return None
