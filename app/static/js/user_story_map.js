/**
 * User Story Map - React Flow Implementation
 */

const { useState, useCallback, useEffect, useRef } = React;
const { 
    ReactFlow, 
    ReactFlowProvider,
    useNodesState, 
    useEdgesState, 
    MiniMap,
    Background,
    BackgroundVariant,
    MarkerType,
} = window.ReactFlow;

// Team ID and optional Map ID from URL
// Extract from path: /user-story-map/{team_id}[/map_id]
const pathParts = window.location.pathname.split('/').filter(p => p);
const teamIdIndex = pathParts.indexOf('user-story-map') + 1;
const teamId = parseInt(pathParts[teamIdIndex]);
const mapIdFromUrl = pathParts[teamIdIndex + 1] ? parseInt(pathParts[teamIdIndex + 1]) : null;

// Layout constants to keep newly added nodes from overlapping
const ROOT_START_X = 100;
const ROOT_START_Y = 100;
const CHILD_HORIZONTAL_OFFSET = 180;
const ROOT_VERTICAL_SPACING = 160;
const SIBLING_VERTICAL_SPACING = 140;
const RELATION_EDGE_PATH_OPTIONS = { offset: 120, borderRadius: 18 }; // 確保關聯邊在節點外形成明顯轉折

const fullUsmAccess = {
    mapCreate: true,
    mapUpdate: true,
    mapDelete: true,
    nodeAdd: true,
    nodeUpdate: true,
    nodeDelete: true,
};

const viewerUsmAccess = {
    mapCreate: false,
    mapUpdate: false,
    mapDelete: false,
    nodeAdd: false,
    nodeUpdate: false,
    nodeDelete: false,
};

if (!window.userStoryMapAccess) {
    window.userStoryMapAccess = { ...fullUsmAccess };
}

const hasUsmAccess = (key) => Boolean(window.userStoryMapAccess?.[key]);

const setElementVisibility = (id, allowed) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (allowed) {
        el.classList.remove('d-none');
        el.disabled = false;
    } else {
        el.classList.add('d-none');
        el.disabled = true;
    }
};

const updateUsmUiVisibility = () => {
    setElementVisibility('newMapBtn', hasUsmAccess('mapCreate'));
    setElementVisibility('createMapBtn', hasUsmAccess('mapCreate'));
    setElementVisibility('saveMapBtn', hasUsmAccess('mapUpdate'));
    setElementVisibility('saveMapEditBtn', hasUsmAccess('mapUpdate'));
    setElementVisibility('calcTicketsBtn', hasUsmAccess('mapUpdate'));
    setElementVisibility('addChildBtn', hasUsmAccess('nodeAdd'));
    setElementVisibility('addSiblingBtn', hasUsmAccess('nodeAdd'));
    setElementVisibility('setRelationsBtn', hasUsmAccess('nodeUpdate'));
    setElementVisibility('autoLayoutBtn', hasUsmAccess('nodeUpdate'));
    setElementVisibility('confirmAddNodeBtn', hasUsmAccess('nodeAdd'));
};

const ensureRelatedDisplayTitle = (entry) => {
    if (!entry || typeof entry === 'string') {
        return entry;
    }

    const displayTitle = entry.display_title
        || entry.node_title
        || entry.displayTitle
        || entry.nodeTitle
        || entry.node_id
        || entry.nodeId
        || 'Related Node';

    return {
        ...entry,
        display_title: displayTitle,
    };
};

const normalizeRelatedEntries = (entries) => {
    if (!Array.isArray(entries)) {
        return [];
    }

    return entries.map((entry) => {
        if (typeof entry === 'string') {
            return entry;
        }

        const relationId = entry.relation_id
            || entry.relationId
            || `legacy-${entry.node_id || entry.nodeId || Math.random().toString(36).slice(2)}`;
        const nodeId = entry.node_id || entry.nodeId || '';
        const mapIdRaw = entry.map_id ?? entry.mapId;
        const teamIdRaw = entry.team_id ?? entry.teamId;
        const mapIdParsed = Number(mapIdRaw);
        const teamIdParsed = Number(teamIdRaw);
        const mapId = Number.isFinite(mapIdParsed) ? mapIdParsed : mapIdRaw;
        const teamId = Number.isFinite(teamIdParsed) ? teamIdParsed : teamIdRaw;
        const mapName = entry.map_name ?? entry.mapName ?? '';
        const teamName = entry.team_name ?? entry.teamName ?? '';

        return ensureRelatedDisplayTitle({
            relation_id: relationId,
            node_id: nodeId,
            map_id: mapId,
            map_name: mapName,
            team_id: teamId,
            team_name: teamName,
            display_title: entry.display_title,
            node_title: entry.node_title || entry.nodeTitle || entry.display_title,
        });
    });
};

const serializeRelatedEntries = (entries) => {
    if (!Array.isArray(entries)) {
        return [];
    }
    return entries.map((entry) => {
        if (typeof entry === 'string') {
            return entry;
        }

        const normalized = ensureRelatedDisplayTitle(entry);
        const mapIdParsed = Number(normalized.map_id);
        const teamIdParsed = Number(normalized.team_id);
        const mapId = Number.isFinite(mapIdParsed) ? mapIdParsed : normalized.map_id;
        const teamId = Number.isFinite(teamIdParsed) ? teamIdParsed : normalized.team_id;

        return {
            relation_id: normalized.relation_id,
            node_id: normalized.node_id,
            map_id: mapId,
            map_name: normalized.map_name || '',
            team_id: teamId,
            team_name: normalized.team_name || '',
            display_title: normalized.display_title,
        };
    });
};

const cloneRelationEntry = (entry) => {
    if (typeof entry === 'string') {
        return ensureRelatedDisplayTitle({
            relation_id: null,
            node_id: entry,
            map_id: null,
            map_name: '',
            team_id: null,
            team_name: '',
            display_title: entry,
        });
    }
    return ensureRelatedDisplayTitle({ ...entry });
};

const relationMatchesSearchNode = (relation, node) => {
    if (!relation || !node) {
        return false;
    }
    if (relation.node_id !== node.node_id) {
        return false;
    }
    const relMapId = relation.map_id != null ? String(relation.map_id) : '';
    const nodeMapId = node.map_id != null ? String(node.map_id) : '';
    if (!relMapId || !nodeMapId) {
        return true;
    }
    return relMapId === nodeMapId;
};

const createRelationFromSearchResult = (node) => ensureRelatedDisplayTitle({
    relation_id: node.relation_id || null,
    node_id: node.node_id,
    map_id: node.map_id,
    map_name: node.map_name,
    team_id: node.team_id,
    team_name: node.team_name,
    display_title: node.node_title || node.node_id,
});

const applyUsmPermissions = async () => {
    let effectiveRole = (localStorage.getItem('user_role') || '').toLowerCase();

    if (effectiveRole === 'viewer') {
        window.userStoryMapAccess = { ...viewerUsmAccess };
    } else if (effectiveRole) {
        window.userStoryMapAccess = { ...fullUsmAccess };
    } else {
        window.userStoryMapAccess = { ...window.userStoryMapAccess };
    }

    try {
        if (!window.AuthClient) {
            console.warn('[USM] AuthClient not ready, retrying permission fetch...');
            updateUsmUiVisibility();
            setTimeout(applyUsmPermissions, 200);
            return;
        }

        const userInfo = await window.AuthClient.getUserInfo?.();
        if (userInfo?.role) {
            effectiveRole = String(userInfo.role).toLowerCase();
        }

        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=user_story_map');
        if (!resp.ok) {
            console.warn('[USM] 無法取得 UI 權限設定，使用預設權限');
            if (effectiveRole === 'viewer') {
                window.userStoryMapAccess = { ...viewerUsmAccess };
            } else {
                window.userStoryMapAccess = { ...fullUsmAccess };
            }
            updateUsmUiVisibility();
            return;
        }

        const config = await resp.json();
        const components = config?.components || {};

        window.userStoryMapAccess = {
            mapCreate: Boolean(components.newMapBtn),
            mapUpdate: Boolean(components.saveMapBtn || components.editMapAction),
            mapDelete: Boolean(components.deleteMapAction),
            nodeAdd: Boolean(components.addChildBtn || components.confirmAddNodeBtn),
            nodeUpdate: Boolean(components.nodeUpdateAction || components.saveMapBtn),
            nodeDelete: Boolean(components.nodeDeleteAction || components.deleteMapAction),
        };

        if (effectiveRole === 'viewer') {
            window.userStoryMapAccess = { ...viewerUsmAccess };
        } else {
            window.userStoryMapAccess = { ...fullUsmAccess, ...window.userStoryMapAccess };
        }
    } catch (error) {
        console.warn('[USM] 讀取權限設定失敗，使用 fallback 權限', error);
        if (effectiveRole === 'viewer') {
            window.userStoryMapAccess = { ...viewerUsmAccess };
        } else {
            window.userStoryMapAccess = { ...fullUsmAccess };
        }
    }

    updateUsmUiVisibility();
};

// Utility: sanitize HTML content before injecting into DOM
const escapeHtml = (value) => {
    if (value === undefined || value === null) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
};

// Custom Node Component
const CustomNode = ({ data, id }) => {
    const { Handle, Position } = window.ReactFlow;
    const badges = [];

    // Node type colors
    const nodeTypeColors = {
        root: '#6f42c1', // Purple
        feature_category: '#87ceeb', // Light blue
        user_story: '#dda0dd', // Plum (light purple)
    };

    const nodeTypeLabels = {
        root: 'Root',
        feature_category: 'Feature',
        user_story: 'Story',
    };

    if (data.jiraTickets && data.jiraTickets.length > 0) {
        badges.push(
            React.createElement(
                'span',
                { key: 'jira', className: 'node-badge bg-info text-white' },
                React.createElement('i', { className: 'fas fa-ticket-alt' }),
                ' ',
                data.jiraTickets.length
            )
        );
    }

    if (data.aggregatedTickets && data.aggregatedTickets.length > 0) {
        badges.push(
            React.createElement(
                'span',
                {
                    key: 'aggregated',
                    className: 'node-badge bg-warning text-dark',
                    title: 'Aggregated tickets from children'
                },
                React.createElement('i', { className: 'fas fa-layer-group' }),
                ' ',
                data.aggregatedTickets.length
            )
        );
    }

    // Add team and map name for external nodes
    let additionalInfo = null;
    if (data.isExternal && (data.team || data.mapName)) {
        const displayText = `${data.team || '未知團隊'} / ${data.mapName || `地圖 ${data.mapId}`}`;
        additionalInfo = React.createElement(
            'div',
            { 
                className: 'text-muted mb-1', 
                style: { fontSize: '10px' } 
            },
            React.createElement('small', null, 
                React.createElement('em', null, displayText)
            )
        );
    }

    const hasChildren = Array.isArray(data.childrenIds) && data.childrenIds.length > 0;
    const collapseToggle = hasChildren && !data.disableCollapse
        ? React.createElement(
              'button',
              {
                  type: 'button',
                  className: 'node-collapse-btn',
                  onClick: (event) => {
                      event.stopPropagation();
                      data.toggleCollapse?.(id);
                  },
                  title: data.collapsed
                      ? '目前為收合狀態，點擊以展開子節點'
                      : '目前為展開狀態，點擊以收合子節點',
              },
              React.createElement('i', { className: `fas fa-chevron-${data.collapsed ? 'down' : 'right'}` })
          )
        : null;

    return React.createElement(
        'div',
        {
            className: `custom-node${data.isRoot ? ' root-node' : ''}${data.isOriginalSelected ? ' original-selected-node' : ''}`,
            'data-node-type': data.nodeType,
            style: {
                opacity: data.dimmed ? 0.3 : 1,
                transition: 'opacity 0.3s ease',
                backgroundColor: data.isExternal ? '#e6f7ff' : (data.isOriginalSelected ? '#fff3cd' : undefined), // 外部節點為淺藍色，原始選定節點為淺黃色
            }
        },
        // Connection Handles - 4 positions (removed corner handles)
        React.createElement(Handle, { type: 'target', position: Position.Top, id: 'top' }),
        React.createElement(Handle, { type: 'source', position: Position.Bottom, id: 'bottom' }),
        React.createElement(Handle, { type: 'target', position: Position.Left, id: 'left' }),
        React.createElement(Handle, { type: 'source', position: Position.Right, id: 'right' }),
        React.createElement(Handle, { type: 'target', position: Position.Right, id: 'right-target' }),
        collapseToggle,
        // Node content
        additionalInfo, // Add external node info if applicable
        React.createElement(
            'div',
            { className: 'node-title' },
            data.title || 'Untitled'
        ),
        React.createElement(
            'div',
            { className: 'node-meta' },
            React.createElement(
                'span',
                {
                    className: 'node-badge',
                    style: {
                        backgroundColor: nodeTypeColors[data.nodeType] || '#0d6efd',
                        color: 'white'
                    }
                },
                nodeTypeLabels[data.nodeType] || 'Node'
            ),
            ...badges
        )
    );
};

const nodeTypes = {
    custom: CustomNode,
};

