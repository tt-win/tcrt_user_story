import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, '../../static/js/usm-layout.js'), 'utf8');
const context = { console, module: { exports: {} }, exports: {} };
vm.createContext(context);
vm.runInContext(source, context);
const UsmLayout = context.UsmLayout || context.module.exports;
assert.ok(UsmLayout, 'UsmLayout must be defined');

// --- computeDepths ---
{
  const nodes = [
    { id: 'r', parent_id: null },
    { id: 'a', parent_id: 'r' },
    { id: 'b', parent_id: 'a' },
  ];
  const { depths, orphanIds, cyclicIds } = UsmLayout.computeDepths(nodes);
  assert.equal(depths.get('r'), 0);
  assert.equal(depths.get('a'), 1);
  assert.equal(depths.get('b'), 2);
  assert.equal(orphanIds.length, 0);
  assert.equal(cyclicIds.length, 0);
}

{
  const nodes = [
    { id: 'orphan', parent_id: 'missing' },
    { id: 'self', parent_id: 'self' },
    { id: 'c1', parent_id: 'c2' },
    { id: 'c2', parent_id: 'c1' },
  ];
  const { depths, orphanIds, cyclicIds } = UsmLayout.computeDepths(nodes);
  assert.equal(depths.get('orphan'), 0);
  assert.equal(depths.get('self'), 0);
  assert.equal(depths.get('c1'), 0);
  assert.equal(depths.get('c2'), 0);
  assert.ok(orphanIds.includes('orphan'));
  assert.ok(cyclicIds.includes('self'));
  assert.ok(cyclicIds.includes('c1') || cyclicIds.includes('c2'));
}

// --- assessLayoutHealth ---
{
  // Single root → healthy (node count < 3 gate for TB)
  const health = UsmLayout.assessLayoutHealth([
    { id: 'r', parent_id: null, position_x: 250, position_y: 250 },
  ]);
  assert.equal(health.verdict, 'healthy');
}

{
  // All-zero coords → unhealthy (100% overlap)
  const zeros = [
    { id: 'r', parent_id: null, position_x: 0, position_y: 0 },
    { id: 'a', parent_id: 'r', position_x: 0, position_y: 0 },
    { id: 'b', parent_id: 'a', position_x: 0, position_y: 0 },
  ];
  assert.equal(UsmLayout.assessLayoutHealth(zeros).verdict, 'unhealthy');
}

{
  // TB fingerprint 100%
  const tb = [
    { id: 'r', parent_id: null, position_x: 250, position_y: 250 },
    { id: 'a', parent_id: 'r', position_x: 100, position_y: 350 },
    { id: 'b', parent_id: 'r', position_x: 250, position_y: 350 },
    { id: 'c', parent_id: 'a', position_x: 0, position_y: 450 },
  ];
  const h = UsmLayout.assessLayoutHealth(tb);
  assert.equal(h.verdict, 'unhealthy');
  assert.ok(h.tbRatio >= 0.9);
}

{
  // TB fingerprint at exactly 90% (need depth >= 2)
  const nodes = [];
  nodes.push({ id: 'r', parent_id: null, position_x: 250, position_y: 250 }); // d0
  for (let i = 0; i < 7; i += 1) {
    nodes.push({ id: `a${i}`, parent_id: 'r', position_x: i * 300, position_y: 350 }); // d1
  }
  nodes.push({ id: 'g', parent_id: 'a0', position_x: 0, position_y: 450 }); // d2 TB
  // 1 root + 7 d1 + 1 d2 = 9 TB hits; add 1 off → 9/10 = 90%
  nodes.push({ id: 'off', parent_id: 'r', position_x: 2100, position_y: 999 });
  const h = UsmLayout.assessLayoutHealth(nodes);
  assert.ok(h.tbRatio >= 0.9, `tbRatio=${h.tbRatio}`);
  assert.equal(h.verdict, 'unhealthy');
}

{
  // Healthy dagre-like grid (no overlap, no TB)
  const healthy = [
    { id: 'r', parent_id: null, position_x: 250, position_y: 250 },
    { id: 'a', parent_id: 'r', position_x: 525, position_y: 250 },
    { id: 'b', parent_id: 'r', position_x: 525, position_y: 400 },
    { id: 'c', parent_id: 'a', position_x: 800, position_y: 250 },
  ];
  assert.equal(UsmLayout.assessLayoutHealth(healthy).verdict, 'healthy');
}

{
  // 5% overlap → hint (1 of 20 pairs involving ~1-2 nodes)
  // Build 20 nodes on a grid; overlap 1 pair → 2/20 = 10% → still hint if < 20%
  const nodes = [];
  for (let i = 0; i < 20; i += 1) {
    nodes.push({
      id: `n${i}`,
      parent_id: i === 0 ? null : 'n0',
      position_x: (i % 5) * 275,
      position_y: Math.floor(i / 5) * 150,
    });
  }
  // Overlap n1 onto n0
  nodes[1].position_x = nodes[0].position_x;
  nodes[1].position_y = nodes[0].position_y;
  const h = UsmLayout.assessLayoutHealth(nodes);
  assert.equal(h.overlapNodeCount, 2);
  assert.ok(h.overlapRatio > 0 && h.overlapRatio < 0.20);
  assert.equal(h.verdict, 'hint');
}

