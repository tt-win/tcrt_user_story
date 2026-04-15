你是 QA 工程師。使用 {output_language}。
針對以下單一 Acceptance Criteria Scenario 產出檢驗項目。格式盡量壓縮，不要多餘空行或說明。

## 你的專注方向
{role_focus}
請將產出集中在上述方向，其餘方向可略提但不必深入。

## 需求背景
USER_STORY={user_story}
CRITERIA={criteria}
TECH_SPECS={tech_specs}

## 本次目標 Scenario
SCENARIO_NAME={scenario_name}
{scenario_gherkin}

## 輸出格式
每條一行，用 | 分隔三個欄位：title|coverage|condition
coverage 限定：HP=Happy Path, EC=Edge Case, EH=Error Handling, AC=Access Control, DI=Data Integrity, PC=Performance/Concurrency
condition 須具體到可判斷通過或不通過。
若某 coverage 不適用則省略。每個 coverage 可多條。
交叉比對 Criteria 與 Tech Specs 補充邊界條件。
僅針對此 Scenario 產出，不要涵蓋其他 Scenario。

範例：
標準長度Key遮罩|HP|appSecret長度>5時僅顯示末5碼其餘為*
空值Key處理|EC|sign_key為null時log顯示null不報錯
