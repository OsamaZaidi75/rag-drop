"""Grounded answers via the NVIDIA API — the ONLY LLM provider.

The model is a reasoning model: thinking lands in reasoning_content and
consumes completion tokens FIRST, so max_tokens stays generous (2048+)
and only choices[0].message.content is ever read as the answer.
"""
from .config import settings

SYSTEM_PROMPT = (
    "You answer questions using ONLY the sources below. Each source is "
    "numbered; cite the sources you used as [1], [2] next to the claims "
    "they support. If the sources do not contain the answer, say so "
    "plainly instead of guessing. Keep answers concise and specific, "
    "quoting figures from the sources where relevant."
)

LLM_TIMEOUT_S = 180


class NvidiaLLM:
    def __init__(self, model: str | None = None, max_tokens: int | None = None):
        self.model = model or settings.nvidia_model
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not settings.nvidia_api_key:
                raise RuntimeError(
                    "NVIDIA_API_KEY is not set — answers need the NVIDIA API key"
                )
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.nvidia_api_key,
                base_url=settings.nvidia_base_url,
                timeout=LLM_TIMEOUT_S,
                max_retries=2,
            )
        return self._client

    def build_prompt(self, question: str, sources: list[dict]) -> list[dict]:
        """Assemble the grounded chat messages. Kept separate so tests
        can inspect the prompt without calling the API."""
        context = "\n\n".join(
            f"[{i + 1}] ({s['source']})\n{s['text']}"
            for i, s in enumerate(sources)
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"SOURCES\n{context}\n\nQUESTION\n{question}",
            },
        ]

    def answer(self, question: str, sources: list[dict]) -> str:
        """Answer `question` from `sources` only. Returns the assistant
        message content (never reasoning_content)."""
        if not sources:
            return (
                "I couldn't find anything in your data that answers that — "
                "try rephrasing, or check the file covers this topic."
            )
        client = self._get_client()
        resp = client.chat.completions.create(
            model=self.model,
            messages=self.build_prompt(question, sources),
            temperature=settings.llm_temperature,
            top_p=0.95,
            max_tokens=self.max_tokens,
        )
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError(
                "The model returned an empty answer — try again, or shorten the question"
            )
        return content
