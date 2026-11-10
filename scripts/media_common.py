"""Shared portable timeline contract; no network calls or media mutation."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(command, cwd=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{Path(command[0]).name} failed: {result.stderr[-3000:]}')
    return result


def executable(name):
    result = shutil.which(name)
    if not result:
        raise ValueError(f'{name} is missing from PATH.')
    return result


def relative_file(job, name):
    value = Path(name)
    if value.is_absolute():
        raise ValueError(f'Expected a job-relative asset path: {name}')
    result = (job / value).resolve()
    if not result.is_relative_to(job.resolve()) or not result.is_file():
        raise ValueError(f'Missing asset or asset outside job: {name}')
    return result


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number.')
    return value


def load_timeline(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    for key in ('width', 'height', 'fps'):
        value = finite(data.get(key), key)
        if int(value) != value or value <= 0:
            raise ValueError(f'{key} must be a positive integer.')
        data[key] = int(value)
    if data['width'] % 2 or data['height'] % 2:
        raise ValueError('Width and height must be even for yuv420p.')
    duration = finite(data.get('duration'), 'duration')
    if duration <= 0:
        raise ValueError('duration must be positive.')
    fps = data['fps']

    def frame(value, name):
        value = finite(value, name)
        result = round(value * fps)
        if value < 0 or abs(result / fps - value) > 0.00001:
            raise ValueError(f'{name} must be nonnegative and aligned to {fps}fps.')
        return result

    total = frame(duration, 'duration')
    if not data.get('shots'):
        raise ValueError('At least one shot is required.')
    previous = 0
    identifiers = set()
    for shot in data['shots']:
        name = shot.get('id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or name in identifiers:
            raise ValueError('Shot IDs must be unique letters/digits/underscores/hyphens.')
        identifiers.add(name)
        start, end = frame(shot.get('start'), name + '.start'), frame(shot.get('end'), name + '.end')
        if start != previous or end <= start or end > total:
            raise ValueError(f'{name}: shots must cover the timeline continuously, with no gap/overlap.')
        if 'frames' in shot and shot['frames'] != end - start:
            raise ValueError(f'{name}: frame count disagrees with start/end.')
        shot['frames'] = end - start
        previous = end
        if shot.get('kind') not in ('image', 'video') or not shot.get('plate'):
            raise ValueError(f'{name}: kind=image/video and plate are required.')
        if shot['kind'] == 'video':
            if not shot.get('source') or finite(shot.get('offset', 0), name + '.offset') < 0:
                raise ValueError(f'{name}: video requires source and nonnegative offset.')
            box = shot.get('box', [])
            if len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in box):
                raise ValueError(f'{name}: box must be integer [x,y,width,height].')
            x, y, width, height = box
            if min(x, y) < 0 or min(width, height) <= 0 or x + width > data['width'] or y + height > data['height']:
                raise ValueError(f'{name}: video box is outside the canvas.')
    if previous != total:
        raise ValueError('Final shot must end at duration, including the outro.')
    previous = 0.0
    for sub in data.get('subtitles', []):
        start, end = finite(sub.get('start'), 'subtitle.start'), finite(sub.get('end'), 'subtitle.end')
        if start < previous - 0.000001 or start < 0 or end <= start or end > duration:
            raise ValueError('Subtitles must be ordered, nonoverlapping and within duration.')
        text = sub.get('text')
        if not isinstance(text, str) or not text.strip() or any(c in text for c in '\r\n{}\\'):
            raise ValueError('Subtitle text must be one nonempty plain line without ASS control characters.')
        previous = end
    return data


def probe(path):
    return json.loads(run([executable('ffprobe'), '-v', 'error', '-show_streams',
                           '-show_format', '-of', 'json', str(path)]).stdout)