// Main Flow Component
const UserStoryMapFlow = () => {
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [selectedNode, setSelectedNode] = useState(null);
    const [currentMapId, setCurrentMapId] = useState(null);
    const [maps, setMaps] = useState([]);
    const [teamName, setTeamName] = useState('');
    const [collapsedNodeIds, setCollapsedNodeIds] = useState(new Set());
    const [highlightedPath, setHighlightedPath] = useState(null);
    const [highlightedNodeIds, setHighlightedNodeIds] = useState([]);
    const reactFlowInstance = useRef(null);
    const nodesRef = useRef([]);

    useEffect(() => {
        nodesRef.current = nodes;
    }, [nodes]);

    // Handle wheel event for zoom with Cmd/Ctrl
    const handleWheel = useCallback((event) => {
        const isCtrlPressed = event.ctrlKey || event.getModifierState?.('Control');
        if (!isCtrlPressed) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        const instance = reactFlowInstance.current;
        if (!instance) {
            return;
        }
        const zoomDelta = event.deltaY < 0 ? 0.2 : -0.2;
        try {
            instance.zoomBy?.(zoomDelta, { duration: 150 });
        } catch (_) {
            const currentZoom = instance.getZoom?.() ?? 1;
            const nextZoom = Math.min(2, Math.max(0.2, currentZoom + zoomDelta));
            instance.zoomTo?.(nextZoom, { duration: 150 });
        }
    }, []);

    useEffect(() => {
        const wrapper = document.getElementById('reactFlowWrapper');
        if (!wrapper) {
            return;
        }

        wrapper.addEventListener('wheel', handleWheel, { passive: false });
        return () => wrapper.removeEventListener('wheel', handleWheel);
    }, [handleWheel]);

    // Tree layout using dagre
    const applyTreeLayout = useCallback((nodes, edges) => {
        if (!window.dagre) {
            console.error('Dagre library not loaded');
            return nodes;
        }

        const g = new dagre.graphlib.Graph();
        g.setGraph({ rankdir: 'LR', ranksep: 75, nodesep: 40 });
        g.setDefaultEdgeLabel(() => ({}));

        nodes.forEach(node => {
            g.setNode(node.id, { width: 200, height: 110 });
        });

        edges.forEach(edge => {
            g.setEdge(edge.source, edge.target);
        });

        dagre.layout(g);

        return nodes.map(node => {
            const position = g.node(node.id);
            return {
                ...node,
                position: { x: position.x, y: position.y },
                targetPosition: 'left',
                sourcePosition: 'right',
            };
        });
    }, []);

    const toggleNodeCollapse = useCallback((nodeId) => {
        const node = nodesRef.current.find((n) => n.id === nodeId);
        if (!node || !(node.data.childrenIds && node.data.childrenIds.length)) {
            return;
        }
        setCollapsedNodeIds((prev) => {
            const next = new Set(prev);
            if (next.has(nodeId)) {
                next.delete(nodeId);
            } else {
                next.add(nodeId);
            }
            return next;
        });
    }, []);

    // 重新應用佈局的函數
    const applyLayoutWithCollapsedNodes = useCallback((currentNodes, currentEdges, collapsedSet) => {
        if (!window.dagre) {
            console.error('Dagre library not loaded');
            return currentNodes;
        }

        const g = new dagre.graphlib.Graph();
        g.setGraph({ rankdir: 'LR', ranksep: 75, nodesep: 40 });
        g.setDefaultEdgeLabel(() => ({}));

        // 只為未收合的節點設置圖形
        const visibleNodes = currentNodes.filter(node => {
            // 檢查節點是否被收合 - 通過檢查其父節點是否被收合
            let parentId = node.data.parentId;
            while (parentId) {
                if (collapsedSet.has(parentId)) {
                    return false; // 如果父節點收合，則隱藏當前節點
                }
                const parent = currentNodes.find(n => n.id === parentId);
                parentId = parent?.data.parentId || null;
            }
            return true;
        });

        visibleNodes.forEach(node => {
            g.setNode(node.id, { width: 200, height: 110 });
        });

        // 只為可見節點之間的邊設置圖形關係
        currentEdges.forEach(edge => {
            const sourceNodeVisible = visibleNodes.some(n => n.id === edge.source);
            const targetNodeVisible = visibleNodes.some(n => n.id === edge.target);
            if (sourceNodeVisible && targetNodeVisible) {
                g.setEdge(edge.source, edge.target);
            }
        });

        dagre.layout(g);

        // 更新可見節點位置，保持隱藏節點的原始位置
        return currentNodes.map(node => {
            if (visibleNodes.includes(node)) {
                const position = g.node(node.id);
                return {
                    ...node,
                    position: { x: position.x, y: position.y },
                    targetPosition: 'left',
                    sourcePosition: 'right',
                };
            }
            return node; // 保持隱藏節點的原始位置
        });
    }, []);

    const loadTeamInfo = useCallback(async () => {
        try {
            const response = await fetch(`/api/teams/${teamId}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
            });
            if (response.ok) {
                const team = await response.json();
                setTeamName(team.name || `Team ${teamId}`);
            }
        } catch (error) {
            console.error('Failed to load team info:', error);
        }
    }, [teamId]);

    // Load maps for team
    const loadMaps = useCallback(async () => {
        try {
            const response = await fetch(`/api/user-story-maps/team/${teamId}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
            });
            if (response.ok) {
                const data = await response.json();
                setMaps(data);

                // Update select dropdown
                const select = document.getElementById('currentMapSelect');
                if (select) {
                    select.innerHTML = '<option value="">選擇地圖...</option>';
                    data.forEach(map => {
                        const option = document.createElement('option');
                        option.value = map.id;
                        option.textContent = map.name;
                        select.appendChild(option);
                    });
                }
            }
        } catch (error) {
            console.error('Failed to load maps:', error);
        }
    }, []);

    // Load specific map
    const loadMap = useCallback(async (mapId) => {
        try {
            const response = await fetch(`/api/user-story-maps/${mapId}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
            });
            if (response.ok) {
                const map = await response.json();
                
                // Convert nodes
                const flowNodes = map.nodes.map(node => ({
                    id: node.id,
                    type: 'custom',
                    position: { x: node.position_x, y: node.position_y },
                    targetPosition: 'left',
                    sourcePosition: 'right',
                    data: {
                        title: node.title,
                        description: node.description,
                        nodeType: node.node_type,
                        team: node.team || teamName || '',
                        jiraTickets: node.jira_tickets,
                        aggregatedTickets: node.aggregated_tickets || [],
                        comment: node.comment,
                        parentId: node.parent_id,
                        childrenIds: node.children_ids || [],
                        relatedIds: normalizeRelatedEntries(node.related_ids),
                        level: node.level || 0,
                        dimmed: false,
                        isRoot: !node.parent_id,
                        as_a: node.as_a,
                        i_want: node.i_want,
                        so_that: node.so_that,
                    },
                }));

                // Convert edges
                const flowEdges = map.edges.map(edge => {
                    const isRelationEdge = edge.edge_type === 'related' || edge.id.startsWith('relation-');
                    const targetHandle = isRelationEdge ? 'right-target' : 'left';
                    const baseEdge = {
                        id: edge.id,
                        source: edge.source,
                        target: edge.target,
                        type: edge.edge_type === 'parent' ? 'smoothstep' : 'default',
                        animated: isRelationEdge,
                        style: isRelationEdge ? {
                            strokeDasharray: '5,5',
                            stroke: '#17a2b8',
                            strokeWidth: 2,
                        } : {},
                        markerEnd: {
                            type: MarkerType.ArrowClosed,
                        },
                        sourceHandle: 'right',
                        targetHandle,
                    };
                    if (isRelationEdge) {
                        baseEdge.type = 'step';
                        baseEdge.pathOptions = RELATION_EDGE_PATH_OPTIONS;
                    }
                    return baseEdge;
                });

                const layoutedNodes = applyTreeLayout(flowNodes, flowEdges);
                const decoratedNodes = layoutedNodes.map(node => ({
                    ...node,
                    data: {
                        ...node.data,
                        collapsed: false,
                        toggleCollapse: toggleNodeCollapse,
                    },
                }));
                
                // Clean up orphaned edges (pointing to non-existent nodes)
                const nodeIds = new Set(decoratedNodes.map(n => n.id));
                const validEdges = flowEdges.filter(edge => 
                    nodeIds.has(edge.source) && nodeIds.has(edge.target)
                );
                
                nodesRef.current = decoratedNodes;
                setNodes(decoratedNodes);
                setSelectedNode((prevSelected) => {
                    if (!prevSelected) {
                        return prevSelected;
                    }
                    const refreshed = decoratedNodes.find(node => node.id === prevSelected.id);
                    return refreshed || null;
                });
                setEdges(validEdges.map(edge => ({ ...edge, hidden: false })));
                setCurrentMapId(mapId);
                setCollapsedNodeIds(() => new Set());
                setHighlightedNodeIds([]);
                setHighlightedPath(null);
                const highlightInfoEl = document.getElementById('highlightInfo');
                if (highlightInfoEl) {
                    highlightInfoEl.classList.remove('show');
                    highlightInfoEl.classList.add('d-none');
                    highlightInfoEl.innerHTML = '';
                }
            }
        } catch (error) {
            console.error('Failed to load map:', error);
        }
    }, [setNodes, setEdges, applyTreeLayout, teamName, toggleNodeCollapse, setSelectedNode, setCurrentMapId, setCollapsedNodeIds, setHighlightedNodeIds, setHighlightedPath]);

    // Save map
    const saveMap = useCallback(async (silent = false) => {
        if (!hasUsmAccess('mapUpdate')) {
            if (!silent) {
                showMessage('您沒有權限儲存此地圖', 'error');
            }
            return;
        }

        if (!currentMapId) {
            alert('請先選擇一個地圖');
            return;
        }

        try {
            // Convert nodes back
            const mapNodes = nodes.map(node => ({
                id: node.id,
                title: node.data.title,
                description: node.data.description,
                node_type: node.data.nodeType,
                parent_id: node.data.parentId,
                children_ids: node.data.childrenIds || [],
                related_ids: serializeRelatedEntries(node.data.relatedIds),
                comment: node.data.comment,
                jira_tickets: node.data.jiraTickets || [],
                team: teamName || node.data.team || '',
                aggregated_tickets: node.data.aggregatedTickets || [],
                position_x: node.position.x,
                position_y: node.position.y,
                level: node.data.level || 0,
                as_a: node.data.as_a,
                i_want: node.data.i_want,
                so_that: node.data.so_that,
            }));

            // Convert edges back
            const mapEdges = edges.map(edge => {
                const isRelationEdge = edge.id.startsWith('relation-') || edge.animated && edge.style?.strokeDasharray === '5,5';
                return {
                    id: edge.id,
                    source: edge.source,
                    target: edge.target,
                    edge_type: edge.type === 'smoothstep' ? 'parent' : isRelationEdge ? 'related' : 'default',
                };
            });

            const response = await fetch(`/api/user-story-maps/${currentMapId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
                body: JSON.stringify({
                    nodes: mapNodes,
                    edges: mapEdges,
                }),
            });

            if (response.ok) {
                if (!silent) {
                    showMessage('地圖已儲存', 'success');
                }
            } else {
                showMessage('儲存失敗', 'error');
            }
        } catch (error) {
            console.error('Failed to save map:', error);
            showMessage('儲存失敗', 'error');
        }
    }, [currentMapId, nodes, edges, teamName]);

    // Add node
    const addNode = useCallback((nodeData) => {
        if (!hasUsmAccess('nodeAdd')) {
            showMessage('您沒有權限新增節點', 'error');
            return null;
        }
        // Calculate position based on tree layout
        let positionX = ROOT_START_X;
        let positionY = ROOT_START_Y;

        if (nodeData.parentId) {
            const parentNode = nodes.find(n => n.id === nodeData.parentId);
            if (parentNode) {
                // Position to the right of parent
                positionX = parentNode.position.x + CHILD_HORIZONTAL_OFFSET;

                // Calculate Y position based on existing siblings to avoid stacking
                const siblings = nodes.filter(n => n.data.parentId === nodeData.parentId);
                if (siblings.length > 0) {
                    const maxSiblingY = Math.max(...siblings.map((s) => s.position.y));
                    positionY = maxSiblingY + SIBLING_VERTICAL_SPACING;
                } else {
                    positionY = parentNode.position.y;
                }
            }
        } else {
            // Root level - position based on existing root nodes
            const rootNodes = nodes.filter(n => !n.data.parentId);
            if (rootNodes.length > 0) {
                const maxRootY = Math.max(...rootNodes.map((root) => root.position.y));
                positionY = maxRootY + ROOT_VERTICAL_SPACING;
            } else {
                positionY = ROOT_START_Y;
            }
        }

        const newNode = {
            id: `node_${Date.now()}`,
            type: 'custom',
            position: { 
                x: positionX, 
                y: positionY 
            },
            targetPosition: 'left',
            sourcePosition: 'right',
            data: {
                title: nodeData.title,
                description: nodeData.description,
                nodeType: nodeData.nodeType || 'feature_category',
                team: teamName,
                jiraTickets: nodeData.jiraTickets || [],
                aggregatedTickets: [],
                comment: '',
                parentId: nodeData.parentId || null,
                childrenIds: [],
                relatedIds: [],
                level: nodeData.level || 0,
                dimmed: false,
                isRoot: !nodeData.parentId,
                collapsed: false,
                toggleCollapse: toggleNodeCollapse,
                as_a: nodeData.as_a,
                i_want: nodeData.i_want,
                so_that: nodeData.so_that,
            },
        };
        setNodes((nds) => {
            const updatedBase = nodeData.parentId
                ? nds.map((node) => {
                    if (node.id === nodeData.parentId) {
                        return {
                            ...node,
                            data: {
                                ...node.data,
                                childrenIds: [...(node.data.childrenIds || []), newNode.id],
                            },
                        };
                    }
                    return node;
                })
                : nds;

            const result = [...updatedBase, newNode];
            nodesRef.current = result;
            return result;
        });

        // If has parent, create edge and update parent's children
        if (nodeData.parentId) {
            setEdges((eds) => eds.concat({
                id: `edge_${Date.now()}`,
                source: nodeData.parentId,
                sourceHandle: 'right',  // 從父節點右側
                target: newNode.id,
                targetHandle: 'left',   // 到子節點左側
                type: 'smoothstep',
                markerEnd: {
                    type: MarkerType.ArrowClosed,
                },
                hidden: false,
            }));
        }

        setCollapsedNodeIds((prev) => new Set(prev));

        setTimeout(() => {
            window.userStoryMapFlow?.saveMap?.(true);
        }, 0);

        return newNode;
    }, [setNodes, setEdges, nodes, teamName, toggleNodeCollapse]);

    // Add child node
    const addChildNode = useCallback((parentId) => {
        if (!hasUsmAccess('nodeAdd')) {
            showMessage('您沒有權限新增節點', 'error');
            return;
        }
        const parentNode = nodes.find(n => n.id === parentId);
        if (!parentNode) return;

        // Clean up any lingering modal backdrops
        document.querySelectorAll('.modal-backdrop').forEach((backdrop) => backdrop.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('padding-right');
        document.body.style.removeProperty('paddingRight');

        const modalElement = document.getElementById('addNodeModal');
        // Ensure modal is visible
        modalElement.style.zIndex = '1050';
        
        const modal = new bootstrap.Modal(modalElement);
        modal.show();
        
        // After showing, adjust backdrop z-index
        setTimeout(() => {
            const backdrops = document.querySelectorAll('.modal-backdrop');
            if (backdrops.length > 0) {
                backdrops[backdrops.length - 1].style.zIndex = '1049';
            }
        }, 10);

        // Set default node type
        const nodeTypeSelect = document.getElementById('nodeType');
        if (nodeTypeSelect) {
            nodeTypeSelect.value = 'feature_category';
            // Trigger change event to show/hide BDD fields
            nodeTypeSelect.dispatchEvent(new Event('change'));
        }

        const teamLabel = document.getElementById('nodeTeamDisplay');
        if (teamLabel) {
            const name = window.userStoryMapFlow?.getTeamName?.();
            teamLabel.textContent = name || '載入中…';
        }

        // Store parent info for later use
        window._tempParentId = parentId;
        window._tempParentLevel = parentNode.data.level || 0;
    }, [nodes]);

    // Add sibling node
    const addSiblingNode = useCallback((siblingId) => {
        if (!hasUsmAccess('nodeAdd')) {
            showMessage('您沒有權限新增節點', 'error');
            return;
        }
        const siblingNode = nodes.find(n => n.id === siblingId);
        if (!siblingNode) return;

        // Root node cannot have siblings - check by level and parentId
        if (siblingNode.data.level === 0 || !siblingNode.data.parentId) {
            alert('根節點不能新增同級節點');
            return;
        }

        // Clean up any lingering modal backdrops
        document.querySelectorAll('.modal-backdrop').forEach((backdrop) => backdrop.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('padding-right');
        document.body.style.removeProperty('paddingRight');

        const modalElement = document.getElementById('addNodeModal');
        // Ensure modal is visible
        modalElement.style.zIndex = '1050';
        
        const modal = new bootstrap.Modal(modalElement);
        modal.show();
        
        // After showing, adjust backdrop z-index
        setTimeout(() => {
            const backdrops = document.querySelectorAll('.modal-backdrop');
            if (backdrops.length > 0) {
                backdrops[backdrops.length - 1].style.zIndex = '1049';
            }
        }, 10);

        const teamLabel = document.getElementById('nodeTeamDisplay');
        if (teamLabel) {
            const name = window.userStoryMapFlow?.getTeamName?.();
            teamLabel.textContent = name || '載入中…';
        }

        // Store sibling info
        window._tempParentId = siblingNode.data.parentId;
        window._tempParentLevel = (siblingNode.data.level || 1) - 1;
    }, [nodes]);

    // Connect nodes (disabled)
    const onConnect = useCallback(() => {
        // Connection feature disabled
    }, []);

    // Node click handler
    const onNodeClick = useCallback((event, node) => {
        setSelectedNode(node);
        updateNodeProperties(node);
    }, []);

    // Update node properties in sidebar
    const updateNodeProperties = (node) => {
        const container = document.getElementById('nodeProperties');
        if (!node) {
            container.innerHTML = '<p class="text-muted small">選擇一個節點以查看和編輯屬性</p>';
            // 隱藏按鈕
            const highlightBtn = document.getElementById('highlightPathBtn');
            const graphBtn = document.getElementById('fullRelationGraphBtn');
            if (highlightBtn) highlightBtn.style.display = 'none';
            if (graphBtn) graphBtn.style.display = 'none';
            return;
        }

        // 顯示按鈕
        const highlightBtn = document.getElementById('highlightPathBtn');
        const graphBtn = document.getElementById('fullRelationGraphBtn');
        if (highlightBtn) {
            highlightBtn.style.display = 'inline-block';
        }
        if (graphBtn) {
            graphBtn.style.display = 'inline-block';
        }

        const data = node.data;
        const resolvedTeam = data.team || teamName || '';
        const canUpdateNode = hasUsmAccess('nodeUpdate');
        const canDeleteNode = hasUsmAccess('nodeDelete');
        const readOnlyAttr = canUpdateNode ? '' : 'readonly';

        const aggregatedTicketsHtml = data.aggregatedTickets && data.aggregatedTickets.length > 0
            ? `<div class="mb-3">
                    <label class="form-label small fw-bold">聚合 Tickets (含子節點)</label>
                    <div class="alert alert-warning p-2 small">
                        ${escapeHtml(data.aggregatedTickets.join(', '))}
                    </div>
                </div>`
            : '';

        const relatedNodesHtml = data.relatedIds && data.relatedIds.length > 0
            ? `<div class="mb-3">
                    <label class="form-label small fw-bold">相關節點 (<span id="relatedNodesCount">${data.relatedIds.length}</span>)</label>
                    <div class="list-group list-group-sm" id="relatedNodesList" style="max-height: 200px; overflow-y: auto;">
                        ${(Array.isArray(data.relatedIds) ? data.relatedIds : []).map((rel, idx) => {
                            if (typeof rel === 'string') {
                                return `<div class="list-group-item small"><span class="text-muted">${escapeHtml(rel)}</span></div>`;
                            }
                            // Only show popup button if:
                            // 1. map_id exists (not undefined/null)
                            // 2. map_id is different from current map
                            // 3. map_id is not 0 or empty string (treating falsy values as same map)
                            const isCrossMap = rel.map_id && String(rel.map_id) !== String(window.currentMapId);
                            return `
                                <div class="list-group-item small" style="display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px;">
                                    <button type="button" class="flex-grow-1 btn btn-secondary btn-sm text-start p-0" data-related-idx="${idx}" title="點擊導航到該節點">
                                        <strong>${escapeHtml(rel.display_title || rel.node_id)}</strong>
                                        <br>
                                        <small class="text-muted">
                                            ${escapeHtml(rel.team_name || '')} / ${escapeHtml(rel.map_name || '')}
                                        </small>
                                    </button>
                                    ${isCrossMap ? `<button type="button" class="btn btn-sm btn-info" data-related-popup-idx="${idx}" data-map-id="${rel.map_id || rel.mapId || ''}" data-team-id="${rel.team_id || rel.teamId || ''}" title="在新視窗開啟外部地圖" style="flex-shrink: 0; position: relative; z-index: 2; pointer-events: auto;"><i class="fas fa-external-link-alt"></i></button>` : ''}
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>`
            : '';

        const actionButtonsHtml = [
            canUpdateNode ? '<button type="button" class="btn btn-sm btn-primary w-100" id="updateNodeBtn">更新節點</button>' : '',
            canDeleteNode ? '<button type="button" class="btn btn-sm btn-danger w-100" id="deleteNodeBtn">刪除節點</button>' : '',
        ].filter(Boolean).join('');

        // Build a stable render signature to avoid unnecessary re-renders
        const renderSig = JSON.stringify({
            id: node.id,
            nodeType: data.nodeType || '',
            title: data.title || '',
            description: data.description || '',
            team: resolvedTeam || '',
            as_a: data.as_a || '',
            i_want: data.i_want || '',
            so_that: data.so_that || '',
            jira: (data.jiraTickets || []).join(', '),
            related: Array.isArray(data.relatedIds) ? JSON.stringify(data.relatedIds) : '[]',
            aggregated: Array.isArray(data.aggregatedTickets) ? JSON.stringify(data.aggregatedTickets) : '[]',
            comment: data.comment || ''
        });
        if (container.dataset.renderSig === renderSig) {
            return; // No change; skip DOM update
        }

        const newHtml = `
            <div class="node-properties-content">
                <div class="mb-3">
                    <label class="form-label small fw-bold">標題</label>
                    <input type="text" class="form-control form-control-sm" id="propTitle" ${readOnlyAttr} value="${escapeHtml(data.title || '')}">
                </div>
                <div class="mb-3">
                    <label class="form-label small fw-bold">描述</label>
                    <textarea class="form-control form-control-sm" id="propDescription" rows="3" ${readOnlyAttr}>${escapeHtml(data.description || '')}</textarea>
                </div>
                <div class="mb-3">
                    <label class="form-label small fw-bold">團隊</label>
                    <p class="form-control-plaintext mb-0">${resolvedTeam ? escapeHtml(resolvedTeam) : '<span class="text-muted">未設定</span>'}</p>
                </div>
                ${data.nodeType === 'user_story' ? `
                <div class="mb-3">
                    <label class="form-label small fw-bold">As a <small class="text-muted">(使用者角色)</small></label>
                    <input type="text" class="form-control form-control-sm" id="propAsA" ${readOnlyAttr} value="${escapeHtml(data.as_a || '')}" placeholder="As a user...">
                </div>
                <div class="mb-3">
                    <label class="form-label small fw-bold">I want <small class="text-muted">(需求描述)</small></label>
                    <textarea class="form-control form-control-sm" id="propIWant" rows="3" ${readOnlyAttr} placeholder="I want to...">${escapeHtml(data.i_want || '')}</textarea>
                </div>
                <div class="mb-3">
                    <label class="form-label small fw-bold">So that <small class="text-muted">(價值目的)</small></label>
                    <textarea class="form-control form-control-sm" id="propSoThat" rows="3" ${readOnlyAttr} placeholder="So that...">${escapeHtml(data.so_that || '')}</textarea>
                </div>
                ` : ''}
                <div class="mb-3">
                    <label class="form-label small fw-bold">JIRA Tickets</label>
                    <div id="jiraTicketsContainer"
                         class="form-control form-control-sm"
                         style="min-height: 32px; padding: 0.35rem 0.6rem; border: 1px solid #dee2e6; border-radius: 0.25rem; background-color: #fff; cursor: ${canUpdateNode ? 'text' : 'default'}; display: flex; align-items: center; flex-wrap: wrap; gap: 4px; position: relative; overflow-y: auto; max-height: 120px;"
                         ${readOnlyAttr ? '' : 'data-editable="true"'}>
                        ${(data.jiraTickets || []).length > 0 ? (data.jiraTickets || []).map(ticket => `<span class="jira-badge">${escapeHtml(ticket)}</span>`).join('') : '<small class="text-muted">未輸入任何票號</small>'}
                    </div>
                    <input type="hidden" id="propJira" name="jira" value="${escapeHtml((data.jiraTickets || []).join(', '))}">
                </div>
                ${aggregatedTicketsHtml}
                ${relatedNodesHtml}
                <div class="mb-3">
                    <label class="form-label small fw-bold">註解</label>
                    <textarea class="form-control form-control-sm" id="propComment" rows="2" ${readOnlyAttr}>${escapeHtml(data.comment || '')}</textarea>
                </div>
            </div>
            <div class="node-properties-actions">
                ${actionButtonsHtml || '<p class="text-muted small mb-0">目前角色無可用操作</p>'}
            </div>
        `;

        container.dataset.renderSig = renderSig;
        container.innerHTML = newHtml;

        if (canUpdateNode) {
            const attachAutoSave = (id) => {
                const el = document.getElementById(id);
                if (el) {
                    el.addEventListener('blur', () => updateNode(node.id));
                }
            };

            attachAutoSave('propTitle');
            attachAutoSave('propDescription');
            attachAutoSave('propComment');

            // 添加 JIRA Tickets 浮層編輯器
            const jiraContainer = document.getElementById('jiraTicketsContainer');
            if (jiraContainer && jiraContainer.dataset.editable === 'true') {
                jiraContainer.addEventListener('click', (e) => {
                    // 點擊 badge 或容器時開始編輯
                    if (e.target === jiraContainer || e.target.classList.contains('badge')) {
                        editJiraTickets(node.id, jiraContainer);
                    }
                });
            }

            if (data.nodeType === 'user_story') {
                attachAutoSave('propAsA');
                attachAutoSave('propIWant');
                attachAutoSave('propSoThat');
            }

            document.getElementById('updateNodeBtn')?.addEventListener('click', () => {
                updateNode(node.id);
            });
        }

        if (canDeleteNode) {
            document.getElementById('deleteNodeBtn')?.addEventListener('click', () => {
                deleteNode(node.id);
            });
        }
    };

    // Update node
    const updateNode = (nodeId) => {
        if (!hasUsmAccess('nodeUpdate')) {
            showMessage('您沒有權限更新節點', 'error');
            return;
        }
        setNodes((nds) =>
            nds.map((node) => {
                if (node.id === nodeId) {
                    const jiraText = document.getElementById('propJira')?.value || '';
                    const jiraTickets = jiraText.split(',').map(t => t.trim()).filter(t => t);
                    
                    const updatedData = {
                        ...node.data,
                        title: document.getElementById('propTitle')?.value || '',
                        description: document.getElementById('propDescription')?.value || '',
                        team: teamName,
                        jiraTickets: jiraTickets,
                        comment: document.getElementById('propComment')?.value || '',
                    };

                    // Add BDD fields for User Story nodes
                    if (node.data.nodeType === 'user_story') {
                        updatedData.as_a = document.getElementById('propAsA')?.value || '';
                        updatedData.i_want = document.getElementById('propIWant')?.value || '';
                        updatedData.so_that = document.getElementById('propSoThat')?.value || '';
                    }

                    node.data = updatedData;
                }
                return node;
            })
        );
        setTimeout(() => {
            window.userStoryMapFlow?.saveMap?.(true);
        }, 0);
    };

    // JIRA Tickets 浮層編輯功能
    window.editJiraTickets = function(nodeId, container) {
        console.log('🟢 editJiraTickets 被呼叫，nodeId:', nodeId);

        // 獲取當前 JIRA Tickets 值
        const propJiraInput = document.getElementById('propJira');
        if (!propJiraInput) {
            console.log('⚠️ editJiraTickets: 找不到 propJira 輸入框');
            return;
        }

        const currentValue = propJiraInput.value || '';
        const currentTickets = currentValue.split(',').map(t => t.trim()).filter(t => t);

        console.log('✏️ editJiraTickets 開始，找到的 JIRA Tickets 值:', currentTickets);

        // 設置編輯器狀態
        window._jiraTicketsEditor = {
            nodeId: nodeId,
            container: container,
            currentTickets: [...currentTickets],
            originalContent: container.innerHTML,
            originalTickets: [...currentTickets],
        };
        console.log('✏️ _jiraTicketsEditor 已設置:', window._jiraTicketsEditor);

        // 開始編輯
        startJiraTicketsSearch(container);
    };

    window.startJiraTicketsSearch = function(container) {
        if (!window._jiraTicketsEditor) return;

        const { currentTickets } = window._jiraTicketsEditor;

        console.log('🟢 startJiraTicketsSearch 開始，currentTickets:', currentTickets);

        // 清空容器內容並設置為編輯模式
        container.innerHTML = '';
        container.style.position = 'relative';
        container.style.display = 'flex';
        container.style.alignItems = 'center';
        container.style.minHeight = '32px';
        container.style.height = '32px';
        container.style.padding = '4px 8px';
        container.style.overflow = 'visible';

        // 創建浮層輸入框 - 使用絕對定位，不會影響版面
        const editorHtml = `
            <div class="jira-inline-editor" style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: 1000; display: flex; align-items: center; padding: 4px 8px;" onclick="event.stopPropagation()">
                <input type="text" class="form-control form-control-sm jira-search-input"
                       placeholder="輸入 JIRA 票號，以逗號分隔 (例: JIRA-123, JIRA-456)"
                       autocomplete="off"
                       onkeydown="window.handleJiraSearchKeydown(event)"
                       style="height: 28px; width: 100%; font-size: 0.75rem; padding: 0.25rem 0.375rem; margin: 0; border: 1px solid #dee2e6; box-sizing: border-box;">
            </div>
        `;

        container.insertAdjacentHTML('beforeend', editorHtml);
        container.classList.add('editing');

        // 聚焦搜尋框
        const searchInput = container.querySelector('.jira-search-input');
        if (searchInput) {
            searchInput.value = currentTickets.join(', ');
            searchInput.focus();
            searchInput.select();
            console.log('✅ JIRA 搜尋框已聚焦，值:', searchInput.value);
        }

        // 添加點擊外部結束編輯的監聽器
        setTimeout(() => {
            document.addEventListener('click', window.handleJiraOutsideClick, true);
        }, 100);
    };

    window.handleJiraOutsideClick = function(event) {
        if (!window._jiraTicketsEditor) {
            console.log('🔵 handleJiraOutsideClick: _jiraTicketsEditor is null, ignore');
            return;
        }

        const { container } = window._jiraTicketsEditor;

        // 檢查點擊是否在編輯區域外
        if (!container.contains(event.target)) {
            console.log('🔴 handleJiraOutsideClick: 點擊在編輯區域外，結束編輯');
            window.finishJiraTicketsEdit();
        } else {
            console.log('🟡 handleJiraOutsideClick: 點擊在編輯區域內，保留編輯');
        }
    };

    window.handleJiraSearchKeydown = function(event) {
        console.log('⌨️ handleJiraSearchKeydown 觸發，key:', event.key);

        if (event.key === 'Enter') {
            event.preventDefault();
            window.finishJiraTicketsEdit();
        } else if (event.key === 'Escape') {
            event.preventDefault();
            window.cancelJiraTicketsEdit();
        }
    };

    window.finishJiraTicketsEdit = async function() {
        if (!window._jiraTicketsEditor) {
            console.log('⚠️ finishJiraTicketsEdit: 沒有當前編輯器');
            return;
        }

        const { nodeId, container, originalTickets } = window._jiraTicketsEditor;

        console.log('=== finishJiraTicketsEdit 開始 ===');
        console.log('nodeId:', nodeId);

        // 移除全域點擊監聽器
        document.removeEventListener('click', window.handleJiraOutsideClick, true);

        // 取得輸入框的值
        const searchInput = container.querySelector('.jira-search-input');
        const inputValue = searchInput ? searchInput.value.trim() : '';

        // 解析輸入的 JIRA Tickets
        const newTickets = inputValue.split(',').map(t => t.trim()).filter(t => t);

        console.log('🆕 新 JIRA Tickets:', newTickets);
        console.log('📌 原 JIRA Tickets:', originalTickets);

        // 更新 propJira 隱藏輸入框
        const propJiraInput = document.getElementById('propJira');
        if (propJiraInput) {
            propJiraInput.value = newTickets.join(', ');
        }

        // 清除浮層編輯器
        const editor = container.querySelector('.jira-inline-editor');
        if (editor) {
            editor.remove();
        }

        // 恢復容器樣式
        container.style.position = 'relative';
        container.style.display = 'flex';
        container.style.alignItems = 'center';
        container.style.minHeight = '32px';
        container.style.height = 'auto';
        container.style.padding = '0.35rem 0.6rem';
        container.style.overflow = 'auto';
        container.classList.remove('editing');

        // 更新容器內容（顯示 badges）
        if (newTickets.length > 0) {
            container.innerHTML = newTickets.map(ticket =>
                `<span class="jira-badge">${escapeHtml(ticket)}</span>`
            ).join('');
        } else {
            container.innerHTML = '<small class="text-muted">未輸入任何票號</small>';
        }

        // 清除編輯器狀態
        window._jiraTicketsEditor = null;

        // 如果值有改變，更新節點
        const ticketsChanged = JSON.stringify(newTickets) !== JSON.stringify(originalTickets);
        if (ticketsChanged) {
            console.log('💾 JIRA Tickets 已更改，呼叫 updateNode');
            updateNode(nodeId);
        }
    };

    window.cancelJiraTicketsEdit = function() {
        if (!window._jiraTicketsEditor) {
            return;
        }

        const { container, originalContent } = window._jiraTicketsEditor;

        console.log('❌ cancelJiraTicketsEdit: 取消編輯');

        // 移除全域點擊監聽器
        document.removeEventListener('click', window.handleJiraOutsideClick, true);

        // 清除浮層編輯器
        const editor = container.querySelector('.jira-inline-editor');
        if (editor) {
            editor.remove();
        }

        // 恢復原內容和樣式
        container.innerHTML = originalContent;
        container.style.position = 'relative';
        container.style.display = 'flex';
        container.style.alignItems = 'center';
        container.style.minHeight = '32px';
        container.style.height = 'auto';
        container.style.padding = '0.35rem 0.6rem';
        container.style.overflow = 'auto';
        container.classList.remove('editing');

        // 清除編輯器狀態
        window._jiraTicketsEditor = null;
    };

    const computeHighlightDetails = useCallback((nodeId, nodesById) => {
        const targetNode = nodesById.get(nodeId);
        if (!targetNode) {
            return null;
        }

        const highlightedIds = new Set([nodeId]);
        const parentNodes = [];
        const childNodes = [];
        const relatedSameMapNodes = [];
        const crossMapRelations = [];

        let currentParentId = targetNode.data.parentId;
        const visitedParents = new Set();
        while (currentParentId && !visitedParents.has(currentParentId)) {
            visitedParents.add(currentParentId);
            const parentNode = nodesById.get(currentParentId);
            if (!parentNode) {
                break;
            }
            parentNodes.push(parentNode);
            highlightedIds.add(parentNode.id);
            currentParentId = parentNode.data.parentId;
        }
        parentNodes.reverse();

        const childQueue = Array.isArray(targetNode.data.childrenIds)
            ? [...targetNode.data.childrenIds]
            : [];
        const visitedChildren = new Set();

        while (childQueue.length > 0) {
            const childId = childQueue.shift();
            if (!childId || visitedChildren.has(childId)) continue;
            visitedChildren.add(childId);

            const childNode = nodesById.get(childId);
            if (!childNode) continue;

            childNodes.push(childNode);
            highlightedIds.add(childNode.id);

            if (Array.isArray(childNode.data.childrenIds)) {
                childQueue.push(...childNode.data.childrenIds);
            }
        }

        const normalizeRelatedEntry = (entry) => {
            if (!entry) return null;

            if (typeof entry === 'string') {
                if (nodesById.has(entry)) {
                    return { type: 'same', node: nodesById.get(entry) };
                }

                const parts = entry.split(':');
                if (parts.length >= 2) {
                    const maybeMapId = parts[0];
                    const nodeIdentifier = parts.slice(1).join(':');
                    const mapIdNumber = Number(maybeMapId);
                    if (!Number.isNaN(mapIdNumber)) {
                        return {
                            type: 'cross',
                            mapId: mapIdNumber,
                            nodeId: nodeIdentifier,
                            raw: entry,
                        };
                    }
                }

                return {
                    type: 'cross',
                    mapId: null,
                    nodeId: entry,
                    raw: entry,
                };
            }

            if (typeof entry === 'object') {
                const mapId =
                    entry.mapId ??
                    entry.map_id ??
                    entry.map ??
                    null;
                const nodeId =
                    entry.nodeId ??
                    entry.node_id ??
                    entry.id ??
                    entry.target ??
                    null;
                const nodeTitle =
                    entry.nodeTitle ??
                    entry.node_title ??
                    entry.title ??
                    null;
                const mapName =
                    entry.mapName ??
                    entry.map_name ??
                    null;

                if (nodeId && nodesById.has(nodeId)) {
                    return { type: 'same', node: nodesById.get(nodeId) };
                }

                return {
                    type: 'cross',
                    mapId,
                    nodeId,
                    nodeTitle,
                    mapName,
                    raw: JSON.stringify(entry),
                };
            }

            return null;
        };

        (targetNode.data.relatedIds || []).forEach((entry) => {
            const normalized = normalizeRelatedEntry(entry);
            if (!normalized) return;

            if (normalized.type === 'same' && normalized.node) {
                relatedSameMapNodes.push(normalized.node);
                highlightedIds.add(normalized.node.id);
            } else if (normalized.type === 'cross') {
                crossMapRelations.push(normalized);
            }
        });

        return {
            node: targetNode,
            highlightedIds,
            parentNodes,
            childNodes,
            relatedSameMapNodes,
            crossMapRelations,
        };
    }, [currentMapId]);

    const applyHighlight = useCallback((activeIds, focusId, nodesById) => {
        if (!Array.isArray(activeIds) || activeIds.length === 0) {
            setHighlightedPath(null);

            setNodes((nds) =>
                nds.map((node) => ({
                    ...node,
                    data: {
                        ...node.data,
                        dimmed: false,
                    },
                }))
            );

            setEdges((eds) =>
                eds
                    // 移除 relation 邊
                    .filter(edge => !edge.id.startsWith('relation-'))
                    .map((edge) => ({
                        ...edge,
                        style: {
                            ...edge.style,
                            opacity: 1,
                        },
                    }))
            );

            const highlightInfoEl = document.getElementById('highlightInfo');
            if (highlightInfoEl) {
                highlightInfoEl.classList.remove('show');
                highlightInfoEl.classList.add('d-none');
                highlightInfoEl.innerHTML = '';
            }
            const clearBtn = document.getElementById('clearHighlightBtn');
            if (clearBtn) {
                clearBtn.style.display = 'none';
            }
            return;
        }

        const combinedIds = new Set();
        const relationPairs = new Map(); // key: `${sourceId}->${targetId}`, value: relation node
        let focusDetails = null;

        activeIds.forEach((id) => {
            const details = computeHighlightDetails(id, nodesById);
            if (!details) {
                return;
            }
            details.highlightedIds.forEach((value) => combinedIds.add(value));
            details.relatedSameMapNodes.forEach((relNode) => {
                combinedIds.add(relNode.id);
                const key = `${id}->${relNode.id}`;
                if (!relationPairs.has(key)) {
                    relationPairs.set(key, { sourceId: id, relNode });
                }
            });
            if (focusId === id) {
                focusDetails = details;
            }
        });

        if (!focusDetails && activeIds.length > 0) {
            focusDetails = computeHighlightDetails(activeIds[0], nodesById);
        }

        if (focusDetails) {
            setHighlightedPath({
                nodeId: focusDetails.node.id,
                nodes: Array.from(focusDetails.highlightedIds),
                parents: focusDetails.parentNodes.map((node) => node.id),
                children: focusDetails.childNodes.map((node) => node.id),
                relatedSameMap: focusDetails.relatedSameMapNodes.map((node) => node.id),
                crossMapRelations: focusDetails.crossMapRelations,
            });
        } else {
            setHighlightedPath(null);
        }

        setNodes((nds) =>
            nds.map((node) => ({
                ...node,
                data: {
                    ...node.data,
                    dimmed: !combinedIds.has(node.id),
                },
            }))
        );

        setEdges((eds) => {
            const existingEdgeIds = new Set(eds.map(edge => edge.id));
            const relationKeys = new Set(relationPairs.keys());

            const updatedEdges = eds.map((edge) => {
                const isHighlighted =
                    combinedIds.has(edge.source) &&
                    combinedIds.has(edge.target);
                const relationKey = `${edge.source}->${edge.target}`;
                const isRelationEdge = edge.id.startsWith('relation-') || relationKeys.has(relationKey);

                const nextStyle = {
                    ...edge.style,
                    opacity: isHighlighted ? 1 : 0.2,
                };
                if (isRelationEdge && isHighlighted) {
                    nextStyle.strokeDasharray = edge.style?.strokeDasharray || '5,5';
                    nextStyle.stroke = edge.style?.stroke || '#17a2b8';
                    nextStyle.strokeWidth = edge.style?.strokeWidth || 2;
                }

                return {
                    ...edge,
                    style: nextStyle,
                };
            });

            const extraEdges = [];
            relationPairs.forEach(({ sourceId, relNode }) => {
                const edgeId = `relation-${sourceId}-${relNode.id}`;
                if (!existingEdgeIds.has(edgeId)) {
                    existingEdgeIds.add(edgeId);
                    extraEdges.push({
                        id: edgeId,
                        source: sourceId,
                        target: relNode.id,
                        type: 'step',
                        sourceHandle: 'right',
                        targetHandle: 'right-target',
                        pathOptions: RELATION_EDGE_PATH_OPTIONS,
                        animated: true,
                        style: {
                            strokeDasharray: '5,5',
                            stroke: '#17a2b8',
                            strokeWidth: 2,
                        },
                    });
                }
            });

            return updatedEdges.concat(extraEdges);
        });

        const highlightInfoEl = document.getElementById('highlightInfo');
        if (highlightInfoEl) {
            const formatNodeBadge = (node) =>
                `<span class="badge rounded-pill text-bg-primary me-1 mb-1">${escapeHtml(node.data.title || node.id)}</span>`;
            const selectedBadges = activeIds
                .map(id => nodesById.get(id))
                .filter(Boolean)
                .map(formatNodeBadge)
                .join('');

            let htmlContent = `<div><strong>已選擇節點：</strong>${selectedBadges || '<span class="text-muted">無</span>'}</div>`;

            if (focusDetails) {
                const parentHtml =
                    focusDetails.parentNodes.length > 0
                        ? focusDetails.parentNodes.map(formatNodeBadge).join('')
                        : '<span class="text-muted">無父節點</span>';

                const childrenHtml =
                    focusDetails.childNodes.length > 0
                        ? focusDetails.childNodes.map(formatNodeBadge).join('')
                        : '<span class="text-muted">無子節點</span>';

                const relatedHtml =
                    focusDetails.relatedSameMapNodes.length > 0
                        ? focusDetails.relatedSameMapNodes.map(formatNodeBadge).join('')
                        : '<span class="text-muted">本圖無關聯節點</span>';

                const crossMapHtml =
                    focusDetails.crossMapRelations.length > 0
                        ? `<ul class="mb-0 ps-3">${focusDetails.crossMapRelations
                              .map((rel) => {
                                  const mapLabel =
                                      rel.mapName ??
                                      (rel.mapId !== null && rel.mapId !== undefined
                                          ? `地圖 ${rel.mapId}`
                                          : '其他地圖');
                                  const nodeLabel =
                                      rel.nodeTitle ??
                                      rel.nodeId ??
                                      rel.raw ??
                                      '未知節點';
                                  return `<li>${escapeHtml(mapLabel)} - ${escapeHtml(nodeLabel)}</li>`;
                              })
                              .join('')}</ul>`
                        : '<span class="text-muted">無跨圖關聯</span>';

                htmlContent += `
                    <div class="mt-1"><strong>當前節點：</strong>${escapeHtml(focusDetails.node.data.title || focusDetails.node.id)}</div>
                    <div class="mt-1"><strong>父節點：</strong>${parentHtml}</div>
                    <div class="mt-1"><strong>子節點：</strong>${childrenHtml}</div>
                    <div class="mt-1"><strong>本圖關聯：</strong>${relatedHtml}</div>
                    <div class="mt-1"><strong>跨圖關聯：</strong>${crossMapHtml}</div>
                `;
            }

            highlightInfoEl.classList.remove('d-none');
            highlightInfoEl.classList.add('show');
            highlightInfoEl.innerHTML = htmlContent;
        }
        const clearBtn = document.getElementById('clearHighlightBtn');
        if (clearBtn) {
            clearBtn.style.display = 'inline-block';
        }
    }, [computeHighlightDetails, setNodes, setEdges, setHighlightedPath]);

    // Highlight path to node
    const highlightPath = useCallback((nodeId, isMultiSelect = false) => {
        if (!nodeId) return;

        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        if (!nodesById.has(nodeId)) {
            showMessage('找不到指定節點，請重新載入地圖', 'error');
            return;
        }

        const selectedIds = nodes
            .filter(node => node.selected)
            .map(node => node.id);

        let nextIds;
        if (isMultiSelect) {
            if (highlightedNodeIds.includes(nodeId)) {
                nextIds = highlightedNodeIds.filter(id => id !== nodeId);
            } else {
                nextIds = [...highlightedNodeIds, nodeId];
            }
        } else if (selectedIds.length > 1) {
            nextIds = Array.from(new Set(selectedIds));
        } else {
            nextIds = [nodeId];
        }

        if (!nextIds.includes(nodeId)) {
            nextIds = nextIds.length > 0 ? [...nextIds, nodeId] : [nodeId];
        }

        setHighlightedNodeIds(nextIds);
        applyHighlight(nextIds, nodeId, nodesById);
    }, [nodes, highlightedNodeIds, applyHighlight]);

    // Clear path highlighting
    const clearHighlight = useCallback(() => {
        setHighlightedNodeIds([]);
        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        applyHighlight([], null, nodesById);
    }, [nodes, applyHighlight]);

    // Show full relation graph
    const showFullRelationGraph = useCallback(async (nodeId) => {
        if (!nodeId) return;

        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        // 支援多選：使用第一個有效的節點作為焦點來驗證
        const activeIds = Array.isArray(nodeId) ? nodeId.filter(Boolean) : [nodeId];
        const targetNode = nodesById.get(activeIds[0]);

        if (!targetNode) {
            showMessage('找不到指定節點', 'error');
            return;
        }

        // 支援多選：合併多個節點的高亮集合
        const highlightedIds = new Set();
        const crossMapRelations = [];
        let focusId = activeIds[0];
        let focusDetails = null;

        activeIds.forEach((id) => {
            const details = computeHighlightDetails(id, nodesById);
            if (!details) return;
            details.highlightedIds.forEach((v) => highlightedIds.add(v));
            details.crossMapRelations.forEach((rel) => crossMapRelations.push(rel));
            if (id === focusId) {
                focusDetails = details;
            }
        });

        const parentNodes = focusDetails ? focusDetails.parentNodes : [];
        const childNodes = focusDetails ? focusDetails.childNodes : [];
        const relatedSameMapNodes = focusDetails ? focusDetails.relatedSameMapNodes : [];

        // 獲取跨圖節點的詳細資訊並加入到圖中
        const externalNodesData = [];
        for (const rel of crossMapRelations) {
            if (rel.mapId && rel.mapId !== currentMapId) {
                // 獲取外部節點的詳細資訊
                try {
                    const url = `/api/user-story-maps/${rel.mapId}${(rel.team_id||rel.teamId)?`?team_id=${rel.team_id||rel.teamId}`:''}`;
                    const response = await fetch(url, {
                        headers: {
                            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                        },
                    });
                    
                    if (response.ok) {
                        const mapData = await response.json();
                        const targetNode = mapData.nodes.find(n => n.id === rel.nodeId);
                        
                        if (targetNode) {
                            // 獲取團隊名稱
                            let teamName = '未知團隊';
                            const teamId = mapData?.team_id || rel.team_id || rel.teamId; // 根據實際API響應結構
                            if (teamId) {
                                const teamResponse = await fetch(`/api/teams/${teamId}`, {
                                    headers: {
                                        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                                    },
                                });
                                
                                if (teamResponse.ok) {
                                    const teamData = await teamResponse.json();
                                    teamName = teamData.name || `團隊 ${teamId}`;
                                } else {
                                    teamName = `團隊 ${teamId}`;
                                }
                            }
                            
                            // 添加到外部節點數組，標記為外部節點
                            externalNodesData.push({
                                ...targetNode,
                                isExternal: true, // 標記為外部節點
                                mapId: rel.mapId,
                                mapName: rel.mapName || mapData?.name || `地圖 ${rel.mapId}`,
                                team: teamName,
                            });
                        }
                    }
                } catch (error) {
                    console.error('獲取跨圖節點資訊失敗:', error);
                }
            }
        }

        // 獲取跨圖節點的詳細資訊（包括 As A, I want, So That 和團隊名稱）
        const enhancedCrossMapRelations = [];
        for (const rel of crossMapRelations) {
            if (rel.mapId && rel.mapId !== (currentMapId || 0)) {
                // 需要從後端獲取此跨圖節點的詳細資訊
                try {
                    const url = `/api/user-story-maps/${rel.mapId}${(rel.team_id||rel.teamId)?`?team_id=${rel.team_id||rel.teamId}`:''}`;
                    const response = await fetch(url, {
                        headers: {
                            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                        },
                    });
                    
                    if (response.ok) {
                        const mapData = await response.json();
                        const targetNode = mapData.nodes.find(n => n.id === rel.nodeId);
                        
                        // 獲取團隊名稱
                        let teamName = rel.team_name || '未知團隊';
                        const teamId = mapData?.team_id || rel.team_id || rel.teamId;
                        if (teamId && !rel.team_name) {
                            const teamResponse = await fetch(`/api/teams/${teamId}`, {
                                headers: {
                                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                                },
                            });
                            
                            if (teamResponse.ok) {
                                const teamData = await teamResponse.json();
                                teamName = teamData.name || `團隊 ${teamId}`;
                            } else {
                                teamName = `團隊 ${teamId}`;
                            }
                        }
                        
                        if (targetNode) {
                            enhancedCrossMapRelations.push({
                                ...rel,
                                as_a: targetNode.as_a,
                                i_want: targetNode.i_want,
                                so_that: targetNode.so_that,
                                nodeTitle: targetNode.title,
                                resolvedTeamName: teamName,
                                team_id: teamId, // 保留 team_id 方便後續使用
                            });
                        } else {
                            enhancedCrossMapRelations.push({
                                ...rel,
                                resolvedTeamName: teamName,
                                team_id: teamId,
                            }); // 如果找不到節點，使用原始資料
                        }
                    } else {
                        const teamId = rel.team_id || rel.teamId;
                        const teamName = rel.team_name || (teamId ? `團隊 ${teamId}` : '未知團隊');
                        enhancedCrossMapRelations.push({
                            ...rel,
                            resolvedTeamName: teamName,
                            team_id: teamId,
                        }); // 如果獲取失敗，使用原始資料
                    }
                } catch (error) {
                    console.error('獲取跨圖節點資訊失敗:', error);
                    const teamId = rel.team_id || rel.teamId;
                    const teamName = rel.team_name || (teamId ? `團隊 ${teamId}` : '未知團隊');
                    enhancedCrossMapRelations.push({
                        ...rel,
                        resolvedTeamName: teamName,
                        team_id: teamId,
                    }); // 出錯時使用原始資料
                }
            } else {
                const teamId = rel.team_id || rel.teamId;
                const teamName = rel.team_name || (teamId ? `團隊 ${teamId}` : '未知團隊');
                enhancedCrossMapRelations.push({
                    ...rel,
                    resolvedTeamName: teamName,
                    team_id: teamId,
                }); // 同圖節點或已有資訊的直接使用
            }
        }

        // 獲取節點顏色的函數（同主圖）
        const getNodeColor = (node) => {
            const nodeTypeColors = {
                root: '#6f42c1',
                feature_category: '#87ceeb',
                user_story: '#dda0dd',
            };
            return nodeTypeColors[node.data.nodeType] || '#0d6efd';
        };

        // 構建 React Flow 用的節點和邊（包含高亮路徑的所有節點）
        const graphNodes = [];
        const graphEdges = [];
        const layoutEdges = [];

        // 添加所有在高亮路徑中的節點
        Array.from(highlightedIds).forEach((id) => {
            const node = nodesById.get(id);
            if (node) {
                // 檢查是否為原始選定節點，如果是則使用不同背景色標示
                const isOriginalSelectedNode = id === nodeId;
                
                graphNodes.push({
                    id: node.id,
                    type: 'custom',
                    data: {
                        ...node.data,
                        title: node.data.title,
                        nodeType: node.data.nodeType,
                        // disable collapse interaction inside modal
                        toggleCollapse: undefined,
                        collapsed: false,
                        // 在完整關係圖中不顯示子節點，所以將 childrenIds 設為空陣列
                        childrenIds: [],
                        // 在完整關係圖中禁用收合功能
                        disableCollapse: true,
                        // 在 data 中標記是否為原始選定節點，以便在 CustomNode 組件中處理
                        isOriginalSelected: isOriginalSelectedNode,
                        isExternal: false, // 標記為非外部節點
                    },
                    position: { 
                        x: node.position.x, 
                        y: node.position.y 
                    }, // 保持原有位置或使用佈局計算的位置
                    style: {
                        width: 200,
                        minHeight: 110,
                        maxHeight: 110,
                    }
                });
            }
        });

        // 添加外部節點，將它們放置在圖表下方
        const externalStartY = Math.max(...graphNodes.map(n => n.position.y || 0)) + 200; // 在現有節點下方開始放置
        externalNodesData.forEach((externalNode, index) => {
            graphNodes.push({
                id: externalNode.id,
                type: 'custom',
                data: {
                    ...externalNode,
                    // disable collapse interaction inside modal
                    toggleCollapse: undefined,
                    collapsed: false,
                    disableCollapse: true, // 在完整關係圖中禁用收合功能
                    // 在完整關係圖中不顯示子節點，所以將 childrenIds 設為空陣列
                    childrenIds: [],
                    isExternal: true, // 標記為外部節點
                },
                position: { 
                    x: 300 + (index % 4) * 250, // 每行最多4個節點
                    y: externalStartY + Math.floor(index / 4) * 150 // 換行放置
                },
                style: {
                    width: 200,
                    minHeight: 110,
                    maxHeight: 110,
                }
            });
        });

        // 構建邊 - 包含層級邊和關聯邊
        highlightedIds.forEach((id) => {
            const node = nodesById.get(id);
            if (!node) return;

            // 添加父子邊
            if (node.data.childrenIds) {
                node.data.childrenIds.forEach((childId) => {
                    if (highlightedIds.has(childId)) {
                        graphEdges.push({
                            id: `edge-${id}-${childId}`,
                            source: id,
                            target: childId,
                            type: 'smoothstep',
                            sourceHandle: 'right',
                            targetHandle: 'left',
                            animated: false,
                            style: { stroke: '#999', strokeWidth: 1 },
                            markerEnd: { type: (window.ReactFlow && window.ReactFlow.MarkerType && window.ReactFlow.MarkerType.ArrowClosed) ? window.ReactFlow.MarkerType.ArrowClosed : 'arrowclosed' }
                        });
                        layoutEdges.push({ source: id, target: childId });
                    }
                });
            }

            // 添加相關邊
            (node.data.relatedIds || []).forEach((entry) => {
                const relatedId = typeof entry === 'string' ? entry : (entry.nodeId || entry.node_id || entry.id);
                // 移除 highlightedIds.has(relatedId) 檢查，這樣外部節點也會被連接
                if (relatedId && id !== relatedId) {
                    graphEdges.push({
                        id: `relation-${id}-${relatedId}`,
                        source: id,
                        target: relatedId,
                        type: 'step',  // 使用階梯式線條讓轉折更明顯
                        sourceHandle: 'right',
                        targetHandle: 'right-target',  // 讓關聯邊預設接到右側
                        pathOptions: RELATION_EDGE_PATH_OPTIONS,
                        animated: true,
                        style: { stroke: '#17a2b8', strokeWidth: 2, strokeDasharray: '5,5' },
                        markerEnd: { type: (window.ReactFlow && window.ReactFlow.MarkerType && window.ReactFlow.MarkerType.ArrowClosed) ? window.ReactFlow.MarkerType.ArrowClosed : 'arrowclosed' }
                    });
                }
            });
        });

        // 應用樹狀佈局（與主圖相同設定）但不包含外部節點
        if (window.dagre && graphNodes.length > 0) {
            const internalNodes = graphNodes.filter(node => !node.data.isExternal);
            const externalNodes = graphNodes.filter(node => node.data.isExternal);
            
            if (internalNodes.length > 0) {
                const g = new dagre.graphlib.Graph();
                g.setGraph({ rankdir: 'LR', ranksep: 75, nodesep: 40 });
                g.setDefaultEdgeLabel(() => ({}));

                internalNodes.forEach(node => {
                    g.setNode(node.id, { width: 200, height: 110 });
                });

                layoutEdges.forEach(edge => {
                    // 只對內部節點之間的邊進行佈局計算
                    if (internalNodes.some(n => n.id === edge.source) && 
                        internalNodes.some(n => n.id === edge.target)) {
                        g.setEdge(edge.source, edge.target);
                    }
                });

                dagre.layout(g);

                internalNodes.forEach(node => {
                    const position = g.node(node.id);
                    node.position = { x: position.x, y: position.y };
                    node.targetPosition = 'left';
                    node.sourcePosition = 'right';
                });
            }
            
            // 計算外部節點位置
            if (externalNodes.length > 0) {
                const internalMaxY = internalNodes.length > 0 
                    ? Math.max(...internalNodes.map(n => (n.position.y || 0) + 110)) 
                    : 0;
                const externalStartY = internalMaxY + 150; // 在內部節點下方留出空間
                
                externalNodes.forEach((node, index) => {
                    node.position = { 
                        x: 300 + (index % 4) * 250, // 每行最多4個節點
                        y: externalStartY + Math.floor(index / 4) * 150 // 換行放置
                    };
                    node.targetPosition = 'top';
                    node.sourcePosition = 'bottom';
                });
            }
        }

        // 生成跨圖節點卡片 HTML，使用預先獲取的團隊名稱
        const crossMapHtml = enhancedCrossMapRelations.length > 0
            ? enhancedCrossMapRelations.map(rel => {
                return `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="flex-grow-1 me-3" style="width: 40%;">
                            <h6 class="mb-1">${escapeHtml(rel.nodeTitle || rel.nodeId)}</h6>
                            <small class="text-muted">
                                ${rel.resolvedTeamName ? escapeHtml(rel.resolvedTeamName) + ' / ' : ''}${rel.mapName ? '地圖: ' + escapeHtml(rel.mapName) : ''}
                            </small>
                        </div>
                        <div class="text-start" style="width: 60%;">
                            ${rel.as_a || rel.asA ? `<div><small><strong>As A:</strong> ${escapeHtml(rel.as_a || rel.asA)}</small></div>` : ''}
                            ${rel.i_want || rel.iWant ? `<div><small><strong>I Want:</strong> ${escapeHtml(rel.i_want || rel.iWant)}</small></div>` : ''}
                            ${rel.so_that || rel.soThat ? `<div><small><strong>So That:</strong> ${escapeHtml(rel.so_that || rel.soThat)}</small></div>` : ''}
                        </div>
                    </div>
                </div>
              `;
              }).join('')
            : '<p class="text-muted small text-center py-3">無跨地圖關聯</p>';

        document.getElementById('crossMapNodesList').innerHTML = crossMapHtml;

        // 在容器中渲染 React Flow
        const containerElement = document.getElementById('relationGraphContainer');
        if (containerElement && window.ReactFlow) {
            // 清空容器並銷毀可能存在的舊 root
            if (window._fullGraphRoot) {
                try {
                    window._fullGraphRoot.unmount();
                } catch (e) {
                    console.warn('Unmount failed, continuing...', e);
                }
                window._fullGraphRoot = null;
            }
            
            // 使用一個簡單的 React 函數組件渲染 React Flow
            const GraphComponent = () => {
                const [rNodes, setRNodes, onNodesChange] = window.ReactFlow.useNodesState(graphNodes);
                const [rEdges, setREdges, onEdgesChange] = window.ReactFlow.useEdgesState(graphEdges);
                const flowInstanceRef = React.useRef(null);

                // Create memoized handleWheel function outside of useEffect
                const handleWheelGraph = React.useCallback((event) => {
                    const isCtrlPressed = event.ctrlKey || event.getModifierState?.('Control');
                    if (!isCtrlPressed) {
                        return;
                    }
                    event.preventDefault();
                    event.stopPropagation();
                    const instance = flowInstanceRef.current;
                    if (!instance) {
                        return;
                    }
                    const zoomDelta = event.deltaY < 0 ? 0.2 : -0.2;
                    try {
                        instance.zoomBy?.(zoomDelta, { duration: 150 });
                    } catch (_) {
                        const currentZoom = instance.getZoom?.() ?? 1;
                        const nextZoom = Math.min(2, Math.max(0.2, currentZoom + zoomDelta));
                        instance.zoomTo?.(nextZoom, { duration: 150 });
                    }
                }, []);

                React.useEffect(() => {
                    if (!containerElement) {
                        return;
                    }

                    containerElement.addEventListener('wheel', handleWheelGraph, { passive: false });
                    return () => containerElement.removeEventListener('wheel', handleWheelGraph);
                }, [handleWheelGraph]);
                
                // Node click handler for properties panel
                const onNodeClick = React.useCallback((event, node) => {
                    const content = document.getElementById('fullRelationNodeProperties');
                    if (!content) return;
                    
                    const data = node.data;
                    
                    // Build aggregated tickets section
                    const aggregatedTicketsHtml = data.aggregatedTickets && data.aggregatedTickets.length > 0
                        ? `<div class="mb-3">
                                <label class="form-label small fw-bold">聚合 Tickets (含子節點)</label>
                                <div class="alert alert-warning p-2 small" style="word-break: break-word;">
                                    ${escapeHtml(data.aggregatedTickets.join(', '))}
                                </div>
                            </div>`
                        : '';
                    
                    // 在完整關係圖的右側面板中不顯示相關節點，以避免與跨地圖節點列表重複
                    const relatedNodesHtml = '';
                    
                    // Build main HTML matching main view layout
                    let html = `
                        <div class="node-properties-content">
                            <div class="mb-3">
                                <label class="form-label small fw-bold">標題</label>
                                <p class="form-control-plaintext mb-0 small">${escapeHtml(data.title || '')}</p>
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label small fw-bold">描述</label>
                                <p class="form-control-plaintext mb-0 small" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(data.description || '')}</p>
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label small fw-bold">團隊</label>
                                <p class="form-control-plaintext mb-0 small">${data.team ? escapeHtml(data.team) : '<span class="text-muted">未設定</span>'}</p>
                            </div>
                    `;
                    
                    // Add user story fields if applicable
                    if (data.nodeType === 'user_story') {
                        html += `
                            <div class="mb-3">
                                <label class="form-label small fw-bold">As a <small class="text-muted">(使用者角色)</small></label>
                                <p class="form-control-plaintext mb-0 small">${escapeHtml(data.as_a || data.asA || '')}</p>
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label small fw-bold">I want <small class="text-muted">(需求描述)</small></label>
                                <p class="form-control-plaintext mb-0 small" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(data.i_want || data.iWant || '')}</p>
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label small fw-bold">So that <small class="text-muted">(價值目的)</small></label>
                                <p class="form-control-plaintext mb-0 small" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(data.so_that || data.soThat || '')}</p>
                            </div>
                        `;
                    }
                    
                    html += `
                            <div class="mb-3">
                                <label class="form-label small fw-bold">JIRA Tickets</label>
                                <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                                    ${data.jiraTickets && data.jiraTickets.length > 0 ? data.jiraTickets.map(ticket => `<span class="jira-badge">${escapeHtml(ticket)}</span>`).join('') : '<small class="text-muted">無</small>'}
                                </div>
                            </div>
                            
                            ${aggregatedTicketsHtml}
                            
                            ${relatedNodesHtml}
                            
                            <div class="mb-3">
                                <label class="form-label small fw-bold">註解</label>
                                <p class="form-control-plaintext mb-0 small" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(data.comment || '')}</p>
                            </div>
                        </div>
                    `;
                    
                    content.innerHTML = html;
                    
                    // Add event listeners for related node popup buttons
                    document.querySelectorAll('[data-related-popup-idx]').forEach((btn) => {
                        btn.addEventListener('click', (e) => {
                            e.stopPropagation();
                            const idx = parseInt(btn.getAttribute('data-related-popup-idx'));
                            const relatedNode = data.relatedIds?.[idx];
                            
                            if (!relatedNode || typeof relatedNode === 'string') return;
                            
                            const mapId = relatedNode.map_id || relatedNode.mapId;
                            const teamId = relatedNode.team_id || relatedNode.teamId;
                            
                            if (!mapId || !teamId) {
                                showMessage('無法開啟外部地圖：缺少必要的資訊', 'error');
                                return;
                            }
                            
                            // Open in popup window
                            const popupUrl = `/user-story-map-popup?mapId=${mapId}&teamId=${teamId}`;
                            const popupWindow = window.open(popupUrl, 'usm-popup', 'width=1200,height=800,resizable=yes,scrollbars=yes');
                            
                            if (popupWindow) {
                                showMessage(`已在新視窗開啟 "${relatedNode.map_name || `地圖 ${mapId}`}" 地圖`, 'success');
                            } else {
                                showMessage('無法開啟新視窗，請檢查瀏覽器設定', 'error');
                            }
                        });
                    });
                }, []);
                
                return React.createElement(
                    window.ReactFlow.ReactFlowProvider,
                    null,
                    React.createElement(
                        window.ReactFlow.ReactFlow,
                        {
                            nodes: rNodes,
                            edges: rEdges,
                            onNodesChange,
                            onEdgesChange,
                            onNodeClick: onNodeClick, // Add node click handler
                            nodeTypes: nodeTypes,
                            defaultEdgeOptions: { type: 'smoothstep' },
                            fitView: true,
                            nodesConnectable: false,
                            edgesUpdatable: false,
                            connectOnClick: false,
                            zoomOnScroll: false,
                            panOnScroll: true,
                            panOnScrollSpeed: 0.8,
                            onInit: (instance) => { flowInstanceRef.current = instance; },
                            style: { width: '100%', height: '100%' }
                        }
                    )
                );
            };
            
            // 創建新的 root 並渲染
            window._fullGraphRoot = ReactDOM.createRoot(containerElement);
            window._fullGraphRoot.render(React.createElement(GraphComponent));
        }

        // 打開 Modal
        const modalElement = document.getElementById('fullRelationGraphModal');
        if (modalElement) {
            modalElement.style.display = 'block';
            modalElement.style.position = 'fixed';
            modalElement.style.zIndex = '1060';
            
            document.querySelectorAll('.modal-backdrop').forEach(bd => bd.remove());
            
            const modal = new bootstrap.Modal(modalElement, {
                backdrop: 'static',
                keyboard: false
            });
            modal.show();
        }
    }, [nodes, nodeTypes, currentMapId]);

    const focusNode = useCallback((nodeId, highlightNodeIds = []) => {
        if (!nodeId) {
            return;
        }

        const instance = reactFlowInstance.current;
        const targetNode = nodesRef.current.find((node) => node.id === nodeId);

        if (!instance || !targetNode) {
            showMessage('找不到指定節點，請重新載入地圖', 'error');
            return;
        }

        // 更新 React Flow 的選取狀態
        setNodes((nds) => {
            const updated = nds.map((node) => ({
                ...node,
                selected: node.id === nodeId,
            }));
            nodesRef.current = updated;
            return updated;
        });

        // 將視窗平移至節點附近（維持現有縮放）
        if (instance.setCenter) {
            const { x, y } = targetNode.position;
            instance.setCenter(x + (targetNode.width || 0) / 2, y + (targetNode.height || 0) / 2, {
                zoom: instance.getZoom?.() ?? undefined,
                duration: 300,
            });
        }

        setSelectedNode(targetNode);
        updateNodeProperties(targetNode);

        const highlightIds = Array.isArray(highlightNodeIds) && highlightNodeIds.length
            ? new Set(highlightNodeIds)
            : null;

        if (highlightIds) {
            setTimeout(() => {
                highlightIds.forEach((id) => {
                    const nodeElement = document.querySelector(`[data-id="${id}"]`);
                    if (nodeElement) {
                        nodeElement.style.boxShadow = '0 0 20px 5px #ffc107';
                    }
                });
            }, 120);
        }
    }, [setNodes, setSelectedNode, updateNodeProperties]);

    // Auto layout
    const autoLayout = useCallback(() => {
        if (!hasUsmAccess('nodeAdd')) {
            showMessage('您沒有權限調整地圖排版', 'error');
            return;
        }
        const layoutedNodes = applyTreeLayout(nodes, edges);
        nodesRef.current = layoutedNodes;
        setNodes(layoutedNodes);
        setTimeout(() => {
            reactFlowInstance.current?.fitView({ padding: 0.2 });
        }, 0);
    }, [nodes, edges, setNodes, applyTreeLayout]);

    // Collapse all parent nodes that have User Story children
    const collapseUserStoryNodes = useCallback(() => {
        setCollapsedNodeIds((prev) => {
            const next = new Set(prev);
            // Find all nodes that have User Story children and add them to collapsed set
            nodes.forEach(node => {
                if (Array.isArray(node.data.childrenIds) && node.data.childrenIds.length > 0) {
                    // Check if any children are User Story nodes
                    const hasUserStoryChild = node.data.childrenIds.some(childId => {
                        const childNode = nodes.find(n => n.id === childId);
                        return childNode && childNode.data.nodeType === 'user_story';
                    });
                    
                    if (hasUserStoryChild) {
                        next.add(node.id);
                    }
                }
            });
            return next;
        });
    }, [nodes, setCollapsedNodeIds]);

    // Expand all nodes (clear all collapsed nodes)
    const expandAllNodes = useCallback(() => {
        setCollapsedNodeIds(new Set());
    }, [setCollapsedNodeIds]);

    // Delete node
    const deleteNode = (nodeId) => {
        if (!hasUsmAccess('nodeDelete')) {
            showMessage('您沒有權限刪除節點', 'error');
            return;
        }
        if (confirm('確定要刪除此節點嗎？')) {
            let remainingIds = new Set();
            setNodes((nds) => {
                const updated = nds
                    .filter((node) => node.id !== nodeId)
                    .map((node) => {
                        if (node.data.childrenIds?.includes(nodeId)) {
                            return {
                                ...node,
                                data: {
                                    ...node.data,
                                    childrenIds: node.data.childrenIds.filter((id) => id !== nodeId),
                                },
                            };
                        }
                        return node;
                    });
                remainingIds = new Set(updated.map((node) => node.id));
                nodesRef.current = updated;
                return updated;
            });
            setEdges((eds) => eds.filter((edge) => edge.source !== nodeId && edge.target !== nodeId));
            setSelectedNode(null);
            document.getElementById('nodeProperties').innerHTML = '<p class="text-muted small">選擇一個節點以查看和編輯屬性</p>';
            setCollapsedNodeIds((prev) => {
                const next = new Set();
                remainingIds.forEach((id) => {
                    if (prev.has(id)) {
                        next.add(id);
                    }
                });
                return next;
            });
            setTimeout(() => {
                window.userStoryMapFlow?.saveMap?.(true);
            }, 0);
            showMessage('節點已刪除', 'success');
        }
    };

    // Initialize
    useEffect(() => {
        loadMaps();
    }, [loadMaps]);

    useEffect(() => {
        loadTeamInfo();
    }, [loadTeamInfo]);

    // Auto-load first map when maps are loaded and no map is selected
    // Or load specific map if provided in URL
    useEffect(() => {
        if (maps.length > 0) {
            if (mapIdFromUrl && !currentMapId) {
                // If mapId is provided in URL, try to load that specific map
                const targetMap = maps.find(map => map.id === mapIdFromUrl);
                if (targetMap) {
                    const select = document.getElementById('currentMapSelect');
                    if (select) {
                        select.value = targetMap.id;
                        loadMap(targetMap.id);
                    }
                } else {
                    // If specified mapId doesn't exist, fall back to loading first map
                    const firstMapId = maps[0].id;
                    const select = document.getElementById('currentMapSelect');
                    if (select) {
                        select.value = firstMapId;
                        loadMap(firstMapId);
                    }
                }
            } else if (!currentMapId) {
                // If no mapId in URL, load first map as usual
                const select = document.getElementById('currentMapSelect');
                if (select && !select.value) {
                    const firstMapId = maps[0].id;
                    select.value = firstMapId;
                    loadMap(firstMapId);
                }
            }
        }
    }, [maps, currentMapId, loadMap]);

    useEffect(() => {
        if (!teamName) {
            return;
        }
        setNodes((nds) => {
            const updated = nds.map((node) => ({
                ...node,
                data: {
                    ...node.data,
                    team: teamName,
                },
            }));
            nodesRef.current = updated;
            return updated;
        });
    }, [teamName, setNodes]);

    useEffect(() => {
        const teamLabel = document.getElementById('nodeTeamDisplay');
        if (teamLabel) {
            teamLabel.textContent = teamName || '載入中…';
        }
    }, [teamName]);

    useEffect(() => {
        const currentNodes = nodesRef.current;
        if (!currentNodes.length) {
            return;
        }

        const nodeMap = new Map(currentNodes.map((node) => [node.id, node]));
        const hiddenStatus = new Map();

        const shouldHide = (nodeId) => {
            let parentId = nodeMap.get(nodeId)?.data?.parentId || null;
            while (parentId) {
                if (collapsedNodeIds.has(parentId)) {
                    return true;
                }
                parentId = nodeMap.get(parentId)?.data?.parentId || null;
            }
            return false;
        };

        const updatedNodes = currentNodes.map((node) => {
            const collapsed = collapsedNodeIds.has(node.id);
            const hidden = node.data.parentId ? shouldHide(node.id) : false;
            hiddenStatus.set(node.id, hidden);
            return {
                ...node,
                hidden,
                data: {
                    ...node.data,
                    collapsed,
                    toggleCollapse: toggleNodeCollapse,
                },
            };
        });

        // 重新應用佈局以適應收合/展開的節點
        const layoutedNodes = applyLayoutWithCollapsedNodes(updatedNodes, edges, collapsedNodeIds);

        nodesRef.current = layoutedNodes;
        setNodes(layoutedNodes);
        setEdges((eds) =>
            eds.map((edge) => {
                const hidden = hiddenStatus.get(edge.source) || hiddenStatus.get(edge.target);
                return hidden === edge.hidden ? edge : { ...edge, hidden };
            })
        );

        if (selectedNode) {
            const isHidden = hiddenStatus.get(selectedNode.id);
            if (isHidden) {
                setSelectedNode(null);
                const container = document.getElementById('nodeProperties');
                if (container) {
                    container.innerHTML = '<p class="text-muted small">選擇一個節點以查看和編輯屬性</p>';
                }
            } else {
                const refreshed = layoutedNodes.find((node) => node.id === selectedNode.id);
                if (refreshed && refreshed !== selectedNode) {
                    setSelectedNode(refreshed);
                    updateNodeProperties(refreshed);
                }
            }
        }
    }, [collapsedNodeIds, setNodes, setEdges, toggleNodeCollapse, setSelectedNode, applyLayoutWithCollapsedNodes, edges]);

    useEffect(() => {
        if (selectedNode) {
            updateNodeProperties(selectedNode);
        }
    }, [selectedNode]);

    // Setup global event delegation for related node buttons (mount once only)
    useEffect(() => {
        const handleRelatedNodeClick = (e) => {
            const navBtn = e.target.closest('[data-related-idx]');
            if (!navBtn) return;
            
            const container = document.getElementById('nodeProperties');
            if (!container?.contains(navBtn)) return;
            
            const idx = parseInt(navBtn.getAttribute('data-related-idx'));
            
            // Get the most current selectedNode from window or state
            const currentSelected = window.userStoryMapFlow?.getSelectedNode?.();
            if (!currentSelected?.data?.relatedIds) return;
            
            const relatedNode = currentSelected.data.relatedIds[idx];
            if (!relatedNode) return;
            
            let nodeId, mapId;
            
            if (typeof relatedNode === 'string') {
                nodeId = relatedNode;
                mapId = window.currentMapId;
            } else if (typeof relatedNode === 'object') {
                nodeId = relatedNode.node_id || relatedNode.nodeId;
                mapId = relatedNode.map_id || relatedNode.mapId;
            } else {
                return;
            }
            
            if (!nodeId) return;
            
            const isCrossMap = mapId && String(mapId) !== String(window.currentMapId);
            
            if (isCrossMap) {
                showMessage('外部節點，請使用「開啟」按鈕在彈出視窗中查看', 'info');
                return;
            }
            
            window.userStoryMapFlow?.focusNode?.(nodeId);
            showMessage(`已聚焦節點: ${relatedNode.display_title || nodeId}`, 'info');
        };

        const handlePopupClick = (e) => {
            const popupBtn = e.target.closest('[data-related-popup-idx]');
            if (!popupBtn) return;
            
            const container = document.getElementById('nodeProperties');
            if (!container?.contains(popupBtn)) return;
            
            e.stopPropagation();
            const idx = parseInt(popupBtn.getAttribute('data-related-popup-idx'));
            
            // Get the most current selectedNode from window
            const currentSelected = window.userStoryMapFlow?.getSelectedNode?.();
            if (!currentSelected?.data?.relatedIds) return;
            
            const relatedNode = currentSelected.data.relatedIds[idx];
            if (!relatedNode || typeof relatedNode === 'string') return;
            
            const mapId = relatedNode.map_id || relatedNode.mapId;
            const teamId = relatedNode.team_id || relatedNode.teamId;
            
            if (!mapId || !teamId) {
                showMessage('無法開啟外部地圖：缺少必要的資訊', 'error');
                return;
            }
            
            const popupUrl = `/user-story-map-popup?mapId=${mapId}&teamId=${teamId}`;
            const popupWindow = window.open(popupUrl, 'usm-popup', 'width=1200,height=800,resizable=yes,scrollbars=yes');
            
            if (popupWindow) {
                showMessage(`已在新視窗開啟 "${relatedNode.map_name || `地圖 ${mapId}`}" 地圖`, 'success');
            } else {
                showMessage('無法開啟新視窗，請檢查瀏覽器設定', 'error');
            }
        };

        const container = document.getElementById('nodeProperties');
        if (!container) return;

        container.addEventListener('click', handleRelatedNodeClick);
        container.addEventListener('click', handlePopupClick);

        return () => {
            container.removeEventListener('click', handleRelatedNodeClick);
            container.removeEventListener('click', handlePopupClick);
        };
    }, []);

    // Expose functions to window for button handlers
    useEffect(() => {
        window.userStoryMapFlow = {
            saveMap,
            addNode,
            loadMap,
            loadMaps,
            fitView: () => reactFlowInstance.current?.fitView(),
            zoomIn: () => reactFlowInstance.current?.zoomIn(),
            zoomOut: () => reactFlowInstance.current?.zoomOut(),
            autoLayout,
            highlightPath,
            clearHighlight,
            focusNode,
            getSelectedNode: () => selectedNode,
            getSelectedNodeIds: () => nodes.filter(n => n.selected).map(n => n.id),
            getNodes: () => nodes,
            getTeamName: () => teamName,
            setNodes,
            setEdges,
        };
        window.currentMapId = currentMapId;
        window.teamId = teamId;
        window.mapIdFromUrl = mapIdFromUrl;
        window.addChildNode = addChildNode;
        window.addSiblingNode = addSiblingNode;
        window.showFullRelationGraph = showFullRelationGraph;
    }, [saveMap, addNode, loadMap, loadMaps, autoLayout, highlightPath, clearHighlight, focusNode, selectedNode, addChildNode, addSiblingNode, setNodes, setEdges, teamName, showFullRelationGraph, currentMapId, teamId, mapIdFromUrl, collapseUserStoryNodes, expandAllNodes]);

    // Expose new functions to window for button handlers
    useEffect(() => {
        if (window.userStoryMapFlow) {
            window.userStoryMapFlow.collapseUserStoryNodes = collapseUserStoryNodes;
            window.userStoryMapFlow.expandAllNodes = expandAllNodes;
        }
    }, [collapseUserStoryNodes, expandAllNodes]);

    // MiniMap node color function
    const getNodeColor = (node) => {
        const nodeTypeColors = {
            root: '#6f42c1', // Purple
            feature_category: '#87ceeb', // Light blue
            user_story: '#dda0dd', // Plum (light purple)
        };
        return nodeTypeColors[node.data.nodeType] || '#0d6efd';
    };

    return React.createElement(
        ReactFlow,
        {
            nodes: nodes,
            edges: edges,
            onNodesChange: onNodesChange,
            onEdgesChange: onEdgesChange,
            onConnect: onConnect,
            onNodeClick: onNodeClick,
            onInit: (instance) => { reactFlowInstance.current = instance; },
            nodeTypes: nodeTypes,
            fitView: true,
            nodesConnectable: false,
            edgesUpdatable: false,
            connectOnClick: false,
            zoomOnScroll: false,
            panOnScroll: true,
            panOnScrollSpeed: 0.8,
        },
        React.createElement(Background, { variant: BackgroundVariant.Dots }),
        React.createElement(MiniMap, { nodeColor: getNodeColor })
    );
};

// Render the app
function initUserStoryMap() {
    const container = document.getElementById('reactFlowWrapper');
    const root = ReactDOM.createRoot(container);
    
    root.render(
        React.createElement(ReactFlowProvider, null,
            React.createElement(UserStoryMapFlow, null)
        )
    );
}

// Helper function for messages
function showMessage(message, type = 'info') {
    const alertClass = type === 'success' ? 'alert-success' : type === 'error' ? 'alert-danger' : 'alert-info';
    const alert = document.createElement('div');
    alert.className = `alert ${alertClass} alert-dismissible fade show`;
    alert.innerHTML = `
        ${escapeHtml(message)}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.getElementById('flash-messages').appendChild(alert);
    setTimeout(() => alert.remove(), 3000);
}

