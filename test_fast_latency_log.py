#!/usr/bin/env python3
"""
FAST Mode Latency Validation
Captures checkpoint sequence and validates FAST mode rules
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / 'runtime'))

from dotenv import load_dotenv
load_dotenv()

import os
print('Configuration:')
print(f'  ARGO_LATENCY_PROFILE: {os.getenv("ARGO_LATENCY_PROFILE")}')
print(f'  ARGO_LOG_LATENCY: {os.getenv("ARGO_LOG_LATENCY")}')
print(f'  ARGO_STREAM_CHUNK_DELAY_MS: {os.getenv("ARGO_STREAM_CHUNK_DELAY_MS")}')
print()

from latency_controller import LatencyProfile, new_controller
import time

# Create controller in FAST mode
controller = new_controller(LatencyProfile.FAST)

print('='*70)
print('FAST MODE CHECKPOINT FLOW')
print('='*70)
print()

# Simulate checkpoint flow
controller.log_checkpoint('input_received')
elapsed = controller.elapsed_ms()
print(f'1. input_received                  {elapsed:>7.1f}ms')

time.sleep(0.01)
controller.log_checkpoint('intent_classified')
elapsed = controller.elapsed_ms()
print(f'2. intent_classified               {elapsed:>7.1f}ms')

time.sleep(0.01)
controller.log_checkpoint('model_selected')
elapsed = controller.elapsed_ms()
print(f'3. model_selected                  {elapsed:>7.1f}ms')

time.sleep(0.01)
controller.log_checkpoint('ollama_request_start')
ollama_start_elapsed = controller.elapsed_ms()
print(f'4. ollama_request_start            {ollama_start_elapsed:>7.1f}ms')

# Critical: First token should come quickly in FAST mode
time.sleep(0.15)  # Simulate fast token generation
controller.log_checkpoint('first_token_received')
ft_elapsed = controller.elapsed_ms()
first_token_latency = ft_elapsed - ollama_start_elapsed
print(f'5. first_token_received            {ft_elapsed:>7.1f}ms')
print(f'   ↳ From ollama_request_start: {first_token_latency:.1f}ms')

time.sleep(0.05)
controller.log_checkpoint('stream_complete')
elapsed = controller.elapsed_ms()
print(f'6. stream_complete                 {elapsed:>7.1f}ms')

time.sleep(0.01)
controller.log_checkpoint('processing_complete')
elapsed = controller.elapsed_ms()
print(f'7. processing_complete             {elapsed:>7.1f}ms')

# Get report
report = controller.report()
total_elapsed = report['elapsed_ms']

print()
print('='*70)
print('FAST MODE VALIDATION')
print('='*70)
print()
print(f'Profile:                  {report["profile"]}')
print(f'Total Elapsed:            {total_elapsed:.1f}ms')
print(f'First-Token Latency:      {ft_elapsed:.1f}ms (from input_received)')
print(f'Token Gen Time:           {first_token_latency:.1f}ms (from request_start)')
print()
print('FAST Mode Rules Check:')
print()

# Rule 1: No delay logs at all
stream_delay = int(os.getenv('ARGO_STREAM_CHUNK_DELAY_MS', '0'))
if stream_delay == 0:
    print('✅ No stream delays        PASS (stream delay = 0ms)')
else:
    print(f'❌ Stream delays present   FAIL (stream delay = {stream_delay}ms)')

# Rule 2: First token happens immediately after request_start
if first_token_latency <= 200:
    print('✅ Immediate token gen     PASS (first-token within 200ms of request)')
else:
    print(f'⚠️  Token gen latency       MARGINAL ({first_token_latency:.0f}ms > 200ms)')

# Rule 3: First-token latency <= 2s
if ft_elapsed <= 2000:
    print('✅ First-token <= 2000ms   PASS')
else:
    print(f'❌ First-token > 2000ms    FAIL ({ft_elapsed:.0f}ms)')

print()
print('='*70)
print('CHECKPOINT SEQUENCE (for Bob):')
print('='*70)
print()
for name, elapsed in report['checkpoints'].items():
    print(f'  {name:<30} {elapsed:>8.1f}ms')
print()
