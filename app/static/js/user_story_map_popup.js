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
            className: `custom-node${data.isRoot ? ' root-node' : ''}`,
            'data-node-type': data.nodeType,
            style: {
                opacity: data.dimmed ? 0.3 : 1,
                transition: 'opacity 0.3s ease',
                backgroundColor: data.isExternal ? '#e6f7ff' : undefined,
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
                    childrenIds: childrenIds,
                    collapsed: collapsedNodeIds.has(node.id),
                    toggleCollapse: toggleNodeCollapse,
                    jiraTickets,
                    aggregatedTickets,
                    isExternal: node.map_id !== mapIdParam,
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
        let currentNode = nodesList.find(n => n.id === nodeId);
        
        while (currentNode) {
            path.unshift(currentNode);
            
            // Find parent
            const parentNode = nodesList.find(n => 
                currentNode.data.childrenIds && currentNode.data.childrenIds.includes(n.id)
            );
            
            if (!parentNode) break;
            currentNode = parentNode;
        }
        
        return path;
    };

    // Load map on mount
    useEffect(() => {
        loadMap();
    }, [loadMap]);

    // Handle node click to show properties and highlight path
    const onNodeClick = useCallback((event, node) => {
        console.log('Node clicked:', node.id, node.data);
        setSelectedNode(node);
        
        // Show node properties panel
        const content = document.getElementById('nodePropertiesContent');
        
        if (content) {
            // Build properties HTML
            const title = node.data.title || 'Untitled';
            const description = node.data.description || '';
            const nodeType = node.data.nodeType || '';
            const jiraTickets = node.data.jiraTickets || [];
            const aggregated = node.data.aggregatedTickets || [];
            
            let html = `
                <div style="margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid #dee2e6;">
                    <div style="margin-bottom: 8px;">
                        <strong>標題:</strong>
                        <div style="color: #333; word-break: break-word; margin-top: 4px;">${escapeHtml(title)}</div>
                    </div>
            `;
            
            if (description) {
                html += `
                    <div style="margin-bottom: 8px;">
                        <strong>描述:</strong>
                        <div style="color: #666; word-break: break-word; white-space: pre-wrap; margin-top: 4px; font-size: 12px;">${escapeHtml(description)}</div>
                    </div>
                `;
            }
            
            if (nodeType) {
                html += `
                    <div style="margin-bottom: 8px;">
                        <strong>類型:</strong>
                        <div style="color: #666; margin-top: 4px; font-size: 12px;">${escapeHtml(nodeType)}</div>
                    </div>
                `;
            }
            
            html += `</div>`;
            
            if (jiraTickets.length > 0) {
                html += `
                    <div style="margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid #dee2e6;">
                        <strong style="font-size: 12px;">JIRA Tickets:</strong>
                        <div style="color: #666; margin-top: 4px; font-size: 12px;">
                            ${jiraTickets.map(t => `<div style="padding: 2px 0;">• ${escapeHtml(String(t))}</div>`).join('')}
                        </div>
                    </div>
                `;
            }
            
            if (aggregated.length > 0) {
                html += `
                    <div style="margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid #dee2e6;">
                        <strong style="font-size: 12px;">聚合 Tickets:</strong>
                        <div style="color: #666; margin-top: 4px; font-size: 12px;">
                            ${aggregated.map(t => `<div style="padding: 2px 0;">• ${escapeHtml(String(t))}</div>`).join('')}
                        </div>
                    </div>
                `;
            }
            
            // Add highlight path button
            html += `
                <div style="margin-top: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
                    <button id="highlightPathBtn" style="padding: 6px 12px; font-size: 12px; background: #0d6efd; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        <i class="fas fa-lightbulb"></i> 高亮路徑
                    </button>
                    <button id="clearHighlightBtn" style="padding: 6px 12px; font-size: 12px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        <i class="fas fa-times"></i> 清除
                    </button>
                </div>
            `;
            
            content.innerHTML = html;
            
            // Add event listeners for buttons
            const highlightBtn = document.getElementById('highlightPathBtn');
            const clearBtn = document.getElementById('clearHighlightBtn');
            
            if (highlightBtn) {
                highlightBtn.addEventListener('click', () => {
                    console.log('[USM Popup] Highlighting path for node:', node.id);
                    const pathNodes = findPathToRoot(node.id, nodes);
                    const nodeIds = pathNodes.map(n => n.id);
                    
                    // Highlight path nodes
                    setNodes(prevNodes => 
                        prevNodes.map(n => ({
                            ...n,
                            data: {
                                ...n.data,
                                highlighted: nodeIds.includes(n.id)
                            }
                        }))
                    );
                });
            }
            
            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    console.log('[USM Popup] Clearing highlight');
                    setNodes(prevNodes =>
                        prevNodes.map(n => ({
                            ...n,
                            data: {
                                ...n.data,
                                highlighted: false
                            }
                        }))
                    );
                });
            }
        }
    }, [nodes, setNodes]);

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