// Event handlers
document.addEventListener('DOMContentLoaded', async function() {
    await applyUsmPermissions();
    initUserStoryMap();

    const mapListModalElement = document.getElementById('mapListModal');
    const mapListContainer = document.getElementById('mapListContainer');
    const editMapModalElement = document.getElementById('editMapModal');
    const editMapIdInput = document.getElementById('editMapId');
    const editMapNameInput = document.getElementById('editMapName');
    const editMapDescriptionInput = document.getElementById('editMapDescription');
    let mapListModalInstance = null;
    let editMapModalInstance = null;

    const ensureSingleModalBackdrop = () => {
        const backdrops = Array.from(document.querySelectorAll('.modal-backdrop'));
        if (!backdrops.length) {
            return;
        }
        backdrops.forEach((backdrop, index) => {
            if (index === 0) {
                backdrop.style.opacity = '';
                return;
            }
            backdrop.remove();
        });
    };

    const handleModalHidden = () => {
        setTimeout(() => {
            if (!document.querySelector('.modal.show')) {
                document.body.classList.remove('modal-open');
                document.body.style.removeProperty('padding-right');
                document.body.style.removeProperty('paddingRight');
                document.querySelectorAll('.modal-backdrop').forEach((backdrop) => backdrop.remove());
                return;
            }
            ensureSingleModalBackdrop();
        }, 0);
    };

    document.querySelectorAll('.modal').forEach((modalEl) => {
        modalEl.addEventListener('shown.bs.modal', ensureSingleModalBackdrop);
        modalEl.addEventListener('hidden.bs.modal', handleModalHidden);
    });

    const openEditMapModal = (mapId, mapName, mapDescription) => {
        if (!editMapModalElement) {
            return;
        }
        if (editMapIdInput) {
            editMapIdInput.value = mapId;
        }
        if (editMapNameInput) {
            editMapNameInput.value = mapName;
        }
        if (editMapDescriptionInput) {
            editMapDescriptionInput.value = mapDescription;
        }
        editMapModalInstance = bootstrap.Modal.getOrCreateInstance(editMapModalElement);
        editMapModalInstance.show();
    };

    const renderMapList = (maps) => {
        if (!mapListContainer) {
            return;
        }

        if (!maps || maps.length === 0) {
            mapListContainer.innerHTML = '<p class="text-muted text-center">尚無地圖</p>';
            return;
        }

        const itemsHtml = maps.map(map => {
            const editBtn = hasUsmAccess('mapUpdate')
                ? `<button class="btn btn-primary edit-map-btn" data-map-id="${map.id}" data-map-name="${escapeHtml(map.name)}" data-map-description="${escapeHtml(map.description || '')}">
                        <i class="fas fa-pen"></i>
                   </button>`
                : '';
            const deleteBtn = hasUsmAccess('mapDelete')
                ? `<button class="btn btn-danger delete-map-btn" data-map-id="${map.id}" data-map-name="${escapeHtml(map.name)}">
                        <i class="fas fa-trash"></i>
                   </button>`
                : '';
            const actionButtons = editBtn || deleteBtn
                ? `<div class="btn-group btn-group-sm" role="group">${editBtn}${deleteBtn}</div>`
                : '';

            return `
                <a href="#" class="list-group-item list-group-item-action" data-map-id="${map.id}">
                    <div class="d-flex w-100 justify-content-between align-items-start">
                        <div class="me-3">
                            <h6 class="mb-1">${escapeHtml(map.name)}</h6>
                            ${map.description ? `<p class="mb-1 small">${escapeHtml(map.description)}</p>` : '<p class="mb-1 small text-muted fst-italic">尚未設定描述</p>'}
                            <small class="text-muted">${map.nodes.length} 個節點</small>
                        </div>
                        <div class="d-flex flex-column gap-2 align-items-end">
                            ${actionButtons}
                            <small class="text-muted">更新: ${new Date(map.updated_at).toLocaleString()}</small>
                        </div>
                    </div>
                </a>
            `;
        }).join('');

        mapListContainer.innerHTML = `<div class="list-group">${itemsHtml}</div>`;

        mapListContainer.querySelectorAll('.list-group-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const mapId = parseInt(item.dataset.mapId);
                if (!mapId) {
                    return;
                }
                window.userStoryMapFlow?.loadMap(mapId);
                const select = document.getElementById('currentMapSelect');
                if (select) {
                    select.value = mapId;
                }
                mapListModalInstance?.hide();
            });
        });

        if (hasUsmAccess('mapUpdate')) {
            mapListContainer.querySelectorAll('.edit-map-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const mapId = parseInt(btn.dataset.mapId);
                    if (!mapId) {
                        return;
                    }
                    const mapName = btn.dataset.mapName || '';
                    const mapDescription = btn.dataset.mapDescription || '';
                    openEditMapModal(mapId, mapName, mapDescription);
                });
            });
        }

        if (hasUsmAccess('mapDelete')) {
            mapListContainer.querySelectorAll('.delete-map-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const mapId = parseInt(btn.dataset.mapId);
                    const mapName = btn.dataset.mapName;

                    if (!mapId) {
                        return;
                    }

                    if (!confirm(`確定要刪除地圖「${mapName}」嗎？此操作無法復原。`)) {
                        return;
                    }

                    try {
                        const response = await fetch(`/api/user-story-maps/${mapId}`, {
                            method: 'DELETE',
                            headers: {
                                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                            },
                        });

                        if (response.ok) {
                            showMessage('地圖已刪除', 'success');

                            const currentSelect = document.getElementById('currentMapSelect');
                            const currentMapId = parseInt(currentSelect?.value);
                            if (currentMapId === mapId) {
                                window.userStoryMapFlow?.setNodes([]);
                                window.userStoryMapFlow?.setEdges([]);
                                if (currentSelect) {
                                    currentSelect.value = '';
                                }
                            }

                            await window.userStoryMapFlow?.loadMaps?.();
                            await loadMapList();
                        } else {
                            showMessage('刪除失敗', 'error');
                        }
                    } catch (error) {
                        console.error('Failed to delete map:', error);
                        showMessage('刪除失敗', 'error');
                    }
                });
            });
        }
    };

    const loadMapList = async () => {
        if (!mapListContainer) {
            return;
        }
        mapListContainer.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';

        try {
            const response = await fetch(`/api/user-story-maps/team/${teamId}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
            });

            if (response.ok) {
                const maps = await response.json();
                renderMapList(maps);
            } else {
                mapListContainer.innerHTML = '<p class="text-danger text-center">載入失敗</p>';
            }
        } catch (error) {
            console.error('Failed to load maps:', error);
            mapListContainer.innerHTML = '<p class="text-danger text-center">載入失敗</p>';
        }
    };

    document.getElementById('saveMapEditBtn')?.addEventListener('click', async () => {
        if (!hasUsmAccess('mapUpdate')) {
            showMessage('您沒有權限編輯地圖', 'error');
            return;
        }
        const mapId = parseInt(editMapIdInput?.value);
        if (!mapId) {
            return;
        }

        const newName = (editMapNameInput?.value || '').trim();
        if (!newName) {
            alert('請輸入地圖名稱');
            return;
        }
        const newDescription = (editMapDescriptionInput?.value || '').trim();

        try {
            const response = await fetch(`/api/user-story-maps/${mapId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
                body: JSON.stringify({
                    name: newName,
                    description: newDescription,
                }),
            });

            if (response.ok) {
                showMessage('地圖已更新', 'success');
                if (editMapModalElement) {
                    editMapModalInstance = bootstrap.Modal.getOrCreateInstance(editMapModalElement);
                    editMapModalInstance.hide();
                }

                await loadMapList();

                if (window.userStoryMapFlow?.loadMaps) {
                    await window.userStoryMapFlow.loadMaps();
                }

                const currentSelect = document.getElementById('currentMapSelect');
                if (parseInt(currentSelect?.value) === mapId) {
                    window.userStoryMapFlow?.loadMap(mapId);
                    if (currentSelect) {
                        currentSelect.value = mapId;
                    }
                }
            } else {
                showMessage('更新失敗', 'error');
            }
        } catch (error) {
            console.error('Failed to update map:', error);
            showMessage('更新失敗', 'error');
        }
    });

    // Save button
    document.getElementById('saveMapBtn')?.addEventListener('click', () => {
        if (!hasUsmAccess('mapUpdate')) {
            showMessage('您沒有權限儲存此地圖', 'error');
            return;
        }
        window.userStoryMapFlow?.saveMap();
    });

    // Calculate tickets button
    document.getElementById('calcTicketsBtn')?.addEventListener('click', async () => {
        if (!hasUsmAccess('mapUpdate')) {
            showMessage('您沒有權限更新聚合票證', 'error');
            return;
        }
        const mapId = document.getElementById('currentMapSelect')?.value;
        if (!mapId) {
            alert('請先選擇一個地圖');
            return;
        }

        try {
            const response = await fetch(`/api/user-story-maps/${mapId}/calculate-aggregated-tickets`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
            });

            if (response.ok) {
                showMessage('已計算聚合票證', 'success');
                // Reload map to get updated data
                window.userStoryMapFlow?.loadMap(parseInt(mapId));
            } else {
                showMessage('計算失敗', 'error');
            }
        } catch (error) {
            console.error('Failed to calculate tickets:', error);
            showMessage('計算失敗', 'error');
        }
    });

    // New map button
    document.getElementById('newMapBtn')?.addEventListener('click', () => {
        if (!hasUsmAccess('mapCreate')) {
            showMessage('您沒有權限建立地圖', 'error');
            return;
        }
        const modal = new bootstrap.Modal(document.getElementById('newMapModal'));
        modal.show();
    });

    // Create map
    document.getElementById('createMapBtn')?.addEventListener('click', async () => {
        if (!hasUsmAccess('mapCreate')) {
            showMessage('您沒有權限建立地圖', 'error');
            return;
        }
        const name = document.getElementById('mapName')?.value;
        const description = document.getElementById('mapDescription')?.value;

        if (!name) {
            alert('請輸入地圖名稱');
            return;
        }

        try {
            const response = await fetch('/api/user-story-maps/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
                body: JSON.stringify({
                    team_id: teamId,
                    name: name,
                    description: description,
                }),
            });

            if (response.ok) {
                const map = await response.json();
                showMessage('地圖已建立', 'success');
                bootstrap.Modal.getInstance(document.getElementById('newMapModal')).hide();
                window.userStoryMapFlow?.loadMaps();
                window.userStoryMapFlow?.loadMap(map.id);
            } else {
                showMessage('建立失敗', 'error');
            }
        } catch (error) {
            console.error('Failed to create map:', error);
            showMessage('建立失敗', 'error');
        }
    });

    // Map selection change
    document.getElementById('currentMapSelect')?.addEventListener('change', (e) => {
        const mapId = e.target.value;
        if (mapId) {
            window.userStoryMapFlow?.loadMap(parseInt(mapId));
        }
    });

    // Node type change - show/hide BDD fields
    document.getElementById('nodeType')?.addEventListener('change', (e) => {
        const bddFields = document.getElementById('bddFields');
        if (bddFields) {
            bddFields.style.display = e.target.value === 'user_story' ? 'block' : 'none';
        }
    });

    // Confirm add node
    document.getElementById('confirmAddNodeBtn')?.addEventListener('click', () => {
        if (!hasUsmAccess('nodeAdd')) {
            showMessage('您沒有權限新增節點', 'error');
            return;
        }
        const title = document.getElementById('nodeTitle')?.value;
        const description = document.getElementById('nodeDescription')?.value;
        const nodeType = document.getElementById('nodeType')?.value;
        const jiraText = document.getElementById('nodeJira')?.value;
        const asA = document.getElementById('nodeAsA')?.value;
        const iWant = document.getElementById('nodeIWant')?.value;
        const soThat = document.getElementById('nodeSoThat')?.value;

        if (!title) {
            alert('請輸入標題');
            return;
        }

        if (!nodeType) {
            alert('請選擇節點類型');
            return;
        }

        const jiraTickets = jiraText ? jiraText.split(',').map(t => t.trim()).filter(t => t) : [];
        const parentId = window._tempParentId || null;
        const level = parentId ? (window._tempParentLevel || 0) + 1 : 0;
        window.userStoryMapFlow?.addNode({
            title,
            description,
            nodeType,
            jiraTickets,
            parentId,
            level,
            as_a: asA,
            i_want: iWant,
            so_that: soThat,
        });

        bootstrap.Modal.getInstance(document.getElementById('addNodeModal')).hide();
        document.getElementById('addNodeForm')?.reset();
        const teamLabel = document.getElementById('nodeTeamDisplay');
        if (teamLabel) {
            const name = window.userStoryMapFlow?.getTeamName?.();
            teamLabel.textContent = name || '載入中…';
        }

        // Clear temp variables
        window._tempParentId = null;
        window._tempParentLevel = null;
        
        window.userStoryMapFlow?.saveMap?.(true);
    });

    // Add child node (toolbar)
    document.getElementById('addChildBtn')?.addEventListener('click', () => {
        if (!hasUsmAccess('nodeAdd')) {
            showMessage('您沒有權限新增節點', 'error');
            return;
        }
        const selectedNode = window.userStoryMapFlow?.getSelectedNode();
        if (!selectedNode) {
            alert('請先選擇一個節點');
            return;
        }
        if (window.addChildNode) {
            window.addChildNode(selectedNode.id);
        }
    });

    // Add sibling node (toolbar)
    document.getElementById('addSiblingBtn')?.addEventListener('click', () => {
        if (!hasUsmAccess('nodeAdd')) {
            showMessage('您沒有權限新增節點', 'error');
            return;
        }
        const selectedNode = window.userStoryMapFlow?.getSelectedNode();
        if (!selectedNode) {
            alert('請先選擇一個節點');
            return;
        }
        if (window.addSiblingNode) {
            window.addSiblingNode(selectedNode.id);
        }
    });

    // Auto layout button
    document.getElementById('autoLayoutBtn')?.addEventListener('click', () => {
        if (!hasUsmAccess('nodeAdd')) {
            showMessage('您沒有權限調整地圖排版', 'error');
            return;
        }
        window.userStoryMapFlow?.autoLayout();
        showMessage('已套用樹狀排版', 'success');
    });

    // Collapse User Story nodes button
    document.getElementById('collapseUserStoryNodesBtn')?.addEventListener('click', () => {
        window.userStoryMapFlow?.collapseUserStoryNodes();
        showMessage('已收合所有 User Story 節點', 'success');
    });

    // Expand all nodes button
    document.getElementById('expandAllNodesBtn')?.addEventListener('click', () => {
        window.userStoryMapFlow?.expandAllNodes();
        showMessage('已展開所有節點', 'success');
    });

    // Highlight path button
    document.getElementById('highlightPathBtn')?.addEventListener('click', (event) => {
        const selectedNode = window.userStoryMapFlow?.getSelectedNode();
        const isMultiSelect = event.ctrlKey || event.metaKey;
        if (selectedNode) {
            window.userStoryMapFlow?.highlightPath(selectedNode.id, isMultiSelect);
        } else {
            alert('請先選擇一個節點');
        }
    });

    // Clear highlight button
    document.getElementById('clearHighlightBtn')?.addEventListener('click', () => {
        window.userStoryMapFlow?.clearHighlight();
    });

    // Map list button
    document.getElementById('mapListBtn')?.addEventListener('click', () => {
        if (!mapListModalElement) {
            return;
        }
        mapListModalInstance = bootstrap.Modal.getOrCreateInstance(mapListModalElement);
        mapListModalInstance.show();
        loadMapList();
    });

    // Search button
    document.getElementById('searchBtn')?.addEventListener('click', () => {
        const modal = new bootstrap.Modal(document.getElementById('searchModal'));
        modal.show();
    });

    // Clear search
    document.getElementById('clearSearchBtn')?.addEventListener('click', () => {
        const searchInput = document.getElementById('searchInput');
        const searchResults = document.getElementById('searchResults');
        const searchNodeType = document.getElementById('searchNodeType');

        if (searchInput) {
            searchInput.value = '';
        }

        if (searchNodeType) {
            searchNodeType.value = '';
        }

        if (searchResults) {
            searchResults.innerHTML = '<p class="text-muted small">輸入搜尋條件並點擊搜尋</p>';
        }

        // Clear highlights
        window.userStoryMapFlow?.clearHighlight();

        // Remove box shadows from nodes
        const nodeElements = document.querySelectorAll('[data-id]');
        nodeElements.forEach(nodeEl => {
            nodeEl.style.boxShadow = '';
        });
    });

    // Perform search
    document.getElementById('performSearchBtn')?.addEventListener('click', async () => {
        const mapId = document.getElementById('currentMapSelect')?.value;
        if (!mapId) {
            alert('請先選擇一個地圖');
            return;
        }

        const query = document.getElementById('searchInput')?.value;
        const nodeTypeFilter = document.getElementById('searchNodeType')?.value;
        const jiraTickets = document.getElementById('searchJiraTickets')?.value;
        const jiraLogic = document.querySelector('input[name="jiraLogic"]:checked')?.value || 'or';

        const params = new URLSearchParams();
        if (query) params.append('q', query);
        if (nodeTypeFilter) params.append('node_type', nodeTypeFilter);

        try {
            const response = await fetch(`/api/user-story-maps/${mapId}/search?${params}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
            });

            if (response.ok) {
                let results = await response.json();
                const container = document.getElementById('searchResults');

                // 前端 JIRA 過濾
                if (jiraTickets && jiraTickets.trim()) {
                    const jiraList = jiraTickets.split(',').map(t => t.trim().toUpperCase()).filter(t => t);
                    if (jiraList.length > 0) {
                        results = results.filter(node => {
                            const nodeJira = (node.jira_tickets || []).map(t => t.toUpperCase());
                            if (jiraLogic === 'and') {
                                // AND: 需要包含所有指定的 JIRA tickets
                                return jiraList.every(ticket => nodeJira.includes(ticket));
                            } else {
                                // OR: 只需包含任一個 JIRA ticket
                                return jiraList.some(ticket => nodeJira.includes(ticket));
                            }
                        });
                    }
                }

                if (results.length === 0) {
                    container.innerHTML = '<p class="text-muted">無搜尋結果</p>';
                } else {
                    window.userStoryMapFlow?.clearHighlight();

                    // Update nodes to highlight matches
                    const reactFlowWrapper = document.querySelector('.react-flow__renderer');
                    if (reactFlowWrapper) {
                        setTimeout(() => {
                            results.forEach(result => {
                                const nodeEl = document.querySelector(`[data-id="${result.node_id}"]`);
                                if (nodeEl) {
                                    nodeEl.style.boxShadow = '0 0 20px 5px #ffc107';
                                }
                            });
                        }, 100);
                    }

                    container.innerHTML = `
                        <div class="list-group">
                            ${results.map(node => `
                                <div class="list-group-item" data-node-id="${node.node_id}">
                                    <h6 class="mb-1">${escapeHtml(node.title)}</h6>
                                    ${node.description ? `<p class="mb-1 small">${escapeHtml(node.description)}</p>` : ''}
                                    ${node.team ? `<small class="text-muted">團隊: ${escapeHtml(node.team)}</small>` : ''}
                                    ${node.jira_tickets && node.jira_tickets.length > 0 ? `<div style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.25rem;">${node.jira_tickets.map(ticket => `<span class="jira-badge">${escapeHtml(ticket)}</span>`).join('')}</div>` : ''}
                                </div>
                            `).join('')}
                        </div>
                    `;

                    const highlightIds = results.map((node) => node.node_id);

                    container.querySelectorAll('.list-group-item').forEach((item) => {
                        item.addEventListener('click', () => {
                            const nodeId = item.getAttribute('data-node-id');
                            if (nodeId) {
                                window.userStoryMapFlow?.focusNode?.(nodeId, highlightIds);
                                const modalElement = document.getElementById('searchModal');
                                const modalInstance = modalElement
                                    ? bootstrap.Modal.getInstance(modalElement)
                                    : null;
                                modalInstance?.hide();
                            }
                        });
                    });
                }
            }
        } catch (error) {
            console.error('Search failed:', error);
            showMessage('搜尋失敗', 'error');
        }
    });

    // ============ Relation Settings ============
    
    // Set Relations Button - Global function
    window.openRelationModal = function() {
        console.log('[Relation] openRelationModal called');

        if (!hasUsmAccess('nodeUpdate')) {
            showMessage('您沒有權限編輯關聯', 'error');
            console.warn('[Relation] Permission denied: nodeUpdate');
            return;
        }

        const selectedNode = window.userStoryMapFlow?.getSelectedNode();
        console.log('[Relation] Selected node:', selectedNode);

        if (!selectedNode) {
            showMessage('請先選擇一個節點', 'warning');
            console.warn('[Relation] No node selected');

            // 移除可能遺留的 Bootstrap backdrop 與樣式，避免畫面無法操作
            document.querySelectorAll('.modal-backdrop').forEach((backdrop) => backdrop.remove());
            document.body.classList.remove('modal-open');
            document.body.style.removeProperty('padding-right');
            document.body.style.removeProperty('paddingRight');

            return;
        }

        try {
            // Initialize relation modal
            window.currentRelationNode = selectedNode;
            console.log('[Relation] Setting up modal with node:', selectedNode.id);

            document.getElementById('relationSourceNodeTitle').textContent = selectedNode.data?.title || '未知節點';
            document.getElementById('relationSourceNodeId').textContent = selectedNode.id;
            document.getElementById('relationSearchInput').value = '';
            document.getElementById('relationSearchResults').innerHTML = '<p class="text-muted small text-center py-3">輸入關鍵字並搜尋</p>';
            
            // Load existing relations
            const existingRelations = normalizeRelatedEntries(selectedNode.data?.relatedIds || []);
            window.selectedRelationTargets = existingRelations.map(rel => cloneRelationEntry(rel));

            updateRelationSelectedList({ refreshSearch: false });

            const modalElement = document.getElementById('relationSettingsModal');
            if (!modalElement) {
                console.error('[Relation] Modal element not found');
                showMessage('關聯設定視窗載入失敗', 'error');
                return;
            }

            console.log('[Relation] Modal element:', modalElement);
            console.log('[Relation] Modal classList:', modalElement.className);
            
            // Remove any existing backdrop
            document.querySelectorAll('.modal-backdrop').forEach(bd => bd.remove());
            
            // Ensure modal is not hidden
            modalElement.style.display = 'block';
            modalElement.style.position = 'fixed';
            modalElement.style.zIndex = '1060';
            
            console.log('[Relation] Creating modal instance');
            const modalInstance = new bootstrap.Modal(modalElement, {
                backdrop: 'static',
                keyboard: false
            });
            console.log('[Relation] Showing modal');
            modalInstance.show();
            
            // Verify modal is visible
            setTimeout(() => {
                console.log('[Relation] Modal visible:', modalElement.style.display);
                console.log('[Relation] Modal opacity:', window.getComputedStyle(modalElement).opacity);
            }, 100);
            
            console.log('[Relation] Modal shown successfully');
        } catch (error) {
            console.error('[Relation] Error setting up modal:', error);
            showMessage('打開關聯設定視窗時出錯: ' + error.message, 'error');
        }
    };
    
    // Full Relation Graph - Global function
    window.openFullRelationGraph = function() {
        console.log('[Relation] openFullRelationGraph called');
        const ids = window.userStoryMapFlow?.getSelectedNodeIds?.() || [];
        if (ids.length > 1) {
            window.showFullRelationGraph?.(ids);
            return;
        }
        const selectedNode = window.userStoryMapFlow?.getSelectedNode();
        if (selectedNode) {
            window.showFullRelationGraph?.(selectedNode.id);
        } else {
            alert('請先選擇一個節點');
        }
    };
    
    // Relation Search Button
    document.getElementById('relationSearchBtn')?.addEventListener('click', async () => {
        console.log('[Relation] Search button clicked');
        
        const query = document.getElementById('relationSearchInput').value.trim();
        const nodeType = document.getElementById('relationNodeTypeFilter').value;
        const includeExternal = document.getElementById('relationIncludeExternal').checked;
        const currentMapId = parseInt(document.getElementById('currentMapSelect').value, 10);

        console.log('[Relation] Search params:', { query, nodeType, includeExternal, currentMapId });

        if (!query && !nodeType) {
            showMessage('請輸入搜尋條件', 'warning');
            return;
        }

        if (Number.isNaN(currentMapId)) {
            showMessage('請先選擇一個地圖', 'warning');
            return;
        }
        
        try {
            const params = new URLSearchParams();
            params.set('map_id', String(currentMapId));
            if (query) {
                params.set('q', query);
            }
            if (nodeType) {
                params.set('node_type', nodeType);
            }
            if (includeExternal) {
                params.set('include_external', 'true');
            }
            if (window.currentRelationNode && window.currentRelationNode.id) {
                params.set('exclude_node_id', window.currentRelationNode.id);
            }

            const url = `/api/user-story-maps/search-nodes?${params.toString()}`;
            console.log('[Relation] Fetching:', url);
            
            const token = localStorage.getItem('access_token');
            const headers = {
                'Content-Type': 'application/json',
            };
            if (token) {
                headers.Authorization = `Bearer ${token}`;
            }

            const response = await fetch(url, {
                method: 'GET',
                headers,
            });
            
            console.log('[Relation] Search response status:', response.status);
            
            if (!response.ok) {
                const errorDetail = await response.text();
                console.error('[Relation] Search error body:', errorDetail);
                throw new Error(`Search failed: ${response.statusText}`);
            }
            
            const results = await response.json();
            console.log('[Relation] Search results:', results);
            
            const resultsContainer = document.getElementById('relationSearchResults');
            
            if (results.length === 0) {
                resultsContainer.innerHTML = '<p class="text-muted small text-center py-3">找不到符合的節點</p>';
                return;
            }
            
            resultsContainer.innerHTML = `
                <div class="list-group">
                    ${results.map((node, idx) => `
                        <div class="list-group-item" data-result-idx="${idx}">
                            <div class="d-flex align-items-start">
                                <div class="form-check me-3">
                                    <input class="form-check-input" type="checkbox" id="relationCheck${idx}" data-result-idx="${idx}">
                                    <label class="form-check-label visually-hidden" for="relationCheck${idx}">選擇此節點</label>
                                </div>
                                <div class="flex-grow-1">
                                    <h6 class="mb-1">${escapeHtml(node.node_title)}</h6>
                                    <small class="text-muted">
                                        ${escapeHtml(node.team_name)} / ${escapeHtml(node.map_name)}
                                    </small>
                                    ${node.description ? `<p class="mb-0 small mt-1">${escapeHtml(node.description)}</p>` : ''}
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
            
            // Store results for access
            window.relationSearchResults = results;

            const ensureSelectionsArray = () => {
                if (!Array.isArray(window.selectedRelationTargets)) {
                    window.selectedRelationTargets = [];
                }
            };

            // Initialize checkboxes and update add button state
            const updateAddButtonState = () => {
                const checkedBoxes = resultsContainer.querySelectorAll('input[type="checkbox"]:checked');
                const addBtn = document.getElementById('relationAddSelectedBtn');
                if (addBtn) {
                    addBtn.disabled = checkedBoxes.length === 0;
                }
            };

            const checkboxes = resultsContainer.querySelectorAll('input[type="checkbox"]');
            checkboxes.forEach((checkbox) => {
                const idx = Number(checkbox.getAttribute('data-result-idx'));
                const node = results[idx];

                // Check if already selected
                if (window.selectedRelationTargets?.some((rel) => relationMatchesSearchNode(rel, node))) {
                    checkbox.checked = true;
                }

                checkbox.addEventListener('change', updateAddButtonState);
            });

            // Initial state update
            updateAddButtonState();
        } catch (error) {
            console.error('[Relation] Relation search failed:', error);
            showMessage('搜尋失敗: ' + error.message, 'error');
        }
    });

    // Add selected relations button
    const ensureSelectionsArray = () => {
        if (!Array.isArray(window.selectedRelationTargets)) {
            window.selectedRelationTargets = [];
        }
    };
    
    document.getElementById('relationAddSelectedBtn')?.addEventListener('click', () => {
        const resultsContainer = document.getElementById('relationSearchResults');
        const checkedBoxes = resultsContainer.querySelectorAll('input[type="checkbox"]:checked');

        if (checkedBoxes.length === 0) {
            showMessage('請先選擇要增加的節點', 'warning');
            return;
        }

        ensureSelectionsArray();

        let addedCount = 0;
        checkedBoxes.forEach((checkbox) => {
            const idx = Number(checkbox.getAttribute('data-result-idx'));
            const node = window.relationSearchResults[idx];

            const alreadySelected = window.selectedRelationTargets.some((rel) => relationMatchesSearchNode(rel, node));

            if (!alreadySelected) {
                window.selectedRelationTargets = [
                    ...window.selectedRelationTargets,
                    createRelationFromSearchResult(node),
                ];
                addedCount++;
            }
        });

        if (addedCount > 0) {
            showMessage(`已增加 ${addedCount} 個關聯節點`, 'success');
            updateRelationSelectedList({ refreshSearch: true });
        } else {
            showMessage('選中的節點都已經在關聯列表中', 'info');
        }

        // Uncheck all checkboxes after adding
        checkedBoxes.forEach((checkbox) => {
            checkbox.checked = false;
        });

        // Update button state
        document.getElementById('relationAddSelectedBtn').disabled = true;
    });
    
    // Update relation selected list display
    function updateRelationSelectedList(options = {}) {
        const { refreshSearch = true } = options;
        const selectedContainer = document.getElementById('relationSelectedList');
        const countDisplay = document.getElementById('relationSelectedCount');

        const targets = (window.selectedRelationTargets || []).map((entry) => cloneRelationEntry(entry));
        window.selectedRelationTargets = targets;

        if (!targets.length) {
            selectedContainer.innerHTML = '<p class="text-muted small text-center py-3">尚未選擇</p>';
            if (countDisplay) {
                countDisplay.textContent = '0';
            }
        } else {
            const listHtml = targets.map((rel, idx) => {
                if (typeof rel === 'string') {
                    return `
                        <div class="list-group-item d-flex justify-content-between align-items-center">
                            <div><strong>${escapeHtml(rel)}</strong></div>
                            <button type="button" class="btn btn-sm btn-danger" data-remove-idx="${idx}">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                    `;
                }

                const mapInfo = rel.map_name ? `${rel.map_name}` : '';
                const teamInfo = rel.team_name ? `${rel.team_name}` : '';
                const infoText = [teamInfo, mapInfo].filter(Boolean).join(' / ');

                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center">
                        <div class="flex-grow-1">
                            <h6 class="mb-1 small">${escapeHtml(rel.display_title || rel.node_id)}</h6>
                            ${infoText ? `<small class="text-muted">${escapeHtml(infoText)}</small>` : ''}
                        </div>
                        <button type="button" class="btn btn-sm btn-danger" data-remove-idx="${idx}">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                `;
            }).join('');

            selectedContainer.innerHTML = `<div class="list-group">${listHtml}</div>`;

            selectedContainer.querySelectorAll('button[data-remove-idx]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const idx = Number(btn.getAttribute('data-remove-idx'));
                    if (!Number.isNaN(idx)) {
                        window.selectedRelationTargets.splice(idx, 1);
                        updateRelationSelectedList({ refreshSearch: true });
                    }
                });
            });

            if (countDisplay) {
                countDisplay.textContent = String(targets.length);
            }
        }

        if (refreshSearch) {
            const resultsContainer = document.getElementById('relationSearchResults');
            if (resultsContainer && Array.isArray(window.relationSearchResults)) {
                resultsContainer.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
                    const idx = Number(checkbox.getAttribute('data-result-idx'));
                    const node = window.relationSearchResults[idx];
                    const matched = targets.some((rel) => relationMatchesSearchNode(rel, node));
                    checkbox.checked = matched;
                });

                // Update add button state
                const checkedBoxes = resultsContainer.querySelectorAll('input[type="checkbox"]:checked');
                const addBtn = document.getElementById('relationAddSelectedBtn');
                if (addBtn) {
                    addBtn.disabled = checkedBoxes.length === 0;
                }
            }
        }
    }
    
    // Save relations button
    document.getElementById('relationSaveBtn')?.addEventListener('click', async () => {
        const sourceNode = window.currentRelationNode;
        const targets = window.selectedRelationTargets || [];

        if (!sourceNode) {
            showMessage('請先選擇一個節點', 'warning');
            return;
        }

        const currentMapId = parseInt(document.getElementById('currentMapSelect').value, 10);
        if (Number.isNaN(currentMapId)) {
            showMessage('請先選擇一個地圖', 'warning');
            return;
        }

        showMessage('正在保存關聯...', 'info');

        try {
            const token = localStorage.getItem('access_token');
            const headers = {
                'Content-Type': 'application/json',
            };
            if (token) {
                headers.Authorization = `Bearer ${token}`;
            }

            const payload = {
                relations: serializeRelatedEntries(targets),
            };

            const response = await fetch(
                `/api/user-story-maps/${currentMapId}/nodes/${sourceNode.id}/relations`,
                {
                    method: 'PUT',
                    headers,
                    body: JSON.stringify(payload),
                }
            );

            console.log('[Relation] Bulk update status:', response.status);

            if (!response.ok) {
                const errorBody = await response.text();
                console.error('[Relation] Bulk update failed:', errorBody);
                showMessage('保存關聯失敗', 'error');
                return;
            }

            const result = await response.json();
            const updatedRelations = normalizeRelatedEntries(result?.relations || []);

            // 更新暫存狀態
            window.selectedRelationTargets = updatedRelations.map(rel => cloneRelationEntry(rel));

            // 更新 React Flow 節點
            const updatedSourceNode = {
                ...sourceNode,
                data: {
                    ...sourceNode.data,
                    relatedIds: updatedRelations,
                },
            };

            window.userStoryMapFlow?.setNodes?.((nodes) =>
                nodes.map((node) => (node.id === sourceNode.id ? updatedSourceNode : node))
            );

            showMessage('關聯已更新', 'success');

            // 關閉 Modal
            const modalElement = document.getElementById('relationSettingsModal');
            const modalInstance = bootstrap.Modal.getInstance(modalElement);
            modalInstance?.hide();

            window.currentRelationNode = null;

            // 重新載入地圖資料以確保與後端同步
            const flow = window.userStoryMapFlow;
            if (flow?.loadMap) {
                await flow.loadMap(currentMapId);
                flow.focusNode?.(updatedSourceNode.id);
            }
        } catch (error) {
            console.error('[Relation] Save relations failed:', error);
            showMessage('保存關聯失敗: ' + error.message, 'error');
        }
    });
});

// ============ Test Cases Review Feature ============
document.getElementById('reviewTestCasesBtn')?.addEventListener('click', async () => {
    const currentMapId = parseInt(document.getElementById('currentMapSelect').value, 10);
    if (Number.isNaN(currentMapId)) {
        showMessage('請先選擇一個地圖', 'warning');
        return;
    }

    // Get all selected node IDs
    const selectedNodeIds = window.userStoryMapFlow?.getSelectedNodeIds?.() || [];
    if (selectedNodeIds.length === 0) {
        showMessage('請先選擇一個或多個節點', 'warning');
        return;
    }

    // Collect all aggregated tickets from all selected nodes
    const aggregatedTickets = new Set();

    // Get the current nodes data from React Flow
    const allNodes = window.userStoryMapFlow?.getNodes?.() || [];

    selectedNodeIds.forEach(nodeId => {
        // Find the node with matching ID
        const node = allNodes.find(n => n.id === nodeId);
        if (node && node.data) {
            let tickets = node.data.aggregatedTickets;

            // Handle if aggregatedTickets is a string (JSON)
            if (typeof tickets === 'string') {
                try {
                    tickets = JSON.parse(tickets);
                } catch (e) {
                    tickets = [];
                }
            }

            if (Array.isArray(tickets)) {
                tickets.forEach(t => {
                    if (t) aggregatedTickets.add(t);
                });
            }
        }
    });

    if (aggregatedTickets.size === 0) {
        showMessage('選定的節點沒有關聯票券', 'info');
        return;
    }

    console.log('Selected nodes:', selectedNodeIds, 'Aggregated Tickets:', Array.from(aggregatedTickets));

    try {
        // Fetch test cases by aggregated tickets
        const teamId = window.teamId;
        if (!teamId) {
            showMessage('無法取得團隊資訊', 'warning');
            return;
        }

        const ticketsParam = Array.from(aggregatedTickets).join(',');
        
        const response = await fetch(`/api/teams/${teamId}/testcases/by-tickets?tickets=${encodeURIComponent(ticketsParam)}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            },
        });

        if (response.ok) {
            const testCases = await response.json();
            displayTestCasesReview(testCases);
            
            const modal = new bootstrap.Modal(document.getElementById('reviewTestCasesModal'));
            modal.show();
        } else {
            const errorMsg = await response.text();
            console.error('API error:', errorMsg);
            showMessage('無法載入相關案例', 'error');
        }
    } catch (error) {
        console.error('Failed to fetch test cases:', error);
        showMessage('載入相關案例失敗: ' + error.message, 'error');
    }
});

