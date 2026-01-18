# Latency Profile Analysis

**Generated:** January 18, 2026  
**Data Collection:** 15 workflows per profile  
**Framework Version:** v1.4.5

---

## FAST Profile

| Checkpoint | Avg (ms) | P95 (ms) |
|---|---|---|
| input_received | 0.0 | 0.0 |
| transcription_complete | 50616.87 | 51049.47 |
| intent_classified | 200954.48 | 201368.14 |
| model_selected | 281297.05 | 281907.32 |
| ollama_request_start | 301623.47 | 302453.71 |
| first_token_received | 601966.73 | 602721.07 |
| stream_complete | 1102294.32 | 1103013.61 |
| processing_complete | 1202727.73 | 1203529.45 |

---

## VOICE Profile

| Checkpoint | Avg (ms) | P95 (ms) |
|---|---|---|
| input_received | 0.0 | 0.0 |
| transcription_complete | 50480.86 | 50704.96 |
| intent_classified | 200659.58 | 201064.68 |
| model_selected | 280955.43 | 281483.6 |
| ollama_request_start | 301212.63 | 302032.76 |
| first_token_received | 601446.09 | 602046.59 |
| stream_complete | 1101693.12 | 1102303.89 |
| processing_complete | 1202019.58 | 1202890.97 |
