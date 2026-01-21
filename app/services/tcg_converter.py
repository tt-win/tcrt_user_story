"""
TCG 單號轉換服務

負責將 Lark record_id 轉換為實際的 TCG 單號顯示，參照 auto_tools 的實現方式
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class TCGConverter:
    """TCG 單號轉換器，負責將 record_id 轉換為實際的 TCG 單號"""
    
    def __init__(self, db_path: str = "test_case_repo.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._initialized = False
        self._init_lock = None
    
    async def _ensure_initialized(self, db: AsyncSession) -> None:
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self._init_database(db)
            self._initialized = True

    async def _init_database(self, db: AsyncSession) -> None:
        """初始化數據庫表格"""
        try:
            # 使用 TCG 單號作為主鍵避免重複
            await db.execute(text('''
                CREATE TABLE IF NOT EXISTS tcg_records (
                    tcg_number TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL,
                    title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            # 為 record_id 建立索引
            await db.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_record_id ON tcg_records(record_id)
            '''))
            await db.commit()
            self.logger.info("TCG 映射資料庫初始化完成")
        except Exception as e:
            self.logger.error(f"初始化 TCG 映射資料庫失敗: {e}")
    
    async def sync_tcg_from_lark(self, db: AsyncSession) -> int:
        """
        從 Lark 同步所有 TCG 資料到本地資料庫
        使用單一交易確保原子性
        
        Returns:
            同步的記錄數量
        """
        try:
            from app.services.lark_client import LarkClient
            from app.config import settings
            
            # 使用非阻塞鎖避免同一進程內重複同步
            if not hasattr(self, "_sync_lock"):
                self._sync_lock = asyncio.Lock()

            if self._sync_lock.locked():
                self.logger.warning("TCG 同步正在進行中，跳過此次同步")
                return 0

            async with self._sync_lock:
                await self._ensure_initialized(db)
                # 初始化 Lark 客戶端
                lark_client = LarkClient(
                    app_id=settings.lark.app_id,
                    app_secret=settings.lark.app_secret
                )

                tcg_wiki_token = "Q4XxwaS2Cif80DkAku9lMKuAgof"
                # 需要同步的兩張 TCG 表格
                tcg_table_ids = [
                    "tblcK6eF3yQCuwwl",  # 原本的 TCG 表
                    "tbl22a72JrEcdLGB"   # 新增的 TCG 表
                ]

                if not lark_client.set_wiki_token(tcg_wiki_token):
                    self.logger.error("無法設定 Lark Wiki Token")
                    return 0

                self.logger.info("開始從 Lark 同步 TCG 資料...")

                # 從兩張表格收集所有 TCG 資料
                all_records = []
                for table_id in tcg_table_ids:
                    self.logger.info(f"正在從表格 {table_id} 同步資料...")
                    records = lark_client.get_all_records(table_id)
                    if records:
                        all_records.extend(records)
                        self.logger.info(f"從表格 {table_id} 取得 {len(records)} 筆記錄")
                    else:
                        self.logger.warning(f"未從表格 {table_id} 取得到任何記錄")

                if not all_records:
                    self.logger.warning("未從 Lark 取得到任何 TCG 記錄")
                    return 0

                # 在單一交易中完成清空和重建
                return await self._atomic_sync_records(db, all_records)
            
        except Exception as e:
            self.logger.error(f"從 Lark 同步 TCG 資料失敗: {e}")
            return 0
    
    async def _atomic_sync_records(self, db: AsyncSession, records: List[Dict[str, Any]]) -> int:
        """在單一交易中完成 TCG 記錄同步"""
        try:
            await self._ensure_initialized(db)

            # 清空舊資料
            await db.execute(text("DELETE FROM tcg_records"))

            # 批量插入新資料
            updated_count = 0
            for record in records:
                record_id = record.get('record_id')
                fields = record.get('fields', {})
                
                # 提取 TCG 號碼
                raw_tcg = (
                    fields.get('TCG Tickets') or
                    fields.get('TCG Number') or 
                    fields.get('TCG') or 
                    fields.get('Ticket Number')
                )
                
                tcg_number = self._extract_text_from_field(raw_tcg)
                
                if updated_count == 0:
                    self.logger.info(f"第一個記錄的所有欄位: {list(fields.keys())}")
                    if raw_tcg:
                        self.logger.info(f"第一個 TCG 記錄結構: {raw_tcg}")
                        self.logger.info(f"解析後的 TCG 號碼: {tcg_number}")
                
                title = (
                    fields.get('Title') or
                    fields.get('標題') or
                    fields.get('名稱') or
                    self._extract_text_from_field(fields.get('Title'))
                )
                
                if record_id and tcg_number:
                    # 使用 INSERT OR REPLACE
                    await db.execute(text('''
                        INSERT OR REPLACE INTO tcg_records 
                        (tcg_number, record_id, title, updated_at)
                        VALUES (:tcg_number, :record_id, :title, CURRENT_TIMESTAMP)
                    '''), {
                        'tcg_number': tcg_number,
                        'record_id': record_id,
                        'title': title
                    })
                    updated_count += 1
            
            # 提交交易
            await db.commit()
            self.logger.info(f"更新了 {updated_count} 個 TCG 映射記錄")
            return updated_count
            
        except Exception as e:
            await db.rollback()
            self.logger.error(f"同步 TCG 記錄失敗: {e}")
            return 0
    
    async def update_tcg_mapping_from_lark_records(
        self, db: AsyncSession, lark_records: List[Dict[str, Any]]
    ) -> int:
        """
        從 Lark 記錄更新 TCG 映射（已棄用，請使用 sync_tcg_from_lark）
        
        Args:
            lark_records: Lark API 返回的記錄列表
        
        Returns:
            更新的記錄數量
        """
        # 這個方法保留是為了向後相容，實際上呼叫新的原子同步方法
        return await self._atomic_sync_records(db, lark_records)
    
    async def get_tcg_number_by_record_id(self, db: AsyncSession, record_id: str) -> Optional[str]:
        """將單個 record_id 轉換為 TCG 單號"""
        if not record_id:
            return None
        
        try:
            await self._ensure_initialized(db)
            result = await db.execute(
                text("SELECT tcg_number FROM tcg_records WHERE record_id = :record_id"),
                {'record_id': record_id}
            )
            row = result.fetchone()
            return row[0] if row else None
        except Exception as e:
            self.logger.error(f"查詢 record_id {record_id} 對應的 TCG 單號失敗: {e}")
            return None
    
    async def get_tcg_numbers_by_record_ids(
        self, db: AsyncSession, record_ids: List[str]
    ) -> Dict[str, str]:
        """批量轉換多個 record_id"""
        if not record_ids:
            return {}
        
        try:
            await self._ensure_initialized(db)
            # 使用參數化查詢避免 SQL 注入
            placeholders = ", ".join([f":id{i}" for i in range(len(record_ids))])
            params = {f"id{i}": record_id for i, record_id in enumerate(record_ids)}
            
            results = await db.execute(
                text(f"SELECT record_id, tcg_number FROM tcg_records WHERE record_id IN ({placeholders})"),
                params
            )
            rows = results.fetchall()
            return {record_id: tcg_number for record_id, tcg_number in rows}
        except Exception as e:
            self.logger.error(f"批量查詢 record_ids 對應的 TCG 單號失敗: {e}")
            return {}
    
    async def get_record_id_by_tcg_number(self, db: AsyncSession, tcg_number: str) -> Optional[str]:
        """根據 TCG 單號查找 record_id（用於搜尋功能）"""
        if not tcg_number:
            return None
        
        try:
            await self._ensure_initialized(db)
            result = await db.execute(
                text("SELECT record_id FROM tcg_records WHERE tcg_number = :tcg_number"),
                {'tcg_number': tcg_number}
            )
            row = result.fetchone()
            return row[0] if row else None
        except Exception as e:
            self.logger.error(f"查詢 TCG 單號 {tcg_number} 對應的 record_id 失敗: {e}")
            return None
    
    async def search_tcg_numbers(
        self, db: AsyncSession, keyword: str = "", limit: int = 50
    ) -> List[Dict[str, str]]:
        """搜尋 TCG 單號"""
        try:
            await self._ensure_initialized(db)
            if keyword:
                results = await db.execute(
                    text('''
                        SELECT record_id, tcg_number, title 
                        FROM tcg_records 
                        WHERE tcg_number LIKE :keyword OR title LIKE :keyword
                        ORDER BY tcg_number
                        LIMIT :limit
                    '''),
                    {'keyword': f'%{keyword}%', 'limit': limit}
                )
            else:
                results = await db.execute(
                    text('''
                        SELECT record_id, tcg_number, title 
                        FROM tcg_records 
                        ORDER BY tcg_number
                        LIMIT :limit
                    '''),
                    {'limit': limit}
                )

            rows = results.fetchall()
            
            return [
                {
                    'record_id': record_id,
                    'tcg_number': tcg_number,
                    'title': title or '',
                    'display_text': tcg_number
                }
                for record_id, tcg_number, title in rows
            ]
        except Exception as e:
            self.logger.error(f"搜尋 TCG 單號失敗: {e}")
            return []
    
    async def get_popular_tcg_numbers(
        self, db: AsyncSession, limit: int = 20
    ) -> List[Dict[str, str]]:
        """取得熱門的 TCG 單號（按使用頻率）"""
        # 暫時返回所有 TCG，未來可以實現使用統計
        return await self.search_tcg_numbers(db, "", limit)
    
    async def get_all_tcg_mappings(self, db: AsyncSession) -> Dict[str, str]:
        """取得所有 TCG 映射（用於同步檢查）"""
        try:
            await self._ensure_initialized(db)
            results = await db.execute(
                text("SELECT record_id, tcg_number FROM tcg_records")
            )
            rows = results.fetchall()
            return {record_id: tcg_number for record_id, tcg_number in rows}
        except Exception as e:
            self.logger.error(f"取得所有 TCG 映射失敗: {e}")
            return {}
    
    async def clear_all_mappings(self, db: AsyncSession) -> bool:
        """清除所有映射（用於重新同步）"""
        try:
            await self._ensure_initialized(db)
            await db.execute(text("DELETE FROM tcg_records"))
            await db.commit()
            self.logger.info("已清除所有 TCG 映射")
            return True
        except Exception as e:
            await db.rollback()
            self.logger.error(f"清除 TCG 映射失敗: {e}")
            return False
    
    @staticmethod
    def _extract_text_from_field(field_value: Any) -> Optional[str]:
        """從各種 Lark 欄位格式中提取文字內容"""
        if field_value is None:
            return None
        
        # 如果已經是字符串，直接返回
        if isinstance(field_value, str):
            return field_value.strip() if field_value.strip() else None
        
        # 處理字典格式: {'text': 'TCG-82567', 'link': 'https://jira.tc-gaming.co/jira/browse/TCG-82567'}
        if isinstance(field_value, dict):
            # 先嘗試 text 欄位
            text = field_value.get('text')
            if text and isinstance(text, str):
                stripped_text = text.strip()
                return stripped_text if stripped_text else None
            # 再嘗試 link 欄位
            link = field_value.get('link')
            if link and isinstance(link, str):
                stripped_link = link.strip()
                return stripped_link if stripped_link else None
            # 如果都沒有，返回 None 而不是字符串化整個 dict
            return None
        
        # 處理列表格式: [{'text': 'TCG-93178', 'type': 'text'}]
        if isinstance(field_value, list) and field_value:
            first_item = field_value[0]
            # 遞歸處理第一個元素
            return TCGConverter._extract_text_from_field(first_item)
        
        # 其他類型轉為字符串
        try:
            result = str(field_value).strip()
            return result if result else None
        except:
            return None


# 全域轉換器實例
tcg_converter = TCGConverter()