/**
 * Sort test cases by test case number (numeric sorting)
 * Reference: Test Case Management sorting algorithm
 */
function sortTestCasesByNumber(testCases) {
    const parseNumberSegments = str => {
        try {
            if (!str) return [];
            const ms = String(str).match(/\d+/g);
            return ms ? ms.map(s => parseInt(s, 10)) : [];
        } catch (_) { return []; }
    };

    const compareByNumericParts = (aStr, bStr) => {
        const aSeg = parseNumberSegments(aStr);
        const bSeg = parseNumberSegments(bStr);
        const len = Math.min(aSeg.length, bSeg.length);
        for (let i = 0; i < len; i++) {
            if (aSeg[i] !== bSeg[i]) return aSeg[i] - bSeg[i];
        }
        return aSeg.length - bSeg.length;
    };

    return testCases.slice().sort((a, b) => {
        const aNum = a.test_case_number || '';
        const bNum = b.test_case_number || '';
        return compareByNumericParts(aNum, bNum);
    });
}

function displayTestCasesReview(testCases) {
    const tbody = document.getElementById('testCasesTableBody');

    if (!testCases || testCases.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-muted text-center py-3">沒有相關的測試案例</td></tr>';
        return;
    }

    // Sort test cases by test case number
    const sortedTestCases = sortTestCasesByNumber(testCases);

    window.selectedTestCases = []; // Store selected cases
    window.lastCheckedCheckbox = null; // For shift-click support

    const getPriorityBadgeClass = (priority) => {
        const classes = {
            'HIGH': 'bg-danger',
            'MEDIUM': 'bg-warning',
            'LOW': 'bg-info'
        };
        return classes[priority] || 'bg-secondary';
    };

    const getPriorityText = (priority) => {
        const text = {
            'HIGH': '高',
            'MEDIUM': '中',
            'LOW': '低'
        };
        return text[priority] || priority || '-';
    };

    const html = sortedTestCases.map((tc, idx) => `
        <tr>
            <td class="text-center">
                <input class="form-check-input test-case-checkbox" type="checkbox" 
                       value="${tc.record_id}" data-tc-id="${tc.record_id}">
            </td>
            <td>
                <code style="color: rgb(194, 54, 120); font-weight: 500;">${escapeHtml(tc.test_case_number)}</code>
            </td>
            <td>
                <strong>${escapeHtml(tc.title)}</strong>
            </td>
            <td class="text-center">
                <span class="badge ${getPriorityBadgeClass(tc.priority)}">${getPriorityText(tc.priority)}</span>
            </td>
        </tr>
    `).join('');
    
    tbody.innerHTML = html;

    const updateSelectedCount = () => {
        document.getElementById('selectedTestCasesCount').textContent = window.selectedTestCases.length;
    };

    // Add change listeners to checkboxes with shift-click support
    tbody.querySelectorAll('.test-case-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                window.selectedTestCases.push({
                    record_id: e.target.value,
                    tcId: e.target.getAttribute('data-tc-id')
                });
            } else {
                window.selectedTestCases = window.selectedTestCases.filter(
                    tc => tc.record_id !== e.target.value
                );
            }
            updateSelectedCount();
        });

        checkbox.addEventListener('click', (e) => {
            if (e.shiftKey && window.lastCheckedCheckbox && window.lastCheckedCheckbox !== checkbox) {
                // Find the range between last checked and current
                const checkboxes = Array.from(tbody.querySelectorAll('.test-case-checkbox'));
                const lastIndex = checkboxes.indexOf(window.lastCheckedCheckbox);
                const currentIndex = checkboxes.indexOf(checkbox);
                const [start, end] = lastIndex < currentIndex ? [lastIndex, currentIndex] : [currentIndex, lastIndex];
                
                // Select all checkboxes in the range
                for (let i = start; i <= end; i++) {
                    const cb = checkboxes[i];
                    if (!cb.checked) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change'));
                    }
                }
            }
            window.lastCheckedCheckbox = checkbox;
        });
    });
    
    // Handle "Select All" checkbox
    const selectAllCheckbox = document.getElementById('selectAllTestCasesCheckbox');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            tbody.querySelectorAll('.test-case-checkbox').forEach(checkbox => {
                checkbox.checked = isChecked;
                checkbox.dispatchEvent(new Event('change'));
            });
        });
    }
}

