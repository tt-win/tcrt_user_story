        // Ensure React Flow is available in window scope
        if (typeof window.ReactFlow === 'undefined') {
            console.warn('Attempting to use global ReactFlow variable');
            if (typeof ReactFlow !== 'undefined') {
                window.ReactFlow = ReactFlow;
            } else {
                console.error('React Flow failed to load. Check CDN availability.');
            }
        }
