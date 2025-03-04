import json
from backend.parse_user_input_with_llm import parse_user_input_with_llm

def main():
    sample_input = (
        "I want to go to Paris with 2 travelers from 2025-03-21 to 2025-03-23. "
        "Our budget is 1500 and we love museums."
    )
    result = parse_user_input_with_llm(sample_input)
    print("Extracted trip details:")
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()

