# Original Hedra Cortana: Motion Analysis

## Correct Source

Checked on 2026-09-13. The user's reference is the Hedra avatar in
[Build a Cortana AI Companion](https://www.youtube.com/watch?v=tqB-jGGQpgA),
whose description links to
[ruxakK/cortana_companion](https://github.com/ruxakK/cortana_companion).
The unrelated ManuNeuro GIF player is NOT the original requested here.

## How the Original Works

In the reference repository, `src/agent.py` loads
`src/portrait_images/cortana_portrait_smirky.png`, constructs
`hedra.AvatarSession(avatar_image=avatar_image)`, then starts that session in
the LiveKit room. It does not contain the facial animation model or a facial rig.

The installed legacy LiveKit Hedra plugin uploads the portrait and routes agent
audio through a data stream to Hedra. Hedra supplies the generated avatar video.
The mouth, eyes and facial motion are therefore produced by a remote service,
not animation embedded in the PNG or implemented in the tutorial's client code.

ARGO's current local WebGL lip deformation and blinks are an approximation.
They are not the original Hedra engine and do not recover its speech-driven
facial performance. Copying the tutorial's connection code cannot recover that
remote model.

## Availability

[LiveKit's official Hedra guide](https://docs.livekit.io/agents/models/avatar/plugins/hedra/)
states that Hedra sunset Realtime Avatar on April 15, 2026 and the plugin no
longer functions. ARGO already guards the retired integration. Installing an
older SDK does not restore the remote endpoint.

Hedra's other video-generation products are distinct from that retired live
service. A replacement needs a working speech-driven renderer and synchronized
audio/video connected to the existing conversation pipeline. No replacement
service was enabled and no paid Hedra generation request was made in this review.
