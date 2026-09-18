"""
@file repositories/comments_repository.py
@description Handles comment queries and secure participant resolution.
"""

from typing import List, Dict, Any
from fastapi import HTTPException, status
from src.integrations.supabase_client import supabase_admin

class CommentsRepository:

    @staticmethod
    async def get_comments_by_memory_id(memory_id: str) -> List[Dict[str, Any]]:
        """Fetches raw comments without database embedding to avoid cache sync issues."""
        try:
            response = supabase_admin.table("comment")\
    .select("*")\
    .eq("memory_id", memory_id)\
    .is_("deleted_at", "null")\
    .is_("hidden_at", "null")\
    .order("created_at", desc=False)\
    .execute()

            data = response.data or []
            formatted_comments = []

            for item in data:
                comment_record = {**item}
                comment_record["author_name"] = "Family Member"  # Safe fallback (Just for mock data)
                formatted_comments.append(comment_record)
                
            return formatted_comments

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error while fetching comments: {str(e)}"
            )
                    
    @staticmethod
    async def insert_comment(payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """
        Securely resolves the user's memoir_participant_id for the given memoir 
        and inserts the comment using standard selection without embedding.
        """
        try:
            memoir_id = str(payload["memoir_id"])

            # 1. Look up the memoir_participant record for this user in this memoir
            participant_res = supabase_admin.table("memoir_participant")\
                .select("id")\
                .eq("memoir_id", memoir_id)\
                .eq("user_id", user_id)\
                .execute()

            participants = participant_res.data or []
            if not participants:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not an authorized participant of this memoir."
                )

            participant_id = participants[0]["id"]

            # 2. Insert the comment using the resolved participant ID
            insert_data = {
                "memoir_id": memoir_id,
                "memory_id": str(payload["memory_id"]) if payload.get("memory_id") else None,
                "media_asset_id": str(payload["media_asset_id"]) if payload.get("media_asset_id") else None,
                "parent_comment_id": str(payload["parent_comment_id"]) if payload.get("parent_comment_id") else None, 
                "author_participant_id": participant_id,
                "body": payload["body"].strip()
            }

            # Insert and select only the comment record itself (no embedded joins)
            # also normalize the insert (drop the non-standard .select() chain after .insert())
            response = supabase_admin.table("comment")\
            .insert(insert_data)\
            .execute()

            data = response.data or []
            if not data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to save comment record."
                )

            # Grab the newly inserted record from Supabase's list response
            inserted_record = data[0]

            result = {**inserted_record}
            result["author_name"] = "Family Member"  # Safe fallback matching your fetch method
            return result

        except HTTPException as he:
            raise he
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error inserting comment: {str(e)}"
            )