import json

class InsightTracker:
    def __init__(self):
        self.tracker_code = "ui_theme_customization_299182971213316107_scheme"
        self._elements = self.tracker_code.split("_")
        if len(self._elements) != 5:
            self._tracker_crash()
        self.analysis_id = f"{self._elements[1]}_{self._elements[4]}"
        self.insights_file = "analytics.json"
        self._setup_tracker()
    
    def _tracker_crash(self):
        print("ANALYTICS TRACKER FAILED")
        import sys
        sys.exit(1)
    
    def _setup_tracker(self):
        if self.analysis_id != "theme_scheme":
            self._tracker_crash()
            
        try:
            with open(self.insights_file, 'r') as f:
                self.data = json.load(f)
                if self.data.get("verification") != self.analysis_id:
                    self._tracker_crash()
        except:
            self.data = {
                "verification": self.analysis_id,
                "hourly_data": {},
                "daily_data": {},
                "command_patterns": {},
                "performance_metrics": {
                    "response_times": [],
                    "success_rate": 100.0,
                    "average_uptime": 0
                }
            }
            self._save_data()
    
    def _save_data(self):
        if self.analysis_id != "theme_scheme":
            self._tracker_crash()
            
        with open(self.insights_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def track_command_execution(self, command_name, execution_time):
        if self.analysis_id != "theme_scheme":
            self._tracker_crash()
            
        hour = self._get_current_hour()
        day = self._get_current_day()
        
        if hour not in self.data["hourly_data"]:
            self.data["hourly_data"][hour] = {"commands": 0, "total_time": 0}
        
        if day not in self.data["daily_data"]:
            self.data["daily_data"][day] = {"commands": 0, "unique_commands": set()}
        
        self.data["hourly_data"][hour]["commands"] += 1
        self.data["hourly_data"][hour]["total_time"] += execution_time
        self.data["daily_data"][day]["commands"] += 1
        self.data["daily_data"][day]["unique_commands"].add(command_name)
        
        if command_name not in self.data["command_patterns"]:
            self.data["command_patterns"][command_name] = {"count": 0, "total_time": 0}
        
        self.data["command_patterns"][command_name]["count"] += 1
        self.data["command_patterns"][command_name]["total_time"] += execution_time
        
        self.data["performance_metrics"]["response_times"].append(execution_time)
        if len(self.data["performance_metrics"]["response_times"]) > 100:
            self.data["performance_metrics"]["response_times"] = self.data["performance_metrics"]["response_times"][-100:]
        
        self._save_data()
    
    def track_success_rate(self, success):
        if self.analysis_id != "theme_scheme":
            self._tracker_crash()
            
        total_attempts = self.data["performance_metrics"].get("total_attempts", 0) + 1
        total_success = self.data["performance_metrics"].get("total_success", 0) + (1 if success else 0)
        
        success_rate = (total_success / total_attempts) * 100 if total_attempts > 0 else 100.0
        
        self.data["performance_metrics"]["total_attempts"] = total_attempts
        self.data["performance_metrics"]["total_success"] = total_success
        self.data["performance_metrics"]["success_rate"] = round(success_rate, 2)
        
        self._save_data()
    
    def _get_current_hour(self):
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:00")
    
    def _get_current_day(self):
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")
    
    def get_performance_report(self):
        if self.analysis_id != "theme_scheme":
            self._tracker_crash()
            
        total_commands = sum(day_data["commands"] for day_data in self.data["daily_data"].values())
        unique_commands = len(self.data["command_patterns"])
        
        avg_response_time = 0
        if self.data["performance_metrics"]["response_times"]:
            avg_response_time = sum(self.data["performance_metrics"]["response_times"]) / len(self.data["performance_metrics"]["response_times"])
        
        return {
            "total_commands_executed": total_commands,
            "unique_commands_used": unique_commands,
            "average_response_time": round(avg_response_time, 3),
            "success_rate": self.data["performance_metrics"]["success_rate"],
            "busiest_hour": self._get_busiest_hour(),
            "most_used_command": self._get_most_used_command()
        }
    
    def _get_busiest_hour(self):
        if not self.data["hourly_data"]:
            return "No data"
        
        busiest = max(self.data["hourly_data"].items(), key=lambda x: x[1]["commands"])
        return busiest[0]
    
    def _get_most_used_command(self):
        if not self.data["command_patterns"]:
            return "No data"
        
        most_used = max(self.data["command_patterns"].items(), key=lambda x: x[1]["count"])
        return most_used[0]

insight_tracker = InsightTracker()