import os
import sys
from datetime import datetime
from typing import Optional


class TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
            except Exception:
                pass

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass

    def isatty(self):
        for stream in self.streams:
            try:
                if stream.isatty():
                    return True
            except Exception:
                continue
        return False

    def __getattr__(self, name):
        return getattr(self.streams[0], name)


class StructuredLogger:
    """Enhanced logging with category support"""
    CATEGORIES = {
        "GATEWAY": "\033[1;36m",      # Cyan - Gateway/Connection events
        "HISTORY": "\033[1;33m",      # Yellow - History/Profile operations
        "CUSTOM": "\033[1;35m",       # Magenta - Custom commands
        "HOST": "\033[1;32m",         # Green - Hosting operations
        "RPC": "\033[1;34m",          # Blue - Rich Presence/VR RPC
        "MAIN": "\033[1;37m",         # White - Main startup/events
        "ERROR": "\033[1;31m",        # Red - Errors
        "WARNING": "\033[1;33m",      # Yellow - Warnings
    }
    RESET = "\033[0m"
    
    def __init__(self, log_file=None):
        self.log_file = log_file
    
    def log(self, category: str, message: str, error: Optional[Exception] = None):
        """Log with category prefix"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color = self.CATEGORIES.get(category, "\033[1;37m")
        
        # Console output with color
        formatted_msg = f"[{timestamp}] {color}[{category}]{self.RESET} {message}"
        print(formatted_msg)
        
        # File output without color codes
        if self.log_file:
            try:
                file_msg = f"[{timestamp}] [{category}] {message}"
                if error:
                    file_msg += f"\n  Error: {str(error)}"
                self.log_file.write(file_msg + "\n")
                self.log_file.flush()
            except Exception:
                pass
    
    def gateway(self, message: str, error: Optional[Exception] = None):
        self.log("GATEWAY", message, error)
    
    def history(self, message: str, error: Optional[Exception] = None):
        self.log("HISTORY", message, error)
    
    def custom(self, message: str, error: Optional[Exception] = None):
        self.log("CUSTOM", message, error)
    
    def host(self, message: str, error: Optional[Exception] = None):
        self.log("HOST", message, error)
    
    def rpc(self, message: str, error: Optional[Exception] = None):
        self.log("RPC", message, error)
    
    def main(self, message: str, error: Optional[Exception] = None):
        self.log("MAIN", message, error)
    
    def error(self, message: str, exc: Optional[Exception] = None):
        self.log("ERROR", message, exc)
    
    def warning(self, message: str):
        self.log("WARNING", message)


def setup_file_logger(base_dir=None):
    if getattr(sys, "_aria_file_logger_enabled", False):
        return None

    root_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(root_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, f"aria-runtime-{datetime.now():%Y%m%d}.log")
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file.write(f"\n===== Aria session started {timestamp} =====\n")

    original_stdout = sys.stdout
    
    # Create structured logger instance
    structured_log = StructuredLogger(log_file)
    original_stderr = sys.stderr
    sys.stdout = TeeStream(original_stdout, log_file)
    sys.stderr = TeeStream(original_stderr, log_file)
    setattr(sys, "_aria_file_logger_enabled", True)
    setattr(sys, "_aria_log_path", log_path)
    return log_path
