# ARGO Terms & Concepts for Non-Coders

## 🏗️ The Building Blocks (Coding Terms)

### 1. Class vs. Object
Think of a **Class** as a **Blueprint** or a **Recipe**. It describes what something *should* be.
Think of an **Object** as the **House** built from that blueprint, or the **Cake** baked from that recipe.

*   **In ARGO:** `PiperOutputSink` is the class (the recipe for how to speak). When we write `sink = PiperOutputSink()`, we create an object (a specific mouth ready to speak).

### 2. Variable
A **Variable** is a **Labelled Box**. You can put data inside it to save for later.
*   **In ARGO:** `text = "Hello"` creates a box labelled `text` and puts the word "Hello" inside.

### 3. Function / Method
A **Function** is an **Action**. It's a set of instructions to do a specific task. When it's inside a Class, we call it a **Method**.
*   **In ARGO:** `speak("Hello")` is a method. It tells the system to perform the action of speaking.

### 4. Loop
A **Loop** is doing the same thing over and over again.
*   **In ARGO:** The `while True:` loop in the Coordinator means "Keep listening forever until someone tells you to stop."

### 5. Thread
A **Thread** is a **Worker**.
*   **Single Thread:** One person doing one thing at a time. (Cooking, then cleaning, then eating).
*   **Multi-Thread:** A team. One person cooks (Main Thread), another person cleans (Worker Thread) at the same time.
*   **In ARGO:** The **Main Thread** runs the GUI (lights and buttons). The **Worker Thread** plays the audio. If we did everything in one thread, the GUI would freeze while audio played!

### 6. Queue
A **Queue** is a **Conveyor Belt** or a **Line at the Bank**.
*   **In ARGO:** The LLM (Brain) puts sentences on the conveyer belt. The Audio Player (Mouth) takes them off one by one. This lets the Brain keep thinking without waiting for the Mouth to finish.

---

## 🤖 The ARGO Parts (Project Terms)

### 1. Coordinator (The Conductor)
This is the "Boss" script. It tells everyone else what to do. It says "Microphone, record now!", then "Brain, think about this!", then "Speaker, say this!".

### 2. Trigger (The Ear)
This waits for the "Wake Word" (like "Hey Argo"). It ignores everything else until it hears that magic word.

### 3. STT (Speech-to-Text)
The Scribe. It takes sound waves (your voice) and turns them into text words the computer can read.

### 4. LLM (The Brain)
**L**arge **L**anguage **M**odel. This is the smart part (Qwen). It reads the text, understands what you want, and writes a response.

### 5. TTS (Text-to-Speech)
The Mouth. It takes the text response from the Brain and turns it back into sound waves (audio).

### 6. Latency
**Lag**. The time it takes between you stopping talking and the computer starting to answer. We want this to be as small as possible!
