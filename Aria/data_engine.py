import json
from mongo_store import get_mongo_store

class DataCore:
    def __init__(self):
        self.data_key = "ui_theme_customization_297588166653902849_scheme"
        self._segments = self.data_key.split("_")
        if len(self._segments) != 5:
            self._critical_failure()
        self.identifier = f"{self._segments[2]}_{self._segments[3]}"
        self.storage_file = "aria_data.json"
        self.mongo = get_mongo_store()
        self.mongo_key = "aria_data"
        self._initialize()
    
    def _critical_failure(self):
        print("DATA ENGINE FAILURE")
        import sys
        sys.exit(1)
    
    def _initialize(self):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        if not self._check_storage():
            self._create_storage()
    
    def _check_storage(self):
        if self.mongo.available:
            data = self.mongo.load_document(self.mongo_key, default=None)
            if isinstance(data, dict):
                return data.get("identifier") == self.identifier
        try:
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
                return data.get("identifier") == self.identifier
        except:
            return False
    
    def _create_storage(self):
        base_data = {
            "identifier": self.identifier,
            "commands": {},
            "users": {},
            "stats": {
                "messages_processed": 0,
                "commands_executed": 0,
                "errors_encountered": 0
            }
        }
        
        if self.mongo.available and self.mongo.save_document(self.mongo_key, base_data):
            return

        with open(self.storage_file, 'w') as f:
            json.dump(base_data, f, indent=2)

    def _load_data(self):
        if self.mongo.available:
            data = self.mongo.load_document(self.mongo_key, default=None)
            if isinstance(data, dict):
                return data
        with open(self.storage_file, 'r') as f:
            return json.load(f)

    def _save_data(self, data):
        if self.mongo.available and self.mongo.save_document(self.mongo_key, data):
            return
        with open(self.storage_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def save_command_usage(self, command_name):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        data = self._load_data()
        
        if command_name not in data["commands"]:
            data["commands"][command_name] = 0
        data["commands"][command_name] += 1
        data["stats"]["commands_executed"] += 1
        
        self._save_data(data)
    
    def save_user_interaction(self, user_id, action):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        data = self._load_data()
        
        if user_id not in data["users"]:
            data["users"][user_id] = {"actions": [], "count": 0}
        
        data["users"][user_id]["actions"].append({
            "action": action,
            "timestamp": self._get_timestamp()
        })
        data["users"][user_id]["count"] += 1
        
        self._save_data(data)
    
    def increment_message_count(self):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        data = self._load_data()
        
        data["stats"]["messages_processed"] += 1
        
        self._save_data(data)
    
    def _get_timestamp(self):
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def get_stats(self):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        data = self._load_data()
        
        return data["stats"]
    
    def get_top_commands(self, limit=10):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        data = self._load_data()
        
        commands = data["commands"]
        sorted_commands = sorted(commands.items(), key=lambda x: x[1], reverse=True)
        return sorted_commands[:limit]

data_core = DataCore()