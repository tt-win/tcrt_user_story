#!/usr/bin/env python3
"""
Lark 部門遍歷服務

負責遞歸遍歷 Lark 組織架構，收集所有部門信息並存儲到本地數據庫。
基於實際 API 測試數據設計，支援斷點續傳和增量同步。
"""

import json
import logging
import requests
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import run_sync
from app.models.database_models import LarkDepartment
from app.services.lark_client import LarkAuthManager


class LarkDepartmentService:
    """Lark 部門遍歷服務"""
    
    def __init__(self, auth_manager: LarkAuthManager):
        self.auth_manager = auth_manager
        self.logger = logging.getLogger(__name__)
        
        # API 配置
        self.base_url = "https://open.larksuite.com/open-apis"
        self.timeout = 30
        
        # 遍歷統計
        self.stats = {
            'departments_discovered': 0,
            'departments_created': 0,
            'departments_updated': 0,
            'api_calls': 0,
            'errors': 0,
            'start_time': None,
            'end_time': None
        }
        
        # 遍歷狀態
        self.visited_departments = set()  # 避免重複遍歷
        self.max_level = 10  # 最大遍歷層級
        
    def get_department_children(self, department_id: str) -> Optional[List[Dict]]:
        """獲取部門的子部門列表"""
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                self.logger.error("無法獲取 access token")
                return None
            
            url = f"{self.base_url}/contact/v3/departments/{department_id}/children"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            params = {
                'department_id_type': 'open_department_id',
                'page_size': 50,  # 每頁最大數量
                'user_id_type': 'open_id'
            }
            
            self.stats['api_calls'] += 1
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    children = data.get('data', {}).get('items', [])
                    self.logger.debug(f"部門 {department_id} 有 {len(children)} 個子部門")
                    return children
                else:
                    self.logger.warning(f"API 返回錯誤: {data}")
                    return None
            else:
                self.logger.error(f"HTTP 請求失敗: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"獲取部門子部門異常: {e}")
            self.stats['errors'] += 1
            return None
    
    async def save_department(
        self,
        db: AsyncSession,
        department_id: str,
        parent_id: Optional[str],
        level: int,
        children_data: List[Dict],
        path: str,
    ) -> bool:
        """保存部門信息到數據庫"""
        def _save(sync_db: Session) -> bool:
            try:
                # 檢查部門是否已存在
                existing_dept = sync_db.query(LarkDepartment).filter(
                    LarkDepartment.department_id == department_id
                ).first()

                now = datetime.utcnow()

                if existing_dept:
                    # 更新現有部門
                    existing_dept.parent_department_id = parent_id
                    existing_dept.level = level
                    existing_dept.path = path
                    existing_dept.updated_at = now
                    existing_dept.last_sync_at = now

                    # 不在部門遍歷時更新 direct_user_count，改由用戶同步後重算

                    self.stats['departments_updated'] += 1
                    self.logger.debug(f"更新部門: {department_id}")
                else:
                    # 創建新部門
                    new_dept = LarkDepartment(
                        department_id=department_id,
                        parent_department_id=parent_id,
                        level=level,
                        path=path,
                        direct_user_count=0,
                        status='active',
                        created_at=now,
                        updated_at=now,
                        last_sync_at=now
                    )

                    # 如果有子部門數據，存儲為 JSON
                    if children_data:
                        # 提取並存儲領導信息和群聊員工類型
                        leaders_data = []
                        group_chat_types = []

                        for child in children_data:
                            if child.get('leaders'):
                                leaders_data.extend(child['leaders'])
                            if child.get('group_chat_employee_types'):
                                group_chat_types.extend(child['group_chat_employee_types'])

                        if leaders_data:
                            new_dept.leaders_json = json.dumps(leaders_data, ensure_ascii=False)
                        if group_chat_types:
                            new_dept.group_chat_employee_types_json = json.dumps(group_chat_types, ensure_ascii=False)

                    sync_db.add(new_dept)
                    self.stats['departments_created'] += 1
                    self.logger.debug(f"創建新部門: {department_id}")

                sync_db.commit()
                return True

            except IntegrityError as e:
                sync_db.rollback()
                self.logger.error(f"保存部門時數據庫完整性錯誤: {e}")
                self.stats['errors'] += 1
                return False
            except Exception as e:
                sync_db.rollback()
                self.logger.error(f"保存部門異常: {e}")
                self.stats['errors'] += 1
                return False

        return await run_sync(db, _save)
    
    async def traverse_department_recursive(
        self,
        db: AsyncSession,
        department_id: str,
        parent_id: Optional[str] = None,
                                    level: int = 0, path: str = "") -> bool:
        """遞歸遍歷部門層次結構"""
        
        # 檢查是否已訪問過此部門（避免循環）
        if department_id in self.visited_departments:
            self.logger.warning(f"部門 {department_id} 已遍歷過，跳過")
            return True
        
        # 檢查層級限制
        if level > self.max_level:
            self.logger.warning(f"達到最大遍歷層級 {self.max_level}，停止遞歸")
            return False
        
        self.logger.info(f"遍歷部門: {department_id} (層級: {level}, 路徑: {path})")
        self.visited_departments.add(department_id)
        self.stats['departments_discovered'] += 1
        
        # 獲取子部門
        children_data = self.get_department_children(department_id)
        if children_data is None:
            self.logger.warning(f"無法獲取部門 {department_id} 的子部門")
            return False
        
        # 構建當前部門路徑
        current_path = f"{path}/{department_id}" if path else f"/{department_id}"
        
        # 保存當前部門信息
        if not await self.save_department(db, department_id, parent_id, level, children_data, current_path):
            self.logger.error(f"保存部門 {department_id} 失敗")
            return False
        
        # 遞歸處理子部門
        success_count = 0
        for child_dept in children_data:
            child_id = child_dept.get('open_department_id')
            if child_id:
                try:
                    if await self.traverse_department_recursive(db, child_id, department_id, level + 1, current_path):
                        success_count += 1
                    else:
                        self.logger.warning(f"遍歷子部門 {child_id} 失敗")
                except Exception as e:
                    self.logger.error(f"遍歷子部門 {child_id} 時發生異常: {e}")
                    self.stats['errors'] += 1
        
        self.logger.info(f"部門 {department_id} 遍歷完成，成功處理 {success_count}/{len(children_data)} 個子部門")
        return True
    
    async def sync_all_departments(self, db: AsyncSession, root_departments: List[str]) -> Dict[str, Any]:
        """同步所有部門數據"""
        self.logger.info("開始 Lark 部門同步...")
        self.stats['start_time'] = datetime.utcnow()
        
        # 重置統計和狀態
        self.visited_departments.clear()
        for key in ['departments_discovered', 'departments_created', 'departments_updated', 'api_calls', 'errors']:
            self.stats[key] = 0
        
        success_roots = 0
        
        try:
            for root_dept_id in root_departments:
                self.logger.info(f"開始遍歷根部門: {root_dept_id}")
                
                if await self.traverse_department_recursive(db, root_dept_id):
                    success_roots += 1
                    self.logger.info(f"根部門 {root_dept_id} 遍歷成功")
                else:
                    self.logger.error(f"根部門 {root_dept_id} 遍歷失敗")
            
            self.stats['end_time'] = datetime.utcnow()
            duration = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
            
            result = {
                'success': success_roots == len(root_departments),
                'duration_seconds': duration,
                'stats': self.stats.copy(),
                'message': f"部門同步完成，處理了 {success_roots}/{len(root_departments)} 個根部門"
            }
            
            self.logger.info(f"部門同步完成: {result['message']}")
            self.logger.info(f"統計: 發現 {self.stats['departments_discovered']} 個部門，"
                           f"新增 {self.stats['departments_created']} 個，"
                           f"更新 {self.stats['departments_updated']} 個，"
                           f"API 調用 {self.stats['api_calls']} 次，"
                           f"錯誤 {self.stats['errors']} 個")
            
            return result
            
        except Exception as e:
            self.logger.error(f"部門同步過程中發生嚴重錯誤: {e}")
            return {
                'success': False,
                'duration_seconds': 0,
                'stats': self.stats.copy(),
                'message': f"部門同步失敗: {str(e)}"
            }
    
    async def get_department_stats(self, db: AsyncSession) -> Dict[str, Any]:
        """獲取部門統計信息"""
        def _get_stats(sync_db: Session) -> Dict[str, Any]:
            try:
                total_depts = sync_db.query(LarkDepartment).count()
                active_depts = sync_db.query(LarkDepartment).filter(
                    LarkDepartment.status == 'active'
                ).count()

                # 層級分布
                level_stats = {}
                for level in range(0, self.max_level + 1):
                    count = sync_db.query(LarkDepartment).filter(
                        LarkDepartment.level == level
                    ).count()
                    if count > 0:
                        level_stats[f'level_{level}'] = count

                # 最近同步時間
                last_sync = sync_db.query(LarkDepartment.last_sync_at).order_by(
                    LarkDepartment.last_sync_at.desc()
                ).first()

                return {
                    'total_departments': total_depts,
                    'active_departments': active_depts,
                    'level_distribution': level_stats,
                    'last_sync_at': last_sync[0].isoformat() if last_sync and last_sync[0] else None
                }

            except Exception as e:
                self.logger.error(f"獲取部門統計信息失敗: {e}")
                return {'error': str(e)}

        return await run_sync(db, _get_stats)
    
    async def cleanup_inactive_departments(self, db: AsyncSession, days_threshold: int = 30) -> int:
        """清理超過指定天數未同步的部門"""
        def _cleanup(sync_db: Session) -> int:
            try:
                threshold_date = datetime.utcnow() - timedelta(days=days_threshold)

                deleted_count = sync_db.query(LarkDepartment).filter(
                    LarkDepartment.last_sync_at < threshold_date,
                    LarkDepartment.status == 'active'
                ).update({'status': 'inactive'})

                sync_db.commit()
                self.logger.info(f"標記了 {deleted_count} 個部門為非活躍狀態")
                return deleted_count

            except Exception as e:
                sync_db.rollback()
                self.logger.error(f"清理非活躍部門失敗: {e}")
                return 0

        return await run_sync(db, _cleanup)
