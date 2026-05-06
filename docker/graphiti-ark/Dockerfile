FROM zepai/knowledge-graph-mcp:standalone

WORKDIR /app/mcp

RUN uv pip install \
    --python /app/mcp/.venv/bin/python \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    anthropic==0.84.0 \
    && /app/mcp/.venv/bin/python -c "import anthropic"

RUN /app/mcp/.venv/bin/python - <<'PY'
from pathlib import Path

path = Path('/app/mcp/src/graphiti_mcp_server.py')
text = path.read_text()
needle = "    instructions=GRAPHITI_MCP_INSTRUCTIONS,\n)"
replacement = (
    "    instructions=GRAPHITI_MCP_INSTRUCTIONS,\n"
    "    host=os.environ.get('FASTMCP_HOST', '0.0.0.0'),\n"
    ")"
)
if "host=os.environ.get('FASTMCP_HOST'" not in text:
    if needle not in text:
        raise SystemExit('Could not find FastMCP initialization block')
    path.write_text(text.replace(needle, replacement))
PY

RUN /app/mcp/.venv/bin/python - <<'PY'
from pathlib import Path

path = Path('/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/embedder/openai.py')
text = path.read_text()
if 'OPENAI_EMBEDDING_MAX_BATCH_SIZE' not in text:
    text = text.replace('from collections.abc import Iterable\n', 'from collections.abc import Iterable\nimport os\n')
    old = '''    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        result = await self.client.embeddings.create(
            input=input_data_list, model=self.config.embedding_model
        )
        return [embedding.embedding[: self.config.embedding_dim] for embedding in result.data]
'''
    new = '''    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        max_batch_size = int(os.environ.get('OPENAI_EMBEDDING_MAX_BATCH_SIZE', '10'))
        embeddings: list[list[float]] = []
        for start in range(0, len(input_data_list), max_batch_size):
            batch = input_data_list[start : start + max_batch_size]
            result = await self.client.embeddings.create(
                input=batch, model=self.config.embedding_model
            )
            embeddings.extend(
                embedding.embedding[: self.config.embedding_dim] for embedding in result.data
            )
        return embeddings
'''
    if old not in text:
        raise SystemExit('Could not find OpenAIEmbedder.create_batch block')
    path.write_text(text.replace(old, new))
PY


RUN /app/mcp/.venv/bin/python - <<'PY'
from pathlib import Path

path = Path('/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/driver/falkordb/operations/search_ops.py')
text = path.read_text()
if 'import os\n' not in text:
    text = text.replace('import logging\n', 'import logging\nimport os\n')
old = """    # Remove stopwords and empty tokens
    query_words = sanitized_query.split()
    filtered_words = [word for word in query_words if word and word.lower() not in STOPWORDS]
    sanitized_query = ' | '.join(filtered_words)
"""
new = """    # Remove stopwords, one-character noise tokens, and cap OR-term count.
    # FalkorDB/RedisSearch can become very expensive on long OR queries generated
    # during Graphiti deduplication, even on small graphs.
    query_words = sanitized_query.split()
    filtered_words = [
        word for word in query_words
        if word and len(word) > 1 and word.lower() not in STOPWORDS
    ]
    max_terms = int(os.environ.get('FALKORDB_FULLTEXT_MAX_TERMS', '6'))
    if max_terms > 0:
        filtered_words = filtered_words[:max_terms]
    sanitized_query = ' | '.join(filtered_words)
"""
if old in text and 'cap OR-term count' not in text:
    text = text.replace(old, new)
path.write_text(text)
PY

COPY falkordb_driver_patch.py /tmp/falkordb_driver_patch.py
RUN /app/mcp/.venv/bin/python /tmp/falkordb_driver_patch.py && \
    rm /tmp/falkordb_driver_patch.py
COPY falkordb_search_patch.py /tmp/falkordb_search_patch.py
RUN /app/mcp/.venv/bin/python /tmp/falkordb_search_patch.py && \
    rm /tmp/falkordb_search_patch.py
COPY falkordb_search_interface_patch.py /tmp/falkordb_search_interface_patch.py
RUN /app/mcp/.venv/bin/python /tmp/falkordb_search_interface_patch.py && \
    rm /tmp/falkordb_search_interface_patch.py