{
  // ~15% overlap → hint
  const nodes = [];
  for (let i = 0; i < 20; i += 1) {
    nodes.push({
      id: `n${i}`,
      parent_id: i === 0 ? null : 'n0',
      position_x: (i % 5) * 275,
      position_y: Math.floor(i / 5) * 150,
    });
  }
  // Overlap 3 pairs → 6 unique nodes / 20 = 30% → unhealthy; use 2 pairs = 4/20 = 20% boundary
  // For 15%: 3 nodes overlapping as a cluster = 3/20 = 15%
  nodes[1].position_x = nodes[0].position_x;
  nodes[1].position_y = nodes[0].position_y;
  nodes[2].position_x = nodes[0].position_x + 50;
  nodes[2].position_y = nodes[0].position_y + 20;
  const h = UsmLayout.assessLayoutHealth(nodes);
  assert.ok(h.overlapRatio > 0 && h.overlapRatio < 0.20, `got ${h.overlapRatio}`);
  assert.equal(h.verdict, 'hint');
}

{
  // 25% overlap → unhealthy
  const nodes = [];
  for (let i = 0; i < 8; i += 1) {
    nodes.push({
      id: `n${i}`,
      parent_id: i === 0 ? null : 'n0',
      position_x: (i % 4) * 275,
      position_y: Math.floor(i / 4) * 150,
    });
  }
  // Overlap 2 pairs → 4/8 = 50%
  nodes[1].position_x = nodes[0].position_x;
  nodes[1].position_y = nodes[0].position_y;
  nodes[3].position_x = nodes[2].position_x;
  nodes[3].position_y = nodes[2].position_y;
  const h = UsmLayout.assessLayoutHealth(nodes);
  assert.ok(h.overlapRatio >= 0.20);
  assert.equal(h.verdict, 'unhealthy');
}

// --- deriveHiddenPositions ---
{
  const all = [
    { id: 'r', parent_id: null, position: { x: 0, y: 0 } },
    { id: 'a', parent_id: 'r', position: { x: 999, y: 999 } },
    { id: 'b', parent_id: 'a', position: { x: 888, y: 888 } },
  ];
  const visible = [{ id: 'r', parent_id: null, position: { x: 100, y: 200 } }];
  const collapsed = new Set(['r']);
  const hidden = UsmLayout.deriveHiddenPositions(visible, all, collapsed);
  assert.ok(hidden.has('a'));
  assert.ok(hidden.has('b'));
  assert.equal(hidden.get('a').x, 100 + UsmLayout.HIDDEN_OFFSET);
  assert.equal(hidden.get('a').y, 200 + UsmLayout.HIDDEN_OFFSET);
  // Must not use original 999/888
  assert.notEqual(hidden.get('a').x, 999);
  // Same input → same output
  const hidden2 = UsmLayout.deriveHiddenPositions(visible, all, collapsed);
  assert.deepEqual([...hidden.entries()], [...hidden2.entries()]);
}

// --- translateAll ---
{
  const nodes = [
    { id: 'a', hidden: false, position: { x: 10, y: 20 } },
    { id: 'b', hidden: true, position: { x: 30, y: 40 } },
  ];
  const moved = UsmLayout.translateAll(nodes, 5, -3);
  assert.equal(moved[0].position.x, 15);
  assert.equal(moved[0].position.y, 17);
  assert.equal(moved[1].position.x, 35);
  assert.equal(moved[1].position.y, 37);
}

// --- nextEdgeHiddenState reference equality ---
{
  const edges = [
    { id: 'e1', source: 'a', target: 'b', hidden: false },
    { id: 'e2', source: 'b', target: 'c', hidden: true },
  ];
  const status = new Map([['a', false], ['b', true], ['c', false]]);
  // e1: hidden because b; e2: already hidden because b — e1 changes, e2 same
  const next = UsmLayout.nextEdgeHiddenState(edges, status);
  assert.notEqual(next, edges);
  assert.equal(next[0].hidden, true);
  assert.equal(next[1].hidden, true);

  const status2 = new Map([['a', false], ['b', false], ['c', false]]);
  // Reset both to not hidden
  const edges2 = [
    { id: 'e1', source: 'a', target: 'b', hidden: false },
    { id: 'e2', source: 'b', target: 'c', hidden: false },
  ];
  const same = UsmLayout.nextEdgeHiddenState(edges2, status2);
  assert.strictEqual(same, edges2, 'unchanged edges must return same reference');
}

// --- 17-map regression fixture ---
{
  const fixture = JSON.parse(
    readFileSync(path.join(here, 'fixtures/usm-layout-health-maps.json'), 'utf8')
  );
  assert.equal(fixture.maps.length, 17);
  for (const m of fixture.maps) {
    const h = UsmLayout.assessLayoutHealth(m.nodes);
    assert.equal(
      h.verdict,
      m.expected_verdict,
      `map ${m.map_id} (${m.name}): got ${h.verdict}, expected ${m.expected_verdict} `
        + `(tb=${h.tbRatio.toFixed(2)} ovlp=${h.overlapRatio.toFixed(2)})`
    );
  }
}

// --- zoom limits (design baseline 96 CSS dpi → CSS px occupancy, not PPI) ---
{
  assert.equal(UsmLayout.DESIGN_CSS_DPI, 96);
  assert.equal(UsmLayout.MIN_NODE_ON_SCREEN_PX, 96);
  const minZoom = UsmLayout.computeMinZoom();
  assert.ok(Math.abs(minZoom - (96 / 110)) < 1e-9);
  assert.ok(UsmLayout.NODE_HEIGHT * minZoom >= UsmLayout.MIN_NODE_ON_SCREEN_PX - 1e-9);
  const limits = UsmLayout.getZoomLimits();
  assert.equal(limits.minZoom, minZoom);
  assert.equal(limits.maxZoom, 2);
  assert.equal(UsmLayout.computeMinZoom({ minOnScreenPx: 55, nodeHeight: 110 }), 0.5);
}

console.log('usm-layout tests passed');
