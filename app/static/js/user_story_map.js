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
                const flowEdges = map.edges.map(edge => ({
                    id: edge.id,
                    source: edge.source,
                    target: edge.target,
                    type: edge.edge_type === 'parent' ? 'smoothstep' : 'default',
                    animated: edge.edge_type === 'related',
                    markerEnd: {
                        type: MarkerType.ArrowClosed,
                    },
                    sourceHandle: 'right',
                    targetHandle: 'left',
                }));

                const layoutedNodes = applyTreeLayout(flowNodes, flowEdges);
                const decoratedNodes = layoutedNodes.map(node => ({
                    ...node,
                    data: {
                        ...node.data,
                        collapsed: false,
                        toggleCollapse: toggleNodeCollapse,
                    },
                }));
                nodesRef.current = decoratedNodes;
                setNodes(decoratedNodes);
                setEdges(flowEdges.map(edge => ({ ...edge, hidden: false })));
                setCurrentMapId(mapId);
                setCollapsedNodeIds(() => new Set());
            }
        } catch (error) {
            console.error('Failed to load map:', error);
        }
    }, [setNodes, setEdges, applyTreeLayout, teamName, toggleNodeCollapse]);

    // Save map
    const saveMap = useCallback(async (silent = false) => {
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
            const mapEdges = edges.map(edge => ({
                id: edge.id,
                source: edge.source,
                target: edge.target,
                edge_type: edge.type === 'smoothstep' ? 'parent' : edge.animated ? 'related' : 'default',
            }));

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
        // Calculate position based on tree layout
        let positionX = 100;
        let positionY = 100;
        
        if (nodeData.parentId) {
            const parentNode = nodes.find(n => n.id === nodeData.parentId);
            if (parentNode) {
                // Position to the right of parent
                positionX = parentNode.position.x + 150;
                
                // Calculate Y position based on siblings
                const siblings = nodes.filter(n => n.data.parentId === nodeData.parentId);
                positionY = parentNode.position.y + (siblings.length * 60);
            }
        } else {
            // Root level - position based on existing root nodes
            const rootNodes = nodes.filter(n => !n.data.parentId);
            positionY = 100 + (rootNodes.length * 100);
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
        const parentNode = nodes.find(n => n.id === parentId);
        if (!parentNode) return;

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
        const siblingNode = nodes.find(n => n.id === siblingId);
        if (!siblingNode) return;
        
        // Root node cannot have siblings - check by level and parentId
        if (siblingNode.data.level === 0 || !siblingNode.data.parentId) {
            alert('根節點不能新增同級節點');
            return;
        }
        
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
            return;
        }

        const data = node.data;
        const resolvedTeam = data.team || teamName || '';
        container.innerHTML = `
            <div class="mb-3">
                <label class="form-label small fw-bold">標題</label>
                <input type="text" class="form-control form-control-sm" id="propTitle" value="${data.title || ''}">
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">描述</label>
                <textarea class="form-control form-control-sm" id="propDescription" rows="3">${data.description || ''}</textarea>
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">團隊</label>
                <p class="form-control-plaintext mb-0">${resolvedTeam ? escapeHtml(resolvedTeam) : '<span class="text-muted">未設定</span>'}</p>
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">JIRA Tickets</label>
                <input type="text" class="form-control form-control-sm" id="propJira" value="${(data.jiraTickets || []).join(', ')}">
            </div>
            ${data.aggregatedTickets && data.aggregatedTickets.length > 0 ? `<div class="mb-3">
                <label class="form-label small fw-bold">聚合 Tickets (含子節點)</label>
                <div class="alert alert-warning p-2 small">
                    ${data.aggregatedTickets.join(', ')}
                </div>
            </div>` : ''}
            <div class="mb-3">
                <label class="form-label small fw-bold">註解</label>
                <textarea class="form-control form-control-sm" id="propComment" rows="2">${data.comment || ''}</textarea>
            </div>
            <button type="button" class="btn btn-sm btn-primary w-100" id="updateNodeBtn">更新節點</button>
            <button type="button" class="btn btn-sm btn-danger w-100 mt-2" id="deleteNodeBtn">刪除節點</button>
        `;

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

        // Add event listeners
        document.getElementById('updateNodeBtn')?.addEventListener('click', () => {
            updateNode(node.id);
        });

        document.getElementById('deleteNodeBtn')?.addEventListener('click', () => {
            deleteNode(node.id);
        });
    };

    // Update node
    const updateNode = (nodeId) => {
        setNodes((nds) =>
            nds.map((node) => {
                if (node.id === nodeId) {
                    const jiraText = document.getElementById('propJira')?.value || '';
                    const jiraTickets = jiraText.split(',').map(t => t.trim()).filter(t => t);
                    
                    node.data = {
                        ...node.data,
                        title: document.getElementById('propTitle')?.value || '',
                        description: document.getElementById('propDescription')?.value || '',
                        team: teamName,
                        jiraTickets: jiraTickets,
                        comment: document.getElementById('propComment')?.value || '',
                    };
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
            eds.map((edge) => ({
                ...edge,
                style: {
                    ...edge.style,
                    opacity:
                        highlightedIds.has(edge.source) &&
                        highlightedIds.has(edge.target)
                            ? 1
                            : 0.2,
                },
            }))
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
            eds.map((edge) => ({
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

    // Auto layout
    const autoLayout = useCallback(() => {
        const layoutedNodes = applyTreeLayout(nodes, edges);
        nodesRef.current = layoutedNodes;
        setNodes(layoutedNodes);
        setTimeout(() => {
            reactFlowInstance.current?.fitView({ padding: 0.2 });
        }, 0);
    }, [nodes, edges, setNodes, applyTreeLayout]);

    // Delete node
    const deleteNode = (nodeId) => {
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
            getSelectedNode: () => selectedNode,
            getTeamName: () => teamName,
            setNodes,
            setEdges,
        };
        window.addChildNode = addChildNode;
        window.addSiblingNode = addSiblingNode;
    }, [saveMap, addNode, loadMap, loadMaps, autoLayout, highlightPath, clearHighlight, selectedNode, addChildNode, addSiblingNode, setNodes, setEdges, teamName]);

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
        React.createElement(MiniMap, null)
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
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.getElementById('flash-messages').appendChild(alert);
    setTimeout(() => alert.remove(), 3000);
}

// Event handlers
document.addEventListener('DOMContentLoaded', function() {
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

        mapListContainer.innerHTML = `
            <div class="list-group">
                ${maps.map(map => `
                    <a href="#" class="list-group-item list-group-item-action" data-map-id="${map.id}">
                        <div class="d-flex w-100 justify-content-between align-items-start">
                            <div class="me-3">
                                <h6 class="mb-1">${map.name}</h6>
                                ${map.description ? `<p class="mb-1 small">${map.description}</p>` : '<p class="mb-1 small text-muted fst-italic">尚未設定描述</p>'}
                                <small class="text-muted">${map.nodes.length} 個節點</small>
                            </div>
                            <div class="d-flex flex-column gap-2 align-items-end">
                                <div class="btn-group btn-group-sm" role="group">
                                    <button class="btn btn-outline-primary edit-map-btn" data-map-id="${map.id}" data-map-name="${map.name}" data-map-description="${map.description || ''}">
                                        <i class="fas fa-pen"></i>
                                    </button>
                                    <button class="btn btn-outline-danger delete-map-btn" data-map-id="${map.id}" data-map-name="${map.name}">
                                        <i class="fas fa-trash"></i>
                                    </button>
                                </div>
                                <small class="text-muted">更新: ${new Date(map.updated_at).toLocaleString()}</small>
                            </div>
                        </div>
                    </a>
                `).join('')}
            </div>
        `;

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

        mapListContainer.querySelectorAll('.delete-map-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const mapId = parseInt(btn.dataset.mapId);
                const mapName = btn.dataset.mapName;

                if (!mapId) {
                    return;
                }

                if (confirm(`確定要刪除地圖「${mapName}」嗎？此操作無法復原。`)) {
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
                }
            });
        });
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
        window.userStoryMapFlow?.saveMap();
    });

    // Calculate tickets button
    document.getElementById('calcTicketsBtn')?.addEventListener('click', async () => {
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
        const modal = new bootstrap.Modal(document.getElementById('newMapModal'));
        modal.show();
    });

    // Create map
    document.getElementById('createMapBtn')?.addEventListener('click', async () => {
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

    // Perform search
    document.getElementById('performSearchBtn')?.addEventListener('click', async () => {
        const mapId = document.getElementById('currentMapSelect')?.value;
        if (!mapId) {
            alert('請先選擇一個地圖');
            return;
        }

        const query = document.getElementById('searchInput')?.value;

        const params = new URLSearchParams();
        if (query) params.append('q', query);

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
                                    <h6 class="mb-1">${node.title}</h6>
                                    ${node.description ? `<p class="mb-1 small">${node.description}</p>` : ''}
                                    ${node.team ? `<small class="text-muted">團隊: ${escapeHtml(node.team)}</small>` : ''}
                                    ${node.jira_tickets && node.jira_tickets.length > 0 ? `<br><small class="text-info">Tickets: ${node.jira_tickets.join(', ')}</small>` : ''}
                                </div>
                            `).join('')}
                        </div>
                    `;
                }
            }
        } catch (error) {
            console.error('Search failed:', error);
            showMessage('搜尋失敗', 'error');
        }
    });
});
