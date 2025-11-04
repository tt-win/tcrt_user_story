/**
 * User Story Map Popup View - Read-only display
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

// Get mapId and teamId from URL parameters
const urlParams = new URLSearchParams(window.location.search);
const mapIdParam = parseInt(urlParams.get('mapId'));
const teamIdParam = parseInt(urlParams.get('teamId'));

// Relation edge options (same as main view)
const RELATION_EDGE_PATH_OPTIONS = { offset: 120, borderRadius: 18 };

// HTML sanitization utility
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

    const nodeTypeColors = {
        root: '#6f42c1',
        feature_category: '#87ceeb',
        user_story: '#dda0dd',
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
            className: `custom-node${data.isRoot ? ' root-node' : ''}${data.highlighted ? ' highlighted' : ''}`,
            'data-node-type': data.nodeType,
            style: {
                opacity: data.dimmed ? 0.3 : 1,
                transition: 'opacity 0.3s ease',
                backgroundColor: data.isExternal ? '#e6f7ff' : undefined,
                borderColor: data.highlighted ? '#ff6b35' : undefined,
                boxShadow: data.highlighted ? '0 0 0 3px rgba(255, 107, 53, 0.35)' : undefined,
            }
        },
        React.createElement(Handle, { type: 'target', position: Position.Top, id: 'top' }),
        React.createElement(Handle, { type: 'source', position: Position.Bottom, id: 'bottom' }),
        React.createElement(Handle, { type: 'target', position: Position.Left, id: 'left' }),
        React.createElement(Handle, { type: 'source', position: Position.Right, id: 'right' }),
        React.createElement(Handle, { type: 'target', position: Position.Right, id: 'right-target' }),
        collapseToggle,
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

// Main Flow Component - Simplified for popup
const UserStoryMapFlow = () => {
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [collapsedNodeIds, setCollapsedNodeIds] = useState(new Set());
    const [selectedNode, setSelectedNode] = useState(null);
    const [mapName, setMapName] = useState('User Story Map');
    const [highlightedNodeIds, setHighlightedNodeIds] = useState([]);
    const reactFlowInstance = useRef(null);

    // Load map data from API
    const loadMap = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            
            console.log('[USM Popup] URL params:', { mapIdParam, teamIdParam });
            
            if (!mapIdParam || !teamIdParam) {
                const errorMsg = `Missing parameters: mapId=${mapIdParam}, teamId=${teamIdParam}`;
                console.error('[USM Popup]', errorMsg);
                setError(errorMsg);
                return;
            }

            const token = localStorage.getItem('access_token');
            const headers = {
                'Content-Type': 'application/json',
            };
            if (token) {
                headers['Authorization'] = `Bearer ${token}`;
            }

            const apiUrl = `/api/user-story-maps/${mapIdParam}?team_id=${teamIdParam}`;
            console.log('[USM Popup] Fetching:', apiUrl);
            
            const response = await fetch(apiUrl, {
                headers: headers,
            });
            
            if (!response.ok) {
                const errorMsg = `Failed to load map: ${response.status} ${response.statusText}. URL: ${apiUrl}`;
                console.error('[USM Popup]', errorMsg);
                throw new Error(errorMsg);
            }

            const mapData = await response.json();
            console.log('[USM Popup] Map data loaded successfully');
            
            // Build nodes and edges from map data
            buildGraphFromMapData(mapData);
            
            // Fit view after short delay to ensure render
            setTimeout(() => {
                if (reactFlowInstance.current) {
                    reactFlowInstance.current.fitView({ padding: 0.2 });
                }
            }, 100);
        } catch (err) {
            console.error('Error loading map:', err);
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, []);

    // Build graph from map data
    const buildGraphFromMapData = (mapData) => {
        if (!mapData.nodes || mapData.nodes.length === 0) {
            console.warn('[USM Popup] No nodes in map data');
            setNodes([]);
            setEdges([]);
            return;
        }

        // Set map name
        if (mapData.name) {
            setMapName(mapData.name);
            document.getElementById('mapTitle').textContent = escapeHtml(mapData.name);
        }

        console.log('[USM Popup] Building graph with', mapData.nodes.length, 'nodes');
        
        // First, create React Flow nodes without positions
        const graphNodes = mapData.nodes.map(node => {
            const jiraTickets = (node.jira_tickets || []).filter(t => t && String(t).trim());
            const aggregatedTickets = (node.aggregated_tickets || []).filter(t => t && String(t).trim());
            const childrenIds = (node.children_ids || []);
            
            return {
                id: node.id,
                data: {
                    title: node.title,
                    description: node.description,
                    nodeType: node.node_type,
                    isRoot: !node.parent_id,
                    parentId: node.parent_id,
                    childrenIds: childrenIds,
                    collapsed: collapsedNodeIds.has(node.id),
                    toggleCollapse: toggleNodeCollapse,
                    jiraTickets,
                    aggregatedTickets,
                    isExternal: node.map_id !== mapIdParam,
                    team: node.team,
                    asA: node.as_a,
                    iWant: node.i_want,
                    soThat: node.so_that,
                    comment: node.comment,
                    relatedIds: node.related_ids,
                },
                position: { x: 0, y: 0 }, // Will be set by Dagre layout
                type: 'custom',
            };
        });

        // Create edges
        const graphEdges = [];
        mapData.nodes.forEach(node => {
            if (node.parent_id) {
                graphEdges.push({
                    id: `e-${node.parent_id}-${node.id}`,
                    source: node.parent_id,
                    target: node.id,
                    type: 'smoothstep',
                    animated: false,
                    sourceHandle: 'right',  // 從父節點右側
                    targetHandle: 'left',   // 到子節點左側
                });
            }

            // Add relation edges
            if (node.related_ids && Array.isArray(node.related_ids)) {
                node.related_ids.forEach((rel) => {
                    if (typeof rel === 'object' && rel.node_id) {
                        graphEdges.push({
                            id: `rel-${node.id}-${rel.node_id}`,
                            source: node.id,
                            target: rel.node_id,
                            type: 'smoothstep',
                            animated: true,
                            style: { stroke: '#ffc107', strokeWidth: 2, strokeDasharray: '5,5' },
                            markerEnd: { type: MarkerType.ArrowClosed, color: '#ffc107' },
                            pathOptions: RELATION_EDGE_PATH_OPTIONS,
                            sourceHandle: 'right',
                            targetHandle: 'right-target',
                        });
                    }
                });
            }
        });

        // Apply Dagre layout (same as main view)
        const layoutedNodes = applyDagreLayout(graphNodes, graphEdges);

        console.log('[USM Popup] Created', layoutedNodes.length, 'React Flow nodes');
        setNodes(layoutedNodes);

        console.log('[USM Popup] Created', graphEdges.length, 'edges');
        setEdges(graphEdges);
    };

    // Apply Dagre layout algorithm (same as main view)
    const applyDagreLayout = (nodes, edges) => {
        if (!window.dagre) {
            console.warn('[USM Popup] Dagre library not loaded, using default layout');
            return nodes;
        }

        const g = new window.dagre.graphlib.Graph();
        g.setGraph({ rankdir: 'LR', ranksep: 75, nodesep: 40 });
        g.setDefaultEdgeLabel(() => ({}));

        // Add nodes to graph
        nodes.forEach(node => {
            g.setNode(node.id, { width: 200, height: 110 });
        });

        // Add edges to graph
        edges.forEach(edge => {
            g.setEdge(edge.source, edge.target);
        });

        // Apply Dagre layout
        window.dagre.layout(g);

        // Update node positions from Dagre layout
        return nodes.map(node => {
            const position = g.node(node.id);
            return {
                ...node,
                position: { x: position.x, y: position.y },
                targetPosition: 'left',
                sourcePosition: 'right',
            };
        });
    };

    // Toggle node collapse state
    const toggleNodeCollapse = useCallback((nodeId) => {
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

    // Find path from node to root
    const findPathToRoot = (nodeId, nodesList) => {
        const path = [];
        let currentNodeId = nodeId;
        const visited = new Set();
        
        // Traverse up to root using parent_id
        while (currentNodeId && !visited.has(currentNodeId)) {
            visited.add(currentNodeId);
            const node = nodesList.find(n => n.id === currentNodeId);
            
            if (node) {
                path.unshift(node);
                // Move to parent
                currentNodeId = node.data.parentId;
            } else {
                break;
            }
        }
        
        console.log('[USM Popup] Path to root:', path.map(n => n.id));
        return path;
    };

    // Compute highlight details for a node (same as main view)
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
    }, []);

    // Apply highlight to all nodes and edges
    const applyHighlight = useCallback((activeIds, focusId, nodesById) => {
        if (!Array.isArray(activeIds) || activeIds.length === 0) {
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
                    .filter(edge => !edge.id.startsWith('relation-'))
                    .map((edge) => ({
                        ...edge,
                        style: {
                            ...edge.style,
                            opacity: 1,
                        },
                    }))
            );
            return;
        }

        const combinedIds = new Set();
        const relationPairs = new Map();
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
                        targetHandle: 'left',
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
    }, [setNodes, setEdges, computeHighlightDetails]);

    // Highlight path with multi-select support
    const highlightPath = useCallback((nodeId, isMultiSelect = false) => {
        if (!nodeId) return;
        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        if (!nodesById.has(nodeId)) {
            console.error('[Popup] Node not found:', nodeId);
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

    const clearHighlight = useCallback(() => {
        setHighlightedNodeIds([]);
        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        applyHighlight([], null, nodesById);
    }, [nodes, applyHighlight]);

    // Load map on mount
    useEffect(() => {
        loadMap();
    }, [loadMap]);

    // Handle node click to show properties and highlight path
    const onNodeClick = useCallback((event, node) => {
        console.log('Node clicked:', node.id, node.data);
        setSelectedNode(node);
        
        const content = document.getElementById('nodePropertiesContent');
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
        
        // Build related nodes section
        const relatedNodesHtml = data.relatedIds && data.relatedIds.length > 0
            ? `<div class="mb-3">
                    <label class="form-label small fw-bold">相關節點 (<span id="relatedNodesCount">${data.relatedIds.length}</span>)</label>
                    <div class="list-group list-group-sm" id="relatedNodesList" style="max-height: 200px; overflow-y: auto;">
                        ${(Array.isArray(data.relatedIds) ? data.relatedIds : []).map((rel, idx) => {
                            if (typeof rel === 'string') {
                                return `<div class="list-group-item small"><span class="text-muted">${escapeHtml(rel)}</span></div>`;
                            }
                            // Check if cross-map
                            const isCrossMap = rel.map_id && String(rel.map_id) !== String(mapIdParam);
                            return `
                                <div class="list-group-item small" style="display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px;">
                                    <div style="flex-grow: 1;">
                                        <strong>${escapeHtml(rel.display_title || rel.node_id)}</strong>
                                        <br>
                                        <small class="text-muted">
                                            ${escapeHtml(rel.team_name || '')} / ${escapeHtml(rel.map_name || '')}
                                        </small>
                                    </div>
                                    ${isCrossMap ? `<button type="button" class="btn btn-sm btn-outline-info" data-related-popup-idx="${idx}" title="在新視窗開啟外部地圖" style="flex-shrink: 0;"><i class="fas fa-external-link-alt"></i></button>` : ''}
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>`
            : '';
        
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
                    <p class="form-control-plaintext mb-0 small">${escapeHtml(data.asA || '')}</p>
                </div>
                
                <div class="mb-3">
                    <label class="form-label small fw-bold">I want <small class="text-muted">(需求描述)</small></label>
                    <p class="form-control-plaintext mb-0 small" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(data.iWant || '')}</p>
                </div>
                
                <div class="mb-3">
                    <label class="form-label small fw-bold">So that <small class="text-muted">(價值目的)</small></label>
                    <p class="form-control-plaintext mb-0 small" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(data.soThat || '')}</p>
                </div>
            `;
        }
        
        html += `
                <div class="mb-3">
                    <label class="form-label small fw-bold">JIRA Tickets</label>
                    <p class="form-control-plaintext mb-0 small">${data.jiraTickets && data.jiraTickets.length > 0 ? escapeHtml(data.jiraTickets.join(', ')) : '<span class="text-muted">無</span>'}</p>
                </div>
                
                ${aggregatedTicketsHtml}
                
                ${relatedNodesHtml}
                
                <div class="mb-3">
                    <label class="form-label small fw-bold">註解</label>
                    <p class="form-control-plaintext mb-0 small" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(data.comment || '')}</p>
                </div>
                
                <div style="margin-top: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
                    <button id="highlightPathBtn" data-node-id="${node.id}" style="padding: 6px 12px; font-size: 12px; background: #0d6efd; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        <i class="fas fa-lightbulb"></i> 高亮路徑
                    </button>
                    <button id="clearHighlightBtn" style="padding: 6px 12px; font-size: 12px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        <i class="fas fa-times"></i> 清除
                    </button>
                </div>
            </div>
        `;
        
        content.innerHTML = html;
        
        // Add event listeners for related node popup buttons
        document.querySelectorAll('[data-related-popup-idx]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.getAttribute('data-related-popup-idx'));
                const relatedNode = data.relatedIds?.[idx];
                
                if (!relatedNode) return;
                
                const mapId = relatedNode.map_id || relatedNode.mapId;
                const nodeId = relatedNode.node_id || relatedNode.nodeId;
                const mapName = relatedNode.map_name || `地圖 ${mapId}`;
                
                if (nodeId && mapId) {
                    console.log(`[USM Popup] Opening external map ${mapId}, node ${nodeId}`);
                    window.open(`/user-story-map-popup?mapId=${mapId}&teamId=${teamIdParam}`, '_blank', 'width=1200,height=800,toolbar=no');
                }
            });
        });
            
            // Add event listeners for buttons
            const highlightBtn = document.getElementById('highlightPathBtn');
            const clearBtn = document.getElementById('clearHighlightBtn');
            
            if (highlightBtn) {
                highlightBtn.addEventListener('click', (event) => {
                    const isMulti = event.ctrlKey || event.metaKey;
                    const nodeId = highlightBtn.getAttribute('data-node-id');
                    highlightPath(nodeId, isMulti);
                });
            }
            
            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    clearHighlight();
                });
            }
    }, [nodes, setNodes, mapIdParam, teamIdParam, highlightPath, clearHighlight]);

    // Handle canvas events
    const onConnect = useCallback((connection) => {
        // No-op in read-only mode
    }, []);

    // Get node color for minimap
    const getNodeColor = (node) => {
        const nodeTypeColors = {
            root: '#6f42c1',
            feature_category: '#87ceeb',
            user_story: '#dda0dd',
        };
        return nodeTypeColors[node.data.nodeType] || '#0d6efd';
    };

    if (loading) {
        return React.createElement(
            'div',
            {
                style: {
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    height: '100%',
                    fontSize: '16px',
                    color: '#6c757d'
                }
            },
            '加載中...'
        );
    }

    if (error) {
        return React.createElement(
            'div',
            {
                style: {
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    height: '100%',
                    fontSize: '16px',
                    color: '#dc3545',
                    textAlign: 'center',
                    padding: '20px'
                }
            },
            `錯誤: ${error}`
        );
    }

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

// Initialize the popup view
function initUserStoryMapPopup() {
    const container = document.getElementById('reactFlowWrapper');
    if (!container) {
        console.error('Container not found');
        return;
    }
    
    const root = ReactDOM.createRoot(container);
    root.render(
        React.createElement(ReactFlowProvider, null,
            React.createElement(UserStoryMapFlow, null)
        )
    );
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', initUserStoryMapPopup);
