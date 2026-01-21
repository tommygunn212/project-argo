#!/usr/bin/env python3
"""
ARGO Interactive Code School
A simple terminal app to explain how the code works using analogies.
"""

import time
import sys
import os

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_slow(text, speed=0.03):
    """Print text like a typewriter."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(speed)
    print()

def pause():
    """Wait for user input to continue."""
    print("\n[Press Enter to continue...]")
    input()
    clear_screen()

def lesson_1_objects():
    print_slow("LESSON 1: THE BLUEPRINT (Classes & Objects)")
    print("-" * 50)
    print("Imagine you are an architect.")
    print("You draw a blueprint for a 'Status Light'.")
    print("The blueprint says: 'It should be round, and it can be red or green.'")
    print("\nIn code, this blueprint is called a CLASS.")
    print("\nCode Example:")
    print("class StatusLight:")
    print("    shape = 'round'")
    print("    color = 'red'")
    
    print("\nNow, you can't actually turn on a blueprint.")
    print("You have to build a real lightbulb based on that blueprint.")
    print("This real lightbulb is called an OBJECT (or INSTANCE).")
    
    print("\nCode Example:")
    print("my_light = StatusLight()  # Build the light")
    print("my_light.color = 'green'  # Turn it green")
    
    print("\nKEY TAKEAWAY: The Class is the plan. The Object is the real thing.")
    pause()

def lesson_2_coordinator():
    print_slow("LESSON 2: THE COORDINATOR (The Main Loop)")
    print("-" * 50)
    print("The 'Coordinator' is the boss of ARGO.")
    print("Its job is to repeat the same 4 steps forever.")
    print("In code, 'doing things forever' is a LOOP.")
    
    print("\nHere is exactly what the Coordinator does:")
    
    steps = [
        "1. LISTEN: Wait for 'Hey Argo' (Wake Word)",
        "2. HEAR: Record what you say (Microphone)",
        "3. THINK: Ask the AI what to do (LLM)",
        "4. SPEAK: Say the answer (TTS)"
    ]
    
    for step in steps:
        time.sleep(0.5)
        print(step)
    
    print("\nAnd then... it goes back to Step 1.")
    print("It uses a 'while True:' loop, which translates to:")
    print("'While the universe exists (True), keep doing this.'")
    pause()

def lesson_3_the_queue():
    print_slow("LESSON 3: THE QUEUE (The Fix We Just Made)")
    print("-" * 50)
    print("Remember the 'RuntimeError' we fixed? Here is the analogy.")
    
    print("\nImagine a Restaurant Kitchen.")
    print("The CHEF is the AI (LLM).")
    print("The WAITER is the Speaker (TTS).")
    
    print("\nTHE OLD WAY (The Broken Way):")
    print("The Chef would cook a burger, run out to the table, and feed the customer himself.")
    print("Result: The Chef stops cooking while he is feeding the customer.")
    print("The kitchen stops working. This crashed the system.")
    
    print("\nTHE NEW WAY (With a Queue):")
    print("We installed a Service Window (The QUEUE).")
    print("1. The Chef (AI) cooks a burger (Sentence).")
    print("2. Puts it in the Window (Queue).")
    print("3. Immediately goes back to cooking the fries.")
    print("\nMeanwhile...")
    print("The Waiter (Worker Thread) sees the burger in the window.")
    print("He takes it and serves it.")
    
    print("\nThis happens at the same time (Asynchronously).")
    print("The Chef doesn't wait. The Waiter doesn't stop the Chef.")
    
    print("\nCode Translation:")
    print("sink.send() -> Put burger in window.")
    print("_worker()   -> Waiter taking burgers from window.")
    pause()

def main():
    clear_screen()
    print_slow("Welcome to the ARGO Code School! 🎓")
    print("You said you're not a coder, so let's explain how this machine works.")
    print("We will cover:")
    print("1. What are these 'files' and 'classes'?")
    print("2. How does the robot actually think?")
    print("3. What was that complex fix we just did?")
    pause()
    
    lesson_1_objects()
    lesson_2_coordinator()
    lesson_3_the_queue()
    
    print_slow("CONGRATULATIONS!")
    print("You now understand the core concepts of the ARGO architecture.")
    print("\nFiles created for you:")
    print("1. i:\\argo\\docs\\guides\\CODE_DICTIONARY.md (Glossary)")
    print("2. This script (teach_me_argo.py) which you can run anytime.")
    print("\nClass dismissed! 🔔")

if __name__ == "__main__":
    main()
