import os

from langchain.chat_models import init_chat_model


def get_llm(temperature: float = 0.0):
    model = os.getenv("SENTINEL_MODEL", "gpt-4o-mini")
    return init_chat_model(model, temperature=temperature)
