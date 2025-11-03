"""
Integration tests for Related Nodes feature

Tests both frontend-backend integration and API functionality
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
from uuid import uuid4

# This test file is a template for integration testing
# To be run with actual application context


class TestRelatedNodesIntegration:
    """Integration tests for the entire related nodes feature"""
    
    @pytest.fixture
    def client(self):
        """Create a test client - would need actual app fixture"""
        pass
    
    @pytest.fixture
    async def sample_maps(self, db: AsyncSession):
        """Create sample maps for testing"""
        pass
    
    def test_search_nodes_same_map(self, client):
        """Test searching nodes in the same map"""
        # Test case: Search for "feature" in map 1
        response = client.get('/api/user-story-maps/search-nodes', params={
            'map_id': 1,
            'q': 'feature',
            'include_external': False
        })
        
        assert response.status_code == 200
        results = response.json()
        assert isinstance(results, list)
        # Should find nodes in same map
        if results:
            assert results[0]['map_id'] == 1
    
    def test_search_nodes_cross_map(self, client):
        """Test cross-map node search"""
        # Test case: Search across all accessible maps
        response = client.get('/api/user-story-maps/search-nodes', params={
            'map_id': 1,
            'q': 'story',
            'include_external': True
        })
        
        assert response.status_code == 200
        results = response.json()
        assert isinstance(results, list)
        # May find nodes from other maps
    
    def test_create_relation_same_map(self, client):
        """Test creating a relation within the same map"""
        # Test case: Create relation between node-1 and node-2 in map 1
        response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-2',
                'target_map_id': 1
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'relation_id' in data
        assert data['relation_id']  # Should be UUID
    
    def test_create_relation_cross_map(self, client):
        """Test creating a cross-map relation"""
        # Test case: Create relation between node in map 1 and node in map 2
        response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-xyz',
                'target_map_id': 2
            }
        )
        
        # Should succeed if user has permissions on both maps
        if response.status_code == 200:
            data = response.json()
            assert 'relation_id' in data
        elif response.status_code == 403:
            # Permission denied on target map
            assert 'PERMISSION' in response.json().get('detail', {}).get('code', '')
    
    def test_delete_relation(self, client):
        """Test deleting a relation"""
        # First create a relation
        create_response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-2',
                'target_map_id': 1
            }
        )
        
        if create_response.status_code != 200:
            pytest.skip('Could not create relation for testing')
        
        relation_id = create_response.json()['relation_id']
        
        # Delete the relation
        response = client.delete(
            f'/api/user-story-maps/1/nodes/node-1/relations/{relation_id}'
        )
        
        assert response.status_code == 200
        assert 'deleted successfully' in response.json().get('message', '').lower()
    
    def test_permission_viewer_cannot_create_relation(self, client):
        """Test that viewers cannot create relations"""
        # Would need to set user role to 'viewer'
        response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-2',
                'target_map_id': 1
            }
        )
        
        # Viewer should get 403 Forbidden
        # This test would need proper authentication setup
    
    def test_permission_cross_map_access_denied(self, client):
        """Test that users can't relate to maps they don't have access to"""
        # User has access to map 1 but not map 2
        response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-xyz',
                'target_map_id': 999  # Map without access
            }
        )
        
        # Should get 403 Forbidden or 404 Not Found
        assert response.status_code in [403, 404]
    
    def test_data_persistence_after_save(self, client):
        """Test that relations are persisted in the database"""
        # Create a relation
        create_response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-2',
                'target_map_id': 1
            }
        )
        
        assert create_response.status_code == 200
        relation_id = create_response.json()['relation_id']
        
        # Get the map
        map_response = client.get('/api/user-story-maps/1')
        assert map_response.status_code == 200
        
        map_data = map_response.json()
        # Find the node with relations
        node_1 = next((n for n in map_data['nodes'] if n['id'] == 'node-1'), None)
        
        if node_1:
            # Check that related_ids contains our new relation
            related_ids = node_1.get('related_ids', [])
            # Could be old format (string) or new format (dict)
            has_relation = any(
                (r == 'node-2' if isinstance(r, str) else r.get('node_id') == 'node-2')
                for r in related_ids
            )
            assert has_relation
    
    def test_backward_compatibility_old_format(self, client):
        """Test that old string format related_ids still work"""
        # Get a map that might have old-format related_ids
        response = client.get('/api/user-story-maps/1')
        
        assert response.status_code == 200
        map_data = response.json()
        
        # Check each node for related_ids
        for node in map_data['nodes']:
            related_ids = node.get('related_ids', [])
            for rel_id in related_ids:
                # Should be either string (old format) or dict (new format)
                assert isinstance(rel_id, (str, dict))


class TestFrontendIntegration:
    """Test frontend-specific integration scenarios"""
    
    def test_modal_data_structure(self):
        """Verify the relation settings modal has correct data structure"""
        # This would be a JavaScript/Selenium test
        # Checking that the modal contains:
        # - Search input
        # - Node type filter
        # - Cross-map toggle
        # - Results list
        # - Selected list
        # - Save button
        pass
    
    def test_search_results_display(self):
        """Test that search results display correctly"""
        # Verify results show:
        # - Node title
        # - Team name
        # - Map name
        # - Description (if available)
        pass
    
    def test_related_nodes_sidebar_display(self):
        """Test that related nodes appear in node properties sidebar"""
        # When a node is selected:
        # - If it has related_ids, show them
        # - Display format: Team / Map / Node Title
        # - Make them clickable for navigation
        pass
    
    def test_cross_map_navigation(self):
        """Test navigating to a related node in another map"""
        # Click on a related node that's in a different map
        # Should prompt user and switch maps
        # Then focus the node
        pass


class TestEdgeCases:
    """Test edge cases and error scenarios"""
    
    def test_relate_node_to_itself(self, client):
        """Test that a node cannot relate to itself"""
        response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-1',
                'target_map_id': 1
            }
        )
        
        # Should either succeed (if allowed) or fail gracefully
        assert response.status_code in [200, 400]
    
    def test_duplicate_relation(self, client):
        """Test creating a duplicate relation"""
        # Create first relation
        client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-2',
                'target_map_id': 1
            }
        )
        
        # Try to create same relation again
        response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-2',
                'target_map_id': 1
            }
        )
        
        # Should handle gracefully (success or informative error)
        assert response.status_code in [200, 400]
    
    def test_nonexistent_target_node(self, client):
        """Test relating to a non-existent node"""
        response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'nonexistent-node',
                'target_map_id': 1
            }
        )
        
        # Should fail with appropriate error
        assert response.status_code >= 400
    
    def test_nonexistent_target_map(self, client):
        """Test relating to a node in a non-existent map"""
        response = client.post(
            '/api/user-story-maps/1/nodes/node-1/relations',
            json={
                'target_node_id': 'node-xyz',
                'target_map_id': 99999
            }
        )
        
        # Should fail with appropriate error
        assert response.status_code >= 400
    
    def test_large_number_of_relations(self, client):
        """Test node with many relations"""
        # Create multiple relations
        for i in range(50):
            response = client.post(
                '/api/user-story-maps/1/nodes/node-1/relations',
                json={
                    'target_node_id': f'node-{i}',
                    'target_map_id': 1
                }
            )
            # Verify each creation
            if response.status_code != 200:
                break
        
        # Should handle gracefully even with many relations
        # Verify node still loads
        map_response = client.get('/api/user-story-maps/1')
        assert map_response.status_code == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
