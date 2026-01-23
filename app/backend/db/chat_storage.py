"""
File-based chat history storage system.

Stores chat messages in JSONL (JSON Lines) format for efficient append operations
and easy parsing. Each line is a complete JSON object representing one message.

Storage structure:
    chat_logs/
        {business_id}/
            {session_id}.jsonl

This design externalizes long-term memory from the database, following
context engineering best practices for AI agents.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class ChatMessage:
    """Structured chat message"""
    timestamp: str
    session_id: str
    business_id: str
    user_id: Optional[str]
    role: str  # "user" or "assistant"
    name: str  # e.g., "customer", "product_agent", "vendor"
    content: str
    agent_used: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatStorage:
    """File-based chat history storage"""

    def __init__(self, base_dir: str = "chat_logs"):
        """
        Initialize chat storage.

        Args:
            base_dir: Base directory for storing chat logs
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

    def _get_log_path(self, business_id: str, session_id: str) -> Path:
        """
        Get the file path for a session's chat log.

        Args:
            business_id: Business identifier
            session_id: Session identifier

        Returns:
            Path to the chat log file
        """
        business_dir = self.base_dir / business_id
        business_dir.mkdir(exist_ok=True)
        return business_dir / f"{session_id}.jsonl"

    def save_message(
        self,
        session_id: str,
        business_id: str,
        role: str,
        name: str,
        content: str,
        user_id: Optional[str] = None,
        agent_used: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Save a chat message to the log file.

        Args:
            session_id: Session identifier
            business_id: Business identifier
            role: Message role ("user" or "assistant")
            name: Sender name (e.g., "customer", "product_agent")
            content: Message content
            user_id: Optional user identifier
            agent_used: Optional agent that generated this response
            metadata: Optional additional metadata
        """
        message = ChatMessage(
            timestamp=datetime.utcnow().isoformat(),
            session_id=session_id,
            business_id=business_id,
            user_id=user_id,
            role=role,
            name=name,
            content=content,
            agent_used=agent_used,
            metadata=metadata,
        )

        log_path = self._get_log_path(business_id, session_id)

        # Append message as JSON line
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(message)) + "\n")

    def load_history(
        self,
        session_id: str,
        business_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Load chat history for a session.

        Args:
            session_id: Session identifier
            business_id: Business identifier
            limit: Maximum number of messages to return (None = all)
            offset: Number of messages to skip from the beginning

        Returns:
            List of message dictionaries
        """
        log_path = self._get_log_path(business_id, session_id)

        if not log_path.exists():
            return []

        messages = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line))

        # Apply offset and limit
        if offset > 0:
            messages = messages[offset:]
        if limit is not None:
            messages = messages[:limit]

        return messages

    def get_recent_messages(
        self,
        session_id: str,
        business_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get the most recent messages from a session.

        Args:
            session_id: Session identifier
            business_id: Business identifier
            limit: Number of recent messages to return

        Returns:
            List of message dictionaries (most recent last)
        """
        log_path = self._get_log_path(business_id, session_id)

        if not log_path.exists():
            return []

        messages = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line))

        # Return last N messages
        return messages[-limit:] if len(messages) > limit else messages

    def clear_history(self, session_id: str, business_id: str) -> bool:
        """
        Clear chat history for a session.

        Args:
            session_id: Session identifier
            business_id: Business identifier

        Returns:
            True if file was deleted, False if it didn't exist
        """
        log_path = self._get_log_path(business_id, session_id)

        if log_path.exists():
            log_path.unlink()
            return True
        return False

    def session_exists(self, session_id: str, business_id: str) -> bool:
        """
        Check if a session has chat history.

        Args:
            session_id: Session identifier
            business_id: Business identifier

        Returns:
            True if session log exists
        """
        log_path = self._get_log_path(business_id, session_id)
        return log_path.exists()

    def get_session_count(self, session_id: str, business_id: str) -> int:
        """
        Get the number of messages in a session.

        Args:
            session_id: Session identifier
            business_id: Business identifier

        Returns:
            Number of messages in the session
        """
        log_path = self._get_log_path(business_id, session_id)

        if not log_path.exists():
            return 0

        count = 0
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1

        return count

    def list_sessions(self, business_id: str) -> List[str]:
        """
        List all session IDs for a business.

        Args:
            business_id: Business identifier

        Returns:
            List of session IDs
        """
        business_dir = self.base_dir / business_id

        if not business_dir.exists():
            return []

        return [f.stem for f in business_dir.glob("*.jsonl")]

    def get_business_stats(self, business_id: str) -> Dict[str, Any]:
        """
        Get statistics for a business's chat history.

        Args:
            business_id: Business identifier

        Returns:
            Dictionary with statistics
        """
        sessions = self.list_sessions(business_id)
        total_messages = sum(
            self.get_session_count(session_id, business_id)
            for session_id in sessions
        )

        return {
            "business_id": business_id,
            "total_sessions": len(sessions),
            "total_messages": total_messages,
            "avg_messages_per_session": (
                total_messages / len(sessions) if sessions else 0
            ),
        }


# Global instance
_storage = None


def get_chat_storage(base_dir: str = "chat_logs") -> ChatStorage:
    """
    Get the global chat storage instance.

    Args:
        base_dir: Base directory for chat logs

    Returns:
        ChatStorage instance
    """
    global _storage
    if _storage is None:
        _storage = ChatStorage(base_dir)
    return _storage


# Convenience functions for backward compatibility
def save_chat_message(
    session_id: str,
    business_id: str,
    role: str,
    name: str,
    content: str,
    user_id: Optional[str] = None,
    agent_used: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Save a chat message (convenience function)."""
    storage = get_chat_storage()
    storage.save_message(
        session_id, business_id, role, name, content, user_id, agent_used, metadata
    )


def load_chat_history(
    session_id: str,
    business_id: str,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Load chat history (convenience function)."""
    storage = get_chat_storage()
    return storage.get_recent_messages(session_id, business_id, limit or 10)


def clear_chat_history(session_id: str, business_id: str) -> bool:
    """Clear chat history (convenience function)."""
    storage = get_chat_storage()
    return storage.clear_history(session_id, business_id)
