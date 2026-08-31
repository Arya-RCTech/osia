import json
from typing import Callable, Dict, Any, List
from pydantic import BaseModel

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, description: str, schema: type[BaseModel], func: Callable, is_destructive: bool = False):
        """Registers a tool with its Pydantic schema and execution function."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "schema": schema,
            "func": func,
            "is_destructive": is_destructive
        }

    def get_schemas(self, tool_names: List[str]) -> List[dict]:
        """Returns the native JSON schema format for the specified tools."""
        schemas = []
        for name in tool_names:
            if name in self._tools:
                tool = self._tools[name]
                schema_dict = tool["schema"].model_json_schema()
                # Remove title to keep it clean
                schema_dict.pop("title", None)
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool["description"],
                        "parameters": schema_dict
                    }
                })
        return schemas

    def parse_gemma_tool_call(self, text: str) -> List[dict]:
        """Parses Gemma-style native tool calls and converts them to OpenAI format.
        Example: <|tool_call>call:get_time{timezone: "Asia/India"}<tool_call|>
        """
        import re
        import json
        
        results = []
        pattern = r"<\|?tool_call\|?>\s*call:\s*([a-zA-Z0-9_]+)\s*(\{.*?\})\s*<[^>]*tool_call[^>]*>"
        
        matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)
        for match in matches:
            tool_name = match.group(1)
            args_str = match.group(2)
            
            # Attempt to fix unquoted keys (e.g. {timezone: "Asia/India"} -> {"timezone": "Asia/India"})
            fixed_args_str = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', args_str)
            
            try:
                args = json.loads(fixed_args_str)
            except json.JSONDecodeError:
                import ast
                try:
                    args = ast.literal_eval(fixed_args_str)
                except Exception:
                    print(f"⚠️ Failed to parse tool call args: {args_str}")
                    continue
                
            if isinstance(args, dict):
                results.append({
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args)
                    }
                })
            
        return results

    def execute_tool(self, name: str, args: dict) -> dict:
        """Validates arguments via Pydantic and executes the tool function."""
        if name not in self._tools:
            print(f"⚠️ Model attempted to call unknown tool: {name}")
            return {"error": f"Tool '{name}' not found."}
        
        print(f"🛠️  Executing tool: {name} with args: {args}")
        tool = self._tools[name]
        try:
            # Validate args
            validated_args = tool["schema"](**args)
            # Execute
            result = tool["func"](**validated_args.model_dump())
            return result
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}"}

    def is_destructive(self, name: str) -> bool:
        """Checks if a tool requires user confirmation before execution."""
        return self._tools.get(name, {}).get("is_destructive", False)

# Singleton registry
tool_registry = ToolRegistry()

from pydantic import BaseModel, Field

# Example tool (to be expanded later)
class GetTimeSchema(BaseModel):
    timezone: str = Field(
        default="UTC", 
        description="The IANA timezone string (e.g. 'America/New_York', 'Asia/Kolkata', 'Asia/Tehran')."
    )

def get_time(timezone: str = "UTC"):
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone)
    except Exception:
        from datetime import timezone as dt_timezone
        tz = dt_timezone.utc
    return {"time": datetime.now(tz).isoformat(), "timezone": timezone}

tool_registry.register(
    name="get_time",
    description="Get the current time in a specific timezone.",
    schema=GetTimeSchema,
    func=get_time,
    is_destructive=False
)
