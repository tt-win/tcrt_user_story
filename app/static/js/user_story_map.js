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

// Team ID from URL
const teamId = parseInt(window.location.pathname.split('/').pop());

// Layout constants to keep newly added nodes from overlapping
const ROOT_START_X = 100;
const ROOT_START_Y = 100;
const CHILD_HORIZONTAL_OFFSET = 180;
const ROOT_VERTICAL_SPACING = 160;
const SIBLING_VERTICAL_SPACING = 140;

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
    setElementVisibility('autoLayoutBtn', hasUsmAccess('nodeAdd'));
    setElementVisibility('confirmAddNodeBtn', hasUsmAccess('nodeAdd'));
};

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

    const truncatedDescription = (() => {
        if (!data.description) return null;
        const plain = String(data.description).trim();
        if (plain.length <= 80) return plain;
        return plain.slice(0, 77) + '...';
    })();

    const hasChildren = Array.isArray(data.childrenIds) && data.childrenIds.length > 0;
    const collapseToggle = hasChildren
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
            className: `custom-node${data.isRoot ? ' root-node' : ''}`,
            'data-node-type': data.nodeType,
            style: {
                opacity: data.dimmed ? 0.3 : 1,
                transition: 'opacity 0.3s ease',
            }
        },
        // Connection Handles - 4 positions (removed corner handles)
        React.createElement(Handle, { type: 'target', position: Position.Top, id: 'top' }),
        React.createElement(Handle, { type: 'source', position: Position.Bottom, id: 'bottom' }),
        React.createElement(Handle, { type: 'target', position: Position.Left, id: 'left' }),
        React.createElement(Handle, { type: 'source', position: Position.Right, id: 'right' }),
        collapseToggle,
        // Node content
        React.createElement(
            'div',
            { className: 'node-title' },
            data.title || 'Untitled'
        ),
        truncatedDescription ? React.createElement(
            'div',
            {
                className: 'text-muted',
                style: { fontSize: '12px', marginTop: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
            },
            truncatedDescription
        ) : null,
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
    const [highlightedPath, setHighlightedPath] = useState(null);
    const [teamName, setTeamName] = useState('');
    const [collapsedNodeIds, setCollapsedNodeIds] = useState(new Set());
    const reactFlowInstance = useRef(null);
    const nodesRef = useRef([]);

    useEffect(() => {
        nodesRef.current = nodes;
    }, [nodes]);

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
    }, [teamId]);

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
                        relatedIds: node.related_ids,
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
                    return {
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
                        targetHandle: 'left',
                    };
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
                setEdges(validEdges.map(edge => ({ ...edge, hidden: false })));
                setCurrentMapId(mapId);
                setCollapsedNodeIds(() => new Set());
            }
        } catch (error) {
            console.error('Failed to load map:', error);
        }
    }, [setNodes, setEdges, applyTreeLayout, teamName, toggleNodeCollapse]);

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
                related_ids: node.data.relatedIds || [],
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

        const modal = new bootstrap.Modal(document.getElementById('addNodeModal'));
        modal.show();

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

        const modal = new bootstrap.Modal(document.getElementById('addNodeModal'));
        modal.show();

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
                            return `
                                <button type="button" class="list-group-item list-group-item-action small text-start" data-related-idx="${idx}" title="點擊導航到該節點">
                                    <strong>${escapeHtml(rel.display_title || rel.node_id)}</strong>
                                    <br>
                                    <small class="text-muted">
                                        ${escapeHtml(rel.team_name || '')} / ${escapeHtml(rel.map_name || '')}
                                    </small>
                                </button>
                            `;
                        }).join('')}
                    </div>
                </div>`
            : '';

        const actionButtonsHtml = [
            canUpdateNode ? '<button type="button" class="btn btn-sm btn-primary w-100" id="updateNodeBtn">更新節點</button>' : '',
            canDeleteNode ? '<button type="button" class="btn btn-sm btn-danger w-100" id="deleteNodeBtn">刪除節點</button>' : '',
        ].filter(Boolean).join('');

        container.innerHTML = `
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
                    <input type="text" class="form-control form-control-sm" id="propJira" ${readOnlyAttr} value="${escapeHtml((data.jiraTickets || []).join(', '))}">
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

        if (canUpdateNode) {
            const attachAutoSave = (id) => {
                const el = document.getElementById(id);
                if (el) {
                    el.addEventListener('blur', () => updateNode(node.id));
                }
            };

            attachAutoSave('propTitle');
            attachAutoSave('propDescription');
            attachAutoSave('propJira');
            attachAutoSave('propComment');

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
        
        // Add event handlers for related nodes
        document.querySelectorAll('[data-related-idx]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.getAttribute('data-related-idx'));
                const relatedNode = data.relatedIds[idx];
                
                if (!relatedNode) return;
                
                // Handle both string and object formats
                let nodeId, mapId;
                
                if (typeof relatedNode === 'string') {
                    // Old format: just node ID
                    nodeId = relatedNode;
                    mapId = window.currentMapId;
                } else if (typeof relatedNode === 'object') {
                    // New format: object with metadata
                    nodeId = relatedNode.node_id || relatedNode.nodeId;
                    mapId = relatedNode.map_id || relatedNode.mapId;
                } else {
                    return;
                }
                
                if (!nodeId) return;
                
                // Same map - directly focus
                if (!mapId || mapId === window.currentMapId) {
                    window.userStoryMapFlow?.focusNode?.(nodeId);
                    showMessage(`已聚焦節點: ${relatedNode.display_title || nodeId}`, 'info');
                } else {
                    // Cross-map - ask user to switch
                    const mapName = relatedNode.map_name || `地圖 ${mapId}`;
                    const nodeTitle = relatedNode.display_title || nodeId;
                    
                    if (confirm(`是否切換到 "${mapName}" 地圖並聚焦節點 "${nodeTitle}"？`)) {
                        console.log(`[Navigation] Switching to map ${mapId}, focusing node ${nodeId}`);
                        
                        // Load the other map
                        const mapSelect = document.getElementById('currentMapSelect');
                        if (mapSelect) {
                            mapSelect.value = mapId;
                            mapSelect.dispatchEvent(new Event('change'));
                            
                            // After map loads, focus the node
                            setTimeout(() => {
                                console.log(`[Navigation] Focusing node ${nodeId} in map ${mapId}`);
                                window.userStoryMapFlow?.focusNode?.(nodeId);
                                showMessage(`已切換到 ${mapName} 並聚焦節點`, 'success');
                            }, 800);
                        }
                    }
                }
            });
        });
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

    // Highlight path to node
    const highlightPath = useCallback((nodeId) => {
        if (!nodeId) return;

        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        const targetNode = nodesById.get(nodeId);

        if (!targetNode) {
            showMessage('找不到指定節點，請重新載入地圖', 'error');
            return;
        }

        const highlightedIds = new Set([nodeId]);
        const parentNodes = [];
        const childNodes = [];
        const relatedSameMapNodes = [];
        const crossMapRelations = [];

        // Collect parents up to root
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

        // Collect all descendants
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

        // Collect related nodes
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

        setHighlightedPath({
            nodeId,
            nodes: Array.from(highlightedIds),
            parents: parentNodes.map((node) => node.id),
            children: childNodes.map((node) => node.id),
            relatedSameMap: relatedSameMapNodes.map((node) => node.id),
            crossMapRelations,
        });

        setNodes((nds) =>
            nds.map((node) => ({
                ...node,
                data: {
                    ...node.data,
                    dimmed: !highlightedIds.has(node.id),
                },
            }))
        );

        setEdges((eds) =>
            eds.map((edge) => {
                // 保持現有邊的樣式
                const isRelationEdge = relatedSameMapNodes.some(n => 
                    (edge.source === nodeId && edge.target === n.id) ||
                    (edge.source === n.id && edge.target === nodeId)
                );
                
                return {
                    ...edge,
                    style: {
                        ...edge.style,
                        opacity:
                            highlightedIds.has(edge.source) &&
                            highlightedIds.has(edge.target)
                                ? 1
                                : 0.2,
                        strokeDasharray: isRelationEdge ? '5,5' : undefined,
                        stroke: isRelationEdge ? '#17a2b8' : undefined,
                    },
                };
            })
            // 添加關聯邊
            .concat(
                relatedSameMapNodes.flatMap(relNode => {
                    const edgeId = `relation-${nodeId}-${relNode.id}`;
                    // 檢查邊是否已存在
                    if (eds.some(e => e.id === edgeId)) {
                        return [];
                    }
                    return [{
                        id: edgeId,
                        source: nodeId,
                        target: relNode.id,
                        type: 'default',
                        animated: true,
                        style: {
                            strokeDasharray: '5,5',
                            stroke: '#17a2b8',
                            strokeWidth: 2,
                        },
                    }];
                })
            )
        );

        const highlightInfoEl = document.getElementById('highlightInfo');
        if (highlightInfoEl) {
            highlightInfoEl.classList.remove('d-none');
            highlightInfoEl.classList.add('show');

            const formatNodeBadge = (node) =>
                `<span class="badge rounded-pill text-bg-primary me-1 mb-1">${escapeHtml(node.data.title || node.id)}</span>`;

            const parentHtml =
                parentNodes.length > 0
                    ? parentNodes.map(formatNodeBadge).join('')
                    : '<span class="text-muted">無父節點</span>';

            const childrenHtml =
                childNodes.length > 0
                    ? childNodes.map(formatNodeBadge).join('')
                    : '<span class="text-muted">無子節點</span>';

            const relatedHtml =
                relatedSameMapNodes.length > 0
                    ? relatedSameMapNodes.map(formatNodeBadge).join('')
                    : '<span class="text-muted">本圖無關聯節點</span>';

            const crossMapHtml =
                crossMapRelations.length > 0
                    ? `<ul class="mb-0 ps-3">${crossMapRelations
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

            highlightInfoEl.innerHTML = `
                <div><strong>當前節點：</strong>${escapeHtml(targetNode.data.title || targetNode.id)}</div>
                <div class="mt-1"><strong>父節點：</strong>${parentHtml}</div>
                <div class="mt-1"><strong>子節點：</strong>${childrenHtml}</div>
                <div class="mt-1"><strong>本圖關聯：</strong>${relatedHtml}</div>
                <div class="mt-1"><strong>跨圖關聯：</strong>${crossMapHtml}</div>
            `;
        }

        const clearBtn = document.getElementById('clearHighlightBtn');
        if (clearBtn) {
            clearBtn.style.display = 'inline-block';
        }
    }, [nodes, setNodes, setEdges]);

    // Clear path highlighting
    const clearHighlight = useCallback(() => {
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
    }, [setNodes, setEdges]);

    // Show full relation graph
    const showFullRelationGraph = useCallback((nodeId) => {
        if (!nodeId) return;

        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        const targetNode = nodesById.get(nodeId);

        if (!targetNode) {
            showMessage('找不到指定節點', 'error');
            return;
        }

        // 收集所有同圖關聯節點
        const relatedSameMapNodes = [];
        const crossMapRelations = [];
        
        (targetNode.data.relatedIds || []).forEach((entry) => {
            if (typeof entry === 'string') {
                if (nodesById.has(entry)) {
                    relatedSameMapNodes.push(nodesById.get(entry));
                } else {
                    crossMapRelations.push({ nodeId: entry, raw: entry });
                }
            } else if (typeof entry === 'object') {
                const nodeId = entry.nodeId || entry.node_id || entry.id;
                if (nodeId && nodesById.has(nodeId)) {
                    relatedSameMapNodes.push(nodesById.get(nodeId));
                } else {
                    crossMapRelations.push({
                        nodeId: nodeId || entry.id,
                        mapId: entry.mapId || entry.map_id,
                        mapName: entry.mapName || entry.map_name,
                        nodeTitle: entry.display_title || entry.node_title || entry.title,
                    });
                }
            }
        });

        // 生成跨圖節點卡片 HTML
        const crossMapHtml = crossMapRelations.length > 0
            ? crossMapRelations.map(rel => `
                <div class="list-group-item">
                    <h6 class="mb-1">${escapeHtml(rel.nodeTitle || rel.nodeId)}</h6>
                    <small class="text-muted">
                        ${rel.mapName ? `地圖: ${escapeHtml(rel.mapName)}` : ''}
                        ${rel.mapId ? ` (ID: ${rel.mapId})` : ''}
                    </small>
                </div>
              `).join('')
            : '<p class="text-muted small text-center py-3">無跨地圖關聯</p>';

        document.getElementById('crossMapNodesList').innerHTML = crossMapHtml;

        // 打開 Modal
        const modalElement = document.getElementById('fullRelationGraphModal');
        if (modalElement) {
            // Ensure modal is not hidden
            modalElement.style.display = 'block';
            modalElement.style.position = 'fixed';
            modalElement.style.zIndex = '9999';
            
            // Remove any existing backdrop
            document.querySelectorAll('.modal-backdrop').forEach(bd => bd.remove());
            
            const modal = new bootstrap.Modal(modalElement, {
                backdrop: 'static',
                keyboard: false
            });
            modal.show();
        }
    }, [nodes]);

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
    useEffect(() => {
        if (maps.length > 0 && !currentMapId) {
            const select = document.getElementById('currentMapSelect');
            if (select && !select.value) {
                const firstMapId = maps[0].id;
                select.value = firstMapId;
                loadMap(firstMapId);
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

        nodesRef.current = updatedNodes;
        setNodes(updatedNodes);
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
                const refreshed = updatedNodes.find((node) => node.id === selectedNode.id);
                if (refreshed && refreshed !== selectedNode) {
                    setSelectedNode(refreshed);
                    updateNodeProperties(refreshed);
                }
            }
        }
    }, [collapsedNodeIds, setNodes, setEdges, toggleNodeCollapse, setSelectedNode]);

    useEffect(() => {
        if (selectedNode) {
            updateNodeProperties(selectedNode);
        }
    }, [teamName, selectedNode]);

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
            getTeamName: () => teamName,
            setNodes,
            setEdges,
        };
        window.addChildNode = addChildNode;
        window.addSiblingNode = addSiblingNode;
        window.showFullRelationGraph = showFullRelationGraph;
    }, [saveMap, addNode, loadMap, loadMaps, autoLayout, highlightPath, clearHighlight, focusNode, selectedNode, addChildNode, addSiblingNode, setNodes, setEdges, teamName, showFullRelationGraph]);

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
            connectOnClick: false
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
                ? `<button class="btn btn-outline-primary edit-map-btn" data-map-id="${map.id}" data-map-name="${escapeHtml(map.name)}" data-map-description="${escapeHtml(map.description || '')}">
                        <i class="fas fa-pen"></i>
                   </button>`
                : '';
            const deleteBtn = hasUsmAccess('mapDelete')
                ? `<button class="btn btn-outline-danger delete-map-btn" data-map-id="${map.id}" data-map-name="${escapeHtml(map.name)}">
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

    // Highlight path button
    document.getElementById('highlightPathBtn')?.addEventListener('click', () => {
        const selectedNode = window.userStoryMapFlow?.getSelectedNode();
        if (selectedNode) {
            window.userStoryMapFlow?.highlightPath(selectedNode.id);
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
                const results = await response.json();
                const container = document.getElementById('searchResults');

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
                                    ${node.jira_tickets && node.jira_tickets.length > 0 ? `<br><small class="text-info">Tickets: ${escapeHtml(node.jira_tickets.join(', '))}</small>` : ''}
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
            const existingRelations = selectedNode.data?.relatedIds || [];
            window.selectedRelationTargets = [];
            
            if (existingRelations.length > 0) {
                existingRelations.forEach(rel => {
                    window.selectedRelationTargets.push(rel);
                });
                
                // Display existing relations
                const relatedHtml = existingRelations.map((rel, idx) => {
                    const displayTitle = typeof rel === 'string' 
                        ? rel 
                        : (rel.display_title || rel.node_title || rel.node_id || rel);
                    const mapInfo = typeof rel === 'string' 
                        ? '' 
                        : (rel.map_name ? ` (${rel.map_name})` : '');
                    
                    return `
                        <div class="list-group-item d-flex justify-content-between align-items-center">
                            <div>
                                <strong>${escapeHtml(displayTitle)}</strong>
                                ${mapInfo ? `<small class="text-muted">${escapeHtml(mapInfo)}</small>` : ''}
                            </div>
                            <button type="button" class="btn btn-sm btn-outline-danger" data-remove-idx="${idx}">
                                <i class="fas fa-trash-alt"></i>
                            </button>
                        </div>
                    `;
                }).join('');
                
                document.getElementById('relationSelectedList').innerHTML = relatedHtml;
                
                // Add remove handlers
                document.querySelectorAll('[data-remove-idx]').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const idx = parseInt(btn.getAttribute('data-remove-idx'));
                        window.selectedRelationTargets.splice(idx, 1);
                        window.openRelationModal?.(); // Refresh modal
                    });
                });
            } else {
                document.getElementById('relationSelectedList').innerHTML = '<p class="text-muted small text-center py-3">尚未選擇</p>';
            }
            
            document.getElementById('relationSelectedCount').textContent = window.selectedRelationTargets.length;

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
            modalElement.style.zIndex = '9999';
            
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
                        <button type="button" class="list-group-item list-group-item-action text-start" data-result-idx="${idx}">
                            <div class="d-flex justify-content-between align-items-start">
                                <div class="flex-grow-1">
                                    <h6 class="mb-1">${escapeHtml(node.node_title)}</h6>
                                    <small class="text-muted">
                                        ${escapeHtml(node.team_name)} / ${escapeHtml(node.map_name)}
                                    </small>
                                    ${node.description ? `<p class="mb-0 small mt-1">${escapeHtml(node.description)}</p>` : ''}
                                </div>
                                <i class="fas fa-check-circle text-success" style="display: none;"></i>
                            </div>
                        </button>
                    `).join('')}
                </div>
            `;
            
             // Store results for access
             window.relationSearchResults = results;

             // Add click handlers
             resultsContainer.querySelectorAll('button[data-result-idx]').forEach((btn) => {
                 btn.addEventListener('click', () => {
                     const idx = parseInt(btn.getAttribute('data-result-idx'));
                     const node = results[idx];

                     // Check if already selected
                     const alreadySelected = window.selectedRelationTargets.some(t => t.node_id === node.node_id && t.map_id === node.map_id);

                     if (!alreadySelected) {
                         window.selectedRelationTargets.push(node);
                         btn.classList.add('active');
                         btn.querySelector('i').style.display = 'inline';
                         updateRelationSelectedList();
                         console.log('[Relation] Added target:', node.node_id);
                     }
                 });
             });
        } catch (error) {
            console.error('[Relation] Relation search failed:', error);
            showMessage('搜尋失敗: ' + error.message, 'error');
        }
    });
    
    // Update relation selected list display
    const updateRelationSelectedList = () => {
        const selectedContainer = document.getElementById('relationSelectedList');
        const countDisplay = document.getElementById('relationSelectedCount');
        
        if (!window.selectedRelationTargets || window.selectedRelationTargets.length === 0) {
            selectedContainer.innerHTML = '<p class="text-muted small text-center py-3">尚未選擇</p>';
            countDisplay.textContent = '0';
            return;
        }
        
        countDisplay.textContent = window.selectedRelationTargets.length;
        selectedContainer.innerHTML = `
            <div class="list-group">
                ${window.selectedRelationTargets.map((node, idx) => `
                    <div class="list-group-item d-flex justify-content-between align-items-center">
                        <div class="flex-grow-1">
                            <h6 class="mb-1 small">${escapeHtml(node.node_title)}</h6>
                            <small class="text-muted">${escapeHtml(node.team_name)} / ${escapeHtml(node.map_name)}</small>
                        </div>
                        <button type="button" class="btn btn-sm btn-outline-danger" data-remove-idx="${idx}">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                `).join('')}
            </div>
        `;
        
        // Add remove handlers
        selectedContainer.querySelectorAll('button[data-remove-idx]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.getAttribute('data-remove-idx'));
                window.selectedRelationTargets.splice(idx, 1);
                updateRelationSelectedList();
                
                // Update search results UI
                const resultsContainer = document.getElementById('relationSearchResults');
                resultsContainer.querySelectorAll('button[data-result-idx]').forEach(resultBtn => {
                    resultBtn.classList.remove('active');
                    resultBtn.querySelector('i').style.display = 'none';
                });
            });
        });
    };
    
    // Save relations button
    document.getElementById('relationSaveBtn')?.addEventListener('click', async () => {
        console.log('[Relation] Save button clicked');
        
        const sourceNode = window.currentRelationNode;
        const targets = window.selectedRelationTargets || [];
        
        console.log('[Relation] Save params:', { sourceNode: sourceNode?.id, targets: targets.length });
        
        if (!sourceNode || targets.length === 0) {
            showMessage('請選擇至少一個目標節點', 'warning');
            return;
        }
        
        try {
            showMessage('正在保存關聯...', 'info');
            let successCount = 0;
            
            for (const target of targets) {
                try {
                    const currentMapId = parseInt(document.getElementById('currentMapSelect').value, 10);
                    if (Number.isNaN(currentMapId)) {
                        throw new Error('未選擇地圖，無法建立關聯');
                    }
                    const token = localStorage.getItem('access_token');
                    const headers = {
                        'Content-Type': 'application/json',
                    };
                    if (token) {
                        headers.Authorization = `Bearer ${token}`;
                    }

                    const response = await fetch(
                        `/api/user-story-maps/${currentMapId}/nodes/${sourceNode.id}/relations`,
                        {
                            method: 'POST',
                            headers,
                            body: JSON.stringify({
                                target_node_id: target.node_id,
                                target_map_id: target.map_id
                            })
                        }
                    );
                    
                    console.log('[Relation] Create relation response:', response.status);
                    
                    if (response.ok) {
                        successCount++;
                        const result = await response.json();
                        
                        // Add to node data
                        const newRelation = {
                            relation_id: result.relation_id,
                            node_id: target.node_id,
                            map_id: target.map_id,
                            map_name: target.map_name,
                            team_id: target.team_id,
                            team_name: target.team_name,
                            display_title: target.node_title,
                        };

                        if (!Array.isArray(sourceNode.data.relatedIds)) {
                            sourceNode.data.relatedIds = [];
                        }
                        sourceNode.data.relatedIds.push(newRelation);

                        window.userStoryMapFlow?.setNodes?.((nodes) =>
                            nodes.map((node) =>
                                node.id === sourceNode.id
                                    ? {
                                        ...node,
                                        data: {
                                            ...node.data,
                                            relatedIds: [
                                                ...(Array.isArray(node.data.relatedIds) ? node.data.relatedIds : []),
                                                newRelation,
                                            ],
                                        },
                                    }
                                    : node
                            )
                        );
                        
                        console.log('[Relation] Relation created:', result.relation_id);
                    } else {
                        const errorData = await response.json();
                        console.error('[Relation] Create relation failed:', errorData);
                    }
                } catch (err) {
                    console.error('[Relation] Error creating single relation:', err);
                }
            }
            
            if (successCount === targets.length) {
                showMessage(`已成功建立 ${successCount} 個關聯`, 'success');
                
                // Save map
                console.log('[Relation] Saving map');
                if (window.userStoryMapFlow?.saveMap) {
                    await window.userStoryMapFlow.saveMap(true);
                    console.log('[Relation] Map saved');
                }

                // Close modal
                const modalElement = document.getElementById('relationSettingsModal');
                const modalInstance = bootstrap.Modal.getInstance(modalElement);
                if (modalInstance) {
                    modalInstance.hide();
                    console.log('[Relation] Modal closed');
                }

                window.selectedRelationTargets = [];
                window.currentRelationNode = null;

                setTimeout(() => {
                    const mapSelect = document.getElementById('currentMapSelect');
                    const activeMapId = mapSelect ? parseInt(mapSelect.value, 10) : NaN;
                    if (!Number.isNaN(activeMapId)) {
                        const flow = window.userStoryMapFlow;
                        if (flow?.loadMap) {
                            flow.loadMap(activeMapId).then(() => {
                                flow.focusNode?.(sourceNode.id);
                            });
                        }
                    }
                }, 300);
            } else if (successCount > 0) {
                showMessage(`已建立 ${successCount}/${targets.length} 個關聯`, 'warning');
            } else {
                showMessage('未成功建立任何關聯', 'error');
            }
        } catch (error) {
            console.error('[Relation] Save relations failed:', error);
            showMessage('保存關聯失敗: ' + error.message, 'error');
        }
    });
});
