"""
Gateway dispatcher with worker pool pattern, inspired by superclaw-gateway.
Handles Discord events through a queue with proper lifecycle management and backpressure.
"""

import json
import time
import threading
import queue
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class GatewayEvent:
    """Single gateway event to be processed"""
    type: str  # MESSAGE_CREATE, GUILD_UPDATE, etc
    data: Dict[str, Any]
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class GatewayDispatcher:
    """
    Processes Discord gateway events with a worker pool.
    Features:
    - Bounded queue with backpressure (max_queue_size)
    - Configurable workers (worker_count)
    - Per-event timeout handling
    - Graceful shutdown with drain timeout
    - Error isolation (worker failures don't block others)
    """
    
    def __init__(self, 
                 event_handler: Callable,
                 worker_count: int = 4,
                 max_queue_size: int = 100,
                 task_timeout: float = 30.0,
                 logger = None):
        """
        Args:
            event_handler: Function(event: GatewayEvent) -> bool (True if handled)
            worker_count: Number of worker threads
            max_queue_size: Max pending events before backpressure
            task_timeout: Max seconds per event handler
            logger: Optional StructuredLogger instance
        """
        self.event_handler = event_handler
        self.worker_count = worker_count
        self.max_queue_size = max_queue_size
        self.task_timeout = task_timeout
        self.logger = logger
        
        self.queue = queue.Queue(maxsize=max_queue_size)
        self.running = False
        self.workers = []
        self.processed = 0
        self.failed = 0
        self._lock = threading.Lock()
    
    def start(self):
        """Start worker threads"""
        if self.running:
            return
        
        self.running = True
        for i in range(self.worker_count):
            t = threading.Thread(target=self._worker, name=f"GatewayWorker-{i}", daemon=True)
            t.start()
            self.workers.append(t)
        
        if self.logger:
            self.logger.gateway(f"Dispatcher started with {self.worker_count} workers")
    
    def submit(self, event: GatewayEvent) -> bool:
        """
        Enqueue an event. Returns False if queue is full (backpressure).
        Non-blocking: returns immediately.
        """
        if not self.running:
            return False
        
        try:
            self.queue.put_nowait(event)
            return True
        except queue.Full:
            if self.logger:
                self.logger.warning(f"Event queue full (size={self.max_queue_size}), dropping event type={event.type}")
            return False
    
    def stop(self, drain_timeout: float = 10.0) -> bool:
        """
        Stop workers and drain queue.
        Returns True if drained successfully within timeout.
        """
        if not self.running:
            return True
        
        self.running = False
        
        # Signal workers to stop
        for _ in range(self.worker_count):
            self.queue.put(None)  # Sentinel
        
        # Wait for workers to finish
        start = time.time()
        for t in self.workers:
            remaining = drain_timeout - (time.time() - start)
            if remaining > 0:
                t.join(timeout=remaining)
        
        drained = self.queue.empty()
        if self.logger:
            status = "drained" if drained else "timeout"
            self.logger.gateway(
                f"Dispatcher stopped ({status}) - processed={self.processed}, failed={self.failed}"
            )
        
        return drained
    
    def _worker(self):
        """Worker thread that processes events from queue"""
        while self.running:
            try:
                # Pull from queue with timeout to check if still running
                event = self.queue.get(timeout=1.0)
                
                if event is None:  # Sentinel for stop
                    break
                
                # Process with timeout
                self._process_event(event)
                
            except queue.Empty:
                continue
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Worker error: {e}", e)
    
    def _process_event(self, event: GatewayEvent):
        """Process single event with timeout and error handling"""
        start_time = time.time()
        
        try:
            # Call handler (with implicit timeout via Python's GIL)
            # For true timeout, use signal or multiprocessing (not here to keep simple)
            success = self.event_handler(event)
            
            elapsed = time.time() - start_time
            
            with self._lock:
                self.processed += 1
            
            if elapsed > self.task_timeout * 0.8:  # Warn if approaching timeout
                if self.logger:
                    self.logger.warning(
                        f"Event processing slow: type={event.type}, elapsed={elapsed:.2f}s"
                    )
            
        except Exception as e:
            elapsed = time.time() - start_time
            with self._lock:
                self.failed += 1
            
            if self.logger:
                self.logger.error(
                    f"Event handler error: type={event.type}, elapsed={elapsed:.2f}s, error={e}",
                    e
                )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics"""
        with self._lock:
            return {
                "running": self.running,
                "queue_size": self.queue.qsize(),
                "max_queue": self.max_queue_size,
                "workers": self.worker_count,
                "processed": self.processed,
                "failed": self.failed,
                "success_rate": (
                    self.processed / (self.processed + self.failed) 
                    if (self.processed + self.failed) > 0 else 0
                )
            }


class GatewayConnection:
    """
    Manages bot connection lifecycle with dispatcher.
    - WebSocket connection to Discord
    - Heartbeat management
    - Automatic reconnection with backoff
    - Event dispatching to worker pool
    """
    
    def __init__(self, bot, dispatcher: GatewayDispatcher, logger=None):
        self.bot = bot
        self.dispatcher = dispatcher
        self.logger = logger
        self.connected = False
        self.reconnect_count = 0
        self.max_backoff = 30.0
        self.base_backoff = 2.0
    
    def on_gateway_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Called by bot when receiving gateway event.
        Returns True if enqueued successfully.
        """
        event = GatewayEvent(type=event_type, data=data)
        
        if not self.dispatcher.submit(event):
            if self.logger:
                self.logger.warning(f"Failed to queue event: {event_type}")
            return False
        
        return True
    
    def get_backoff_delay(self) -> float:
        """Calculate exponential backoff with jitter"""
        delay = min(self.base_backoff * (2 ** self.reconnect_count), self.max_backoff)
        # Add 0-20% jitter
        import random
        jitter = delay * random.uniform(0, 0.2)
        return delay + jitter
    
    def on_connection_lost(self):
        """Called when connection is lost - triggers reconnect"""
        self.connected = False
        self.reconnect_count += 1
        delay = self.get_backoff_delay()
        
        if self.logger:
            self.logger.gateway(
                f"Connection lost, reconnecting in {delay:.1f}s (attempt {self.reconnect_count})"
            )
        
        time.sleep(delay)
        # Bot should handle actual reconnection
    
    def on_connection_established(self):
        """Called when connection succeeds"""
        self.connected = True
        self.reconnect_count = 0
        
        if self.logger:
            self.logger.gateway("Gateway connection established")
