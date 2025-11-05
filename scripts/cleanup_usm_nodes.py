#!/usr/bin/env python3
"""
Script to clean up inconsistent USM node data in maps.
This fixes issues where nodes from other maps were incorrectly added to a map's nodes list.
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.user_story_map_db import get_usm_db, UserStoryMapDB, UserStoryMapNodeDB
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def cleanup_inconsistent_nodes():
    """Remove nodes from map.nodes that don't belong to that map"""
    async for usm_db in get_usm_db():
        # Get all maps
        result = await usm_db.execute(select(UserStoryMapDB))
        maps = result.scalars().all()

        for map_db in maps:
            print(f"Processing map {map_db.id}: {map_db.name}")

            if not map_db.nodes:
                continue

            # Get actual nodes for this map from node table
            node_result = await usm_db.execute(
                select(UserStoryMapNodeDB.node_id).where(UserStoryMapNodeDB.map_id == map_db.id)
            )
            actual_node_ids = {row.node_id for row in node_result}

            # Filter nodes in map.nodes to only include those that belong to this map
            cleaned_nodes = []
            removed_count = 0

            for node in map_db.nodes:
                node_id = node.get('id')
                if node_id in actual_node_ids:
                    cleaned_nodes.append(node)
                else:
                    print(f"  Removing inconsistent node {node_id} from map {map_db.id}")
                    removed_count += 1

            if removed_count > 0:
                print(f"  Removed {removed_count} inconsistent nodes from map {map_db.id}")
                map_db.nodes = cleaned_nodes
                await usm_db.commit()
            else:
                print(f"  No inconsistent nodes found in map {map_db.id}")
        break  # Only process once since it's a generator


if __name__ == "__main__":
    asyncio.run(cleanup_inconsistent_nodes())
    print("Cleanup completed.")</content>
<parameter name="filePath">scripts/cleanup_usm_nodes.py