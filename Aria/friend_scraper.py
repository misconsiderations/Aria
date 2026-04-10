"""
Enhanced Friend Scraper - Extracts friends' user IDs and data
Fixes: Not gaining users' friends user IDs to load
"""

from typing import List, Dict, Any, Optional

class EnhancedFriendScraper:
    """Extract and manage friends' data with user IDs"""
    
    def __init__(self, api_client):
        self.api = api_client
        self.friends_cache = {}
        self.friend_ids = set()
        self.friend_details = {}
        
    def get_all_friend_ids(self, force_refresh: bool = True) -> List[str]:
        """
        Get all friend user IDs.
        Returns list of friend user IDs (strings)
        """
        if not force_refresh and self.friend_ids:
            return list(self.friend_ids)
        
        self.friend_ids.clear()
        self.friend_details.clear()
        
        try:
            # Get relationships (friends list)
            response = self.api.request("GET", "/users/@me/relationships")
            if not response or response.status_code != 200:
                print("[FriendScraper] Failed to fetch relationships")
                return []
            
            relationships = response.json()
            if not isinstance(relationships, list):
                print("[FriendScraper] Relationships not a list")
                return []
            
            # Extract friend user IDs and details
            for rel in relationships:
                if not isinstance(rel, dict):
                    continue
                
                rel_type = rel.get("type")
                user = rel.get("user", {})
                user_id = str(user.get("id", ""))
                
                if not user_id or not user_id.isdigit():
                    continue
                
                # Type 1 = friend, 2 = blocked, 3 = incoming request, 4 = outgoing request
                if rel_type == 1:  # Friends only
                    self.friend_ids.add(user_id)
                    self.friend_details[user_id] = {
                        "id": user_id,
                        "username": user.get("username", "Unknown"),
                        "global_name": user.get("global_name"),
                        "avatar": user.get("avatar"),
                        "discriminator": user.get("discriminator", "0000"),
                        "bot": user.get("bot", False),
                        "system": user.get("system", False),
                        "premium_type": user.get("premium_type"),
                        "public_flags": user.get("public_flags"),
                    }
            
            print(f"[FriendScraper] Found {len(self.friend_ids)} friends")
            return list(self.friend_ids)
            
        except Exception as e:
            print(f"[FriendScraper] Error fetching friends: {e}")
            return []
    
    def get_friend_details(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get cached details for a friend"""
        return self.friend_details.get(str(user_id))
    
    def get_all_friend_details(self) -> Dict[str, Dict[str, Any]]:
        """Get all cached friend details"""
        return dict(self.friend_details)
    
    def get_mutual_friends_with(self, target_user_id: str) -> List[str]:
        """
        Get list of mutual friends with another user.
        Returns list of mutual friend user IDs
        """
        try:
            response = self.api.request("GET", f"/users/{target_user_id}/profile")
            if not response or response.status_code != 200:
                return []
            
            profile = response.json()
            mutual_friends = profile.get("mutual_friends", [])
            
            mutual_ids = []
            for friend in mutual_friends:
                if isinstance(friend, dict):
                    fid = str(friend.get("id", ""))
                    if fid.isdigit():
                        mutual_ids.append(fid)
            
            return mutual_ids
            
        except Exception as e:
            print(f"[FriendScraper] Error getting mutual friends: {e}")
            return []
    
    def get_friend_status(self, user_id: str) -> Optional[str]:
        """
        Get friend's current status (online, idle, dnd, invisible)
        """
        try:
            response = self.api.request("GET", f"/users/{user_id}/profile")
            if not response or response.status_code != 200:
                return None
            
            profile = response.json()
            presence = profile.get("presence", {})
            return presence.get("status")
            
        except Exception as e:
            print(f"[FriendScraper] Error getting friend status: {e}")
            return None
    
    def batch_get_friend_info(self, limit: int = None) -> List[Dict[str, Any]]:
        """
        Get detailed info for all friends in batch.
        Returns list of friend details
        """
        ids = self.get_all_friend_ids()
        if limit:
            ids = ids[:limit]
        
        results = []
        for user_id in ids:
            details = self.friend_details.get(user_id)
            if details:
                results.append(details)
        
        return results
    
    def export_friends_to_dict(self) -> Dict[str, Any]:
        """Export all friend data as dictionary"""
        return {
            "friend_ids": list(self.friend_ids),
            "friend_count": len(self.friend_ids),
            "friend_details": dict(self.friend_details),
            "exported_at": __import__("time").time()
        }
    
    def get_friend_mutual_guilds(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get mutual servers/guilds with a friend"""
        try:
            response = self.api.request("GET", f"/users/{user_id}/profile")
            if not response or response.status_code != 200:
                return []
            
            profile = response.json()
            mutual_guilds = profile.get("mutual_guilds", [])
            
            return mutual_guilds[:limit]
            
        except Exception as e:
            print(f"[FriendScraper] Error getting mutual guilds: {e}")
            return []
