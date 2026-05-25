"""
API Key 加密/解密工具
使用 Fernet (AES-128-CBC + HMAC) 加密，密钥从 passphrase 派生。
passphrase 通过环境变量 SECRET_PASSPHRASE 传入，不在代码中存储。
"""
import base64
import json
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ENV_KEY = "SECRET_PASSPHRASE"


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
    return key


def encrypt(plaintext: str, passphrase: str) -> str:
    """加密 API Key，返回 base64 字符串"""
    salt = os.urandom(16)
    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)
    token = fernet.encrypt(plaintext.encode("utf-8"))
    payload = {"salt": base64.b64encode(salt).decode(), "token": token.decode()}
    return json.dumps(payload)


def decrypt(encrypted: str, passphrase: str) -> str:
    """解密 API Key"""
    payload = json.loads(encrypted)
    salt = base64.b64decode(payload["salt"])
    token = payload["token"].encode()
    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)
    return fernet.decrypt(token).decode("utf-8")


def load_api_key(env_var: str) -> str:
    """从加密文件加载并解密 API Key。
    加密文件路径: env_var 指向的 .enc 文件
    passphrase: 从环境变量 SECRET_PASSPHRASE 读取
    """
    enc_path = os.getenv(env_var)
    if not enc_path:
        raise RuntimeError(f"环境变量 {env_var} 未设置（应指向 .enc 加密文件）")

    passphrase = os.getenv(_ENV_KEY)
    if not passphrase:
        raise RuntimeError(f"环境变量 {_ENV_KEY} 未设置，无法解密 API Key")

    with open(enc_path, "r") as f:
        encrypted = f.read().strip()

    return decrypt(encrypted, passphrase)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python crypto_utils.py <api-key>")
        print("  加密 API Key 并输出到 stdout")
        sys.exit(1)

    api_key = sys.argv[1]
    passphrase = os.getenv(_ENV_KEY)
    if not passphrase:
        passphrase = base64.b64encode(os.urandom(24)).decode()
        print(f"[INFO] 自动生成 passphrase，请保存: {passphrase}")

    encrypted = encrypt(api_key, passphrase)
    print(f"ENCRYPTED_KEY={encrypted}")
