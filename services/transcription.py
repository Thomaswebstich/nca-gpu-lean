# Copyright (c) 2025 Stephen G. Pope
# Lean Version: Transcription Support Removed
import logging

logger = logging.getLogger(__name__)

def process_transcription(*args, **kwargs):
    logger.error("Transcription requested in Lean Engine. This feature is disabled.")
    raise NotImplementedError("Auto-transcription is not available in the Lean Engine. Please provide your own captions or use the Full Engine.")

def generate_ass_subtitle(*args, **kwargs):
    return ""