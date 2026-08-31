import subprocess
import socket
import time
from pathlib import Path
from model_registry import registry

_kobold_processes = {}

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def ensure_model_running(model_id: str) -> bool:
    """Ensures the KoboldCpp instance for the given model_id is running."""
    provider = registry.provider_for(model_id)
    if provider != "koboldcpp":
        return True

    port = registry.get_port(model_id)
    if not port:
        print(f"⚠️  No port configured for {model_id} in models.json")
        return False

    if is_port_in_use(port):
        return True

    gguf = registry.get_gguf_filename(model_id)
    gpulayers = registry.get_gpulayers(model_id)
    context_size = registry.max_context_tokens(model_id)

    if not gguf:
        print(f"⚠️  No gguf_filename configured for {model_id} in models.json")
        return False

    # Assuming koboldcpp is in a subdirectory called 'koboldcpp' inside osia v0
    project_root = Path(__file__).resolve().parent.parent
    kobold_dir = project_root / "koboldcpp"
    
    if not kobold_dir.exists():
        # Fallback to checking next to osia v0
        kobold_dir = project_root.parent / "koboldcpp"

    executable = kobold_dir / "koboldcpp-linux-x64-nocuda"
    
    if not executable.exists():
        print(f"⚠️  KoboldCpp executable not found at {executable}")
        return False

    model_path = kobold_dir / gguf
    if not model_path.exists():
        print(f"⚠️  GGUF file not found at {model_path}")
        return False

    cmd = [
        str(executable),
        str(model_path),
        "--usevulkan",
        "--gpulayers", str(gpulayers) if gpulayers else "30",
        "--contextsize", str(context_size) if context_size else "8192",
        "--port", str(port),
        "--jinjathink", "true"
    ]

    print(f"🚀 Starting KoboldCpp for {model_id} on port {port}...")
    
    import threading
    proc = subprocess.Popen(
        cmd,
        cwd=str(kobold_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    _kobold_processes[model_id] = proc
    
    def _log_reader(p, m_id):
        try:
            for line in iter(p.stdout.readline, ''):
                if not line:
                    break
                if "CtxLimit:" in line and "Processed:" in line:
                    print(f"📊 [KoboldCpp {m_id}] {line.strip()}")
        except Exception:
            pass
            
    threading.Thread(target=_log_reader, args=(proc, model_id), daemon=True).start()

    # Wait for the port to become active
    retries = 120
    while retries > 0:
        if is_port_in_use(port):
            print(f"✅ KoboldCpp for {model_id} is now ready on port {port}.")
            return True
        time.sleep(1)
        retries -= 1
        
        # Check if process crashed
        if proc.poll() is not None:
            print(f"❌ KoboldCpp for {model_id} crashed immediately with code {proc.returncode}.")
            return False

    print(f"❌ Timeout waiting for KoboldCpp {model_id} to start on port {port}.")
    return False

def shutdown_model(model_id: str):
    """Kills the KoboldCpp instance for a specific model, forcefully freeing the port."""
    port = registry.get_port(model_id)
    
    # 1. Try killing via subprocess handle if we own it
    if model_id in _kobold_processes:
        proc = _kobold_processes[model_id]
        if proc.poll() is None:
            print(f"🛑 Shutting down KoboldCpp instance for {model_id} (PID: {proc.pid})...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        del _kobold_processes[model_id]
        
    # 2. Force kill any rogue process still holding the port (e.g. from a previous crashed session)
    if port:
        # fuser -k sends SIGKILL to the process bound to the port
        subprocess.run(["fuser", "-k", f"{port}/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"🧹 Force-cleared port {port} for model {model_id}")
        return True
        
    return False

def shutdown_all():
    """Kills all KoboldCpp subprocesses and clears all local model ports."""
    # Kill tracked processes
    for model_id, proc in _kobold_processes.items():
        if proc.poll() is None:
            print(f"🛑 Shutting down KoboldCpp instance for {model_id} (PID: {proc.pid})...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    _kobold_processes.clear()
    
    # Force kill any process holding local model ports
    for model_id in registry.all_models():
        if registry.provider_for(model_id) == "koboldcpp":
            port = registry.get_port(model_id)
            if port:
                subprocess.run(["fuser", "-k", f"{port}/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
