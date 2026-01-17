#!/usr/bin/env python3
"""
Conversation browser: read-only access to past conversations.

Exposes memory without reinterpreting it.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Tuple

MEMORY_FILE = Path("memory/interactions.json")


def load_conversations() -> List[Dict]:
    """Load all stored conversations (read-only)."""
    if not MEMORY_FILE.exists():
        return []
    
    with open(MEMORY_FILE, 'r') as f:
        return json.load(f)


def parse_date(date_str: str) -> datetime:
    """Parse ISO timestamp."""
    return datetime.fromisoformat(date_str)


def format_date(dt: datetime) -> str:
    """Format datetime for display."""
    today = datetime.now().date()
    dt_date = dt.date()
    
    if dt_date == today:
        return "Today"
    elif dt_date == today - timedelta(days=1):
        return "Yesterday"
    else:
        return dt_date.strftime("%b %d")


def group_by_date(conversations: List[Dict]) -> Dict[str, List[Dict]]:
    """Group conversations by date."""
    groups = defaultdict(list)
    
    for conv in conversations:
        dt = parse_date(conv["timestamp"])
        date_key = format_date(dt)
        groups[date_key].append(conv)
    
    return groups


def list_conversations(limit: int = 5) -> str:
    """List recent conversations by date."""
    conversations = load_conversations()
    
    if not conversations:
        return "No conversations stored yet."
    
    # Group by date (reverse order: newest first)
    groups = group_by_date(conversations)
    sorted_groups = sorted(groups.items(), 
                          key=lambda x: parse_date(x[1][0]["timestamp"]), 
                          reverse=True)
    
    output = "Recent conversations:\n"
    count = 0
    
    for date_label, convs in sorted_groups:
        topics = list(set(c.get("topic", "unknown") for c in convs))
        topic_str = ", ".join(topics[:3])  # First 3 topics
        output += f"{count + 1}. {date_label} – {topic_str}\n"
        count += 1
        if count >= limit:
            break
    
    return output.strip()


def show_by_date(date_query: str) -> str:
    """Show conversations for a specific date."""
    conversations = load_conversations()
    
    if not conversations:
        return "No conversations stored yet."
    
    # Parse date query
    today = datetime.now().date()
    
    if date_query.lower() == "today":
        target_date = today
    elif date_query.lower() == "yesterday":
        target_date = today - timedelta(days=1)
    else:
        try:
            target_date = datetime.fromisoformat(date_query).date()
        except ValueError:
            return f"Invalid date format. Use 'today', 'yesterday', or 'YYYY-MM-DD'."
    
    # Filter conversations for that date
    matching = []
    for conv in conversations:
        dt = parse_date(conv["timestamp"])
        if dt.date() == target_date:
            matching.append(conv)
    
    if not matching:
        return f"No conversations found for {target_date.strftime('%b %d')}."
    
    # Group by topic
    by_topic = defaultdict(list)
    for conv in matching:
        topic = conv.get("topic", "unknown")
        by_topic[topic].append(conv)
    
    output = f"Conversations on {target_date.strftime('%b %d')}:\n"
    idx = 1
    for topic, convs in sorted(by_topic.items()):
        output += f"{idx}. {topic} ({len(convs)} turn{'s' if len(convs) != 1 else ''})\n"
        idx += 1
    
    return output.strip()


def show_by_topic(topic: str) -> str:
    """Show conversations for a specific topic."""
    conversations = load_conversations()
    
    if not conversations:
        return "No conversations stored yet."
    
    # Find matching conversations
    matching = [c for c in conversations 
                if c.get("topic", "").lower() == topic.lower()]
    
    if not matching:
        return f"No conversations tagged '{topic}'."
    
    # Group by date
    groups = group_by_date(matching)
    sorted_groups = sorted(groups.items(),
                          key=lambda x: parse_date(x[1][0]["timestamp"]),
                          reverse=True)
    
    output = f"Conversations tagged '{topic}':\n"
    idx = 1
    for date_label, convs in sorted_groups:
        output += f"{idx}. {date_label} – {len(convs)} turn{'s' if len(convs) != 1 else ''}\n"
        idx += 1
    
    return output.strip()


def get_conversation_context(topic_or_idx: str) -> Tuple[bool, str, List[Dict]]:
    """
    Get context for opening a conversation.
    
    Returns:
        (success: bool, summary: str, context: List[Dict])
    """
    conversations = load_conversations()
    
    if not conversations:
        return False, "No conversations stored.", []
    
    # Try numeric index first
    try:
        idx = int(topic_or_idx) - 1
        if 0 <= idx < len(conversations):
            # Get all conversations with this topic
            topic = conversations[idx].get("topic")
            matching = [c for c in conversations 
                       if c.get("topic", "").lower() == topic.lower()]
            
            output = f"Loaded conversation: {topic}\n"
            output += f"({len(matching)} total turns on this topic)"
            return True, output, matching
    except ValueError:
        pass
    
    # Try topic match
    matching = [c for c in conversations 
                if c.get("topic", "").lower() == topic_or_idx.lower()]
    
    if matching:
        output = f"Loaded conversation: {topic_or_idx}\n"
        output += f"({len(matching)} total turns)"
        return True, output, matching
    
    return False, f"No conversation found for '{topic_or_idx}'.", []


def summarize_conversation(topic_or_idx: str) -> str:
    """
    Summarize a conversation (ephemeral, not stored).
    
    Returns factual summary without opinion.
    """
    success, msg, context = get_conversation_context(topic_or_idx)
    
    if not success:
        return msg
    
    if not context:
        return "No context to summarize."
    
    # Extract key points (factual, no interpretation)
    questions = []
    for conv in context:
        user_input = conv.get("user_input", "").strip()
        if user_input and user_input not in questions:
            questions.append(user_input)
    
    output = f"Summary: {context[0].get('topic', 'unknown').title()}\n"
    output += f"({len(context)} turn{'s' if len(context) != 1 else ''})\n\n"
    
    output += "Questions asked:\n"
    for i, q in enumerate(questions[:6], 1):  # First 6 questions
        # Truncate long questions
        q_short = q[:60] + "..." if len(q) > 60 else q
        output += f"{i}. {q_short}\n"
    
    return output.strip()


if __name__ == "__main__":
    # Test
    print(list_conversations())
    print("\n---\n")
    print(show_by_topic("dogs"))
