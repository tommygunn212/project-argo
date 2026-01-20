# ARGO Speed Optimization Baseline (Jan 19, 2026)

## WINNER: Qwen (2.3GB) ⚡

### Current Configuration (FINAL)
- **LLM Model**: qwen:latest (2.3GB, ~7B parameters)
- **Latency Profile**: FAST (zero intentional delays)
- **Stream Chunk Delay**: 0ms
- **LLM Context Window**: 256 tokens (num_predict 256)
- **LLM Temperature**: 0.3 (deterministic)
- **TTS Voice**: allen (British male, en_GB-alan-medium.onnx)
- **TTS Speech Rate**: 0.85 length_scale (15% faster speech)

### Performance Comparison
| Metric | Neural-Chat | Qwen | Winner |
|--------|-------------|------|--------|
| TTFT | 2,315ms | 1,675ms | **Qwen** |
| Model Size | 4.1GB | 2.3GB | **Qwen** |
| Memory | Higher | Lower | **Qwen** |
| **Speedup** | — | **+27.7%** faster | **Qwen** |

### Expected End-to-End Improvement
- Previous (llama3.1:8b + 1.0 speech): Baseline
- Neural-Chat: ~15-20% faster
- **Qwen + 0.85 speech: ~40-45% faster total** ⚡

### Quality Assessment
- Neural-Chat: Vivid, longer responses, creative
- **Qwen: Concise, direct, personality-appropriate** ✓

### Deployment
✅ Qwen set as argo:latest
✅ Ready for production (wake-word testing)
