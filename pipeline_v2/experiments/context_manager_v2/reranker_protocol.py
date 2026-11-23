"""Frozen CM4 Qwen reranker worker and client settings."""

APP_NAME = 'coliee-cm4-qwen3-reranker-l4'
MODEL = 'Qwen/Qwen3-Reranker-0.6B'
REVISION = 'e61197ed45024b0ed8a2d74b80b4d909f1255473'
INSTRUCTION = ('Given a passage from a Canadian court decision, retrieve passages relevant to identifying '
               'the legal proposition and the judicial authority being discussed.')
MAX_TOKENS = 8192
BATCH_SIZE = 8