// Create Test Run button - use event delegation
document.addEventListener('click', (e) => {
    if (e.target.id === 'createTestRunBtn') {
        console.log('createTestRunBtn clicked');
        console.log('selectedTestCases:', window.selectedTestCases);
        
        if (!window.selectedTestCases || window.selectedTestCases.length === 0) {
            showMessage('請先選擇至少一個測試案例', 'warning');
            return;
        }

        (async () => {
            const teamId = window.teamId;
            const recordIds = window.selectedTestCases.map(tc => tc.record_id);
            console.log('teamId:', teamId, 'recordIds:', recordIds);

            try {
                // 保存預選信息到 sessionStorage
                const preselectedCaseIds = recordIds.join(',');
                sessionStorage.setItem('testRunSelectedCaseIds', preselectedCaseIds);
                sessionStorage.setItem('testRunSetId', '0'); // 0 表示從 USM 來
                
                console.log('[USM] Saved preselected cases to sessionStorage:', preselectedCaseIds);
                showMessage('準備建立 Test Run...', 'success');
                
                // 關閉 reviewTestCasesModal
                const reviewModal = bootstrap.Modal.getInstance(document.getElementById('reviewTestCasesModal'));
                reviewModal?.hide();
                
                // 跳轉到 Test Run 管理頁面，由頁面負責打開建立表單
                window.location.href = `/test-run-management?team_id=${teamId}`;
            } catch (error) {
                console.error('Failed to prepare test run:', error);
                showMessage('準備失敗: ' + error.message, 'error');
            }
        })();
    }
});

