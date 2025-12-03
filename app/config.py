"""
Конфигурация API endpoints
"""

# Базовый URL ngrok endpoint
NGROK_BASE_URL = "https://louvred-madie-gigglier.ngrok-free.dev"


def get_marker_base_url() -> str:
    """
    Получить URL для разметки PDF через Marker
    
    Returns:
        URL endpoint для сегментации PDF
    """
    return f"{NGROK_BASE_URL}/api/v1/segment"


def get_lm_base_url() -> str:
    """
    Получить URL для LLM запросов (LM Studio proxy)
    
    Returns:
        URL endpoint для chat completions
    """
    return f"{NGROK_BASE_URL}/api/v1/lm/chat"