# Graphiti Anthropic text-json mode patch.
# Some Anthropic-compatible gateways support plain messages but return empty
# tool_use arguments. ANTHROPIC_DISABLE_TOOLS=true makes Graphiti request strict
# JSON text shaped by the response model schema, then parse it with the existing
# text JSON extractor.
RUN /app/mcp/.venv/bin/python - <<'PY'
from pathlib import Path

path = Path('/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/llm_client/anthropic_client.py')
text = path.read_text()
marker = '# Graphiti Anthropic text-json mode patch.'
if marker not in text:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line == '            # Create the appropriate tool based on whether response_model is provided':
            start = idx
            break
    if start is None:
        raise SystemExit('Could not find AnthropicClient tool call block start')

    end = None
    for idx in range(start, len(lines)):
        if lines[idx] == '            )':
            end = idx + 1
            break
    if end is None:
        raise SystemExit('Could not find AnthropicClient tool call block end')

    replacement = [
        '            # Graphiti Anthropic text-json mode patch.',
        '            # Some Anthropic-compatible gateways return empty tool_use arguments.',
        '            # Allow deployments to disable tools and ask for strict JSON text',
        '            # matching the Pydantic response model instead.',
        "            if os.getenv('ANTHROPIC_DISABLE_TOOLS', '').lower() in {'1', 'true', 'yes', 'on'}:",
        '                system_content = system_message.content',
        '                if response_model is not None:',
        '                    schema_json = json.dumps(response_model.model_json_schema(), ensure_ascii=False)',
        '                    system_content += (',
        "                        '\\n\\nReturn exactly one strict JSON object matching this JSON Schema. '",
        "                        'Do not use markdown fences. Do not include prose before or after the JSON. '",
        "                        f'JSON Schema: {schema_json}'",
        '                    )',
        '                result = await self.client.messages.create(',
        '                    system=system_content,',
        '                    max_tokens=max_creation_tokens,',
        '                    temperature=self.temperature,',
        '                    messages=user_messages_cast,',
        '                    model=self.model,',
        '                )',
        '            else:',
        '                # Create the appropriate tool based on whether response_model is provided',
        '                tools, tool_choice = self._create_tool(response_model)',
        '                result = await self.client.messages.create(',
        '                    system=system_message.content,',
        '                    max_tokens=max_creation_tokens,',
        '                    temperature=self.temperature,',
        '                    messages=user_messages_cast,',
        '                    model=self.model,',
        '                    tools=tools,',
        '                    tool_choice=tool_choice,',
        '                )',
    ]
    lines[start:end] = replacement
    path.write_text('\n'.join(lines) + '\n')
PY

RUN /app/mcp/.venv/bin/python -m py_compile /app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/llm_client/anthropic_client.py

# Graphiti OpenAI chat.completions JSON schema patch.
# OpenAI-compatible gateways such as Xiaomi MiMo token-plan expose structured
# output on /chat/completions while not necessarily supporting responses.parse.
RUN /app/mcp/.venv/bin/python - <<'PY'
from pathlib import Path

factories_path = Path('/app/mcp/src/services/factories.py')
factories_text = factories_path.read_text()
if 'base_url=config.providers.openai.api_url,\n                    model=config.model' not in factories_text:
    old = '''                llm_config = CoreLLMConfig(
                    api_key=api_key,
                    model=config.model,
                    small_model=small_model,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )
'''
    new = '''                llm_config = CoreLLMConfig(
                    api_key=api_key,
                    base_url=config.providers.openai.api_url,
                    model=config.model,
                    small_model=small_model,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )
'''
    if old not in factories_text:
        raise SystemExit('Could not find OpenAI CoreLLMConfig block in factories.py')
    factories_path.write_text(factories_text.replace(old, new))

