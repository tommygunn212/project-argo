# Raspberry Pi as Eyes, Ears, and Display Node

## Trust and Safety Role

The Raspberry Pi is not the brain of the system. ARGO Core on your main PC is the brain. The Raspberry Pi exists to be a sensory and output node—it sees, hears, speaks, and displays content, but it has no authority, no memory, and no independent decision-making ability.

This separation is intentional. It keeps the trust boundary simple: all critical decisions, all memory, and all authority live in one place. The Pi is a dumb, obedient peripheral that reports what it senses and waits for instructions from Core.

---

## OVERVIEW

The Raspberry Pi is not the brain of the system.
ARGO Core (main PC) is the brain.
The Raspberry Pi acts only as a sensory and output node.

The Pi provides:
- Hearing (microphone)
- Vision (camera)
- Speech output (Bluetooth soundbar)
- Visual output (HDMI display)
- Input switching (HDMI-CEC / IR / TV API)

All decisions, memory, and authority live in ARGO Core.


## EARS — MICROPHONE INPUT

1. USB microphone plugs directly into the Raspberry Pi
2. Pi recognizes the mic as an ALSA input device
3. Pi captures raw audio only
4. Pi performs basic checks:
   - silence detection
   - max recording length
   - audio file integrity
5. Audio is saved as a WAV file
6. WAV file is sent to ARGO Core over the local network
7. Pi waits for instructions

Rules:
- No transcription on the Pi
- No intent detection
- No retries if mic fails
- Failure is reported immediately


## EYES — CAMERA INPUT

8. Pi camera or USB camera connects to the Raspberry Pi
9. Camera activates only when explicitly requested
10. Pi captures still images or short clips
11. Optional lightweight processing:
    - motion detection
    - object labels only
12. Media is sent to ARGO Core

Rules:
- No continuous recording
- No cloud uploads
- No memory storage on the Pi
- No interpretation or decision-making


## MOUTH — BLUETOOTH SOUNDBAR

13. Bluetooth soundbar pairs with the Raspberry Pi
14. Soundbar becomes the default audio output
15. ARGO Core generates speech (TTS)
16. Audio stream is sent from Core to the Pi
17. Pi outputs audio to the soundbar

Rules:
- No local TTS generation on the Pi
- If Bluetooth disconnects, Pi reports failure and stops output
- No background or unsolicited speech


## VISUAL OUTPUT — HDMI DISPLAY

18. Raspberry Pi connects to TV or monitor via HDMI
19. Pi displays:
    - images
    - system dashboards
    - documents or specs
20. Pi shows only content sent by ARGO Core
21. Visuals auto-dismiss when complete


## HDMI INPUT SWITCHING

22. Pi controls TV input using:
    - HDMI-CEC (preferred)
    - IR blaster (fallback)
    - Smart TV API (if available)
23. ARGO Core decides when visuals are needed
24. Core commands Pi to switch TV input
25. Pi switches input to the Pi HDMI source
26. Pi displays requested content
27. Pi optionally returns TV to previous input

Rules:
- Manual TV remote override always wins
- Pi backs off immediately if overridden


## NETWORK ROLE

28. Pi connects to ARGO Core over the local network
29. Each Pi has a unique room ID
30. Pi uses a single secure communication channel
31. Audio, video, and commands flow through this channel
32. Pi never communicates with other Pis directly


## FAILURE BEHAVIOR

33. On any failure (mic, camera, audio, HDMI):
    - Pi reports the failure
    - Pi stops activity
    - ARGO Core decides next steps
34. No auto-recovery without instruction


## WHAT THE PI NEVER DOES

35. No intent decisions
36. No memory storage
37. No email or messaging actions
38. No autonomous execution
39. No continuous listening
40. No cloud dependency
41. No guessing or inference


## SUMMARY

The Raspberry Pi is a dumb, obedient peripheral.
It sees, hears, speaks, and displays only when instructed.
All intelligence, authority, and trust live in ARGO Core.
