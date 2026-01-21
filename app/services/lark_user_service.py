#!/usr/bin/env python3
"""
Lark 用戶收集服務

負責從 Lark 各部門收集用戶數據並存儲到本地數據庫。
基於實際 API 測試數據設計，支援增量同步和重複處理。
"""

import json
import logging
import requests
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from app.database import run_sync
from app.models.database_models import LarkUser, LarkDepartment
from app.services.lark_client import LarkAuthManager


class LarkUserService:
    """Lark 用戶收集服務"""
    
    def __init__(self, auth_manager: LarkAuthManager):
        self.auth_manager = auth_manager
        self.logger = logging.getLogger(__name__)
        
        # API 配置
        self.base_url = "https://open.larksuite.com/open-apis"
        self.timeout = 30
        
        # 收集統計
        self.stats = {
            'departments_processed': 0,
            'users_discovered': 0,
            'users_created': 0,
            'users_updated': 0,
            'users_duplicated': 0,  # 同一用戶在多個部門
            'api_calls': 0,
            'errors': 0,
            'start_time': None,
            'end_time': None
        }
        
        # 用戶去重集合
        self.processed_users = set()  # user_id 集合
        self.user_dept_mapping = {}   # user_id -> [dept_ids] 映射
        
    def get_users_by_department(self, department_id: str, page_size: int = 50) -> Optional[List[Dict]]:
        """獲取指定部門的直屬用戶列表"""
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                self.logger.error("無法獲取 access token")
                return None
            
            all_users = []
            page_token = None
            
            while True:
                url = f"{self.base_url}/contact/v3/users/find_by_department"
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                params = {
                    'department_id': department_id,
                    'department_id_type': 'open_department_id',
                    'page_size': page_size,
                    'user_id_type': 'user_id'  # 使用 user_id 作為主要標識
                }
                
                if page_token:
                    params['page_token'] = page_token
                
                self.stats['api_calls'] += 1
                response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 0:
                        users = data.get('data', {}).get('items', [])
                        all_users.extend(users)
                        
                        # 檢查是否有更多頁面
                        page_token = data.get('data', {}).get('page_token')
                        if not page_token or not data.get('data', {}).get('has_more', False):
                            break
                    else:
                        self.logger.warning(f"API 返回錯誤: {data}")
                        return None
                else:
                    self.logger.error(f"HTTP 請求失敗: {response.status_code} - {response.text}")
                    return None
            
            self.logger.debug(f"部門 {department_id} 有 {len(all_users)} 個直屬用戶")
            return all_users
            
        except Exception as e:
            self.logger.error(f"獲取部門用戶異常: {e}")
            self.stats['errors'] += 1
            return None
    
    def process_user_data(self, user_data: Dict, department_id: str) -> Dict[str, Any]:
        """處理單個用戶數據，轉換為數據庫格式"""
        try:
            # 提取基本ID
            user_id = user_data.get('user_id')
            open_id = user_data.get('open_id')
            union_id = user_data.get('union_id')
            
            if not user_id:
                self.logger.warning(f"用戶數據缺少 user_id: {user_data}")
                return None
            
            # 提取頭像信息
            avatar_info = user_data.get('avatar', {})
            avatar_240 = avatar_info.get('avatar_240')
            avatar_640 = avatar_info.get('avatar_640')  
            avatar_origin = avatar_info.get('avatar_origin')
            
            # 提取狀態信息
            status_info = user_data.get('status', {})
            is_activated = status_info.get('is_activated', True)
            is_exited = status_info.get('is_exited', False)
            is_frozen = status_info.get('is_frozen', False)
            is_resigned = status_info.get('is_resigned', False)
            is_unjoin = status_info.get('is_unjoin', False)
            
            # 處理部門歸屬
            if user_id in self.user_dept_mapping:
                # 用戶已存在，添加到部門列表
                if department_id not in self.user_dept_mapping[user_id]:
                    self.user_dept_mapping[user_id].append(department_id)
                self.stats['users_duplicated'] += 1
            else:
                # 新用戶
                self.user_dept_mapping[user_id] = [department_id]
            
            # 構建用戶數據
            processed_data = {
                'user_id': user_id,
                'open_id': open_id,
                'union_id': union_id,
                'name': user_data.get('name'),
                'en_name': user_data.get('en_name'),
                'enterprise_email': user_data.get('enterprise_email'),
                'primary_department_id': department_id,  # 第一次遇到的部門作為主部門
                'department_ids_json': json.dumps(self.user_dept_mapping[user_id], ensure_ascii=False),
                'description': user_data.get('description'),
                'job_title': user_data.get('job_title'),
                'employee_type': user_data.get('employee_type'),
                'employee_no': user_data.get('employee_no'),
                'city': user_data.get('city'),
                'country': user_data.get('country'),
                'work_station': user_data.get('work_station'),
                'mobile_visible': user_data.get('mobile_visible', True),
                'is_activated': is_activated,
                'is_exited': is_exited,
                'is_frozen': is_frozen,
                'is_resigned': is_resigned,
                'is_unjoin': is_unjoin,
                'is_tenant_manager': user_data.get('is_tenant_manager', False),
                'avatar_240': avatar_240,
                'avatar_640': avatar_640,
                'avatar_origin': avatar_origin,
                'join_time': user_data.get('join_time'),
                'last_sync_at': datetime.utcnow()
            }
            
            return processed_data
            
        except Exception as e:
            self.logger.error(f"處理用戶數據異常: {e}")
            return None
    
    async def save_user(self, db: AsyncSession, user_data: Dict[str, Any]) -> bool:
        """保存用戶數據到數據庫"""
        def _save(sync_db: Session) -> bool:
            try:
                user_id = user_data['user_id']

                # 檢查用戶是否已存在
                existing_user = sync_db.query(LarkUser).filter(
                    LarkUser.user_id == user_id
                ).first()

                now = datetime.utcnow()

                if existing_user:
                    # 更新現有用戶
                    for key, value in user_data.items():
                        if key != 'user_id':  # 不更新主鍵
                            setattr(existing_user, key, value)

                    existing_user.updated_at = now
                    existing_user.last_sync_at = now

                    # 更新部門歸屬（合併部門列表）
                    existing_depts = json.loads(existing_user.department_ids_json or '[]')
                    new_depts = json.loads(user_data.get('department_ids_json', '[]'))
                    merged_depts = list(set(existing_depts + new_depts))
                    existing_user.department_ids_json = json.dumps(merged_depts, ensure_ascii=False)

                    self.stats['users_updated'] += 1
                    self.logger.debug(f"更新用戶: {user_id} ({user_data.get('name', 'Unknown')})")
                else:
                    # 創建新用戶
                    new_user = LarkUser(**user_data)
                    new_user.created_at = now
                    new_user.updated_at = now

                    sync_db.add(new_user)
                    self.stats['users_created'] += 1
                    self.logger.debug(f"創建新用戶: {user_id} ({user_data.get('name', 'Unknown')})")

                sync_db.commit()
                return True

            except IntegrityError as e:
                sync_db.rollback()
                self.logger.error(f"保存用戶時數據庫完整性錯誤: {e}")
                self.stats['errors'] += 1
                return False
            except Exception as e:
                sync_db.rollback()
                self.logger.error(f"保存用戶異常: {e}")
                self.stats['errors'] += 1
                return False

        return await run_sync(db, _save)
    
    async def collect_users_from_department(self, db: AsyncSession, department_id: str) -> bool:
        """從指定部門收集用戶數據"""
        self.logger.info(f"開始收集部門 {department_id} 的用戶")
        
        try:
            users_data = self.get_users_by_department(department_id)
            if users_data is None:
                self.logger.warning(f"無法獲取部門 {department_id} 的用戶數據")
                return False
            
            success_count = 0
            for user_data in users_data:
                self.stats['users_discovered'] += 1
                
                processed_data = self.process_user_data(user_data, department_id)
                if processed_data:
                    if await self.save_user(db, processed_data):
                        success_count += 1
                    else:
                        self.logger.warning(f"保存用戶失敗: {user_data.get('user_id')}")
                else:
                    self.logger.warning(f"處理用戶數據失敗: {user_data}")
            
            self.logger.info(f"部門 {department_id} 用戶收集完成，成功 {success_count}/{len(users_data)} 個用戶")
            return True
            
        except Exception as e:
            self.logger.error(f"從部門 {department_id} 收集用戶時發生異常: {e}")
            self.stats['errors'] += 1
            return False
    
    async def sync_all_users(self, db: AsyncSession) -> Dict[str, Any]:
        """同步所有用戶數據（從已同步的部門中收集）"""
        self.logger.info("開始 Lark 用戶同步...")
        self.stats['start_time'] = datetime.utcnow()
        
        # 重置統計和狀態
        self.processed_users.clear()
        self.user_dept_mapping.clear()
        for key in ['departments_processed', 'users_discovered', 'users_created', 
                   'users_updated', 'users_duplicated', 'api_calls', 'errors']:
            self.stats[key] = 0
        
        try:
            # 獲取所有活躍部門
            def _load_departments(sync_db: Session) -> List[str]:
                return [
                    dept.department_id
                    for dept in sync_db.query(LarkDepartment).filter(
                        LarkDepartment.status == 'active'
                    ).all()
                ]

            departments = await run_sync(db, _load_departments)
            
            if not departments:
                return {
                    'success': False,
                    'message': '沒有找到活躍的部門，請先同步部門數據',
                    'stats': self.stats.copy()
                }
            
            self.logger.info(f"找到 {len(departments)} 個活躍部門，開始收集用戶...")
            
            success_count = 0
            for department_id in departments:
                if await self.collect_users_from_department(db, department_id):
                    success_count += 1
                    self.stats['departments_processed'] += 1
                else:
                    self.logger.error(f"部門 {department_id} 用戶收集失敗")
            
            self.stats['end_time'] = datetime.utcnow()
            duration = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
            
            # 更新部門用戶統計
            await self.update_department_user_counts(db)
            
            result = {
                'success': success_count > 0,
                'duration_seconds': duration,
                'stats': self.stats.copy(),
                'message': f"用戶同步完成，處理了 {success_count}/{len(departments)} 個部門"
            }
            
            self.logger.info(f"用戶同步完成: {result['message']}")
            self.logger.info(f"統計: 發現 {self.stats['users_discovered']} 個用戶，"
                           f"新增 {self.stats['users_created']} 個，"
                           f"更新 {self.stats['users_updated']} 個，"
                           f"重複 {self.stats['users_duplicated']} 個，"
                           f"API 調用 {self.stats['api_calls']} 次，"
                           f"錯誤 {self.stats['errors']} 個")
            
            return result
            
        except Exception as e:
            self.logger.error(f"用戶同步過程中發生嚴重錯誤: {e}")
            return {
                'success': False,
                'duration_seconds': 0,
                'stats': self.stats.copy(),
                'message': f"用戶同步失敗: {str(e)}"
            }
    
    async def update_department_user_counts(self, db: AsyncSession):
        """更新各部門的用戶統計數量"""
        def _update(sync_db: Session) -> None:
            try:
                # 更新各部門的直屬用戶數量
                departments = sync_db.query(LarkDepartment).all()

                for department in departments:
                    # 計算直屬用戶數
                    direct_count = sync_db.query(func.count(LarkUser.user_id)).filter(
                        LarkUser.primary_department_id == department.department_id,
                        LarkUser.is_activated == True,
                        LarkUser.is_exited == False
                    ).scalar()

                    department.direct_user_count = direct_count
                    department.updated_at = datetime.utcnow()

                sync_db.commit()
                self.logger.info("部門用戶統計更新完成")

            except Exception as e:
                sync_db.rollback()
                self.logger.error(f"更新部門用戶統計失敗: {e}")

        await run_sync(db, _update)
    
    async def get_user_stats(self, db: AsyncSession) -> Dict[str, Any]:
        """獲取用戶統計信息"""
        def _stats(sync_db: Session) -> Dict[str, Any]:
            try:
                total_users = sync_db.query(LarkUser).count()
                active_users = sync_db.query(LarkUser).filter(
                    LarkUser.is_activated == True,
                    LarkUser.is_exited == False
                ).count()

                # 員工類型分布
                employee_type_stats = {}
                types = sync_db.query(LarkUser.employee_type, func.count(LarkUser.user_id)).group_by(
                    LarkUser.employee_type
                ).all()
                for emp_type, count in types:
                    employee_type_stats[f'type_{emp_type}'] = count

                # 部門分布（前10個最大部門）
                dept_stats = sync_db.query(
                    LarkUser.primary_department_id,
                    func.count(LarkUser.user_id).label('user_count')
                ).group_by(
                    LarkUser.primary_department_id
                ).order_by(
                    func.count(LarkUser.user_id).desc()
                ).limit(10).all()

                top_departments = {dept_id: count for dept_id, count in dept_stats}

                # 最近同步時間
                last_sync = sync_db.query(LarkUser.last_sync_at).order_by(
                    LarkUser.last_sync_at.desc()
                ).first()

                return {
                    'total_users': total_users,
                    'active_users': active_users,
                    'employee_type_distribution': employee_type_stats,
                    'top_departments': top_departments,
                    'last_sync_at': last_sync[0].isoformat() if last_sync and last_sync[0] else None
                }

            except Exception as e:
                self.logger.error(f"獲取用戶統計信息失敗: {e}")
                return {'error': str(e)}

        return await run_sync(db, _stats)
    
    async def search_users(self, db: AsyncSession, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """搜索用戶（本地數據庫搜索）"""
        def _search(sync_db: Session) -> List[Dict[str, Any]]:
            try:
                query_val = query.lower().strip()
                if not query_val:
                    return []

                # 構建搜索條件
                users = sync_db.query(LarkUser).filter(
                    (LarkUser.name.ilike(f'%{query_val}%')) |
                    (LarkUser.en_name.ilike(f'%{query_val}%')) |
                    (LarkUser.enterprise_email.ilike(f'%{query_val}%')),
                    LarkUser.is_activated == True,
                    LarkUser.is_exited == False
                ).limit(limit).all()

                result = []
                for user in users:
                    result.append({
                        'id': user.user_id,
                        'name': user.name,
                        'display_name': user.name or user.en_name,
                        'email': user.enterprise_email,
                        'avatar': user.avatar_240,
                        'department_id': user.primary_department_id,
                        'job_title': user.job_title,
                        'employee_type': user.employee_type
                    })

                return result

            except Exception as e:
                self.logger.error(f"搜索用戶失敗: {e}")
                return []

        return await run_sync(db, _search)

    async def get_top_users(self, db: AsyncSession, limit: int = 50) -> List[Dict[str, Any]]:
        """返回前端可用的前 N 名活躍用戶（無搜尋詞時的預設清單）。

        以本地同步的 LarkUser 為資料來源，僅返回啟用且未離職的用戶，
        依名稱排序，取前 N 筆，並轉為前端聯絡人格式。
        """
        def _get_top(sync_db: Session) -> List[Dict[str, Any]]:
            try:
                users = sync_db.query(LarkUser).filter(
                    LarkUser.is_activated == True,
                    LarkUser.is_exited == False
                ).order_by(LarkUser.name.asc()).limit(limit).all()

                result: List[Dict[str, Any]] = []
                for user in users:
                    result.append({
                        'id': user.user_id,
                        'name': user.name,
                        'display_name': user.name or user.en_name,
                        'email': user.enterprise_email,
                        'avatar': user.avatar_240,
                        'department_id': user.primary_department_id,
                        'job_title': user.job_title,
                        'employee_type': user.employee_type
                    })

                return result
            except Exception as e:
                self.logger.error(f"獲取預設用戶清單失敗: {e}")
                return []

        return await run_sync(db, _get_top)
    
    async def cleanup_inactive_users(self, db: AsyncSession, days_threshold: int = 30) -> int:
        """清理超過指定天數未同步的用戶"""
        def _cleanup(sync_db: Session) -> int:
            try:
                threshold_date = datetime.utcnow() - timedelta(days=days_threshold)

                # 標記為非活躍而不是刪除
                updated_count = sync_db.query(LarkUser).filter(
                    LarkUser.last_sync_at < threshold_date,
                    LarkUser.is_activated == True
                ).update({'is_activated': False})

                sync_db.commit()
                self.logger.info(f"標記了 {updated_count} 個用戶為非活躍狀態")
                return updated_count

            except Exception as e:
                sync_db.rollback()
                self.logger.error(f"清理非活躍用戶失敗: {e}")
                return 0

        return await run_sync(db, _cleanup)