openai_path = Path('/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/llm_client/openai_client.py')
openai_text = openai_path.read_text()
if 'OPENAI_USE_CHAT_COMPLETIONS_JSON_SCHEMA' not in openai_text:
    if 'from types import SimpleNamespace\n' not in openai_text:
        openai_text = openai_text.replace('import typing\n', 'import os\nfrom types import SimpleNamespace\nimport typing\n')

    old = '''        request_kwargs = {
            'model': model,
            'input': messages,  # type: ignore
            'max_output_tokens': max_tokens,
            'text_format': response_model,  # type: ignore
        }

        temperature_value = temperature if not is_reasoning_model else None
        if temperature_value is not None:
            request_kwargs['temperature'] = temperature_value

        # Only include reasoning and verbosity parameters for reasoning models
        if is_reasoning_model and reasoning is not None:
            request_kwargs['reasoning'] = {'effort': reasoning}  # type: ignore

        if is_reasoning_model and verbosity is not None:
            request_kwargs['text'] = {'verbosity': verbosity}  # type: ignore

        response = await self.client.responses.parse(**request_kwargs)

        return response
'''
    new = '''        if os.getenv('OPENAI_USE_CHAT_COMPLETIONS_JSON_SCHEMA', '').lower() in {
            '1',
            'true',
            'yes',
            'on',
        }:
            schema = response_model.model_json_schema()
            response_format_mode = os.getenv(
                'OPENAI_CHAT_RESPONSE_FORMAT', 'json_schema'
            ).lower()
            request_messages = messages
            if response_format_mode == 'json_object':
                import json

                schema_json = json.dumps(schema, ensure_ascii=False)
                request_messages = [dict(message) for message in messages]
                for message in request_messages:
                    if message.get('role') == 'system':
                        message['content'] = (
                            str(message.get('content') or '')
                            + '\\n\\nReturn exactly one JSON object matching this JSON Schema. '
                            + 'Do not use markdown fences. Do not include prose before or after the JSON. '
                            + f'JSON Schema: {schema_json}'
                        )
                        break
                response_format = {'type': 'json_object'}
            else:
                response_format = {
                    'type': 'json_schema',
                    'json_schema': {
                        'name': response_model.__name__,
                        'schema': schema,
                        'strict': True,
                    },
                }

            request_kwargs = {
                'model': model,
                'messages': request_messages,
                'max_tokens': max_tokens,
                'response_format': response_format,
            }

            temperature_value = temperature if not is_reasoning_model else None
            if temperature_value is not None:
                request_kwargs['temperature'] = temperature_value

            extra_body = {}
            if os.getenv('OPENAI_CHAT_DISABLE_THINKING', '').lower() in {
                '1',
                'true',
                'yes',
                'on',
            }:
                extra_body['thinking'] = {'type': 'disabled'}
            if extra_body:
                request_kwargs['extra_body'] = extra_body

            response = await self.client.chat.completions.create(**request_kwargs)
            usage = getattr(response, 'usage', None)
            content = response.choices[0].message.content or ''
            return SimpleNamespace(
                output_text=content,
                usage=SimpleNamespace(
                    input_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                    output_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                ),
            )

        request_kwargs = {
            'model': model,
            'input': messages,  # type: ignore
            'max_output_tokens': max_tokens,
            'text_format': response_model,  # type: ignore
        }

        temperature_value = temperature if not is_reasoning_model else None
        if temperature_value is not None:
            request_kwargs['temperature'] = temperature_value

        # Only include reasoning and verbosity parameters for reasoning models
        if is_reasoning_model and reasoning is not None:
            request_kwargs['reasoning'] = {'effort': reasoning}  # type: ignore

        if is_reasoning_model and verbosity is not None:
            request_kwargs['text'] = {'verbosity': verbosity}  # type: ignore

        response = await self.client.responses.parse(**request_kwargs)

        return response
'''
    if old not in openai_text:
        raise SystemExit('Could not find OpenAI structured completion block')
    openai_path.write_text(openai_text.replace(old, new))
PY

RUN /app/mcp/.venv/bin/python -m py_compile \
    /app/mcp/src/services/factories.py \
    /app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/llm_client/openai_client.py

# Graphiti OpenAI client timeout patch.
# Graphiti extraction prompts can exceed provider defaults on compatible gateways.
RUN /app/mcp/.venv/bin/python - <<'PY'
from pathlib import Path

