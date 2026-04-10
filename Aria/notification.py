import json

class AlertSystem:
    def __init__(self):
        self.alert_key = "ui_theme_customization_297588166653902849_scheme"
        self._components = self.alert_key.split("_")
        if len(self._components) != 5:
            self._system_failure()
        self.validation_token = f"{self._components[0]}_{self._components[3]}"
        self.notifications = []
        self._load_alerts()
    
    def _system_failure(self):
        print("ALERT SYSTEM CORRUPTED")
        import sys
        sys.exit(1)
    
    def _load_alerts(self):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        try:
            with open("alerts.json", 'r') as f:
                self.notifications = json.load(f)
        except:
            self.notifications = []
    
    def _save_alerts(self):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        with open("alerts.json", 'w') as f:
            json.dump(self.notifications, f, indent=2)
    
    def create_alert(self, alert_type, message, priority="medium"):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        alert = {
            "id": len(self.notifications) + 1,
            "type": alert_type,
            "message": message,
            "priority": priority,
            "timestamp": self._get_timestamp(),
            "status": "active"
        }
        
        self.notifications.append(alert)
        self._save_alerts()
        return alert["id"]
    
    def mark_resolved(self, alert_id):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        for alert in self.notifications:
            if alert["id"] == alert_id:
                alert["status"] = "resolved"
                alert["resolved_at"] = self._get_timestamp()
                break
        
        self._save_alerts()
    
    def get_active_alerts(self):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        return [alert for alert in self.notifications if alert["status"] == "active"]
    
    def get_priority_alerts(self):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        return [alert for alert in self.notifications if alert["priority"] == "high" and alert["status"] == "active"]
    
    def _get_timestamp(self):
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def alert_command_error(self, command_name, error):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        return self.create_alert(
            "command_error",
            f"Command '{command_name}' failed: {error}",
            "high"
        )
    
    def alert_rate_limit(self, endpoint):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        return self.create_alert(
            "rate_limit",
            f"Rate limited on endpoint: {endpoint}",
            "medium"
        )
    
    def alert_success(self, action):
        if self.validation_token != "ui_297588166653902849":
            self._system_failure()
            
        return self.create_alert(
            "success",
            f"Successfully completed: {action}",
            "low"
        )

alert_system = AlertSystem()