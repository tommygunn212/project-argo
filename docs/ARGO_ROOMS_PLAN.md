# Room-to-room (phase 8) - what exists and what is needed

Status: planning only. No satellite hardware has been built or tested.

## Already in place
- Voice runs through a self-hosted LiveKit server, so a second room is just another client joining the same server.
- The board, jobs, topics and parked ideas are server-side, so every room sees the same state.
- The wake/sleep gate and urgent-stop gate work per session.

## Needed for a room satellite
1. A Raspberry Pi (or any small PC) with a USB speakerphone or mic array per room.
2. A small client that joins LiveKit as that room's identity (room name = the room) and plays Argo's audio.
3. Wake word handled locally on the Pi so the room is not streaming constantly.
4. A rule for which room Argo answers in when two hear the same phrase (nearest/loudest wins).
5. Per-room context: the board knows which room asked.

## Decisions for Tommy
- Which rooms first, and what hardware he already has.
- Whether satellites may speak job results, or only the room he is in.

Not started until these are answered.