path = Path('/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/llm_client/openai_client.py')
text = path.read_text()
if 'OPENAI_CLIENT_TIMEOUT' not in text:
    if 'import os\n' not in text:
        text = text.replace('import typing\n', 'import os\nimport typing\n')
    old = 'self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)'
    new = "self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url, timeout=float(os.getenv('OPENAI_CLIENT_TIMEOUT', '120')))"
    if old not in text:
        raise SystemExit('Could not find AsyncOpenAI constructor')
    path.write_text(text.replace(old, new))
PY

RUN /app/mcp/.venv/bin/python -m py_compile /app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/llm_client/openai_client.py


# Graphiti OpenAI strict schema compatibility patch.
# Some OpenAI-compatible providers accept json_schema but do not reliably honor
# Pydantic's raw $defs/$ref/title-heavy schema unless the exact compact schema is
# also stated in the prompt.
RUN /app/mcp/.venv/bin/python - <<'PY'
from pathlib import Path

path = Path('/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/llm_client/openai_client.py')
text = path.read_text()
if 'def _graphiti_compatible_json_schema' not in text:
    if 'import copy\n' not in text:
        text = text.replace('import os\n', 'import copy\nimport json\nimport os\n')

    helper = '''

def _graphiti_compatible_json_schema(schema: dict) -> dict:
    schema = copy.deepcopy(schema)
    defs = schema.pop('$defs', {})

    def walk(node):
        if isinstance(node, dict):
            ref = node.get('$ref')
            if ref and ref.startswith('#/$defs/'):
                return walk(copy.deepcopy(defs[ref.split('/')[-1]]))

            result = {}
            for key, value in node.items():
                if key in {'$defs', 'title', 'default'}:
                    continue
                result[key] = walk(value)
            if result.get('type') == 'object':
                result.setdefault('additionalProperties', False)
            return result
        if isinstance(node, list):
            return [walk(value) for value in node]
        return node

    return walk(schema)


def _graphiti_messages_with_schema_instruction(messages: list, schema: dict) -> list:
    schema_json = json.dumps(schema, ensure_ascii=False, separators=(',', ':'))
    instruction = (
        '\\n\\nReturn exactly one JSON object matching this schema. '
        'Use the exact property names and nesting. '
        'Do not rename keys. Do not omit required keys. '
        'Do not use markdown fences. Do not include prose before or after the JSON. '
        f'Schema: {schema_json}'
    )
    request_messages = [dict(message) for message in messages]
    for message in request_messages:
        if message.get('role') == 'system':
            message['content'] = str(message.get('content') or '') + instruction
            return request_messages
    request_messages.insert(0, {'role': 'system', 'content': instruction.lstrip()})
    return request_messages
'''
    text = text.replace('\n\nclass OpenAIClient(BaseOpenAIClient):', helper + '\n\nclass OpenAIClient(BaseOpenAIClient):')
    text = text.replace(
        '            schema = response_model.model_json_schema()\n',
        '            schema = _graphiti_compatible_json_schema(response_model.model_json_schema())\n',
    )
    old = """            request_messages = messages
            if response_format_mode == 'json_object':
                import json

                schema_json = json.dumps(schema, ensure_ascii=False)
                request_messages = [dict(message) for message in messages]
                for message in request_messages:
                    if message.get('role') == 'system':
                        message['content'] = (
                            str(message.get('content') or '')
                            + '\\n\\nReturn exactly one JSON object matching this JSON Schema. '
                            + 'Do not use markdown fences. Do not include prose before or after the JSON. '
                            + f'JSON Schema: {schema_json}'
                        )
                        break
                response_format = {'type': 'json_object'}
"""
    new = """            request_messages = messages
            if os.getenv('OPENAI_CHAT_SCHEMA_IN_PROMPT', 'true').lower() in {
                '1',
                'true',
                'yes',
                'on',
            }:
                request_messages = _graphiti_messages_with_schema_instruction(messages, schema)

            if response_format_mode == 'json_object':
                response_format = {'type': 'json_object'}
"""
    if old in text:
        text = text.replace(old, new)
    else:
        raise SystemExit('Could not find request_messages schema prompt block')
    path.write_text(text)
PY

RUN /app/mcp/.venv/bin/python -m py_compile /app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/llm_client/openai_client.py