// ============ Quick Search (Slash command) ============
document.addEventListener('DOMContentLoaded', function() {
    // Setup global keydown listener for slash
    document.addEventListener('keydown', function(e) {
        const tag = (e.target && e.target.tagName || '').toLowerCase();
        const isTyping = ['input', 'textarea', 'select'].includes(tag) || (e.target && e.target.isContentEditable);
        
        if (!isTyping && e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            openQuickSearchUSM();
        }
    });
    
    // Add hint at bottom
    if (document.getElementById('quickSearchHint')) return;
    const hint = document.createElement('div');
    hint.id = 'quickSearchHint';
    hint.className = 'position-fixed';
    hint.style.cssText = 'left:12px; bottom:12px; z-index:1040; opacity:0.85; pointer-events:none;';
    hint.innerHTML = `<span class="badge bg-secondary-subtle text-secondary border" style="--bs-bg-opacity:.65;">按 / 開啟快速搜尋</span>`;
    document.body.appendChild(hint);
});

function openQuickSearchUSM() {
    const overlay = document.getElementById('quickSearchOverlay');
    const input = document.getElementById('quickSearchInput');
    const results = document.getElementById('quickSearchResults');
    if (!overlay || !input || !results) return;
    
    overlay.style.display = 'block';
    input.value = '';
    results.innerHTML = '';
    input.focus();
    
    const handleKey = (e) => {
        if (e.key === 'Escape') {
            closeQuickSearchUSM();
            return;
        }
        if (e.key === 'Enter') {
            const active = results.querySelector('.active');
            if (active) {
                active.click();
            }
        } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const items = Array.from(results.querySelectorAll('.list-group-item'));
            if (items.length === 0) return;
            let idx = items.findIndex(li => li.classList.contains('active'));
            if (idx < 0) idx = 0;
            idx = (e.key === 'ArrowDown') ? Math.min(idx + 1, items.length - 1) : Math.max(idx - 1, 0);
            items.forEach(li => li.classList.remove('active'));
            items[idx].classList.add('active');
            items[idx].scrollIntoView({ block: 'nearest' });
        }
    };
    
    input.onkeydown = handleKey;
    input.oninput = () => quickSearchRenderUSM(input.value, results);
}

