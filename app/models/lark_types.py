"""
Lark 基礎資料類型模型

基於真實的 Lark API 回應資料結構定義
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum


class LarkUser(BaseModel):
    """Lark 人員欄位資料結構 (類型11)"""
    id: str = Field(..., description="使用者 ID")
    name: str = Field(..., description="使用者名稱")
    en_name: Optional[str] = Field(None, description="英文名稱")
    email: str = Field(..., description="電子郵件")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "ou_941beef388982f1f4a1a6ef9c568f21b",
                "name": "Jacky Hsueh",
                "en_name": "Jacky Hsueh",
                "email": "jacky.h@st-win.com.tw"
            }
        }
    )
    
    def __str__(self) -> str:
        return self.name
    
    @property
    def display_name(self) -> str:
        """顯示名稱，優先使用中文名，否則使用英文名"""
        return self.name or self.en_name or self.email.split('@')[0]


class LarkAttachment(BaseModel):
    """Lark 附件欄位資料結構 (類型17)"""
    file_token: str = Field(..., description="檔案 Token")
    name: str = Field(..., description="檔案名稱")
    size: int = Field(..., description="檔案大小（位元組）")
    type: str = Field(..., description="MIME 類型")
    url: str = Field(..., description="下載 URL")
    tmp_url: Optional[str] = Field(None, description="臨時下載 URL")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_token": "NjGkb2iGvonNi3x5cURlPjv2gic",
                "name": "截圖 2025-08-06 下午5.12.23.png",
                "size": 139246,
                "type": "image/png",
                "url": "https://open.larksuite.com/open-apis/drive/v1/medias/NjGkb2iGvonNi3x5cURlPjv2gic/download",
                "tmp_url": "https://open.larksuite.com/open-apis/drive/v1/medias/batch_get_tmp_download_url?file_tokens=NjGkb2iGvonNi3x5cURlPjv2gic"
            }
        }
    )
    
    @property
    def is_image(self) -> bool:
        """檢查是否為圖片檔案"""
        return self.type.startswith('image/')
    
    @property
    def file_extension(self) -> str:
        """取得檔案副檔名"""
        return self.name.split('.')[-1].lower() if '.' in self.name else ''
    
    @property
    def size_mb(self) -> float:
        """取得檔案大小（MB）"""
        return round(self.size / (1024 * 1024), 2)


class LarkRecord(BaseModel):
    """Lark 關聯記錄欄位資料結構 (類型21)"""
    record_ids: List[str] = Field(..., description="關聯記錄 ID 列表")
    table_id: str = Field(..., description="關聯表格 ID")
    text: str = Field(..., description="顯示文字")
    text_arr: List[str] = Field(..., description="文字陣列")
    type: str = Field(..., description="資料類型")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "record_ids": ["recuSBJAfVaZ5F"],
                "table_id": "tblovGcG5mC9sHRP",
                "text": "Story-CRM-00004",
                "text_arr": ["Story-CRM-00004"],
                "type": "text"
            }
        }
    )
    
    @property
    def primary_record_id(self) -> Optional[str]:
        """取得主要記錄 ID（第一個）"""
        return self.record_ids[0] if self.record_ids else None
    
    @property
    def display_text(self) -> str:
        """顯示文字"""
        return self.text or (self.text_arr[0] if self.text_arr else "")


class LarkFieldType(str, Enum):
    """Lark 欄位類型枚舉"""
    TEXT = "1"           # 文字
    NUMBER = "2"         # 數字
    SINGLE_SELECT = "3"  # 單選
    MULTI_SELECT = "4"   # 多選
    DATE = "5"          # 日期
    CHECKBOX = "7"      # 核取方塊
    USER = "11"         # 人員
    PHONE = "13"        # 電話號碼
    URL = "15"          # 網址
    ATTACHMENT = "17"   # 附件
    LOOKUP = "18"       # 查找
    FORMULA = "20"      # 公式
    LINK = "21"         # 關聯記錄


class LarkFieldMapping(BaseModel):
    """Lark 欄位映射資訊"""
    field_id: str = Field(..., description="Lark 欄位 ID")
    field_name: str = Field(..., description="欄位名稱")
    field_type: LarkFieldType = Field(..., description="欄位類型")
    mapping_field: str = Field(..., description="對應的模型欄位名稱")
    
    model_config = ConfigDict(
        use_enum_values=True,
        protected_namespaces=()
    )


# 定義常用的優先級和狀態枚舉
class Priority(str, Enum):
    """優先級枚舉"""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class TestResultStatus(str, Enum):
    """測試結果狀態枚舉"""
    PASSED = "Passed"
    FAILED = "Failed"
    RETEST = "Retest"
    NOT_AVAILABLE = "Not Available"
    PENDING = "Pending"
    NOT_REQUIRED = "Not Required"
    SKIP = "Skip"


# 輔助函數
def parse_lark_user(data: Union[List[Dict], Dict, None]) -> Optional[LarkUser]:
    """解析 Lark 人員欄位資料"""
    if not data:
        return None
    
    if isinstance(data, list) and data:
        user_data = data[0]  # 單選人員欄位取第一個
    elif isinstance(data, dict):
        user_data = data
    else:
        return None
    
    try:
        return LarkUser(**user_data)
    except Exception:
        return None


def parse_lark_attachments(data: Union[List[Dict], None]) -> List[LarkAttachment]:
    """解析 Lark 附件欄位資料"""
    if not data or not isinstance(data, list):
        return []
    
    attachments = []
    for item in data:
        try:
            attachment = LarkAttachment(**item)
            attachments.append(attachment)
        except Exception:
            continue  # 忽略無效的附件資料
    
    return attachments


def parse_lark_records(data: Union[List[Dict], None]) -> List[LarkRecord]:
    """解析 Lark 關聯記錄欄位資料"""
    if not data or not isinstance(data, list):
        return []
    
    records = []
    for item in data:
        try:
            record = LarkRecord(**item)
            records.append(record)
        except Exception:
            continue  # 忽略無效的記錄資料
    
    return records
