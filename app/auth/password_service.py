"""
密碼管理服務

提供密碼雜湊、驗證、強度檢查等功能。
使用 bcrypt 進行安全的密碼雜湊。
"""

import secrets
import string
import re
from passlib.hash import bcrypt
from typing import Tuple


class PasswordService:
    """密碼管理服務"""
    
    # bcrypt cost factor = 12 (平衡安全性與效能)
    BCRYPT_ROUNDS = 12
    
    # 密碼強度規則
    MIN_LENGTH = 8
    MAX_LENGTH = 128
    
    @classmethod
    def hash_password(cls, password: str) -> str:
        """
        雜湊密碼
        
        Args:
            password: 明文密碼
            
        Returns:
            雜湊後的密碼
        """
        return bcrypt.using(rounds=cls.BCRYPT_ROUNDS).hash(password)
    
    @classmethod
    def verify_password(cls, password: str, hashed_password: str) -> bool:
        """
        驗證密碼
        
        Args:
            password: 明文密碼
            hashed_password: 雜湊密碼
            
        Returns:
            密碼是否正確
        """
        try:
            return bcrypt.verify(password, hashed_password)
        except Exception:
            return False
    
    @classmethod
    def check_password_strength(cls, password: str) -> Tuple[bool, str]:
        """
        檢查密碼強度
        
        Args:
            password: 要檢查的密碼
            
        Returns:
            tuple: (是否符合強度要求, 錯誤訊息)
        """
        if len(password) < cls.MIN_LENGTH:
            return False, f"密碼長度至少需要 {cls.MIN_LENGTH} 字符"
        
        if len(password) > cls.MAX_LENGTH:
            return False, f"密碼長度不能超過 {cls.MAX_LENGTH} 字符"
        
        # 檢查是否包含數字
        if not re.search(r'\d', password):
            return False, "密碼必須包含至少一個數字"
        
        # 檢查是否包含字母
        if not re.search(r'[a-zA-Z]', password):
            return False, "密碼必須包含至少一個字母"
        
        return True, ""
    
    @classmethod
    def generate_temp_password(cls, length: int = 12) -> str:
        """
        生成臨時密碼
        
        Args:
            length: 密碼長度（預設 12）
            
        Returns:
            隨機生成的密碼
        """
        if length < cls.MIN_LENGTH:
            length = cls.MIN_LENGTH
        
        # 確保密碼包含字母和數字
        chars = string.ascii_letters + string.digits
        
        # 至少包含一個字母和一個數字
        password = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase), 
            secrets.choice(string.digits)
        ]
        
        # 填充剩餘長度
        for _ in range(length - 3):
            password.append(secrets.choice(chars))
        
        # 打亂順序
        secrets.SystemRandom().shuffle(password)
        
        return ''.join(password)
    
    @classmethod
    def is_password_compromised(cls, password: str) -> bool:
        """
        檢查密碼是否為常見弱密碼
        
        Args:
            password: 要檢查的密碼
            
        Returns:
            是否為常見弱密碼
        """
        # 常見弱密碼列表（可擴展）
        common_passwords = {
            "password", "123456", "123456789", "qwerty", "abc123",
            "password123", "admin", "root", "test", "user",
            "12345678", "1234567890", "qwerty123", "admin123"
        }
        
        return password.lower() in common_passwords
    
    @classmethod
    def validate_password_for_creation(cls, password: str) -> Tuple[bool, str]:
        """
        驗證密碼是否適合建立新帳戶
        
        Args:
            password: 要驗證的密碼
            
        Returns:
            tuple: (是否有效, 錯誤訊息)
        """
        # 檢查基本強度
        is_strong, strength_msg = cls.check_password_strength(password)
        if not is_strong:
            return False, strength_msg
        
        # 檢查是否為常見弱密碼
        if cls.is_password_compromised(password):
            return False, "此密碼過於常見，請選擇更安全的密碼"
        
        return True, ""