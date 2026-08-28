from app.agent.context import ConversationContext


def test_short_semantic_history_keeps_order_and_excludes_tools() -> None:
    history = [
        {"role": "user", "content": "goal"},
        {"role": "tool", "content": "very long tool output"},
        {"role": "assistant", "content": "done"},
    ]
    messages = ConversationContext(1000).build(history)
    assert [(item.role, item.content) for item in messages] == [
        ("user", "goal"),
        ("assistant", "done"),
    ]


def test_long_history_keeps_first_goal_summary_and_recent_turn() -> None:
    history = [{"role": "user", "content": "first goal"}]
    history += [{"role": "assistant", "content": "x" * 200}, {"role": "user", "content": "latest"}]
    messages = ConversationContext(150).build(history)
    assert messages[0].content == "first goal"
    assert any("较早对话摘要" in (item.content or "") for item in messages)
    assert messages[-1].content == "latest"