function closeQuickSearchUSM() {
    const overlay = document.getElementById('quickSearchOverlay');
    if (overlay) overlay.style.display = 'none';
}

function quickSearchRenderUSM(query, container) {
    const q = (query || '').trim().toLowerCase();
    let matches = [];
    
    if (q.length > 0) {
        let nodesData = [];
        
        // 查詢所有自定義節點的 DOM
        const nodeElements = document.querySelectorAll('.custom-node');
        if (nodeElements.length > 0) {
            nodesData = Array.from(nodeElements).map((el) => {
                // 嘗試從多個地方獲取實際的節點 ID
                let nodeId = null;
                
                // 方法1：查找 data-id 屬性
                const parentWithId = el.closest('[data-id]');
                if (parentWithId) {
                    nodeId = parentWithId.getAttribute('data-id');
                }
                
                // 方法2：查找 React Flow 節點的 ID（在 data-testid 或其他屬性中）
                if (!nodeId) {
                    const rfNode = el.closest('[data-testid="rf__node"]');
                    if (rfNode) {
                        // React Flow 通常在 class 中包含節點 ID
                        const classes = rfNode.getAttribute('class') || '';
                        const match = classes.match(/rf__node-[^\s]*/);
                        if (match) {
                            nodeId = match[0].replace('rf__node-', '');
                        }
                    }
                }
                
                // 方法3：從標題推斷（備用）
                const titleEl = el.querySelector('.node-title') || el.querySelector('strong');
                const title = titleEl?.textContent?.trim() || '';
                
                if (!nodeId) {
                    nodeId = title;
                }
                
                return {
                    id: nodeId,
                    data: {
                        title: title,
                        description: '',
                        as_a: '',
                        i_want: '',
                        so_that: ''
                    }
                };
            }).filter(n => n.id && n.id.length > 0);
        }
        
        // 去重：使用 Map 根據 nodeId 去除重複
        const uniqueMap = new Map();
        nodesData.forEach(node => {
            if (!uniqueMap.has(node.id)) {
                uniqueMap.set(node.id, node);
            }
        });
        nodesData = Array.from(uniqueMap.values());
        
        console.log('Quick search: found', nodesData.length, 'unique nodes', nodesData.map(n => ({ id: n.id, title: n.data.title })));
        
        matches = nodesData.filter(node => {
            if (!node || !node.id) return false;
            const data = node.data || {};
            const title = (data.title || '').toLowerCase();
            const desc = (data.description || '').toLowerCase();
            const asA = (data.as_a || '').toLowerCase();
            const iWant = (data.i_want || '').toLowerCase();
            const soThat = (data.so_that || '').toLowerCase();
            const nodeId = (node.id || '').toLowerCase();
            
            return title.includes(q) || 
                   desc.includes(q) || 
                   asA.includes(q) || 
                   iWant.includes(q) || 
                   soThat.includes(q) ||
                   nodeId.includes(q);
        }).slice(0, 100);
    }
    
    if (matches.length === 0) {
        container.innerHTML = `<div class="list-group-item text-muted text-center py-3">沒有找到符合條件的節點</div>`;
        return;
    }
    
    container.innerHTML = matches.map((node, idx) => `
        <button type="button" class="list-group-item list-group-item-action ${idx === 0 ? 'active' : ''}" data-node-id="${escapeHtml(node.id)}">
            <div class="d-flex justify-content-between align-items-start gap-2">
                <div style="flex: 1; text-align: left;">
                    <strong class="text-truncate d-block">${escapeHtml(node.data?.title || node.id)}</strong>
                    <small class="text-muted text-truncate d-block">${escapeHtml((node.data?.description || '').substring(0, 60))}</small>
                </div>
            </div>
        </button>
    `).join('');
    
    container.querySelectorAll('.list-group-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const nodeId = btn.getAttribute('data-node-id');
            console.log('Quick search: clicking node', nodeId);
            closeQuickSearchUSM();
            if (nodeId && window.userStoryMapFlow?.focusNode) {
                window.userStoryMapFlow.focusNode(nodeId);
            }
        });
    });
}
