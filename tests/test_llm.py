"""LLM grounding: the prompt carries numbered sources + the question,
citations are required, and empty retrieval gets an honest no-answer."""
from src.llm import NvidiaLLM

SOURCES = [
    {"text": "Espresso Blend sold 120 units in the North", "source": "orders.csv:row 2"},
    {"text": "Cold Brew sold 200 units in the West", "source": "orders.csv:row 4"},
]


def test_build_prompt_grounds_in_sources():
    llm = NvidiaLLM.__new__(NvidiaLLM)  # no client needed for prompt building
    messages = llm.build_prompt("Which product sold most?", SOURCES)
    assert messages[0]["role"] == "system"
    assert "ONLY the sources" in messages[0]["content"]
    assert "[1]" in messages[0]["content"] or "cite" in messages[0]["content"].lower()
    user = messages[1]["content"]
    assert "[1] (orders.csv:row 2)" in user
    assert "Espresso Blend sold 120 units" in user
    assert "[2] (orders.csv:row 4)" in user
    assert "Which product sold most?" in user


def test_answer_with_no_sources_is_honest(monkeypatch):
    llm = NvidiaLLM.__new__(NvidiaLLM)
    answer = llm.answer("anything?", [])
    assert "couldn't find" in answer.lower()
    assert "try rephrasing" in answer.lower()
