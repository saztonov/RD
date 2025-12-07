"""
Конфигурация API endpoints
"""

# Базовый URL ngrok endpoint
NGROK_BASE_URL = "https://louvred-madie-gigglier.ngrok-free.dev"


def get_layout_url() -> str:
    """URL для layout (Surya + Paddle)"""
    return f"{NGROK_BASE_URL}/layout"


def get_lm_base_url() -> str:
    """URL для LLM запросов"""
    return f"{NGROK_BASE_URL}/v1/chat/completions"


# Алиас для обратной совместимости
def get_marker_base_url() -> str:
    return get_paddle_url()


