import urllib.request
import json
import httpx
from groq import Groq
from model_registry import registry
from kobold_manager import ensure_model_running

class LLMTransport:
    def __init__(self, groq_key=None, gemini_client=None):
        if not groq_key:
            groq_key = registry.get_api_key("groq")
        self.groq_client = Groq(api_key=groq_key)

        if gemini_client is None:
            gemini_key = registry.get_api_key("google")
            if gemini_key:
                try:
                    from google import genai
                    gemini_client = genai.Client(api_key=gemini_key)
                except ImportError:
                    pass
        self.gemini_client = gemini_client

    def call_sync(self, model_id, messages, thinking=False, tools=None):
        provider = registry.provider_for(model_id)
        if provider == "google":
            return self._call_gemini(model_id, messages, thinking, tools)
        elif provider == "koboldcpp" or provider == "ollama":
            return self._call_koboldcpp(model_id, messages, thinking, tools)
        else:
            return self._call_groq(model_id, messages, thinking, tools)

    def call_stream(self, model_id, messages, thinking=False, tools=None):
        provider = registry.provider_for(model_id)
        if provider == "koboldcpp" or provider == "ollama":
            return self._call_koboldcpp_stream(model_id, messages, thinking, tools)
        elif provider == "google":
            return self._call_gemini_stream(model_id, messages, thinking, tools)
        else:
            return self._call_groq_stream(model_id, messages, thinking, tools)

    def _call_koboldcpp(self, model_id, messages, thinking=False, tools=None):
        if not ensure_model_running(model_id):
            return f"Error: Failed to start KoboldCpp for {model_id}."
            
        port = registry.get_port(model_id)
        max_out = registry.max_output_tokens(model_id)
        
        # Deep copy messages so we don't mutate the original list for future retries
        import copy
        import re
        payload_messages = []
        for msg in messages:
            new_msg = copy.deepcopy(msg)
            if new_msg["role"] == "assistant" and isinstance(new_msg.get("content"), str):
                new_msg["content"] = re.sub(r"<\|channel>thought.*?<channel\|>", "", new_msg["content"], flags=re.DOTALL | re.IGNORECASE).strip()
            payload_messages.append(new_msg)
            
        if thinking and payload_messages and payload_messages[0]["role"] == "system":
            payload_messages[0]["content"] = "<|think|>\n" + payload_messages[0]["content"].lstrip()
        
        payload = {
            "messages": payload_messages, 
            "stream": False, 
            "temperature": 1.0, 
            "top_p": 0.95,
            "top_k": 64,
            "max_tokens": max_out
        }
        
        if tools:
            payload["tools"] = tools
            
        endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
        req = urllib.request.Request(endpoint, headers={"Content-Type": "application/json"}, data=json.dumps(payload).encode("utf-8"))
        
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})
                if "tool_calls" in msg and msg["tool_calls"]:
                    return {"tool_calls": msg["tool_calls"]}
                content = msg.get("content", "")
                
                return content
        except Exception as e:
            return f"Error connecting to local KoboldCpp ({e})."

    def _call_gemini(self, model_id, messages, thinking=False, tools=None):
        if not self.gemini_client: return "Error: Gemini client not initialized."
        system_text = ""
        contents = []
        from google.genai import types
        import json
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            elif msg["role"] == "tool":
                try:
                    result_dict = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
                    part = types.Part.from_function_response(name=msg.get("name", "tool"), response=result_dict)
                    contents.append(types.Content(role="user", parts=[part]))
                except Exception as e:
                    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=str(msg["content"]))]))
            else:
                role = "user" if msg["role"] == "user" else "model"
                parts = []
                if msg.get("content"):
                    import re
                    clean_content = re.sub(r"<\|channel>thought.*?<channel\|>", "", msg["content"], flags=re.DOTALL | re.IGNORECASE).strip()
                    if clean_content:
                        parts.append(types.Part.from_text(text=clean_content))
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        fn = tc.get("function", {})
                        if isinstance(fn, dict):
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except:
                                    args = {}
                            parts.append(types.Part.from_function_call(name=fn.get("name", ""), args=args))
                if not parts:
                    parts.append(types.Part.from_text(text=""))
                contents.append(types.Content(role=role, parts=parts))

        max_out = registry.max_output_tokens(model_id)
        config_kwargs = {"system_instruction": system_text.strip() if system_text else None, "temperature": 0.7, "max_output_tokens": max_out}
        from thinking_manager import apply_thinking_config_gemini
        apply_thinking_config_gemini(model_id, config_kwargs, thinking)
        if tools:
            gemini_tools = [{"function_declarations": [t["function"] for t in tools]}]
            config_kwargs["tools"] = gemini_tools

        history = contents[:-1]
        last_message = contents[-1].parts if contents else [types.Part.from_text(text="")]
        
        chat = self.gemini_client.chats.create(model=model_id, config=types.GenerateContentConfig(**config_kwargs), history=history)
        response = chat.send_message(last_message)  # type: ignore  # type: ignore
        
        if response.function_calls:
            calls = []
            for fc in response.function_calls:
                calls.append({"function": {"name": fc.name, "arguments": fc.args}})
            return {"tool_calls": calls}
            
        text_parts = []
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for p in response.candidates[0].content.parts:
                is_thought = getattr(p, 'thought', False)
                p_text = getattr(p, 'text', '')
                if is_thought:
                    thought_content = is_thought if isinstance(is_thought, str) else p_text
                    if thought_content:
                        text_parts.append(f"<|channel>thought\n{thought_content}\n<channel|>\n")
                elif p_text:
                    text_parts.append(p_text)
                    
        return "".join(text_parts) if text_parts else response.text

    def _call_groq(self, model_id, messages, thinking=False, tools=None):
        max_out = registry.max_output_tokens(model_id)
        kwargs = {"messages": messages, "model": model_id, "temperature": 0.7, "max_tokens": max_out}
        from thinking_manager import apply_thinking_config_groq
        apply_thinking_config_groq(model_id, kwargs, thinking)
        if tools: kwargs["tools"] = tools
        completion = self.groq_client.chat.completions.create(**kwargs)
        msg = completion.choices[0].message
        if msg.tool_calls:
            calls = [{"function": {"name": call.function.name, "arguments": json.loads(call.function.arguments)}} for call in msg.tool_calls]
            return {"tool_calls": calls}
        return msg.content

    async def _call_koboldcpp_stream(self, model_id, messages, thinking=False, tools=None):
        if not ensure_model_running(model_id):
            yield f"Error: Failed to start KoboldCpp for {model_id}."
            return

        port = registry.get_port(model_id)
        max_out = registry.max_output_tokens(model_id)
        
        import copy
        import re
        payload_messages = []
        for msg in messages:
            new_msg = copy.deepcopy(msg)
            if new_msg["role"] == "assistant" and isinstance(new_msg.get("content"), str):
                # Remove past thoughts from history
                new_msg["content"] = re.sub(r"<\|channel>thought.*?<channel\|>", "", new_msg["content"], flags=re.DOTALL | re.IGNORECASE).strip()
            payload_messages.append(new_msg)
            
        payload = {
            "messages": payload_messages, 
            "stream": True, 
            "temperature": 1.0, 
            "top_p": 0.95,
            "top_k": 64,
            "max_tokens": max_out
        }
        
        from thinking_manager import apply_thinking_config_koboldcpp
        apply_thinking_config_koboldcpp(model_id, payload, thinking)
        
        if tools:
            payload["tools"] = tools
            
        print(f"🔥 KOBOLD PAYLOAD: max_tokens={payload.get('max_tokens')} thinking={thinking}")
            
        endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
        timeout = httpx.Timeout(connect=120.0, read=120.0, write=10.0, pool=10.0)
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", endpoint, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or line == "data: [DONE]":
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        try: 
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                            
                        delta = choices[0].get("delta", {})
                        
                        if "tool_calls" in delta and delta["tool_calls"]:
                            yield {"tool_calls": delta["tool_calls"]}
                            continue
                            
                        content = delta.get("content", "")
                        
                        if content:
                            yield content
        except Exception as e:
            yield f"Error: {e}"


    def _call_gemini_stream(self, model_id, messages, thinking=False, tools=None):
        if not self.gemini_client:
            yield "Error: Gemini client not initialized."
            return
        system_text = ""
        contents = []
        from google.genai import types
        import json
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            elif msg["role"] == "tool":
                try:
                    result_dict = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
                    part = types.Part.from_function_response(name=msg.get("name", "tool"), response=result_dict)
                    contents.append(types.Content(role="user", parts=[part]))
                except Exception as e:
                    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=str(msg["content"]))]))
            else:
                role = "user" if msg["role"] == "user" else "model"
                parts = []
                if msg.get("content"):
                    import re
                    clean_content = re.sub(r"<\|channel>thought.*?<channel\|>", "", msg["content"], flags=re.DOTALL | re.IGNORECASE).strip()
                    if clean_content:
                        parts.append(types.Part.from_text(text=clean_content))
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        fn = tc.get("function", {})
                        if isinstance(fn, dict):
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except:
                                    args = {}
                            parts.append(types.Part.from_function_call(name=fn.get("name", ""), args=args))
                if not parts:
                    parts.append(types.Part.from_text(text=""))
                contents.append(types.Content(role=role, parts=parts))

        max_out = registry.max_output_tokens(model_id)
        config_kwargs = {"system_instruction": system_text.strip() if system_text else None, "temperature": 0.7, "max_output_tokens": max_out}
        from thinking_manager import apply_thinking_config_gemini
        apply_thinking_config_gemini(model_id, config_kwargs, thinking)
        if tools:
            gemini_tools = [{"function_declarations": [t["function"] for t in tools]}]
            config_kwargs["tools"] = gemini_tools

        history = contents[:-1]
        last_message = contents[-1].parts if contents else [types.Part.from_text(text="")]
        
        chat = self.gemini_client.chats.create(model=model_id, config=types.GenerateContentConfig(**config_kwargs), history=history)
        response = chat.send_message_stream(last_message)  # type: ignore
        for chunk in response:
            if chunk.function_calls:
                calls = [{"function": {"name": fc.name, "arguments": json.dumps(fc.args) if fc.args else "{}"}} for fc in chunk.function_calls]
                yield {"tool_calls": calls}
            
            if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                text_parts = []
                for p in chunk.candidates[0].content.parts:
                    is_thought = getattr(p, 'thought', False)
                    p_text = getattr(p, 'text', '')
                    if is_thought:
                        # If p.thought is a string, use it. Otherwise use p.text.
                        thought_content = is_thought if isinstance(is_thought, str) else p_text
                        if thought_content:
                            text_parts.append(f"<|channel>thought\n{thought_content}\n<channel|>\n")
                    elif p_text:
                        text_parts.append(p_text)
                if text_parts:
                    yield "".join(text_parts)

    def _call_groq_stream(self, model_id, messages, thinking=False, tools=None):
        max_out = registry.max_output_tokens(model_id)
        kwargs = {"messages": messages, "model": model_id, "temperature": 0.7, "max_tokens": max_out, "stream": True}
        from thinking_manager import apply_thinking_config_groq
        apply_thinking_config_groq(model_id, kwargs, thinking)
        if tools: kwargs["tools"] = tools
        response = self.groq_client.chat.completions.create(**kwargs)
        
        # If API ignores stream=True and returns a ChatCompletion directly
        if hasattr(response, 'choices'):
            msg = response.choices[0].message
            if getattr(msg, "tool_calls", None):
                calls = [{"function": {"name": call.function.name, "arguments": json.loads(call.function.arguments)}} for call in msg.tool_calls]
                yield {"tool_calls": calls}
            elif msg.content:
                yield msg.content
            return

        tool_calls_buffer = {}
        for chunk in response:
            if hasattr(chunk, 'choices') and chunk.choices:
                delta = chunk.choices[0].delta
                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_buffer:
                            name = tc.function.name if tc.function and tc.function.name else "unknown"
                            args = tc.function.arguments if tc.function and tc.function.arguments else ""
                            tool_calls_buffer[idx] = {"name": name, "arguments": args}
                        else:
                            if tc.function and tc.function.arguments:
                                tool_calls_buffer[idx]["arguments"] += tc.function.arguments
                content = delta.content
                if content: yield content
        
        if tool_calls_buffer:
            calls = [{"function": {"name": v["name"], "arguments": json.loads(v["arguments"])}} for v in tool_calls_buffer.values()]
            yield {"tool_calls": calls}

    def call_cheap_model(self, messages, model_id, max_tokens=400):
        provider = registry.provider_for(model_id)
        if provider == "koboldcpp" or provider == "ollama":
            if not ensure_model_running(model_id):
                return ""
            port = registry.get_port(model_id)
            payload = {
                "messages": messages, 
                "stream": False, 
                "temperature": 0.3, 
                "max_tokens": max_tokens
            }
            endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
            req = urllib.request.Request(endpoint, headers={"Content-Type": "application/json"}, data=json.dumps(payload).encode("utf-8"))
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
            except Exception:
                return ""
        elif provider == "google":
            if not self.gemini_client:
                fallback = next((m for m, cfg in registry.all_models().items() if cfg.get("provider") == "groq"), None)
                if fallback: return self._call_groq(fallback, messages)
                return ""
            system_text = ""
            contents = []
            for msg in messages:
                if msg["role"] == "system":
                    system_text += msg["content"] + "\n"
                else:
                    contents.append({"role": "user" if msg["role"] == "user" else "model", "parts": [{"text": msg["content"]}]})
            from google.genai import types
            history = contents[:-1] if len(contents) > 1 else []
            last_message = contents[-1]["parts"][0]["text"] if contents else ""
            chat = self.gemini_client.chats.create(model=model_id, config=types.GenerateContentConfig(system_instruction=system_text.strip() or None, temperature=0.3, max_output_tokens=max_tokens), history=history)
            resp = chat.send_message(last_message)
            return resp.text
        else:
            completion = self.groq_client.chat.completions.create(messages=messages, model=model_id, temperature=0.3, max_tokens=max_tokens)
            return completion.choices[0].message.content