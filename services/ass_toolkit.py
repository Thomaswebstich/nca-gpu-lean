# Copyright (c) 2025 Stephen G. Pope
# Lean Version: Transcription Support Removed
import os
import ffmpeg
import logging
import subprocess
from datetime import timedelta
import srt
import re
from services.file_management import download_file
from services.cloud_storage import upload_file
import requests
from urllib.parse import urlparse
from config import LOCAL_STORAGE_PATH

# Initialize logger
logger = logging.getLogger(__name__)

# Mock transcription function for Lean version
def generate_transcription(video_path, language='auto'):
    logger.error("Transcription requested in Lean Engine. This feature is disabled.")
    raise NotImplementedError("Auto-transcription is not available in the Lean Engine. Please provide your own captions or use the Full Engine.")

def get_video_resolution(video_path):
    try:
        probe = ffmpeg.probe(video_path)
        video_streams = [s for s in probe['streams'] if s['codec_type'] == 'video']
        if video_streams:
            width = int(video_streams[0]['width'])
            height = int(video_streams[0]['height'])
            return width, height
        return 384, 288
    except Exception:
        return 384, 288

def get_available_fonts():
    try:
        import matplotlib.font_manager as fm
        font_list = fm.findSystemFonts(fontpaths=None, fontext='ttf')
        font_names = set()
        for font in font_list:
            try:
                font_prop = fm.FontProperties(fname=font)
                font_names.add(font_prop.get_name())
            except: continue
        return list(font_names)
    except ImportError:
        return []

def rgb_to_ass_color(rgb_color):
    if isinstance(rgb_color, str):
        rgb_color = rgb_color.lstrip('#')
        if len(rgb_color) == 6:
            r = int(rgb_color[0:2], 16)
            g = int(rgb_color[2:4], 16)
            b = int(rgb_color[4:6], 16)
            return f"&H00{b:02X}{g:02X}{r:02X}"
    return "&H00FFFFFF"

def format_ass_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    return f"{hours}:{minutes:02}:{secs:02}.{centiseconds:02}"

def process_subtitle_text(text, replace_dict, all_caps, max_words_per_line):
    for old_word, new_word in replace_dict.items():
        text = re.sub(re.escape(old_word), new_word, text, flags=re.IGNORECASE)
    if all_caps:
        text = text.upper()
    if max_words_per_line > 0:
        words = text.split()
        lines = [' '.join(words[i:i+max_words_per_line]) for i in range(0, len(words), max_words_per_line)]
        text = '\\N'.join(lines)
    return text

def srt_to_transcription_result(srt_content):
    subtitles = list(srt.parse(srt_content))
    segments = []
    for sub in subtitles:
        segments.append({
            'start': sub.start.total_seconds(),
            'end': sub.end.total_seconds(),
            'text': sub.content.strip(),
            'words': []
        })
    return {'segments': segments}

def split_lines(text, max_words_per_line):
    if max_words_per_line <= 0: return [text]
    words = text.split()
    return [' '.join(words[i:i+max_words_per_line]) for i in range(0, len(words), max_words_per_line)]

def is_url(string):
    try:
        result = urlparse(string)
        return result.scheme in ('http', 'https')
    except: return False

def download_captions(captions_url):
    response = requests.get(captions_url)
    response.raise_for_status()
    return response.text

def determine_alignment_code(position_str, alignment_str, x, y, video_width, video_height):
    horizontal_map = {'left': 1, 'center': 2, 'right': 3}
    if x is not None and y is not None:
        return 5, True, x, y
    pos_lower = position_str.lower()
    if 'top' in pos_lower:
        v_base, v_center = 7, video_height / 6
    elif 'middle' in pos_lower:
        v_base, v_center = 4, video_height / 2
    else:
        v_base, v_center = 1, (5 * video_height) / 6
    
    if 'left' in pos_lower:
        l_bound, r_bound, c_line = 0, video_width / 3, video_width / 6
    elif 'right' in pos_lower:
        l_bound, r_bound, c_line = (2 * video_width) / 3, video_width, (5 * video_width) / 6
    else:
        l_bound, r_bound, c_line = video_width / 3, (2 * video_width) / 3, video_width / 2

    if alignment_str == 'left': f_x, h_code = l_bound, 1
    elif alignment_str == 'right': f_x, h_code = r_bound, 3
    else: f_x, h_code = c_line, 2
    
    return v_base + (h_code - 1), True, int(f_x), int(v_center)

def generate_ass_header(style_options, video_resolution):
    res_x, res_y = video_resolution
    header = f"[Script Info]\nScriptType: v4.00+\nPlayResX: {res_x}\nPlayResY: {res_y}\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    
    font = style_options.get('font_family', 'Arial')
    size = style_options.get('font_size', int(res_y * 0.05))
    c1 = rgb_to_ass_color(style_options.get('line_color', '#FFFFFF'))
    c3 = rgb_to_ass_color(style_options.get('outline_color', '#000000'))
    c4 = rgb_to_ass_color(style_options.get('box_color', '#000000'))
    b = '1' if style_options.get('bold') else '0'
    i = '1' if style_options.get('italic') else '0'
    
    header += f"Style: Default,{font},{size},{c1},{c1},{c3},{c4},{b},{i},0,0,100,100,0,0,1,2,0,5,20,20,20,0\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    return header

def handle_classic(transcription_result, style_options, replace_dict, video_resolution):
    max_w = int(style_options.get('max_words_per_line', 0))
    all_caps = style_options.get('all_caps', False)
    an, _, fx, fy = determine_alignment_code(style_options.get('position', 'middle_center'), style_options.get('alignment', 'center'), style_options.get('x'), style_options.get('y'), video_resolution[0], video_resolution[1])
    events = []
    for seg in transcription_result['segments']:
        text = seg['text'].strip().replace('\n', ' ')
        lines = split_lines(text, max_w)
        proc = '\\N'.join(process_subtitle_text(l, replace_dict, all_caps, 0) for l in lines)
        events.append(f"Dialogue: 0,{format_ass_time(seg['start'])},{format_ass_time(seg['end'])},Default,,0,0,0,,{{\\an{an}\\pos({fx},{fy})}}{proc}")
    return "\n".join(events)

def generate_ass_captions_v1(video_url, captions, settings, replace, exclude_time_ranges, job_id, language='auto', PlayResX=None, PlayResY=None):
    if not captions:
        return {"error": "Captions are required in the Lean Engine. Transcription is disabled."}
    
    resolution = (PlayResX or 1920, PlayResY or 1080)
    captions_content = download_captions(captions) if is_url(captions) else captions
    trans_res = srt_to_transcription_result(captions_content)
    
    style_options = {k.replace('-', '_'): v for k, v in settings.items()}
    replace_dict = {item['find']: item['replace'] for item in replace if 'find' in item and 'replace' in item}
    
    header = generate_ass_header(style_options, resolution)
    body = handle_classic(trans_res, style_options, replace_dict, resolution)
    
    ass_path = os.path.join(LOCAL_STORAGE_PATH, f"{job_id}.ass")
    with open(ass_path, 'w') as f:
        f.write(header + body)
    
    return ass_path
