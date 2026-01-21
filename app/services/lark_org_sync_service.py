#!/usr/bin/env python3
"""
Lark 組織架構同步服務

整合部門遍歷和用戶收集功能，提供完整的組織架構同步解決方案。
支援完整同步、增量同步和狀態監控。
"""

import logging
import json
from typing import Dict, List, Optional, Any, Callable, Awaitable
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.services.lark_client import LarkAuthManager
from app.services.lark_department_service import LarkDepartmentService
from app.services.lark_user_service import LarkUserService
from app.models.database_models import SyncHistory
from app.database import SessionLocal, run_sync

class LarkOrgSyncService:
    """Lark 組織架構同步服務"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.logger = logging.getLogger(__name__)
        
        # 初始化認證管理器
        self.auth_manager = LarkAuthManager(app_id, app_secret)
        
        # 初始化子服務
        self.department_service = LarkDepartmentService(self.auth_manager)
        self.user_service = LarkUserService(self.auth_manager)
        
        # 根部門配置
        self.root_departments = [
            "od-55da57115ccbd0cc330ce5350754cb2b",
            "od-52e860a5435261d6843c5191111c4ccd"
        ]
        
        # 同步狀態
        self.sync_status = {
            'is_syncing': False,
            'last_sync_start': None,
            'last_sync_end': None,
            'last_sync_result': None,
            'current_sync_id': None  # 當前同步記錄ID
        }

    async def _with_session(
        self,
        db: Optional[AsyncSession],
        fn: Callable[[AsyncSession], Awaitable[Any]]
    ) -> Any:
        if db is not None:
            return await fn(db)
        async with SessionLocal() as session:
            return await fn(session)
    
    async def sync_full_organization(self, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """完整組織架構同步（部門 + 用戶）"""
        if self.sync_status['is_syncing']:
            return {
                'success': False,
                'message': '同步正在進行中，請稍後再試'
            }
        
        self.logger.info("開始完整組織架構同步...")
        self.sync_status['is_syncing'] = True
        self.sync_status['last_sync_start'] = datetime.utcnow()
        
        try:
            async def _run(session: AsyncSession) -> Dict[str, Any]:
                # Phase 1: 同步部門架構
                self.logger.info("Phase 1: 同步部門架構...")
                dept_result = await self.department_service.sync_all_departments(
                    session, self.root_departments
                )

                if not dept_result.get('success', False):
                    self.logger.error("部門同步失敗，終止組織架構同步")
                    return {
                        'success': False,
                        'message': '部門同步失敗',
                        'department_result': dept_result,
                        'user_result': None
                    }

                # Phase 2: 同步用戶數據
                self.logger.info("Phase 2: 同步用戶數據...")
                user_result = await self.user_service.sync_all_users(session)

                # 整合結果
                overall_success = dept_result.get('success', False) and user_result.get('success', False)

                result = {
                    'success': overall_success,
                    'sync_time': datetime.utcnow().isoformat(),
                    'department_result': dept_result,
                    'user_result': user_result,
                    'message': self._generate_sync_summary(dept_result, user_result)
                }

                self.sync_status['last_sync_result'] = result
                self.logger.info(f"完整組織架構同步完成: {result['message']}")

                return result

            return await self._with_session(db, _run)
            
        except Exception as e:
            self.logger.error(f"完整組織架構同步發生嚴重錯誤: {e}")
            return {
                'success': False,
                'message': f'組織架構同步失敗: {str(e)}',
                'error': str(e)
            }
        finally:
            self.sync_status['is_syncing'] = False
            self.sync_status['last_sync_end'] = datetime.utcnow()
    
    async def sync_departments_only(self, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """僅同步部門架構"""
        self.logger.info("開始部門架構同步...")
        async def _run(session: AsyncSession) -> Dict[str, Any]:
            result = await self.department_service.sync_all_departments(
                session, self.root_departments
            )
            try:
                # 部門同步後，基於本地用戶資料重算直屬用戶數
                await self.user_service.update_department_user_counts(session)
            except Exception as e:
                self.logger.error(f"部門同步後重算用戶數失敗: {e}")
            return result

        return await self._with_session(db, _run)
    
    async def sync_users_only(self, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """僅同步用戶數據"""
        self.logger.info("開始用戶數據同步...")
        async def _run(session: AsyncSession) -> Dict[str, Any]:
            return await self.user_service.sync_all_users(session)

        return await self._with_session(db, _run)
    
    def get_sync_status(self) -> Dict[str, Any]:
        """獲取同步狀態"""
        return {
            'is_syncing': self.sync_status['is_syncing'],
            'last_sync_start': self.sync_status['last_sync_start'].isoformat() if self.sync_status['last_sync_start'] else None,
            'last_sync_end': self.sync_status['last_sync_end'].isoformat() if self.sync_status['last_sync_end'] else None,
            'last_sync_result': self.sync_status['last_sync_result']
        }
    
    async def get_organization_stats(self, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """獲取組織架構統計信息"""
        try:
            async def _run(session: AsyncSession) -> Dict[str, Any]:
                dept_stats = await self.department_service.get_department_stats(session)
                user_stats = await self.user_service.get_user_stats(session)

                return {
                    'departments': dept_stats,
                    'users': user_stats,
                    'sync_status': self.get_sync_status()
                }

            return await self._with_session(db, _run)
            
        except Exception as e:
            self.logger.error(f"獲取組織架構統計失敗: {e}")
            return {'error': str(e)}
    
    async def search_users(
        self, db: Optional[AsyncSession], query: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """搜索用戶"""
        async def _run(session: AsyncSession) -> List[Dict[str, Any]]:
            return await self.user_service.search_users(session, query, limit)

        return await self._with_session(db, _run)
    
    async def cleanup_old_data(self, db: Optional[AsyncSession] = None, days_threshold: int = 30) -> Dict[str, int]:
        """清理舊數據"""
        self.logger.info(f"開始清理超過 {days_threshold} 天的舊數據...")
        
        try:
            async def _run(session: AsyncSession) -> Dict[str, int]:
                dept_cleaned = await self.department_service.cleanup_inactive_departments(
                    session, days_threshold
                )
                user_cleaned = await self.user_service.cleanup_inactive_users(
                    session, days_threshold
                )

                result = {
                    'departments_cleaned': dept_cleaned,
                    'users_cleaned': user_cleaned,
                    'total_cleaned': dept_cleaned + user_cleaned
                }

                self.logger.info(f"清理完成: {result}")
                return result

            return await self._with_session(db, _run)
            
        except Exception as e:
            self.logger.error(f"清理舊數據失敗: {e}")
            return {'error': str(e)}
    
    def _generate_sync_summary(self, dept_result: Dict, user_result: Dict) -> str:
        """生成同步結果摘要"""
        try:
            dept_stats = dept_result.get('stats', {})
            user_stats = user_result.get('stats', {})
            
            dept_summary = (f"部門: 發現 {dept_stats.get('departments_discovered', 0)} 個, "
                          f"新增 {dept_stats.get('departments_created', 0)} 個, "
                          f"更新 {dept_stats.get('departments_updated', 0)} 個")
            
            user_summary = (f"用戶: 發現 {user_stats.get('users_discovered', 0)} 個, "
                          f"新增 {user_stats.get('users_created', 0)} 個, "
                          f"更新 {user_stats.get('users_updated', 0)} 個")
            
            total_duration = (dept_result.get('duration_seconds', 0) + 
                            user_result.get('duration_seconds', 0))
            
            return f"組織架構同步完成 ({total_duration:.1f}秒). {dept_summary}; {user_summary}"
            
        except Exception as e:
            self.logger.error(f"生成同步摘要失敗: {e}")
            return "組織架構同步完成"
    
    async def get_contacts_for_team(
        self, db: Optional[AsyncSession], team_id: int, limit: int = 100
    ) -> Dict[str, Any]:
        """為特定團隊獲取聯絡人列表（兼容現有 API）。

        無搜尋詞時，返回前 N 名活躍用戶作為預設清單（避免舊邏輯以空關鍵字搜尋導致空結果）。
        """
        try:
            async def _run(session: AsyncSession) -> Dict[str, Any]:
                # 無搜尋詞情境：從本地同步的用戶取前 N 名活躍用戶
                top_users = await self.user_service.get_top_users(session, limit)

                # 轉換為聯絡人格式
                contacts = []
                for user in top_users:
                    contacts.append({
                        'id': user.get('id'),
                        'name': user.get('name'),
                        'display_name': user.get('display_name'),
                        'email': user.get('email'),
                        'avatar': user.get('avatar')
                    })

                return {
                    'success': True,
                    'data': {
                        'contacts': contacts,
                        'total': len(contacts)
                    }
                }

            return await self._with_session(db, _run)
            
        except Exception as e:
            self.logger.error(f"獲取團隊聯絡人失敗: {e}")
            return {
                'success': False,
                'message': f'獲取聯絡人失敗: {str(e)}'
            }
    
    async def search_contacts_for_team(
        self, db: Optional[AsyncSession], team_id: int, query: str, limit: int = 10
    ) -> Dict[str, Any]:
        """為特定團隊搜索聯絡人建議（兼容現有 API）"""
        try:
            users = await self.search_users(db, query, limit)

            # 轉換為建議格式
            suggestions = []
            for user in users:
                suggestions.append({
                    'id': user['id'],
                    'name': user['name'],
                    'display_name': user['display_name'],
                    'email': user['email'],
                    'avatar': user['avatar']
                })

            return {
                'success': True,
                'data': {
                    'suggestions': suggestions,
                    'total': len(suggestions)
                }
            }
            
        except Exception as e:
            self.logger.error(f"搜索聯絡人建議失敗: {e}")
            return {
                'success': False,
                'message': f'搜索失敗: {str(e)}'
            }
    
    async def _create_sync_history(
        self,
        db: AsyncSession,
        team_id: int,
        sync_type: str,
        trigger_type: str = 'manual',
        trigger_user: Optional[str] = None
    ) -> Optional[int]:
        """創建同步歷史記錄"""
        def _create(sync_db: Session) -> Optional[int]:
            try:
                sync_record = SyncHistory(
                    team_id=team_id,
                    sync_type=sync_type,
                    trigger_type=trigger_type,
                    trigger_user=trigger_user,
                    status='started',
                    start_time=datetime.utcnow()
                )
                sync_db.add(sync_record)
                sync_db.commit()
                sync_db.refresh(sync_record)
                return sync_record.id
            except Exception as e:
                self.logger.error(f"創建同步歷史記錄失敗: {e}")
                sync_db.rollback()
                return None

        return await run_sync(db, _create)
    
    async def _update_sync_history(
        self,
        db: AsyncSession,
        sync_id: int,
        status: str,
        dept_result: Optional[Dict] = None,
        user_result: Optional[Dict] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """更新同步歷史記錄"""
        if not sync_id:
            return False

        def _update(sync_db: Session) -> bool:
            try:
                sync_record = sync_db.query(SyncHistory).filter(SyncHistory.id == sync_id).first()
                if not sync_record:
                    return False

                # 更新基本狀態
                sync_record.status = status
                sync_record.end_time = datetime.utcnow()

                if sync_record.start_time:
                    duration = (sync_record.end_time - sync_record.start_time).total_seconds()
                    sync_record.duration_seconds = duration

                # 更新錯誤信息
                if error_message:
                    sync_record.error_message = error_message

                # 更新統計信息
                if dept_result:
                    dept_stats = dept_result.get('stats', {})
                    sync_record.departments_discovered = dept_stats.get('departments_discovered', 0)
                    sync_record.departments_created = dept_stats.get('departments_created', 0)
                    sync_record.departments_updated = dept_stats.get('departments_updated', 0)
                    sync_record.api_calls = dept_stats.get('api_calls', 0)
                    sync_record.department_result_json = json.dumps(dept_result, ensure_ascii=False, default=str)

                if user_result:
                    user_stats = user_result.get('stats', {})
                    sync_record.users_discovered = user_stats.get('users_discovered', 0)
                    sync_record.users_created = user_stats.get('users_created', 0)
                    sync_record.users_updated = user_stats.get('users_updated', 0)
                    sync_record.users_duplicated = user_stats.get('users_duplicated', 0)
                    sync_record.user_result_json = json.dumps(user_result, ensure_ascii=False, default=str)

                # 創建結果摘要
                if dept_result or user_result:
                    summary = self._generate_sync_summary(dept_result or {}, user_result or {})
                    sync_record.result_summary_json = json.dumps({
                        'message': summary,
                        'dept_result': dept_result,
                        'user_result': user_result
                    }, ensure_ascii=False, default=str)

                sync_db.commit()
                return True

            except Exception as e:
                self.logger.error(f"更新同步歷史記錄失敗: {e}")
                sync_db.rollback()
                return False

        return await run_sync(db, _update)
    
    async def get_sync_history(self, db: AsyncSession, team_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """獲取團隊同步歷史記錄"""
        def _get_history(sync_db: Session) -> List[Dict[str, Any]]:
            try:
                records = sync_db.query(SyncHistory).filter(
                    SyncHistory.team_id == team_id
                ).order_by(SyncHistory.start_time.desc()).limit(limit).all()

                history = []
                for record in records:
                    history.append({
                        'id': record.id,
                        'sync_type': record.sync_type,
                        'trigger_type': record.trigger_type,
                        'trigger_user': record.trigger_user,
                        'status': record.status,
                        'start_time': record.start_time.isoformat() if record.start_time else None,
                        'end_time': record.end_time.isoformat() if record.end_time else None,
                        'duration_seconds': record.duration_seconds,
                        'departments_discovered': record.departments_discovered,
                        'departments_created': record.departments_created,
                        'departments_updated': record.departments_updated,
                        'users_discovered': record.users_discovered,
                        'users_created': record.users_created,
                        'users_updated': record.users_updated,
                        'users_duplicated': record.users_duplicated,
                        'api_calls': record.api_calls,
                        'error_message': record.error_message,
                        'result_summary': json.loads(record.result_summary_json) if record.result_summary_json else None
                    })

                return history

            except Exception as e:
                self.logger.error(f"獲取同步歷史失敗: {e}")
                return []

        return await run_sync(db, _get_history)
    
    async def sync_for_team(
        self,
        db: Optional[AsyncSession],
        team_id: int,
        sync_type: str = 'full',
        trigger_user: Optional[str] = None
    ) -> Dict[str, Any]:
        """為特定團隊執行同步（支持歷史記錄）"""
        if self.sync_status['is_syncing']:
            return {
                'success': False,
                'message': '同步正在進行中，請稍後再試'
            }
        
        async def _run(session: AsyncSession) -> Dict[str, Any]:
            # 創建同步記錄
            sync_id = await self._create_sync_history(session, team_id, sync_type, 'manual', trigger_user)
            if not sync_id:
                return {
                    'success': False,
                    'message': '無法創建同步記錄'
                }

            self.sync_status['is_syncing'] = True
            self.sync_status['current_sync_id'] = sync_id
            self.sync_status['last_sync_start'] = datetime.utcnow()

            try:
                # 更新狀態為運行中
                await self._update_sync_history(session, sync_id, 'running')

                if sync_type == 'departments':
                    result = await self.sync_departments_only(session)
                    await self._update_sync_history(
                        session,
                        sync_id,
                        'completed' if result.get('success') else 'failed',
                        dept_result=result,
                        error_message=result.get('message') if not result.get('success') else None
                    )

                elif sync_type == 'users':
                    result = await self.sync_users_only(session)
                    await self._update_sync_history(
                        session,
                        sync_id,
                        'completed' if result.get('success') else 'failed',
                        user_result=result,
                        error_message=result.get('message') if not result.get('success') else None
                    )

                elif sync_type == 'full':
                    dept_result = await self.sync_departments_only(session)
                    if dept_result.get('success', False):
                        user_result = await self.sync_users_only(session)
                        overall_success = user_result.get('success', False)

                        result = {
                            'success': overall_success,
                            'sync_time': datetime.utcnow().isoformat(),
                            'department_result': dept_result,
                            'user_result': user_result,
                            'message': self._generate_sync_summary(dept_result, user_result)
                        }

                        await self._update_sync_history(
                            session,
                            sync_id,
                            'completed' if overall_success else 'failed',
                            dept_result,
                            user_result,
                            error_message=result.get('message') if not overall_success else None
                        )
                    else:
                        result = {
                            'success': False,
                            'message': '部門同步失敗',
                            'department_result': dept_result,
                            'user_result': None
                        }
                        await self._update_sync_history(
                            session, sync_id, 'failed', dept_result, error_message='部門同步失敗'
                        )
                else:
                    result = {
                        'success': False,
                        'message': f'不支援的同步類型: {sync_type}'
                    }
                    await self._update_sync_history(
                        session, sync_id, 'failed', error_message=f'不支援的同步類型: {sync_type}'
                    )

                result['sync_id'] = sync_id
                self.sync_status['last_sync_result'] = result
                return result

            except Exception as e:
                error_msg = f'同步過程發生異常: {str(e)}'
                self.logger.error(error_msg)
                await self._update_sync_history(session, sync_id, 'failed', error_message=error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'sync_id': sync_id
                }
            finally:
                self.sync_status['is_syncing'] = False
                self.sync_status['last_sync_end'] = datetime.utcnow()
                self.sync_status['current_sync_id'] = None

        return await self._with_session(db, _run)


# 創建全局服務實例（使用配置中的 Lark 認證信息）
def create_lark_org_sync_service():
    """創建 Lark 組織同步服務實例"""
    from app.config import settings
    
    if not settings.lark.app_id or not settings.lark.app_secret:
        raise ValueError("缺少 Lark App ID 或 App Secret 配置")
    
    return LarkOrgSyncService(settings.lark.app_id, settings.lark.app_secret)


# 全局服務實例（延遲初始化）
_lark_org_sync_service = None

def get_lark_org_sync_service() -> LarkOrgSyncService:
    """獲取 Lark 組織同步服務實例（單例模式）"""
    global _lark_org_sync_service
    if _lark_org_sync_service is None:
        _lark_org_sync_service = create_lark_org_sync_service()
    return _lark_org_sync_service
