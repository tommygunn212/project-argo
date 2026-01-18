Target checkpoint: ollama_request_start

Profile affected: FAST

Reason: Largest single latency gap (300,152ms avg). The delay from ollama_request_start to first_token_received represents 49.8% of total first-token latency (300ms / 601ms). Reducing request startup latency will directly improve first-token SLA.
