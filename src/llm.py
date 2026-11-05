import os
import requests

BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")
MODEL = os.getenv("LM_STUDIO_MODEL", "qwen/qwen3-4b")
API_KEY = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
TIMEOUT = int(os.getenv("LM_STUDIO_TIMEOUT", "45"))

# Common recommended models for easy selection
POPULAR_MODELS = [
    "qwen/qwen3-4b",
    "qwen/qwen2.5-7b-instruct",
    "qwen/qwen2.5-3b-instruct",
    "meta-llama/llama-3.2-3b-instruct",
    "meta-llama/llama-3.1-8b-instruct",
    "mistralai/mistral-7b-instruct-v0.3",
    "deepseek-ai/deepseek-r1-distill-qwen-7b",
    "microsoft/phi-4",
    "google/gemma-2-2b-it"
]

def get_config():
    return {
        "base_url": BASE_URL,
        "model": MODEL,
        "api_key": API_KEY,
        "timeout": TIMEOUT
    }

def set_config(base_url=None, model=None, api_key=None, timeout=None):
    global BASE_URL, MODEL, API_KEY, TIMEOUT
    if base_url is not None:
        BASE_URL = base_url.strip().rstrip("/")
    if model is not None and model.strip():
        MODEL = model.strip()
    if api_key is not None:
        API_KEY = api_key.strip()
    if timeout is not None:
        try:
            TIMEOUT = int(timeout)
        except (ValueError, TypeError):
            pass

def fetch_available_models(base_url=None, api_key=None):
    """
    Query the /v1/models endpoint to fetch all loaded/available models in LM Studio or Ollama.
    Returns: (success: bool, models: list[str], message: str)
    """
    target_url = (base_url or BASE_URL).strip().rstrip("/")
    target_key = api_key if api_key is not None else API_KEY
    url = f"{target_url}/models"
    try:
        response = requests.get(url, timeout=4, headers={"Authorization": f"Bearer {target_key}"})
        if response.status_code == 200:
            data = response.json()
            models = []
            for item in data.get("data", []):
                m_id = item.get("id")
                if m_id and isinstance(m_id, str):
                    models.append(m_id)
            return True, models, "Connection successful."
        return False, [], f"Server responded with status code {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, [], f"Could not connect to {target_url}. Is LM Studio or Ollama running with local server started?"
    except requests.exceptions.Timeout:
        return False, [], f"Connection to {target_url} timed out after 4 seconds."
    except Exception as exc:
        return False, [], f"Connection error: {exc}"

def test_connection(base_url=None, api_key=None):
    """
    Test connection to the LLM server and return a user-friendly report.
    Returns: (success: bool, models: list[str], message: str)
    """
    target_url = (base_url or BASE_URL).strip().rstrip("/")
    ok, models, detail = fetch_available_models(target_url, api_key)
    if ok:
        if models:
            msg = f"Connected to {target_url}!\nFound {len(models)} model(s): {', '.join(models[:5])}"
            if len(models) > 5:
                msg += f" ... (+{len(models)-5} more)"
        else:
            msg = f"Connected to {target_url}!\nServer is running, but no models are loaded yet. Load a model in LM Studio."
        return True, models, msg
    else:
        msg = f"Failed to connect to {target_url}.\n\nDetails: {detail}\n\nTo connect:\n1. Open LM Studio\n2. Go to the Developer / Local Server tab\n3. Start the server (default port 1234)\n4. Load your model (e.g. qwen/qwen3-4b)"
        return False, [], msg

def chat(prompt, system="You are a practical job-search assistant. Be concise and honest."):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": "/no_think\n" + prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 500,
        "stream": False
    }
    try:
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            json=payload,
            timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {API_KEY}"}
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return "The local model returned no answer. Check the LM Studio model and server."
        content = (choices[0].get("message") or {}).get("content") or ""
        if isinstance(content, list):
            content = " ".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
        return content.strip() or "The model returned an empty answer. Try again or adjust settings."
    except requests.exceptions.RequestException as exc:
        return (
            f"Could not connect to LM Studio at {BASE_URL} (Model: {MODEL}).\n\n"
            f"Please verify:\n"
            f"1. LM Studio is running and the Local Server is started (port 1234).\n"
            f"2. Model '{MODEL}' is loaded.\n\n"
            f"Error details: {exc}"
        )
