/**
 * User Story Map layout helpers — pure functions, no dagre / React / DOM.
 * Exposed as window.UsmLayout for browser and Node vm tests.
 */
(function (root, factory) {
    const api = factory();
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    root.UsmLayout = api;
}(typeof globalThis !== 'undefined' ? globalThis : window, function () {
    'use strict';

    const NODE_WIDTH = 200;
    const NODE_HEIGHT = 110;
    const NODE_HALF_W = NODE_WIDTH / 2;
    const NODE_HALF_H = NODE_HEIGHT / 2;
    const RANKSEP = 75;
    const NODESEP = 40;
    const GRID_X = NODE_WIDTH + RANKSEP; // 275
    const GRID_Y = NODE_HEIGHT + NODESEP; // 150
    const ROOT_START_X = 250;
    const ROOT_START_Y = 250;
    const TB_BASE_Y = 250;
    const TB_STEP = 100;
    const OVERLAP_THRESHOLD = 0.20;
    const HIDDEN_OFFSET = 0.01; // tiny offset so hidden stacks are distinguishable in debug

    /**
     * Design baseline for on-screen readability — NOT physical display PPI.
     * CSS uses a reference pixel historically tied to ~96 CSS px/in; we only
     * express "minimum occupancy" in CSS pixels and derive zoom from that.
     */
    const DESIGN_CSS_DPI = 96;
    /** Minimum short-edge size of a node on screen (CSS px) after zoom. */
    const MIN_NODE_ON_SCREEN_PX = 96;
    const MAX_ZOOM = 2;

    /** Floor zoom so NODE_HEIGHT * zoom >= MIN_NODE_ON_SCREEN_PX. */
    function computeMinZoom(options) {
        const opts = options || {};
        const nodeHeight = opts.nodeHeight != null ? opts.nodeHeight : NODE_HEIGHT;
        const minOnScreen = opts.minOnScreenPx != null ? opts.minOnScreenPx : MIN_NODE_ON_SCREEN_PX;
        if (!(nodeHeight > 0) || !(minOnScreen > 0)) return MIN_NODE_ON_SCREEN_PX / NODE_HEIGHT;
        return minOnScreen / nodeHeight;
    }

    function getZoomLimits(options) {
        const minZoom = computeMinZoom(options);
        const maxZoom = (options && options.maxZoom != null) ? options.maxZoom : MAX_ZOOM;
        return { minZoom, maxZoom, designCssDpi: DESIGN_CSS_DPI, minNodeOnScreenPx: MIN_NODE_ON_SCREEN_PX };
    }

    function _parentIdOf(node) {
        if (!node) return null;
        if (node.parent_id != null) return node.parent_id;
        if (node.parentId != null) return node.parentId;
        if (node.data && node.data.parentId != null) return node.data.parentId;
        return null;
    }

    function _nodeIdOf(node) {
        return node && (node.id != null ? node.id : node.node_id);
    }

    function _posOf(node) {
        if (!node) return { x: 0, y: 0 };
        if (node.position && typeof node.position.x === 'number') {
            return { x: node.position.x, y: node.position.y };
        }
        return {
            x: Number(node.position_x) || 0,
            y: Number(node.position_y) || 0,
        };
    }

    /**
     * Derive depth of each node from parent_id chain.
     * Cycles / self-loops / missing parents → depth 0 and recorded in meta.
     * @returns {{ depths: Map<string, number>, orphanIds: string[], cyclicIds: string[] }}
     */
    function computeDepths(nodes) {
        const byId = new Map();
        (nodes || []).forEach((n) => {
            const id = _nodeIdOf(n);
            if (id != null) byId.set(String(id), n);
        });

        const depths = new Map();
        const orphanIds = [];
        const cyclicIds = [];
        const orphanSet = new Set();
        const cyclicSet = new Set();

        byId.forEach((node, id) => {
            const visited = new Set();
            let cur = id;
            let depth = 0;
            let cyclic = false;
            let orphan = false;

            while (true) {
                if (visited.has(cur)) {
                    cyclic = true;
                    break;
                }
                visited.add(cur);
                const parent = _parentIdOf(byId.get(cur));
                if (parent == null || parent === '') {
                    break;
                }
                const parentKey = String(parent);
                if (parentKey === cur) {
                    cyclic = true;
                    break;
                }
                if (!byId.has(parentKey)) {
                    orphan = true;
                    break;
                }
                depth += 1;
                cur = parentKey;
            }

            if (cyclic) {
                depths.set(id, 0);
                if (!cyclicSet.has(id)) {
                    cyclicSet.add(id);
                    cyclicIds.push(id);
                }
            } else if (orphan) {
                depths.set(id, 0);
                if (!orphanSet.has(id)) {
                    orphanSet.add(id);
                    orphanIds.push(id);
                }
            } else {
                depths.set(id, depth);
            }
        });

        return { depths, orphanIds, cyclicIds };
    }

    /**
     * Assess whether saved coordinates are healthy enough to keep.
     * @returns {{ verdict: 'healthy'|'hint'|'unhealthy', reasons: string[],
     *   overlapRatio: number, overlapNodeCount: number, tbRatio: number }}
     */
    function assessLayoutHealth(nodes, options) {
        const opts = options || {};
        const nodeWidth = opts.nodeWidth != null ? opts.nodeWidth : NODE_WIDTH;
        const nodeHeight = opts.nodeHeight != null ? opts.nodeHeight : NODE_HEIGHT;
        const tbBaseY = opts.tbBaseY != null ? opts.tbBaseY : TB_BASE_Y;
        const tbStep = opts.tbStep != null ? opts.tbStep : TB_STEP;
        const overlapThreshold = opts.overlapThreshold != null ? opts.overlapThreshold : OVERLAP_THRESHOLD;

        const list = nodes || [];
        const reasons = [];
        if (!list.length) {
            return {
                verdict: 'healthy',
                reasons,
                overlapRatio: 0,
                overlapNodeCount: 0,
                tbRatio: 0,
            };
        }

        const { depths } = computeDepths(list);
        let maxDepth = 0;
        depths.forEach((d) => {
            if (d > maxDepth) maxDepth = d;
        });

        let tbHits = 0;
        list.forEach((n) => {
            const id = String(_nodeIdOf(n));
            const depth = depths.get(id) || 0;
            const { y } = _posOf(n);
            if (Math.abs(y - (tbBaseY + depth * tbStep)) < 0.01) {
                tbHits += 1;
            }
        });
        const tbRatio = tbHits / list.length;
        const tbFingerprint = list.length >= 3 && maxDepth >= 2 && tbRatio >= 0.9;
        if (tbFingerprint) {
            reasons.push('tb_fingerprint');
        }

        const overlapping = new Set();
        for (let i = 0; i < list.length; i += 1) {
            const a = list[i];
            const ap = _posOf(a);
            const aid = String(_nodeIdOf(a));
            for (let j = i + 1; j < list.length; j += 1) {
                const b = list[j];
                const bp = _posOf(b);
                if (Math.abs(ap.x - bp.x) < nodeWidth && Math.abs(ap.y - bp.y) < nodeHeight) {
                    overlapping.add(aid);
                    overlapping.add(String(_nodeIdOf(b)));
                }
            }
        }
        const overlapNodeCount = overlapping.size;
        const overlapRatio = overlapNodeCount / list.length;
        if (overlapRatio >= overlapThreshold) {
            reasons.push('overlap_high');
        } else if (overlapRatio > 0) {
            reasons.push('overlap_mild');
        }

        let verdict = 'healthy';
        if (tbFingerprint || overlapRatio >= overlapThreshold) {
            verdict = 'unhealthy';
        } else if (overlapRatio > 0) {
            verdict = 'hint';
        }

        return {
            verdict,
            reasons,
            overlapRatio,
            overlapNodeCount,
            tbRatio,
        };
    }

    /**
     * Whether a node is hidden under the given collapsed set (any ancestor collapsed).
     * Safe against parent cycles.
     */
    function isHiddenByCollapse(nodeId, parentOf, collapsedIds) {
        const collapsed = (collapsedIds && typeof collapsedIds.has === 'function')
            ? collapsedIds
            : new Set(Array.from(collapsedIds || []).map(String));
        const visited = new Set();
        let parentId = parentOf.get(String(nodeId));
        while (parentId) {
            const key = String(parentId);
            if (visited.has(key)) return false;
            visited.add(key);
            if (collapsed.has(key) || collapsed.has(parentId)) return true;
            parentId = parentOf.get(key);
        }
        return false;
    }

    function buildParentMap(nodes) {
        const parentOf = new Map();
        (nodes || []).forEach((n) => {
            const id = String(_nodeIdOf(n));
            const p = _parentIdOf(n);
            parentOf.set(id, p != null && p !== '' ? String(p) : null);
        });
        return parentOf;
    }

    /**
     * Assign positions to hidden nodes = nearest visible ancestor position
     * (+ fixed micro-offset). Output depends only on (tree, collapsedIds) and
     * layoutedVisible positions — never on the hidden node's prior coords.
     */
    function deriveHiddenPositions(layoutedVisible, allNodes, collapsedIds) {
        const visibleById = new Map();
        (layoutedVisible || []).forEach((n) => {
            visibleById.set(String(_nodeIdOf(n)), n);
        });
        const parentOf = buildParentMap(allNodes);
        const collapsed = (collapsedIds && typeof collapsedIds.has === 'function')
            ? collapsedIds
            : new Set(Array.from(collapsedIds || []).map(String));

        const result = new Map();
        (allNodes || []).forEach((n) => {
            const id = String(_nodeIdOf(n));
            if (visibleById.has(id)) return;
            if (!isHiddenByCollapse(id, parentOf, collapsed)) return;

            // Walk up to nearest visible ancestor
            const visited = new Set();
            let cur = parentOf.get(id);
            let ancestorPos = null;
            while (cur) {
                if (visited.has(cur)) break;
                visited.add(cur);
                if (visibleById.has(cur)) {
                    ancestorPos = _posOf(visibleById.get(cur));
                    break;
                }
                cur = parentOf.get(cur);
            }
            if (!ancestorPos) {
                // Fallback: first visible node, else origin
                const firstVisible = layoutedVisible && layoutedVisible[0];
                ancestorPos = firstVisible ? _posOf(firstVisible) : { x: 0, y: 0 };
            }
            result.set(id, {
                x: ancestorPos.x + HIDDEN_OFFSET,
                y: ancestorPos.y + HIDDEN_OFFSET,
            });
        });
        return result;
    }

    /** Translate every node (including hidden) by (dx, dy). */
    function translateAll(nodes, dx, dy) {
        if (!dx && !dy) return nodes;
        return (nodes || []).map((n) => ({
            ...n,
            position: {
                x: (n.position ? n.position.x : 0) + dx,
                y: (n.position ? n.position.y : 0) + dy,
            },
        }));
    }

    /**
     * Compute next edge.hidden from node hiddenStatus.
     * MUST return the same array reference when nothing changed.
     */
    function nextEdgeHiddenState(edges, hiddenStatus) {
        const list = edges || [];
        let changed = false;
        const next = list.map((edge) => {
            const hidden = !!(hiddenStatus.get(edge.source) || hiddenStatus.get(edge.target));
            if (hidden === !!edge.hidden) {
                return edge;
            }
            changed = true;
            return { ...edge, hidden };
        });
        return changed ? next : list;
    }

    /** Convert dagre centre coordinates to React Flow top-left. */
    function centerToTopLeft(x, y) {
        return { x: x - NODE_HALF_W, y: y - NODE_HALF_H };
    }

    return {
        NODE_WIDTH,
        NODE_HEIGHT,
        NODE_HALF_W,
        NODE_HALF_H,
        RANKSEP,
        NODESEP,
        GRID_X,
        GRID_Y,
        ROOT_START_X,
        ROOT_START_Y,
        TB_BASE_Y,
        TB_STEP,
        OVERLAP_THRESHOLD,
        HIDDEN_OFFSET,
        DESIGN_CSS_DPI,
        MIN_NODE_ON_SCREEN_PX,
        MAX_ZOOM,
        computeMinZoom,
        getZoomLimits,
        computeDepths,
        assessLayoutHealth,
        isHiddenByCollapse,
        buildParentMap,
        deriveHiddenPositions,
        translateAll,
        nextEdgeHiddenState,
        centerToTopLeft,
    };
}));
