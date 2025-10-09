"""
密碼加密解密服務
使用 RSA 非對稱加密來保護傳輸中的密碼
"""
import base64
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class PasswordEncryptionService:
    """密碼加密解密服務"""

    # 金鑰儲存路徑
    KEY_DIR = Path(__file__).parent.parent.parent / "keys"
    PRIVATE_KEY_FILE = KEY_DIR / "private_key.pem"
    PUBLIC_KEY_FILE = KEY_DIR / "public_key.pem"

    _private_key = None
    _public_key = None

    @classmethod
    def initialize(cls):
        """初始化金鑰對（如果不存在則生成）"""
        try:
            # 確保金鑰目錄存在
            cls.KEY_DIR.mkdir(parents=True, exist_ok=True)

            # 如果金鑰已存在，載入它們
            if cls.PRIVATE_KEY_FILE.exists() and cls.PUBLIC_KEY_FILE.exists():
                logger.info("載入現有的 RSA 金鑰對")
                cls._load_keys()
            else:
                logger.info("生成新的 RSA 金鑰對")
                cls._generate_and_save_keys()

            logger.info("密碼加密服務初始化成功")
        except Exception as e:
            logger.error(f"密碼加密服務初始化失敗: {e}")
            raise

    @classmethod
    def _generate_and_save_keys(cls):
        """生成並保存 RSA 金鑰對"""
        # 生成私鑰
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )

        # 生成公鑰
        public_key = private_key.public_key()

        # 保存私鑰
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(cls.PRIVATE_KEY_FILE, 'wb') as f:
            f.write(private_pem)
        # 設置私鑰檔案權限為只有擁有者可讀寫
        os.chmod(cls.PRIVATE_KEY_FILE, 0o600)

        # 保存公鑰
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with open(cls.PUBLIC_KEY_FILE, 'wb') as f:
            f.write(public_pem)

        cls._private_key = private_key
        cls._public_key = public_key

        logger.info("RSA 金鑰對已生成並保存")

    @classmethod
    def _load_keys(cls):
        """載入 RSA 金鑰對"""
        # 載入私鑰
        with open(cls.PRIVATE_KEY_FILE, 'rb') as f:
            private_pem = f.read()
            cls._private_key = serialization.load_pem_private_key(
                private_pem,
                password=None,
                backend=default_backend()
            )

        # 載入公鑰
        with open(cls.PUBLIC_KEY_FILE, 'rb') as f:
            public_pem = f.read()
            cls._public_key = serialization.load_pem_public_key(
                public_pem,
                backend=default_backend()
            )

        logger.info("RSA 金鑰對已載入")

    @classmethod
    def get_public_key_base64(cls) -> str:
        """
        獲取 Base64 編碼的公鑰（用於前端）

        Returns:
            Base64 編碼的公鑰（SPKI 格式）
        """
        if cls._public_key is None:
            cls.initialize()

        public_pem = cls._public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return base64.b64encode(public_pem).decode('utf-8')

    @classmethod
    def decrypt_password(cls, encrypted_password: str) -> str:
        """
        解密前端加密的密碼

        Args:
            encrypted_password: Base64 編碼的加密密碼

        Returns:
            解密後的明文密碼
        """
        if cls._private_key is None:
            cls.initialize()

        try:
            # Base64 解碼
            encrypted_data = base64.b64decode(encrypted_password)

            # 使用私鑰解密
            decrypted_data = cls._private_key.decrypt(
                encrypted_data,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )

            # 轉換為字串
            return decrypted_data.decode('utf-8')
        except Exception as e:
            logger.error(f"解密密碼失敗: {e}")
            raise ValueError("密碼解密失敗")


# 服務實例
password_encryption_service = PasswordEncryptionService
