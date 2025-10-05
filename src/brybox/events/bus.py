"""
Simple in-process event bus for brybox pub-sub system.
Thread-safe event dispatcher with topic-based subscriptions.
"""

from collections import defaultdict
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Dict, List, Type, TypeVar

from .models import FileMovedEvent, FileDeletedEvent, FileCopiedEvent

# Type for event classes
EventType = TypeVar('EventType')
# Type for event handler functions
EventHandler = Callable[[Any], None]


class EventBus:
    """
    Simple in-process event bus with topic-based subscriptions.
    
    Thread-safe event dispatcher that allows publishers to emit events
    and subscribers to register handlers for specific event types.
    """
    
    def __init__(self):
        self._subscribers: Dict[Type, List[EventHandler]] = defaultdict(list)
        self._lock = Lock()
    
    def subscribe(self, event_type: Type[EventType], handler: EventHandler) -> None:
        """
        Subscribe a handler function to a specific event type.
        
        Args:
            event_type: The class type of events to listen for (e.g., FileMovedEvent)
            handler: Function that will be called when event is published
            
        Example:
            bus.subscribe(FileMovedEvent, my_verifier.handle_file_moved)
        """
        with self._lock:
            self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: Type[EventType], handler: EventHandler) -> bool:
        """
        Remove a handler from an event type subscription.
        
        Args:
            event_type: The event type to unsubscribe from
            handler: The handler function to remove
            
        Returns:
            True if handler was found and removed, False otherwise
        """
        with self._lock:
            try:
                self._subscribers[event_type].remove(handler)
                return True
            except ValueError:
                return False
    
    def publish(self, event: EventType) -> None:
        """
        Publish an event to all registered subscribers.
        
        Args:
            event: The event instance to publish
            
        Note:
            Handlers are called synchronously in registration order.
            If a handler raises an exception, other handlers still execute.
        """
        event_type = type(event)
        
        with self._lock:
            # Get copy of subscribers to avoid issues if handlers modify subscriptions
            handlers = self._subscribers[event_type].copy()
        
        if not handlers:
            return
        
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                # Silently continue processing other handlers even if one fails
                pass
    
    def get_subscriber_count(self, event_type: Type[EventType]) -> int:
        """Get the number of subscribers for an event type."""
        with self._lock:
            return len(self._subscribers[event_type])
    
    def clear_all_subscriptions(self) -> None:
        """Remove all subscriptions. Useful for testing."""
        with self._lock:
            self._subscribers.clear()


# Global event bus instance - shared across all brybox modules
event_bus = EventBus()


# Convenience functions for common usage patterns
def publish_file_moved(source_path: str, destination_path: str, 
                      file_size: int, is_healthy: bool) -> None:
    """
    Convenience function to publish FileMovedEvent.
    
    Args:
        source_path: Original file location
        destination_path: New file location  
        file_size: Size of the moved file in bytes
        is_healthy: Whether the file passed health checks
    """
  
    event = FileMovedEvent(
        source_path=source_path,
        destination_path=destination_path,
        file_size=file_size,
        is_healthy=is_healthy,
        timestamp=datetime.now()
    )
    
    event_bus.publish(event)

def publish_file_deleted(file_path: str, file_size: int) -> None:
    """
    Convenience function to publish FileDeletedEvent.
    
    Args:
        file_path: Path of the file that was deleted
        file_size: Size of the deleted file in bytes
    """
   
    event = FileDeletedEvent(
        file_path=file_path,
        file_size=file_size,
        timestamp=datetime.now()
    )
    
    event_bus.publish(event)

def publish_file_copied(source_path: str, destination_path: str,
                       source_size: int, destination_size: int,
                       source_healthy: bool, destination_healthy: bool) -> None:
    """
    Publish FileCopiedEvent **only** after the copy and both post-checks succeed.
    Caller must guarantee:
        - both files exist
        - source_healthy and destination_healthy are True
        - sizes are non-negative
    """
    event = FileCopiedEvent(
        source_path=source_path,
        destination_path=destination_path,
        source_size=source_size,
        destination_size=destination_size,
        source_healthy=source_healthy,
        destination_healthy=destination_healthy,
        timestamp=datetime.now()
    )
    event_bus.publish(event)