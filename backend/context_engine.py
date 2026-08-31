import time
import asyncio
from model_registry import registry
from state_manager import StateManager
from prompt_builder import PromptBuilder
from llm_transport import LLMTransport
from stream_processor import StreamProcessor
from tools.tool_registry import tool_registry
import json

class ContextEngine:
    def __init__(self, groq_key=None, gemini_client=None, gemini_key_ignored=None):
        print("🧠 Booting up Osia v2.0 (Modular Refactor)...")

        self.state = StateManager()
        self.transport = LLMTransport(groq_key=groq_key, gemini_client=gemini_client)
        
        self.chat_model = registry.default_chat_model()
        self.cheap_model = registry.default_cheap_model()
        print(f"   -> Default chat model  : {self.chat_model}")
        print(f"   -> Background model    : {self.cheap_model}")

        print("✅ Osia Context Engine Online.")

    @property
    def current_thread_id(self): return self.state.current_thread_id
    @current_thread_id.setter
    def current_thread_id(self, value): self.state.current_thread_id = value
    @property
    def current_persona(self): return self.state.current_persona
    @property
    def scratchpad(self): return self.state.scratchpad
    @scratchpad.setter
    def scratchpad(self, value): self.state.scratchpad = value
    @property
    def user_profile(self): return self.state.user_profile
    @property
    def conn(self): return self.state.conn
    @property
    def rolling_summary(self): return self.state.rolling_summary
    @property
    def active_session(self): return self.state.active_session

    def get_threads(self): return self.state.get_threads()
    def create_thread(self, name): return self.state.create_thread(name)
    def load_history(self, limit=50, thread_id=None): return self.state.load_history(limit=limit, thread_id=thread_id)
    def load_persona(self, persona_name): return self.state.load_persona(persona_name)
    def rename_thread(self, thread_id, new_name): return self.state.rename_thread(thread_id, new_name)
    def delete_thread(self, thread_id): return self.state.delete_thread(thread_id)
    def save_interaction(self, user_msg, ai_msg, internal_note=None): return self.state.save_interaction(user_msg, ai_msg, internal_note)
    def switch_thread(self, new_thread_id): return self.state.switch_thread(new_thread_id)

    def chat(self, user_message, model_id=None, thinking=False):
        if not model_id: model_id = self.chat_model
        
        messages, original_user_msg = PromptBuilder.prepare_context(
            self.state, user_message, model_id, self.cheap_model, self.transport.call_cheap_model
        )

        tool_names = self.current_persona.get("tools", [])
        tools = tool_registry.get_schemas(tool_names) if tool_names else None

        start_time = time.time()
        
        while True:
            try:
                raw_response = self.transport.call_sync(model_id, messages, thinking=thinking, tools=tools)
                
                # Check if it's a dict containing tool_calls
                if isinstance(raw_response, dict) and "tool_calls" in raw_response:
                    tool_calls = raw_response["tool_calls"]
                    
                    messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})  # type: ignore
                    
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            func = tc.get("function", {})
                            if isinstance(func, dict):
                                name = func.get("name", "unknown")
                                args = func.get("arguments", {})
                                if isinstance(args, str):
                                    try: args = json.loads(args)
                                    except: args = {}
                                    
                                result = tool_registry.execute_tool(name, args)
                                messages.append({"role": "tool", "name": name, "content": json.dumps(result)})
                        
                    continue # loop back to call model again
                    
                user_visible_response, internal_note_content = StreamProcessor._extract_scratchpad(self.state, raw_response)
                thread_name = StreamProcessor._extract_thread_title(raw_response)
                
                if thread_name: self.rename_thread(self.current_thread_id, thread_name)
                self.save_interaction(original_user_msg, user_visible_response, internal_note_content)

                return user_visible_response, {"latency": round(time.time() - start_time, 2), "thread_name": thread_name}
            except Exception as e:
                return f"Error: {e}", None

    async def chat_stream(self, user_message, model_id=None, thinking=False):
        if not model_id: model_id = self.chat_model
        
        messages, original_user_msg = await asyncio.to_thread(
            PromptBuilder.prepare_context, self.state, user_message, model_id, self.cheap_model, self.transport.call_cheap_model
        )

        tool_names = self.current_persona.get("tools", [])
        tools = tool_registry.get_schemas(tool_names) if tool_names else None

        start_time = time.time()
        
        while True:
            tool_call_requests = []
            assistant_content = ""
            
            async for chunk in StreamProcessor.process_stream(
                self.state, self.transport, original_user_msg, messages, model_id, thinking, start_time, tools=tools
            ):
                if isinstance(chunk, dict):
                    c_type = chunk.get("type")
                    if c_type == "tool_call_request":
                        calls = chunk.get("tool_calls", [])
                        if isinstance(calls, list):
                            tool_call_requests.extend(calls)
                            for tc in calls:
                                if isinstance(tc, dict):
                                    func = tc.get("function", {})
                                    if isinstance(func, dict):
                                        yield {"type": "tool_call", "name": func.get("name", "unknown"), "status": "executing"}
                        continue
                        
                    if c_type == "chunk":
                        assistant_content += str(chunk.get("content", ""))
                        
                    if c_type == "done":
                        if not chunk.get("has_tool_calls"):
                            yield chunk
                            return
                        else:
                            break # execute tools
                yield chunk
            
            if not tool_call_requests:
                break
                
            messages.append({"role": "assistant", "content": assistant_content, "tool_calls": tool_call_requests})  # type: ignore
            
            for tc in tool_call_requests:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    if isinstance(func, dict):
                        name = func.get("name", "unknown")
                        args = func.get("arguments", {})
                        if isinstance(args, str):
                            try: args = json.loads(args)
                            except: args = {}
                            
                        result = await asyncio.to_thread(tool_registry.execute_tool, name, args)
                        messages.append({"role": "tool", "name": name, "content": json.dumps(result)})