from core.response_generator import LLMResponseGenerator
from core.intent_parser import RuleBasedIntentParser

generator = LLMResponseGenerator()
parser = RuleBasedIntentParser()

# Test questions
questions = [
    "What is an eggshell?",
    "Is it hot outside?",
    "Tell me about AI",
]

print("\n" + "="*70)
print("TESTING CURRENT ARGO PERSONALITY & RESPONSE QUALITY")
print("="*70 + "\n")

for question in questions:
    intent = parser.parse(question)
    response = generator.generate(intent, None)
    
    print(f"Q: {question}")
    print(f"   Intent: {intent.intent_type.value}")
    print(f"   Response: {response}")
    print()
