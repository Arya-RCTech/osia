"""
End-to-end test: hit the FastAPI /api/v1/chat/stream endpoint
exactly like the Flutter app does, for both local Ollama models.
"""
import requests
import json
import sys
import time

BASE_URL = "http://127.0.0.1:8000"

def test_stream(model_id, message="Say hello in 3 words."):
    print(f"\n{'='*60}")
    print(f"[E2E] Testing model: {model_id}")
    print(f"[E2E] Message: {message}")
    print("-" * 60)
    
    payload = {
        "message": message,
        "model_id": model_id,
        "thinking": False,
    }
    
    start = time.time()
    full_text = ""
    chunk_count = 0
    done_payload = None
    
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/chat/stream",
            json=payload,
            stream=True,
            timeout=(10, 120),
        )
        resp.raise_for_status()
        
        for line in resp.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8").strip()
            if not line_str.startswith("data: "):
                continue
            data_str = line_str[6:].strip()
            if not data_str:
                continue
            
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            
            msg_type = data.get("type")
            
            if msg_type == "chunk":
                content = data.get("content", "")
                full_text += content
                sys.stdout.write(content)
                sys.stdout.flush()
                chunk_count += 1
            elif msg_type == "done":
                done_payload = data
                print(f"\n[DONE] latency={data.get('latency')}s thread_name={data.get('thread_name')}")
                break
            elif msg_type == "error":
                print(f"\n[ERROR] {data.get('error')}")
                break
    
    except Exception as e:
        print(f"\n[CONNECTION ERROR] {e}")
        return False
    
    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"[RESULT] {chunk_count} chunks in {elapsed:.2f}s")
    print(f"[RESULT] Text ({len(full_text)} chars): {repr(full_text[:300])}")
    
    success = len(full_text) > 0
    print(f"[{'PASS' if success else 'FAIL'}] {'Got text output' if success else 'NO TEXT OUTPUT!'}")
    return success

if __name__ == "__main__":
    # First check if backend is up
    try:
        h = requests.get(f"{BASE_URL}/api/v1/health", timeout=3)
        print(f"[OK] Backend is running. Health: {h.status_code}")
    except:
        print("[FAIL] Backend not running at port 8000. Start it first.")
        sys.exit(1)

    # Test both local models
    results = {}
    for model in ["qwen3.5:4b", "gemma4:12b"]:
        results[model] = test_stream(model)

    print(f"\n\n{'='*60}")
    print("FINAL RESULTS:")
    for m, ok in results.items():
        print(f"  {m}: {'✅ PASS' if ok else '❌ FAIL'}")
