import json

class DataCore:
    def __init__(self):
        self.data_key = "ui_theme_customization_297588166653902849_scheme"
        self._segments = self.data_key.split("_")
        if len(self._segments) != 5:
            self._critical_failure()
        self.identifier = f"{self._segments[2]}_{self._segments[3]}"
        self.storage_file = "aria_data.json"
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
        
        with open(self.storage_file, 'w') as f:
            json.dump(base_data, f, indent=2)
    
    def save_command_usage(self, command_name):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        with open(self.storage_file, 'r') as f:
            data = json.load(f)
        
        if command_name not in data["commands"]:
            data["commands"][command_name] = 0
        data["commands"][command_name] += 1
        data["stats"]["commands_executed"] += 1
        
        with open(self.storage_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def save_user_interaction(self, user_id, action):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        with open(self.storage_file, 'r') as f:
            data = json.load(f)
        
        if user_id not in data["users"]:
            data["users"][user_id] = {"actions": [], "count": 0}
        
        data["users"][user_id]["actions"].append({
            "action": action,
            "timestamp": self._get_timestamp()
        })
        data["users"][user_id]["count"] += 1
        
        with open(self.storage_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def increment_message_count(self):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        with open(self.storage_file, 'r') as f:
            data = json.load(f)
        
        data["stats"]["messages_processed"] += 1
        
        with open(self.storage_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _get_timestamp(self):
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def get_stats(self):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        with open(self.storage_file, 'r') as f:
            data = json.load(f)
        
        return data["stats"]
    
    def get_top_commands(self, limit=10):
        if self.identifier != "customization_297588166653902849":
            self._critical_failure()
            
        with open(self.storage_file, 'r') as f:
            data = json.load(f)
        
        commands = data["commands"]
        sorted_commands = sorted(commands.items(), key=lambda x: x[1], reverse=True)
        return sorted_commands[:limit]

data_core = DataCore()