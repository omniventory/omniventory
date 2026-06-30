"""LLM provider seam — `app/services/llm/` package (M9.1 Step 2).

This package mirrors ``app/services/product_lookup/`` in structure:
    provider.py  — ``LLMProvider`` Protocol + ``ChatMessage`` / ``ChatResult`` dataclasses
    openai.py    — ``OpenAICompatibleProvider`` (duck-typed, not inheriting Protocol)
    service.py   — ``LLMService`` + ``build_llm_service`` factory

Do NOT import ``app.services.llm`` directly; import from the sub-modules.
"""
