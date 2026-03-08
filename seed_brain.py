"""
Seed ARGO's brain with Tommy's known facts.
Run once: python seed_brain.py
"""
import sys
sys.path.insert(0, ".")

from core.brain import get_brain


def main():
    brain = get_brain()
    
    facts = [
        # Identity
        {"category": "identity", "subject": "Tommy", "relation": "is_the_user", "value": "owner"},
        {"category": "identity", "subject": "Tommy", "relation": "is", "value": "a filmmaker and software builder"},
        {"category": "identity", "subject": "Tommy", "relation": "email", "value": "tommygunnfilms@gmail.com"},
        
        # Relationships
        {"category": "relationship", "subject": "Jesse", "relation": "is_user_son", "value": "son"},
        {"category": "relationship", "subject": "Bandit", "relation": "is_user_dog", "value": "dog"},
        
        # Projects
        {"category": "project", "subject": "Tommy", "relation": "built", "value": "ARGO voice assistant"},
        {"category": "project", "subject": "Tommy", "relation": "built", "value": "ChefsByte"},
        
        # Preferences
        {"category": "preference", "subject": "user", "relation": "likes", "value": "sarcasm and dry humor"},
        {"category": "preference", "subject": "user", "relation": "likes", "value": "blunt direct responses"},
        {"category": "preference", "subject": "user", "relation": "prefers", "value": "no corporate filler or therapy talk"},
    ]
    
    count = brain.seed_facts(facts)
    print(f"Seeded {count} facts into ARGO's brain.")
    
    # Verify
    all_facts = brain.get_all_facts()
    print(f"\nTotal facts in brain: {len(all_facts)}")
    for f in all_facts:
        print(f"  [{f.category}] {f.subject} {f.relation} → {f.value}")
    
    # Test recall
    print("\n--- Testing recall ---")
    print("Query: 'Tell me about the dog'")
    results = brain.retrieve_relevant_facts("Tell me about the dog", limit=3)
    for f in results:
        print(f"  → {f.subject} {f.relation} {f.value}")
    
    print("\nQuery: 'What did Tommy build?'")
    results = brain.retrieve_relevant_facts("What did Tommy build?", limit=3)
    for f in results:
        print(f"  → {f.subject} {f.relation} {f.value}")
    
    print("\nQuery: 'Who is Jesse?'")
    results = brain.retrieve_relevant_facts("Who is Jesse?", limit=3)
    for f in results:
        print(f"  → {f.subject} {f.relation} {f.value}")


if __name__ == "__main__":
    main()
