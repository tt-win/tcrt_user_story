// Bulk Create 第 8 欄 test_data 判定的 DOM-free 測試：
//   node --test app/testsuite/js/bulk-test-data.test.mjs
// bulk.js 是瀏覽器全域 script（無 module.exports），以 vm 載入後測其全域函式，
// 重點鎖定與 server normalize_test_data_items 的 Unicode parity。
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(
    path.join(here, '../../static/js/test-case-management/bulk.js'),
    'utf-8',
);
// BULK_PRIORITY_ALLOWED 在瀏覽器由 Section 1（constants.js）提供，vm 需自行注入
const context = vm.createContext({
    window: {},
    console,
    BULK_PRIORITY_ALLOWED: ['High', 'Medium', 'Low'],
});
vm.runInContext(source, context);

const validate = context.validateBulkTestDataArray;
const clean = context.cleanBulkTestDataName;
const codePointLength = context.bulkCodePointLength;

test('基本合法陣列通過；credential 值不影響判定', () => {
    assert.equal(validate([
        { name: 'user', category: 'email', value: 'qa@example.com' },
        { name: 'pwd', category: 'credential', value: 's3cret' },
        { name: 'no_cat', value: '' },
        { id: null, name: 'null_id', value: 'x', category: '' },
    ]), true);
});

test('schema 型別違規被拒：缺 value / numeric id / 未知 category / 非物件元素', () => {
    assert.equal(validate([{ name: 'x' }]), false);
    assert.equal(validate([{ id: 1, name: 'x', value: 'y' }]), false);
    assert.equal(validate([{ name: 'x', value: 'y', category: 'not-a-real-category' }]), false);
    assert.equal(validate([1]), false);
    assert.equal(validate([[]]), false);
    assert.equal(validate([null]), false);
    assert.equal(validate({ name: 'x', value: 'y' }), false);
});

test('normalize 穩定性違規被拒：清洗後重複 name / 前後空白 / 換行 / null byte / 101 筆', () => {
    assert.equal(validate([{ name: 'a', value: '' }, { name: ' a ', value: '' }]), false);
    assert.equal(validate([{ name: ' x', value: '' }]), false);
    assert.equal(validate([{ name: 'x\ny', value: '' }]), false);
    assert.equal(validate([{ name: 'x', value: 'a\u0000b' }]), false);
    const many = Array.from({ length: 101 }, (_, i) => ({ name: `n${i}`, value: '' }));
    assert.equal(validate(many), false);
});

test('Unicode parity：長度以 code point 計，300 emoji name 必須通過', () => {
    const emojiName = '😀'.repeat(300); // 300 code points、UTF-16 length 600
    assert.equal(emojiName.length, 600);
    assert.equal(codePointLength(emojiName), 300);
    assert.equal(validate([{ name: emojiName, value: 'v' }]), true);
    // 501 code points 超過 name 上限
    assert.equal(validate([{ name: '😀'.repeat(501), value: 'v' }]), false);
    // value 以 code point 計：60000 emoji（UTF-16 120000）在 100000 上限內
    assert.equal(validate([{ name: 'big', value: '😀'.repeat(60000) }]), true);
    assert.equal(validate([{ name: 'too-big', value: 'v'.repeat(100001) }]), false);
});

test('Unicode parity：strip 集合與 Python 一致（NEL 被 strip、BOM 不被 strip）', () => {
    // U+0085 (NEL)：Python strip 會移除 → 前端也必須視為不穩定
    assert.equal(clean('x\u0085'), 'x');
    assert.equal(validate([{ name: 'x\u0085', value: 'v' }]), false);
    // U+FEFF (BOM)：Python strip 不移除（JS trim 會）→ 前端必須保留並接受
    assert.equal(clean('\ufeffx'), '\ufeffx');
    assert.equal(validate([{ name: '\ufeffx', value: 'v' }]), true);
    // U+3000 全形空白：兩邊都 strip
    assert.equal(clean('　x　'), 'x');
    assert.equal(validate([{ name: '　x', value: 'v' }]), false);
});

