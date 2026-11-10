"""Generate single-line ASS/SRT from a verified timeline, measuring the real font."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from PIL import ImageFont

from media_common import load_timeline, sha256


def timestamp(seconds, ass=False):
    scale = 100 if ass else 1000
    units = round(seconds * scale)
    hours, units = divmod(units, 3600 * scale)
    minutes, units = divmod(units, 60 * scale)
    seconds, fraction = divmod(units, scale)
    if ass:
        return f'{hours}:{minutes:02}:{seconds:02}.{fraction:02}'
    return f'{hours:02}:{minutes:02}:{seconds:02},{fraction:03}'


def build(args):
    timeline = load_timeline(args.timeline)
    if not args.font.is_file():
        raise ValueError('Provide an installed, licensed Chinese font file with --font.')
    if any(char in args.font_name for char in ',\r\n') or not args.font_name.strip():
        raise ValueError('font-name must be a valid single ASS field.')
    if args.margin < 0 or args.bottom < 0 or args.bottom >= timeline['height']:
        raise ValueError('Invalid subtitle margins.')
    available = timeline['width'] - 2 * args.margin
    if available <= 0 or not 0 < args.min_size <= args.size:
        raise ValueError('Invalid font sizes or horizontal margins.')
    output = args.out.resolve()
    if output.exists():
        raise ValueError('Choose a fresh --out directory to preserve earlier subtitles.')
    fonts = {size: ImageFont.truetype(str(args.font), size)
             for size in range(args.min_size, args.size + 1)}
    body, srt, metrics = [], [], []
    for index, sub in enumerate(timeline.get('subtitles', [])):
        text, size = sub['text'], args.size
        while size >= args.min_size and fonts[size].getlength(text) > available:
            size -= 1
        if size < args.min_size:
            raise ValueError(f'Subtitle {index + 1} is too wide: split it at a verified semantic boundary: {text}')
        start, end = timestamp(sub['start'], True), timestamp(sub['end'], True)
        if start == end or timestamp(sub['start']) == timestamp(sub['end']):
            raise ValueError('Subtitle interval collapses at ASS/SRT time precision.')
        body.append(f'Dialogue: 0,{start},{end},Caption,,0,0,0,,{{\\q2\\fs{size}}}{text}')
        srt.append(f'{index + 1}\n{timestamp(sub["start"])} --> {timestamp(sub["end"])}\n{text}')
        metrics.append({'id': sub.get('id', str(index + 1)), 'size': size,
                        'width': fonts[size].getlength(text), 'text': text})
    fields = ('Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
              'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, '
              'Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding')
    values = ['Caption', args.font_name, str(args.size), '&H00EFF6F7', '&H00EFF6F7',
              '&H0017140F', '&H0017140F', '-1', '0', '0', '0', '100', '100', '0', '0',
              '1', '2.5', '0', '2', str(args.margin), str(args.margin), str(args.bottom), '1']
    if len(fields.split(',')) != len(values):
        raise ValueError('ASS style field count mismatch.')
    header = (f'[Script Info]\nScriptType: v4.00+\nPlayResX: {timeline["width"]}\n'
              f'PlayResY: {timeline["height"]}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n'
              f'[V4+ Styles]\nFormat: {fields}\nStyle: {",".join(values)}\n\n'
              '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
    output.mkdir(parents=True)
    (output / 'captions.ass').write_text(header + '\n'.join(body) + '\n', encoding='utf-8-sig')
    (output / 'captions.srt').write_text('\n\n'.join(srt) + '\n', encoding='utf-8')
    (output / 'metrics.json').write_text(json.dumps({
        'timeline_sha256': sha256(args.timeline), 'font_sha256': sha256(args.font),
        'ass_sha256': sha256(output / 'captions.ass'),
        'font_name': args.font_name, 'available_width': available, 'subtitles': metrics,
        'text_and_audio_alignment': 'must_be_verified_before_this_step'
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Generated {len(body)} single-line captions in {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('timeline', type=Path)
    parser.add_argument('--font', required=True, type=Path)
    parser.add_argument('--font-name', required=True, help='Installed family used by libass, matching --font.')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--size', type=int, default=52)
    parser.add_argument('--min-size', type=int, default=38)
    parser.add_argument('--margin', type=int, default=72)
    parser.add_argument('--bottom', type=int, default=245)
    try:
        build(parser.parse_args())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f'STOP: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
