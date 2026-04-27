import ollama

MODEL_NAME = "phi3:mini"


def ask_llama(system_prompt: str, user_prompt: str) -> str:
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        options={
            "temperature": 0.1,
            "num_predict": 900,
        }
    )
    return response["message"]["content"]