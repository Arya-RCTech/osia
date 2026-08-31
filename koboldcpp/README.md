## Put your .gguf files here which you want to try inside OSIA.
- I used 2 models to test since Koboldcpp offers ports 5001 and 5002
- Link to the models I tried (my code uses slightly different file names):

```bash
hf download hf://unsloth/gemma-4-12b-it-GGUF/gemma-4-12b-it-UD-Q4_K_XL.gguf
```
alternatively, a slightly smaller better version is QAT release

```bash
hf download hf://unsloth/gemma-4-12B-it-qat-GGUF/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf
```

```bash
hf download hf://unsloth/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q5_K_M.gguf
```
