from core.conversation_buffer import ConversationBuffer


def test_buffer_caps_at_max():
    buf = ConversationBuffer(max_turns=3)
    buf.add("User", "one")
    buf.add("Assistant", "two")
    buf.add("User", "three")
    buf.add("Assistant", "four")
    assert buf.size() == 3
    context = buf.as_context_block()
    assert "one" not in context
    assert "two" in context
    assert "three" in context
    assert "four" in context


def test_buffer_clears_on_new_instance():
    buf = ConversationBuffer(max_turns=2)
    buf.add("User", "hello")
    assert buf.size() == 1
    buf2 = ConversationBuffer(max_turns=2)
    assert buf2.size() == 0


def test_buffer_is_ram_only():
    buf = ConversationBuffer(max_turns=2)
    buf.add("User", "remember this")
    assert "Conversation context" in buf.as_context_block()
