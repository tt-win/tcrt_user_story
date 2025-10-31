# User Story Map 資料庫路徑調整

## 變更
將 User Story Map 資料庫從 `data/` 目錄移至專案根目錄，與其他資料庫（`audit.db`、`test_case_repo.db`）保持一致。

## 修改內容

### `app/models/user_story_map_db.py`

**修改前**:
```python
DATABASE_DIR = "data"
DATABASE_PATH = os.path.join(DATABASE_DIR, "userstorymap.db")
DATABASE_URL = f"sqlite+aiosqlite:///{_ABSOLUTE_DB_PATH}"
```

**修改後**:
```python
DATABASE_PATH = "userstorymap.db"
# 使用絕對路徑
import os as _os
_ABSOLUTE_DB_PATH = _os.path.abspath(DATABASE_PATH)
DATABASE_URL = f"sqlite+aiosqlite:///{_ABSOLUTE_DB_PATH}"
```

### `database_init.py`

移除 `DATABASE_DIR` 的導入和使用，簡化 `initialize_usm_engine()` 函數。

## 資料庫位置

### 修改前
```
專案根目錄/
├── audit.db
├── test_case_repo.db
└── data/
    └── userstorymap.db  ❌
```

### 修改後
```
專案根目錄/
├── audit.db
├── test_case_repo.db
└── userstorymap.db  ✅
```

## 驗證

```bash
# 檢查資料庫位置
ls -lh *.db

# 輸出應包含
-rw-r--r--  audit.db
-rw-r--r--  test_case_repo.db
-rw-r--r--  userstorymap.db
```

## 遷移

如果已有 `data/userstorymap.db`，可以移動到根目錄：

```bash
mv data/userstorymap.db ./
```

## 測試

```bash
# 同步初始化
python3 database_init.py

# 預期輸出
✅ user_story_maps: 0 筆記錄, 8 欄位
✅ user_story_map_nodes: 0 筆記錄, 20 欄位
📂 User Story Map 資料庫位置：sqlite://///path/to/userstorymap.db
```

## 總結

✅ 資料庫位置統一在根目錄  
✅ 與其他資料庫保持一致  
✅ 初始化正常運作  
✅ 應用程式可正常啟動  

無需其他配置變更，重啟服務即可。
