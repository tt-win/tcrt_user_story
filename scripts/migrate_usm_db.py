"""
Database Migration Script for User Story Map Enhancements
Adds new fields: team_tags, aggregated_tickets, and level
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.user_story_map_db import init_usm_db, get_usm_db, UserStoryMapDB
from sqlalchemy import select


async def migrate():
    """Migrate existing User Story Map data"""
    print("Starting migration...")
    
    # Initialize database (will add new columns if they don't exist)
    await init_usm_db()
    print("✓ Database schema updated")
    
    # Update existing data
    async for db in get_usm_db():
        try:
            result = await db.execute(select(UserStoryMapDB))
            maps = result.scalars().all()
            
            print(f"Found {len(maps)} maps to migrate...")
            
            for map_db in maps:
                nodes = map_db.nodes or []
                updated = False
                
                for node in nodes:
                    # Add team_tags if missing
                    if 'team_tags' not in node:
                        node['team_tags'] = []
                        updated = True
                    
                    # Add aggregated_tickets if missing
                    if 'aggregated_tickets' not in node:
                        node['aggregated_tickets'] = []
                        updated = True
                    
                    # Add level if missing
                    if 'level' not in node:
                        node['level'] = 0
                        updated = True
                    
                    # Migrate old team field to team_tags if needed
                    if node.get('team') and not node['team_tags']:
                        node['team_tags'] = [{
                            'team_name': node['team'],
                            'labels': [],
                            'comment': None
                        }]
                        updated = True
                
                if updated:
                    map_db.nodes = nodes
                    await db.commit()
                    print(f"✓ Migrated map: {map_db.name} (ID: {map_db.id})")
            
            print("\n✅ Migration completed successfully!")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            await db.rollback()
            raise
        finally:
            break


if __name__ == "__main__":
    print("User Story Map Database Migration")
    print("=" * 50)
    asyncio.run(migrate())
