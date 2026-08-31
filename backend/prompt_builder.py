import datetime
from model_registry import registry

SAFETY_INPUT_LIMIT = 2500

class PromptBuilder:
    @staticmethod
    def prepare_context(state, user_message, model_id, cheap_model, call_cheap_model_fn):
        import time
        t0 = time.time()
        with state._engine_lock:
            if model_id == "manager-lite":
                import os
                import re
                payload_path = os.path.join(os.path.dirname(__file__), "manager_payload.json")
                try:
                    with open(payload_path, "r", encoding="utf-8") as f:
                        payload = f.read()
                except Exception as e:
                    payload = f"Error reading manager_payload.json: {e}"
                
                # Replace the multiline {INSERT_REQUEST_HERE ... } with the actual prompt
                payload = re.sub(r"\{INSERT_REQUEST_HERE\s*\}", user_message, payload)
                
                # The entire payload acts as the system/user instruction.
                # We can just pass it as a single "user" message.
                print(f"⏱️ Total Context Prep: {time.time() - t0:.2f}s")
                return [{"role": "user", "content": payload}], user_message

            if state.memory.count_tokens(user_message, model_id=model_id) > SAFETY_INPUT_LIMIT:
                user_message = user_message[:(SAFETY_INPUT_LIMIT * 3)] + "\n...[TRUNCATED]..."

            rag_budget = registry.rag_budget(model_id)
            print(f"⏱️ Starting RAG at: {time.time() - t0:.2f}s")
            retrieved_context, _ = state.memory.retrieve_packed_context(user_message, state.db.conn, rag_budget)
            print(f"⏱️ Finished RAG at: {time.time() - t0:.2f}s")

            from state_manager import VERBATIM_WINDOW, MIN_SUMMARY_BATCH, SCRATCHPAD_LIMIT
            stable_index = len(state.active_session) - VERBATIM_WINDOW
            if stable_index > state.summary_pointer + MIN_SUMMARY_BATCH:
                delta_slice = state.active_session[state.summary_pointer:stable_index]
                
                import threading
                def _update_summary():
                    import time
                    time.sleep(2)  # Delay so main request hits KoboldCpp queue first!
                    new_summary = state.memory.run_delta_summary(
                        delta_slice,
                        state.rolling_summary,
                        completion_fn=call_cheap_model_fn,
                        cheap_model=cheap_model,
                    )
                    with state._engine_lock:
                        state.rolling_summary = new_summary
                
                threading.Thread(target=_update_summary, daemon=True).start()
                state.summary_pointer = stable_index

            recent_history = state.active_session[-VERBATIM_WINDOW:] if state.active_session else []
            current_iso_string = datetime.datetime.now(datetime.timezone.utc).isoformat()

            if state.memory.count_tokens(state.scratchpad, model_id=model_id) > SCRATCHPAD_LIMIT:
                state.save_interaction("", "", internal_note=state.scratchpad)
                state.scratchpad = "Previous thoughts archived."

            style_bullets = "\n".join([f"- {rule}" for rule in state.current_persona.get("style_guidelines", [])])
            
            if retrieved_context and len(retrieved_context) > 8000:
                retrieved_context = retrieved_context[:8000] + "\n...[memory truncated]"

            if state.rolling_summary and len(state.rolling_summary) > 4000:
                state.rolling_summary = state.rolling_summary[:4000] + "..."

            if state.scratchpad and len(state.scratchpad) > 1500:
                state.scratchpad = state.scratchpad[:1500] + "..."

            system_instruction = f"""
[System Anchor]: You are Osia. You have access to the current time(in UTC). Do not write or include timestamp or [just now] in your response. 
{state.current_persona.get("role_definition", "You are a Osia, witty,sarcastic friend.")}
Style Rules:
{style_bullets}
</system_role>

<system_context>
Profile: {state.user_profile}
</system_context>

<instructions>
**Internal Monologue**: You MUST end every response with <scratchpad>[Your hidden internal monologue]</scratchpad> 
    The scratchpad is:
    - A brief, structured internal note for YOU (the model)
    - a VOLATILE memory block, not an appending log. It is returned to you in the next turn as `<internal_scratchpad>`.
    - CRITICAL CONSTRAINTS:
        *   **DO NOT** copy, repeat, or summarize the contents of the previous `<internal_scratchpad>`.
        *   **DO NOT** transcribe/summarise the current conversation turn.
        *   **ONLY** write the "delta" (new changes in user state, shifted intent, or new temporary facts).
        *   Keep the scratchpad CONCISE (3-6 LINES MAX).
        *   **DO NOT** write Chain-of-Thought in the scratchpad.
    - inferred mood, intent, or goal
    - stability/changes in behavior
    - key data the user provided subtly
    - decisions you made like tone adjustment/jokes.(optional)
    - important context for continuity(optional)

</instructions>

<long_term_memory>
{retrieved_context}
</long_term_memory>

<session_summary>
{state.rolling_summary}
</session_summary>

<internal_scratchpad>
{state.scratchpad}
</internal_scratchpad>
"""

            msg_count = state.db.get_thread_message_count(state.current_thread_id)
            if msg_count == 0:
                system_instruction += """
    <thread_naming>
    This is the FIRST message in a new conversation thread. You MUST include a short title for this conversation.
    Format: <thread_title>Your Short Title Here</thread_title>
    Rules:
    - 3 to 6 words maximum
    - Capture the core topic/intent of the user's message
    - No quotes, no punctuation at the end
    - Place this tag at the very end of your response, AFTER the scratchpad
    </thread_naming>
"""

            messages = [{"role": "system", "content": system_instruction}]
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            current_ts = now_utc.isoformat()
            
            def get_relative_time(ts_str):
                try:
                    msg_time = datetime.datetime.fromisoformat(ts_str)
                    if msg_time.tzinfo is None:
                        msg_time = msg_time.replace(tzinfo=datetime.timezone.utc)
                    diff_mins = int((now_utc - msg_time).total_seconds() / 60)
                    if diff_mins < 2: return "Just now"
                    elif diff_mins < 5: return "2 mins ago"
                    elif diff_mins < 10: return "5 mins ago"
                    elif diff_mins < 60: return "10 mins ago"
                    elif diff_mins < 1440: return "1 hour ago"
                    else: return "More than 1 day ago"
                except Exception:
                    return "Unknown Time"

            for msg in recent_history:
                ts = msg.get("iso_timestamp", "")
                rel_time = get_relative_time(ts) if ts else "Unknown Time"
                fmt_content = f"[{rel_time}] {msg['content']}"
                messages.append({"role": msg["role"], "content": fmt_content})
                
            messages.append({"role": "user", "content": f"{user_message}\n\n<current_time_utc>{current_ts}</current_time_utc>"})
            
            # User wants tool instructions appended here
            from tools.tool_registry import tool_registry
            import json
            tools_data = tool_registry.get_schemas(["get_time"])
            if tools_data:
                tools_str = json.dumps(tools_data, indent=2)
                tool_msg = f"You have access to the following tools. To use a tool, output a JSON block with the tool call.\nCRITICAL RULE: Only use tools if the current user prompt asks for it or infers it.\n{tools_str}"
                messages.append({"role": "system", "content": tool_msg})
            
            print(f"⏱️ Total Context Prep: {time.time() - t0:.2f}s")
            return messages, user_message