try:
    from .asr_tool import ASRTool
except ImportError:
    ASRTool = None
    import logging
    logging.warning("ASRTool unavailable (whisper not installed). ASR features disabled.")