test('出貨 sample CSV 的資料行可被 parseBulkText 完整解析（貼上情境）', () => {
    const parseBulkText = context.parseBulkText;
    const sample = readFileSync(
        path.join(here, '../../static/samples/bulk_test_cases_sample.csv'),
        'utf-8',
    );
    const lines = sample.trim().split('\n');
    // 使用者貼上的是資料行（不含表頭）
    const result = parseBulkText(lines.slice(1).join('\n'));
    assert.equal(result.errors.length, 0);
    assert.equal(result.items.length, 3);

    // 列 1：email / credential / number
    const row1 = result.items[0].test_data;
    // vm 跨 realm 陣列 prototype 不同，spread 成本 realm 陣列再比較
    assert.deepEqual(
        [...row1.map((td) => td.category)],
        ['email', 'credential', 'number'],
    );

    // 第 8 欄省略 → 無 test_data
    assert.equal(result.items[1].test_data, null);

    // 列 3：url / json / identifier / date / other + 最小形狀（category 省略 → text）
    const row3 = result.items[2].test_data;
    assert.deepEqual(
        [...row3.map((td) => td.category)],
        ['url', 'json', 'identifier', 'date', 'other', undefined],
    );
    assert.equal(row3[5].name, 'service_name');
    assert.equal(context.bulkTestDataEffectiveCategory(row3[5].category), 'text');

    // 範例整體覆蓋全部九種 category（text 由省略示範）
    const demonstrated = new Set(
        [...row1, ...row3].map((td) => context.bulkTestDataEffectiveCategory(td.category)),
    );
    assert.deepEqual(
        [...demonstrated].sort(),
        ['credential', 'date', 'email', 'identifier', 'json', 'number', 'other', 'text', 'url'],
    );

    // 表頭列不是資料：貼入會被判為錯誤（Priority 欄為字面 "Priority"）
    const headerPasted = parseBulkText(lines[0]);
    assert.equal(headerPasted.errors.length, 1);
});

test('三語系 placeholder 與 sample CSV 的 test_data 範例同步', () => {
    const parseBulkText = context.parseBulkText;
    const sample = readFileSync(
        path.join(here, '../../static/samples/bulk_test_cases_sample.csv'),
        'utf-8',
    );
    const sampleItems = parseBulkText(sample.trim().split('\n').slice(1).join('\n')).items;
    const sampleCells = [...sampleItems].map((it) => JSON.stringify(it.test_data));

    for (const locale of ['en-US', 'zh-CN', 'zh-TW']) {
        const messages = JSON.parse(
            readFileSync(path.join(here, `../../static/locales/${locale}.json`), 'utf-8'),
        );
        const placeholder = messages.testCase.bulkText.placeholder;
        const result = parseBulkText(placeholder.trim());
        assert.equal(result.errors.length, 0, `${locale} placeholder 必須可被解析`);
        assert.equal(result.items.length, 3, `${locale} placeholder 應為 3 列`);
        assert.deepEqual(
            [...result.items].map((it) => JSON.stringify(it.test_data)),
            sampleCells,
            `${locale} placeholder 的 test_data 範例必須與 sample CSV 一致`,
        );
    }
});

test('7 欄舊格式與空第 8 欄不受影響（parseBulkText 整合）', () => {
    const parseBulkText = context.parseBulkText;
    const legacy = parseBulkText('TC-1,Title,,,,,High');
    assert.equal(legacy.errors.length, 0);
    assert.equal(legacy.items.length, 1);
    assert.equal(legacy.items[0].test_data, null);

    const withTd = parseBulkText('TC-2,Title,,,,,,"[{""name"":""u"",""value"":""v""}]"');
    assert.equal(withTd.errors.length, 0);
    // vm 跨 realm 物件 prototype 不同，deepEqual 會誤判 → 以 JSON 字面比較
    assert.equal(JSON.stringify(withTd.items[0].test_data), '[{"name":"u","value":"v"}]');

    const badTd = parseBulkText('TC-3,Title,,,,,,"[{""name"":""u""}]"');
    assert.equal(badTd.errors.length, 1);
    assert.equal(badTd.errors[0].code, 'invalid_test_data');

    const nineCols = parseBulkText('TC-4,Title,,,,,,x,y');
    assert.equal(nineCols.errors[0].code, 'too_many_columns');
});
