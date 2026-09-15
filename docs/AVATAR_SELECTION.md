# Avatar Selection

The default **Auto** setting follows the selected voice: male presets select
Cyber Male and female presets select Cortana. Neutral or unspecified voices
keep the current face. Smooth Voice follows its active realtime voice.
Choose **Cortana** or **Cyber Male** manually to override automatic matching.
The Avatar selector is on the dashboard and Voice page; both panels change
together. The choice is saved in this
browser's local storage (`argo_avatar`) and synchronized with other ARGO tabs
on the same origin. Other browsers/devices retain their own choice.

Avatar selection does not change the TTS voice or restart an audio session.
Select the desired voice in Voice > Text-to-Speech. Both avatars
use local 2D expression deformation and the existing playback audio meters;
they are not photorealistic generated video or phoneme-based lip sync.

Cortana preserves the configured local media. The male source is the bundled
`frontend-v2/assets/argo_cyber_male.png`, with facial landmarks calibrated in
`frontend-v2/assets/cortana-avatar.js`. No text is drawn over either portrait.

## Artwork Provenance

Generated with the built-in image-generation tool. Original generated file was
copied into the project without replacing the existing Cortana artwork.

### Generation Prompt

Use case: stylized-concept. Asset type: square portrait source art for ARGO's animated male AI assistant. Create an original cinematic science-fiction male cybernetic AI avatar, something that could convincingly appear in a high-budget futuristic movie. Head and upper shoulders, precisely front-facing and looking straight at camera, no head tilt. Masculine adult around 35-45, strong natural facial structure, short swept-back dark hair, clean shaven, composed and intelligent expression, human-like face with subtle precision-engineered cybernetic inlays around temples and sides of neck. Realistic skin texture, restrained cyan illuminated circuitry in graphite and brushed titanium collar, a small warm amber electronic detail for contrast. Clear human eyes with subtle cyan irises, unobstructed natural lips very slightly parted with a narrow dark mouth interior. Both eyes and the entire mouth must remain clearly visible with soft even facial lighting, no strong shadow across the face. Cinematic photorealistic VFX, sophisticated and credible rather than cartoonish or toy-like. Almost-black simple background. Center the face symmetrically; include the complete crown with modest space above and upper shoulders at bottom. 1024x1024 square composition. No helmet, no sunglasses, no mask, no beard, no text, no labels, no watermarks, no interface panels. A brand-new original character, not a recognizable actor.

### Android Revision Prompt

Edit the provided ARGO male avatar into a smoother, more robotic cinematic male android. Keep the same square framing, exact frontal head pose, face center, eye positions and mouth position, and dark background so an existing facial animation rig still fits. The current face is too rugged and too human. Replace realistic weathered skin, stubble and visible skin pores with smooth refined pale graphite/satin titanium synthetic face surfaces, elegant subtle segmented seams following the facial anatomy, and clean engineered cheek and jaw contours. Make him unmistakably masculine but youthful and sleek, not muscular or rugged. Replace the bulky natural hair with a sleek close-fitting sculpted synthetic cranial shell, no helmet covering eyes. Keep human-shaped cyan eyes and flexible synthetic lips slightly parted, unobstructed, expressive and easy to animate. Refine the cybernetic collar and subtle cyan circuitry; retain tiny warm amber accents. High-budget sci-fi movie android, elegant and believable. Avoid skulls, exposed teeth, scary Terminator-like features, beard, stubble, grime, aging wrinkles, bulky armor, exaggerated muscles, text, watermarks, panels. Preserve balanced soft frontal illumination; full face clearly readable.
