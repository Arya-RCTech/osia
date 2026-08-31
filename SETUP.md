# Welcome to OSIA Setup! 🚀

Hello there! Welcome to OSIA (On-device Sovereign Intent Agent). Getting this local-first OS layer up and running takes just a few steps. This guide will walk you through the setup process on Linux so you can start chatting and executing tasks in no time.

## 💻 Hardware Requirements

OSIA is designed to run locally, which means your hardware does the heavy lifting.
- **Minimum:** 8GB VRAM (Great for smaller triage models like Qwen 4B).
- **Recommended:** 12GB+ VRAM (Perfect for running our default workhorse, **Gemma 4 (12B)**, alongside your vector memory).
- **No GPU?** - You can still run OSIA on your CPU, but I recommend running cloud models instead (for free).
---

## 🛠️ Step 1: Python Environment Setup

We highly recommend using a virtual environment to keep your dependencies tidy!

1. Clone the repo and navigate into it — this is your project root:
   ```bash
   git clone https://github.com/<your-username>/osia.git
   cd osia
   ```
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install the required Python packages (including FastAPI, ChromaDB, FastEmbed, and our API clients):
   ```bash
   pip install -r requirements.txt
   ```

---

## 🔑 Step 2: Setting Up Your `.env` File

OSIA uses a cloud fallback system for the heaviest tasks. The Hugging Face token isn't strictly required to run OSIA — its main job is caching: it prevents redundant re-downloads of models after major changes to `api.py` or `context_engine.py`. It's also handy if you want to download different embedding/tokenizer models from Hugging Face yourself, or swap the tokenizer entirely.

1. Create a file named `.env` in the project root.
2. Add the following keys to your `.env` file:

```env
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=your_google_key_here
HF_TOKEN=your_huggingface_token_here
```

**Where to get these keys (they are all free!):**
- [Groq API Key](https://console.groq.com/keys) (For lightning-fast cloud fallback)
- [Google Gemini API Key](https://aistudio.google.com/app/apikey) (For heavy-duty reasoning)
- [Hugging Face Token](https://huggingface.co/settings/tokens) (Optional — speeds up caching and lets you swap embedding/tokenizer models)

---

## 🧠 Step 3: Local Models & Configuration

By default, OSIA expects to run **Gemma 4** as its main "On Duty" model using **KoboldCpp**. 

- **If you have 12GB VRAM:** Stick with Gemma 4! Just ensure the `.gguf` file is placed inside the `koboldcpp/` directory.
- **If you have less than 12GB VRAM:** You can easily swap to a lighter model (like Qwen 3.5 4B).
- Make sure the exact file name is inserted inside `backend/models.json` under the `koboldcpp` key.

### GPU Backend Configuration (NVIDIA / AMD / Intel)

OSIA automatically manages and launches KoboldCpp instances for you in the background! **Do not run KoboldCpp manually**, or you will encounter port conflicts. 

By default, OSIA is configured to use the **Vulkan** backend (`--usevulkan`), which works universally across AMD, Intel, and NVIDIA GPUs. However, if you have an NVIDIA GPU, you'll get better performance by switching to CUDA.

To switch to CUDA (or tweak GPU offloading layers):
1. Open `backend/kobold_manager.py`
2. Look for the `cmd = [...]` list where the subprocess is configured.
3. Change `"--usevulkan"` to `"--usecublas"`.
4. (Optional) You can also adjust the fallback `"--gpulayers"` count if you need to manually control VRAM offloading.

> ⚠️ **Quantization heads-up:** if you're running Gemma4-family models, avoid `q4_0` KV cache quantization — it's caused KV-cache crashes on this project due to an architecture incompatibility. `q4_K_M`/`q8_0` or similar have been stable instead.

### Customizing Models (`backend/models.json`)
You can tweak, disable, or swap out models based on your hardware directly inside `backend/models.json`. 
Feel free to change the `default_chat_model` or adjust the `gpulayers` and `context_size` parameters for your specific GPU.

---

## 🧪 Step 4: Run the Tests

Want to make sure everything is wired up correctly before launching the UI? We have a comprehensive test suite ready for you.

From your project root (with your virtual environment activated), simply run:
```bash
pytest
```
*Note: The test suite uses isolated mock databases, so it won't touch your actual chat history!*

---

## 🐢 A Quick Heads-Up: The First Run

The **entry point is *flutter_ui/lib/main.dart* Debug and run it**
The very first time you launch OSIA or run a chat/test, it might feel a bit slow. **Don't panic!** 
OSIA is busy downloading the FastEmbed ONNX models and setting up your local ChromaDB vector store. Once those files are safely cached on your machine, subsequent runs will be blazingly fast. ⚡
Editing the user_profile.json with your personal information for relevance and memory is recommended for consistent memory.
---

**You're all set!** Enjoy your new local-first AI operating system. 
If you run into any quirks, double-check your `.env` keys and your model paths in `models.json`. Happy coding! 🎉
