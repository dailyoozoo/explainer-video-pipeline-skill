"""Read-only media checks and review frames; never certifies perceptual quality."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from media_common import load_timeline


def positive_float(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('Expected a finite positive number.')
    return result


def positive_int(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError('Expected a positive integer.')
    return result


def run(command):
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode != 0:
        raise RuntimeError(f'{command[0]} exited {result.returncode}: {result.stderr[-3000:]}')
    return result


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def inspect(args):
    source = args.video.resolve()
    output = args.out.resolve()
    if not source.is_file():
        raise ValueError(f'Missing video: {source}')
    timeline = load_timeline(args.timeline) if args.timeline else None
    if timeline:
        for name in ('width', 'height', 'fps', 'duration'):
            expected = getattr(args, name)
            if expected is not None and abs(expected - timeline[name]) > 0.00001:
                raise ValueError(f'--{name} disagrees with timeline.')
            setattr(args, name, timeline[name])
    for executable in ('ffprobe', 'ffmpeg'):
        if not shutil.which(executable):
            raise ValueError(f'{executable} is missing from PATH.')
    # A fresh directory prevents accidental replacement of an earlier review.
    if output.exists():
        raise ValueError(f'Review directory already exists; choose a new --out: {output}')
    output.mkdir(parents=True)
    report = {
        'input': str(source),
        'technical_checks': 'FAIL',
        'visual_review': 'PENDING: inspect the frames and play the video.',
        'listening_and_sync_review': 'PENDING: listen to and watch the entire video.',
        'checks': [], 'review_frames': [],
    }

    def check(name, passed, detail):
        report['checks'].append({'name': name, 'pass': bool(passed), 'detail': detail})

    try:
        with source.open('rb') as stream:
            report['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        probe = json.loads(run(['ffprobe', '-v', 'error', '-show_streams',
                                '-show_format', '-of', 'json', str(source)]).stdout)
        videos = [s for s in probe.get('streams', []) if s.get('codec_type') == 'video'
                  and not s.get('disposition', {}).get('attached_pic')]
        audios = [s for s in probe.get('streams', []) if s.get('codec_type') == 'audio']
        check('video_stream', bool(videos), f'{len(videos)} video stream(s)')
        check('audio_stream', bool(audios), f'{len(audios)} audio stream(s)')
        if not videos:
            raise ValueError('No playable video stream.')
        video = videos[0]
        audio = audios[0] if audios else None
        fps = float(Fraction(video.get('avg_frame_rate', '0/1')))
        duration = number(video.get('duration'))
        if duration is None:
            duration = number(probe.get('format', {}).get('duration'))
        check('duration_available', duration is not None and duration > 0, duration)
        check('frame_rate_available', fps > 0, fps)
        report['observed'] = {
            'width': video.get('width'), 'height': video.get('height'),
            'fps': fps, 'duration': duration, 'frames': video.get('nb_frames'),
            'video_codec': video.get('codec_name'),
            'audio_codec': audio.get('codec_name') if audio else None,
            'audio_duration': number(audio.get('duration')) if audio else None,
            'sample_rate': audio.get('sample_rate') if audio else None,
        }
        check('h264_video', video.get('codec_name') == 'h264', video.get('codec_name'))
        check('aac_audio', bool(audio) and audio.get('codec_name') == 'aac',
              audio.get('codec_name') if audio else None)
        check('audio_48khz', bool(audio) and audio.get('sample_rate') == '48000',
              report['observed']['sample_rate'])
        if timeline and video.get('nb_frames') is not None:
            expected_frames = sum(shot['frames'] for shot in timeline['shots'])
            check('timeline_frame_count', int(video['nb_frames']) == expected_frames,
                  {'expected': expected_frames, 'actual': video['nb_frames']})
        if timeline:
            with args.timeline.open('rb') as stream:
                report['timeline_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        for name in ('width', 'height'):
            expected = getattr(args, name)
            if expected is not None:
                check(name, video.get(name) == expected,
                      {'expected': expected, 'actual': video.get(name)})
        if args.fps is not None:
            check('target_fps', abs(fps - args.fps) < 0.01,
                  {'expected': args.fps, 'actual': fps})
        tolerance = max(0.1, 2 / fps) if fps > 0 else 0.1
        if args.duration is not None:
            check('target_duration', duration is not None
                  and abs(duration - args.duration) <= tolerance,
                  {'expected': args.duration, 'actual': duration, 'tolerance': tolerance})
        audio_duration = report['observed']['audio_duration']
        if audio_duration is not None and duration is not None:
            check('audio_video_duration', abs(audio_duration - duration) <= tolerance,
                  {'video': duration, 'audio': audio_duration, 'tolerance': tolerance})
        print('Decoding the full video and audio...', flush=True)
        decode = run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(source),
                      '-map', f'0:{video["index"]}', '-map', '0:a:0?', '-f', 'null', '-'])
        check('full_decode', not decode.stderr.strip(), decode.stderr[-3000:])
        if audio:
            measurement = run(['ffmpeg', '-hide_banner', '-i', str(source), '-map', '0:a:0',
                               '-af', 'loudnorm=I=-14.5:TP=-1.5:LRA=8:print_format=json',
                               '-f', 'null', '-'])
            objects = re.findall(r'\{[^{}]+\}', measurement.stderr, re.S)
            if not objects:
                raise ValueError('Could not measure encoded loudness.')
            measured = json.loads(objects[-1])
            integrated, true_peak = number(measured.get('input_i')), number(measured.get('input_tp'))
            report['encoded_loudness'] = {'integrated_lufs': integrated, 'true_peak_dbtp': true_peak}
            check('integrated_loudness', integrated is not None and args.min_lufs <= integrated <= args.max_lufs,
                  {'actual': integrated, 'range': [args.min_lufs, args.max_lufs]})
            check('true_peak', true_peak is not None and true_peak <= args.max_true_peak,
                  {'actual': true_peak, 'maximum': args.max_true_peak})
        if duration is not None and duration > 0:
            if timeline:
                samples = [(f'{shot["id"]}_mid', (shot['start'] + shot['end']) / 2)
                           for shot in timeline['shots']]
                for shot in timeline['shots'][1:]:
                    samples.extend([(f'{shot["id"]}_before', max(0, shot['start'] - 1 / fps)),
                                    (f'{shot["id"]}_after', shot['start'])])
                samples.extend([('first', 0), ('last', max(0, duration - 1 / fps))])
            else:
                samples = [(f'frame_{index + 1:02d}', duration * (0.05 + 0.9 * index / 7))
                           for index in range(8)]
            for label, timestamp in samples:
                frame = output / f'{label}.jpg'
                run(['ffmpeg', '-v', 'error', '-n', '-ss', f'{timestamp:.6f}',
                     '-i', str(source), '-map', f'0:{video["index"]}',
                     '-frames:v', '1', '-vf', 'scale=540:-2', '-q:v', '2', str(frame)])
                if not frame.is_file() or frame.stat().st_size == 0:
                    raise RuntimeError(f'Missing review frame at {timestamp:.3f}s')
                report['review_frames'].append({'time': timestamp, 'file': frame.name})
            check('review_frames_extracted', True, f'{len(samples)} frames; not a visual assessment')
        if all(item['pass'] for item in report['checks']):
            report['technical_checks'] = 'PASS'
    except (RuntimeError, ValueError, KeyError, OSError, ZeroDivisionError) as error:
        check('inspection_completed', False, str(error))
    report_path = output / 'report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{report["technical_checks"]}: {report_path}', flush=True)
    print('Visual, listening and sync reviews remain PENDING.', flush=True)
    return 0 if report['technical_checks'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--out', required=True, type=Path, help='New review directory.')
    parser.add_argument('--width', type=positive_int)
    parser.add_argument('--height', type=positive_int)
    parser.add_argument('--fps', type=positive_float)
    parser.add_argument('--duration', type=positive_float)
    parser.add_argument('--timeline', type=Path, help='Validated timeline: all shot midpoints, cuts, first and last frame.')
    parser.add_argument('--min-lufs', type=float, default=-16)
    parser.add_argument('--max-lufs', type=float, default=-13)
    parser.add_argument('--max-true-peak', type=float, default=-0.9)
    args = parser.parse_args()
    if not all(math.isfinite(value) for value in (args.min_lufs, args.max_lufs, args.max_true_peak)) or args.min_lufs > args.max_lufs:
        parser.error('Loudness targets must be finite and min-lufs <= max-lufs.')
    try:
        return inspect(args)
    except (ValueError, OSError) as error:
        print(f'STOP: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
