import re
import time
import asyncio
from model_registry import registry

class StreamProcessor:
    @staticmethod
    def _strip_hidden_thinking(text):
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<\|channel>thought.*?<channel\|>(?:assistant)?", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        return cleaned.strip()

    @staticmethod
    def _extract_scratchpad(state, raw_response):
        internal_note_content = None
        
        # Check for Gemma 4 native thinking channel BEFORE stripping
        gemma_match = re.search(r"<\|channel>thought(.*?)<channel\|>", raw_response, re.DOTALL | re.IGNORECASE)
        if gemma_match:
            internal_note_content = gemma_match.group(1).strip()
            
        cleaned = StreamProcessor._strip_hidden_thinking(raw_response)
        note_match = re.search(r"<scratchpad>(.*?)</scratchpad>", cleaned, re.DOTALL | re.IGNORECASE)
        
        if note_match and not internal_note_content:
            internal_note_content = note_match.group(1).strip()
            
        user_visible_response = re.sub(r"<scratchpad>.*?</scratchpad>", "", cleaned, flags=re.DOTALL | re.IGNORECASE).strip()

        if internal_note_content:
            if state.scratchpad in ["No current internal notes.", "Previous thoughts archived."]:
                state.scratchpad = internal_note_content
            else:
                state.scratchpad += f"\n- {internal_note_content}"

        user_visible_response = re.sub(r"<thread_title>.*?</thread_title>", "", user_visible_response, flags=re.DOTALL | re.IGNORECASE).strip()
        user_visible_response = re.sub(r"<thread_naming>.*?</thread_naming>", "", user_visible_response, flags=re.DOTALL | re.IGNORECASE).strip()
        user_visible_response = re.sub(r"^\[\d{4}-\d{2}-\d{2}T[^\]]+\]\s*(?:(?:ASSISTANT|AI|MODEL|OSIA|USER):)?\s*", "", user_visible_response, flags=re.IGNORECASE).strip()
        user_visible_response = re.sub(r"^(?:ASSISTANT|OSIA|MODEL):\s*", "", user_visible_response, flags=re.IGNORECASE).strip()
        user_visible_response = re.sub(r"\[Just now\]", "", user_visible_response, flags=re.IGNORECASE).strip()

        return user_visible_response, internal_note_content

    @staticmethod
    def _extract_thread_title(raw_response):
        match = re.search(r"<thread_title>(.*?)</thread_title>", raw_response, re.DOTALL | re.IGNORECASE)
        if match:
            title = match.group(1).strip().strip('"\'“”‘’')
            if len(title) > 60: title = title[:57] + "..."
            if title: return title
        return None

    @staticmethod
    async def process_stream(state, transport, user_message, messages, model_id, thinking, start_time, tools=None):
        provider = registry.provider_for(model_id)
        raw_response = ""
        try:
            yielded_length = 0
            indices = []
            has_tool_calls = False

            if provider in ("ollama", "koboldcpp"):
                ollama_gen = transport.call_stream(model_id, messages, thinking, tools)
                async for chunk in ollama_gen:
                    if isinstance(chunk, dict) and "tool_calls" in chunk:
                        has_tool_calls = True
                        yield {"type": "tool_call_request", "tool_calls": chunk["tool_calls"]}
                        continue

                    raw_response += chunk
                    indices = [i for i in [raw_response.find("<scratchpad>"), raw_response.find("<thread_title>"), raw_response.find("<thread_naming>"), raw_response.find("<|tool_call>"), raw_response.find("<tool_call>")] if i != -1]
                    if indices:
                        hidden_idx = min(indices)
                        if hidden_idx > yielded_length:
                            yield {"type": "chunk", "content": raw_response[yielded_length:hidden_idx]}
                            yielded_length = hidden_idx
                        try:
                            async for tail in ollama_gen: raw_response += tail
                        except Exception: pass
                        break
                    else:
                        safe_length = max(0, len(raw_response) - 16)
                        if safe_length > yielded_length:
                            yield {"type": "chunk", "content": raw_response[yielded_length:safe_length]}
                            yielded_length = safe_length
            else:
                sync_gen = transport.call_stream(model_id, messages, thinking, tools)
                def _next_or_stop(gen):
                    try: return next(gen), False
                    except StopIteration: return None, True
                while True:
                    chunk, done = await asyncio.to_thread(_next_or_stop, sync_gen)
                    if done or chunk is None: break
                    if isinstance(chunk, dict) and "tool_calls" in chunk:
                        has_tool_calls = True
                        yield {"type": "tool_call_request", "tool_calls": chunk["tool_calls"]}
                        continue

                    raw_response += chunk
                    indices = [i for i in [raw_response.find("<scratchpad>"), raw_response.find("<thread_title>"), raw_response.find("<thread_naming>"), raw_response.find("<|tool_call>"), raw_response.find("<tool_call>")] if i != -1]
                    if indices:
                        hidden_idx = min(indices)
                        if hidden_idx > yielded_length:
                            yield {"type": "chunk", "content": raw_response[yielded_length:hidden_idx]}
                            yielded_length = hidden_idx
                        def _drain(gen):
                            out = ""
                            for c in gen: out += c
                            return out
                        try: raw_response += await asyncio.to_thread(_drain, sync_gen)
                        except Exception: pass
                        break
                    else:
                        safe_length = max(0, len(raw_response) - 16)
                        if safe_length > yielded_length:
                            yield {"type": "chunk", "content": raw_response[yielded_length:safe_length]}
                            yielded_length = safe_length

            if not indices and yielded_length < len(raw_response):
                yield {"type": "chunk", "content": raw_response[yielded_length:]}

            user_visible_response, internal_note_content = StreamProcessor._extract_scratchpad(state, raw_response)
            thread_name = StreamProcessor._extract_thread_title(raw_response)
            if thread_name:
                state.rename_thread(state.current_thread_id, thread_name)

            if not has_tool_calls:
                from tools.tool_registry import tool_registry
                parsed_calls = tool_registry.parse_gemma_tool_call(raw_response)
                if parsed_calls:
                    has_tool_calls = True
                    # Clean it from the visible response
                    import re
                    user_visible_response = re.sub(r"<\|?tool_call\|?>\s*call:\s*[a-zA-Z0-9_]+\s*\{.*?\}\s*<[^>]*tool_call[^>]*>", "", user_visible_response, flags=re.DOTALL | re.IGNORECASE).strip()
                    yield {"type": "tool_call_request", "tool_calls": parsed_calls}

            if not has_tool_calls:
                state.save_interaction(user_message, user_visible_response, internal_note_content)

            yield {
                "type": "done",
                "latency": round(time.time() - start_time, 2),
                "thread_name": thread_name,
                "scratchpad": internal_note_content,
                "has_tool_calls": has_tool_calls
            }

        except asyncio.CancelledError:
            if raw_response.strip():
                print("⚠️ Stream interrupted! Saving partial response...")
                user_visible_response, internal_note_content = StreamProcessor._extract_scratchpad(state, raw_response)
                thread_name = StreamProcessor._extract_thread_title(raw_response)
                if thread_name: state.rename_thread(state.current_thread_id, thread_name)
                state.save_interaction(user_message, user_visible_response, internal_note_content)
            raise
        except Exception as e:
            yield {"type": "error", "error": str(e)}