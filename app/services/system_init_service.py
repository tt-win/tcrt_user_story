"""
系統初始化服務
處理系統第一次啟動時的初始化檢查和 Super Admin 建立
"""

from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_sync_db
from app.models.database_models import User as UserORM
from app.auth.models import UserRole, UserCreate
from app.services.user_service import UserService


class SystemInitService:
    """系統初始化服務"""
    
    def __init__(self, db: Session = None):
        self.db = db
        self.user_service = UserService()
    
    def check_system_initialized(self) -> bool:
        """
        檢查系統是否已初始化（有至少一個 super_admin）
        
        Returns:
            bool: True 如果已初始化，False 需要初始化
        """
        try:
            if not self.db:
                # 如果沒有傳入 db session，創建一個
                from app.database import get_sync_db
                db_gen = get_sync_db()
                self.db = next(db_gen)
            
            # 檢查是否有 super_admin 使用者
            super_admin_count = (
                self.db.query(UserORM)
                .filter(UserORM.role == UserRole.SUPER_ADMIN.value)
                .filter(UserORM.is_active == True)
                .count()
            )
            
            return super_admin_count > 0
            
        except Exception as e:
            print(f"檢查系統初始化狀態時發生錯誤: {e}")
            # 出現錯誤時假設需要初始化
            return False
    
    def get_system_stats(self) -> Dict[str, Any]:
        """
        取得系統統計資訊
        
        Returns:
            Dict[str, Any]: 系統統計資訊
        """
        try:
            if not self.db:
                from app.database import get_sync_db
                db_gen = get_sync_db()
                self.db = next(db_gen)
            
            stats = {}
            
            # 使用者統計
            total_users = self.db.query(UserORM).count()
            active_users = self.db.query(UserORM).filter(UserORM.is_active == True).count()
            
            # 角色統計
            role_stats = {}
            for role in UserRole:
                count = (
                    self.db.query(UserORM)
                    .filter(UserORM.role == role.value)
                    .filter(UserORM.is_active == True)
                    .count()
                )
                role_stats[role.value] = count
            
            # 檢查資料表是否存在
            tables_exist = self._check_required_tables()
            
            stats.update({
                'total_users': total_users,
                'active_users': active_users,
                'role_distribution': role_stats,
                'tables_exist': tables_exist,
                'is_initialized': self.check_system_initialized(),
                'checked_at': datetime.now().isoformat()
            })
            
            return stats
            
        except Exception as e:
            print(f"取得系統統計時發生錯誤: {e}")
            return {
                'error': str(e),
                'is_initialized': False,
                'checked_at': datetime.now().isoformat()
            }
    
    def _check_required_tables(self) -> Dict[str, bool]:
        """檢查必要資料表是否存在"""
        required_tables = [
            'users', 'teams', 'team_permissions',
            'test_run_configs', 'test_run_items',
            'auth_sessions'
        ]
        
        table_status = {}
        
        try:
            for table_name in required_tables:
                try:
                    result = self.db.execute(
                        text(f"SELECT 1 FROM {table_name} LIMIT 1")
                    )
                    table_status[table_name] = True
                except Exception:
                    table_status[table_name] = False
                    
            return table_status
            
        except Exception as e:
            print(f"檢查資料表時發生錯誤: {e}")
            return {table: False for table in required_tables}
    
    def initialize_system(self, admin_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        初始化系統，建立第一個 Super Admin
        
        Args:
            admin_data: 管理員資料
                - username: 使用者名稱
                - password: 密碼
                - confirm_password: 確認密碼
        
        Returns:
            Dict[str, Any]: 初始化結果
        """
        try:
            # 驗證系統是否需要初始化
            if self.check_system_initialized():
                return {
                    'success': False,
                    'error': '系統已經初始化，不能重複執行初始化程序'
                }
            
            # 驗證輸入資料
            validation_error = self._validate_admin_data(admin_data)
            if validation_error:
                return {
                    'success': False,
                    'error': validation_error
                }
            
            if not self.db:
                from app.database import get_sync_db
                db_gen = get_sync_db()
                self.db = next(db_gen)
            
            # 建立 Super Admin 使用者
            user_create = UserCreate(
                username=admin_data['username'],
                password=admin_data['password'],
                role=UserRole.SUPER_ADMIN,
                primary_team_id=None,
                is_active=True
            )
            
            # 使用使用者服務建立使用者
            new_user = self.user_service.create_user(user_create, db=self.db)
            
            if new_user:
                # 設定 last_login_at 以跳過首次登入流程
                new_user.last_login_at = datetime.utcnow()
                self.db.add(new_user)
                self.db.commit()
                self.db.refresh(new_user)
                
                return {
                    'success': True,
                    'message': f'系統初始化完成！Super Admin "{new_user.username}" 已建立。',
                    'user_id': new_user.id,
                    'username': new_user.username,
                    'role': new_user.role.value, # 確保回傳字串
                    'created_at': new_user.created_at.isoformat()
                }
            else:
                self.db.rollback()
                return {
                    'success': False,
                    'error': '建立 Super Admin 時發生未知錯誤'
                }
                
        except Exception as e:
            if self.db:
                self.db.rollback()
            error_msg = f'系統初始化失敗: {str(e)}'
            print(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
    
    def _validate_admin_data(self, admin_data: Dict[str, Any]) -> Optional[str]:
        """驗證管理員資料"""
        required_fields = ['username', 'password', 'confirm_password']
        
        # 檢查必要欄位
        for field in required_fields:
            if field not in admin_data or not admin_data[field]:
                return f'缺少必要欄位: {field}'
        
        username = admin_data['username'].strip()
        password = admin_data['password']
        confirm_password = admin_data['confirm_password']
        
        # 驗證使用者名稱
        if len(username) < 3:
            return '使用者名稱至少需要3個字符'
        
        if len(username) > 50:
            return '使用者名稱不能超過50個字符'
        
        # 檢查使用者名稱是否已存在
        try:
            if not self.db:
                from app.database import get_sync_db
                db_gen = get_sync_db()
                self.db = next(db_gen)
                
            existing_user = (
                self.db.query(UserORM)
                .filter(UserORM.username == username)
                .first()
            )
            
            if existing_user:
                return f'使用者名稱 "{username}" 已存在'
                
        except Exception as e:
            return f'驗證使用者名稱時發生錯誤: {str(e)}'
        
        # 驗證密碼
        if len(password) < 8:
            return '密碼至少需要8個字符'
        
        if password != confirm_password:
            return '密碼與確認密碼不一致'
        
        return None
    
    def get_initialization_guide(self) -> Dict[str, Any]:
        """
        取得初始化指引
        
        Returns:
            Dict[str, Any]: 初始化指引資訊
        """
        return {
            'title': '系統初始化',
            'description': '歡迎使用測試用例管理系統！系統需要建立第一個 Super Admin 帳戶才能開始使用。',
            'steps': [
                {
                    'step': 1,
                    'title': '建立 Super Admin 帳戶',
                    'description': '設定系統管理員的使用者名稱和密碼'
                },
                {
                    'step': 2,
                    'title': '登入系統',
                    'description': '使用建立的帳戶登入系統'
                },
                {
                    'step': 3,
                    'title': '建立團隊和使用者',
                    'description': '開始建立團隊並邀請其他使用者'
                }
            ],
            'requirements': {
                'username': {
                    'min_length': 3,
                    'max_length': 50,
                    'description': '使用者名稱需要3-50個字符'
                },
                'password': {
                    'min_length': 8,
                    'description': '密碼至少需要8個字符'
                }
            },
            'security_notes': [
                '請使用強密碼保護 Super Admin 帳戶',
                'Super Admin 擁有系統所有權限，請妥善保管',
                '建議完成初始化後建立其他管理員帳戶分散風險'
            ]
        }