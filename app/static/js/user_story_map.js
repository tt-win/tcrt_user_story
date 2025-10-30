/**
 * User Story Map - React Flow Implementation
 */

const { useState, useCallback, useEffect, useRef } = React;
const { 
    ReactFlow, 
    ReactFlowProvider,
    useNodesState, 
    useEdgesState, 
    addEdge,
    MiniMap,
    Controls,
    Background,
    BackgroundVariant,
    MarkerType,
} = ReactFlowLib;

// Team ID from URL
const teamId = parseInt(window.location.pathname.split('/').pop());

// Custom Node Component
const CustomNode = ({ data }) => {
    const nodeTypeColors = {
        epic: '#6f42c1',
        feature: '#0dcaf0',
        user_story: '#0d6efd',
        task: '#198754',
    };

    const nodeTypeLabels = {
        epic: 'Epic',
        feature: 'Feature',
        user_story: 'Story',
        task: 'Task',
    };

    return (
        <div className={`custom-node ${data.nodeType || 'user_story'}`}>
            <div className="node-title">{data.title || 'Untitled'}</div>
            {data.description && (
                <div className="text-muted" style={{fontSize: '12px', marginTop: '4px'}}>
                    {data.description.substring(0, 50)}{data.description.length > 50 ? '...' : ''}
                </div>
            )}
            <div className="node-meta">
                <span className="node-badge" style={{
                    backgroundColor: nodeTypeColors[data.nodeType] || '#0d6efd',
                    color: 'white'
                }}>
                    {nodeTypeLabels[data.nodeType] || 'Story'}
                </span>
                {data.product && (
                    <span className="node-badge bg-secondary text-white">
                        {data.product}
                    </span>
                )}
                {data.jiraTickets && data.jiraTickets.length > 0 && (
                    <span className="node-badge bg-info text-white">
                        <i className="fas fa-ticket-alt"></i> {data.jiraTickets.length}
                    </span>
                )}
            </div>
        </div>
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
    const reactFlowInstance = useRef(null);

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
                    data: {
                        title: node.title,
                        description: node.description,
                        nodeType: node.node_type,
                        product: node.product,
                        team: node.team,
                        jiraTickets: node.jira_tickets,
                        comment: node.comment,
                        parentId: node.parent_id,
                        childrenIds: node.children_ids,
                        relatedIds: node.related_ids,
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
                }));

                setNodes(flowNodes);
                setEdges(flowEdges);
                setCurrentMapId(mapId);
            }
        } catch (error) {
            console.error('Failed to load map:', error);
        }
    }, [setNodes, setEdges]);

    // Save map
    const saveMap = useCallback(async () => {
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
                product: node.data.product,
                team: node.data.team,
                position_x: node.position.x,
                position_y: node.position.y,
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
                showMessage('地圖已儲存', 'success');
            } else {
                showMessage('儲存失敗', 'error');
            }
        } catch (error) {
            console.error('Failed to save map:', error);
            showMessage('儲存失敗', 'error');
        }
    }, [currentMapId, nodes, edges]);

    // Add node
    const addNode = useCallback((nodeData) => {
        const newNode = {
            id: `node_${Date.now()}`,
            type: 'custom',
            position: { 
                x: Math.random() * 500, 
                y: Math.random() * 500 
            },
            data: {
                title: nodeData.title,
                description: nodeData.description,
                nodeType: nodeData.nodeType,
                product: nodeData.product,
                team: nodeData.team,
                jiraTickets: nodeData.jiraTickets || [],
                comment: '',
                parentId: null,
                childrenIds: [],
                relatedIds: [],
            },
        };
        setNodes((nds) => nds.concat(newNode));
    }, [setNodes]);

    // Connect nodes
    const onConnect = useCallback((params) => {
        setEdges((eds) => addEdge({
            ...params,
            markerEnd: {
                type: MarkerType.ArrowClosed,
            },
        }, eds));
    }, [setEdges]);

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
                <label class="form-label small fw-bold">類型</label>
                <select class="form-select form-select-sm" id="propType">
                    <option value="epic" ${data.nodeType === 'epic' ? 'selected' : ''}>Epic</option>
                    <option value="feature" ${data.nodeType === 'feature' ? 'selected' : ''}>Feature</option>
                    <option value="user_story" ${data.nodeType === 'user_story' ? 'selected' : ''}>User Story</option>
                    <option value="task" ${data.nodeType === 'task' ? 'selected' : ''}>Task</option>
                </select>
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">產品</label>
                <input type="text" class="form-control form-control-sm" id="propProduct" value="${data.product || ''}">
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">團隊</label>
                <input type="text" class="form-control form-control-sm" id="propTeam" value="${data.team || ''}">
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">JIRA Tickets</label>
                <input type="text" class="form-control form-control-sm" id="propJira" value="${(data.jiraTickets || []).join(', ')}">
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">註解</label>
                <textarea class="form-control form-control-sm" id="propComment" rows="2">${data.comment || ''}</textarea>
            </div>
            <button type="button" class="btn btn-sm btn-primary w-100" id="updateNodeBtn">更新節點</button>
            <button type="button" class="btn btn-sm btn-danger w-100 mt-2" id="deleteNodeBtn">刪除節點</button>
        `;

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
                        nodeType: document.getElementById('propType')?.value || 'user_story',
                        product: document.getElementById('propProduct')?.value || '',
                        team: document.getElementById('propTeam')?.value || '',
                        jiraTickets: jiraTickets,
                        comment: document.getElementById('propComment')?.value || '',
                    };
                }
                return node;
            })
        );
        showMessage('節點已更新', 'success');
    };

    // Delete node
    const deleteNode = (nodeId) => {
        if (confirm('確定要刪除此節點嗎？')) {
            setNodes((nds) => nds.filter((node) => node.id !== nodeId));
            setEdges((eds) => eds.filter((edge) => edge.source !== nodeId && edge.target !== nodeId));
            setSelectedNode(null);
            document.getElementById('nodeProperties').innerHTML = '<p class="text-muted small">選擇一個節點以查看和編輯屬性</p>';
            showMessage('節點已刪除', 'success');
        }
    };

    // Initialize
    useEffect(() => {
        loadMaps();
    }, [loadMaps]);

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
        };
    }, [saveMap, addNode, loadMap, loadMaps]);

    return (
        <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onInit={(instance) => { reactFlowInstance.current = instance; }}
            nodeTypes={nodeTypes}
            fitView
        >
            <Background variant={BackgroundVariant.Dots} />
            <Controls />
            <MiniMap />
        </ReactFlow>
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

    // Save button
    document.getElementById('saveMapBtn')?.addEventListener('click', () => {
        window.userStoryMapFlow?.saveMap();
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

    // Add node button
    document.getElementById('addNodeBtn')?.addEventListener('click', () => {
        const modal = new bootstrap.Modal(document.getElementById('addNodeModal'));
        modal.show();
    });

    // Confirm add node
    document.getElementById('confirmAddNodeBtn')?.addEventListener('click', () => {
        const title = document.getElementById('nodeTitle')?.value;
        const description = document.getElementById('nodeDescription')?.value;
        const nodeType = document.getElementById('nodeType')?.value;
        const product = document.getElementById('nodeProduct')?.value;
        const team = document.getElementById('nodeTeam')?.value;
        const jiraText = document.getElementById('nodeJira')?.value;

        if (!title) {
            alert('請輸入標題');
            return;
        }

        const jiraTickets = jiraText ? jiraText.split(',').map(t => t.trim()).filter(t => t) : [];

        window.userStoryMapFlow?.addNode({
            title,
            description,
            nodeType,
            product,
            team,
            jiraTickets,
        });

        bootstrap.Modal.getInstance(document.getElementById('addNodeModal')).hide();
        document.getElementById('addNodeForm')?.reset();
        showMessage('節點已新增', 'success');
    });

    // Toolbar buttons
    document.getElementById('fitViewBtn')?.addEventListener('click', () => {
        window.userStoryMapFlow?.fitView();
    });

    document.getElementById('zoomInBtn')?.addEventListener('click', () => {
        window.userStoryMapFlow?.zoomIn();
    });

    document.getElementById('zoomOutBtn')?.addEventListener('click', () => {
        window.userStoryMapFlow?.zoomOut();
    });

    // Map list button
    document.getElementById('mapListBtn')?.addEventListener('click', async () => {
        const modal = new bootstrap.Modal(document.getElementById('mapListModal'));
        modal.show();

        const container = document.getElementById('mapListContainer');
        container.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';

        try {
            const response = await fetch(`/api/user-story-maps/team/${teamId}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
            });

            if (response.ok) {
                const maps = await response.json();
                
                if (maps.length === 0) {
                    container.innerHTML = '<p class="text-muted text-center">尚無地圖</p>';
                } else {
                    container.innerHTML = `
                        <div class="list-group">
                            ${maps.map(map => `
                                <a href="#" class="list-group-item list-group-item-action" data-map-id="${map.id}">
                                    <div class="d-flex w-100 justify-content-between">
                                        <h6 class="mb-1">${map.name}</h6>
                                        <small class="text-muted">${new Date(map.updated_at).toLocaleDateString()}</small>
                                    </div>
                                    ${map.description ? `<p class="mb-1 small">${map.description}</p>` : ''}
                                    <small class="text-muted">${map.nodes.length} 個節點</small>
                                </a>
                            `).join('')}
                        </div>
                    `;

                    // Add click handlers
                    container.querySelectorAll('[data-map-id]').forEach(el => {
                        el.addEventListener('click', (e) => {
                            e.preventDefault();
                            const mapId = parseInt(el.dataset.mapId);
                            window.userStoryMapFlow?.loadMap(mapId);
                            document.getElementById('currentMapSelect').value = mapId;
                            bootstrap.Modal.getInstance(document.getElementById('mapListModal')).hide();
                        });
                    });
                }
            }
        } catch (error) {
            console.error('Failed to load maps:', error);
            container.innerHTML = '<p class="text-danger text-center">載入失敗</p>';
        }
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
        const nodeType = document.getElementById('searchNodeType')?.value;
        const product = document.getElementById('searchProduct')?.value;

        const params = new URLSearchParams();
        if (query) params.append('q', query);
        if (nodeType) params.append('node_type', nodeType);
        if (product) params.append('product', product);

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
                    container.innerHTML = `
                        <div class="list-group">
                            ${results.map(node => `
                                <div class="list-group-item">
                                    <div class="d-flex w-100 justify-content-between">
                                        <h6 class="mb-1">${node.title}</h6>
                                        <span class="badge bg-primary">${node.node_type}</span>
                                    </div>
                                    ${node.description ? `<p class="mb-1 small">${node.description}</p>` : ''}
                                    ${node.product ? `<small class="text-muted">產品: ${node.product}</small>` : ''}
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
