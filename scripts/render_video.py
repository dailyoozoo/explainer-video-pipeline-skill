"""Render prepared plates/video and verified captions with a complete audio master."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from PIL import Image

from media_common import executable, load_timeline, probe, relative_file, run, sha256


def render(args):
    job = args.job.resolve()
    timeline_path = args.timeline.resolve()
    timeline = load_timeline(timeline_path)
    width, height, fps, duration = (timeline[key] for key in ('width', 'height', 'fps', 'duration'))
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Output exists. Use a new versioned filename.')
    if output.suffix.lower() != '.mp4' or not output.is_relative_to(job):
        raise ValueError('Output must be an MP4 within the job directory.')
    if not args.subtitles.is_file():
        raise ValueError('Missing ASS subtitles; run build_subtitles.py first.')
    caption_metrics_path = args.subtitles.parent / 'metrics.json'
    if not caption_metrics_path.is_file():
        raise ValueError('Missing subtitle metrics; use build_subtitles.py output.')
    metrics = json.loads(caption_metrics_path.read_text(encoding='utf-8'))
    if metrics.get('timeline_sha256') != sha256(timeline_path):
        raise ValueError('Subtitles were generated from a different timeline.')
    if metrics.get('ass_sha256') != sha256(args.subtitles):
        raise ValueError('ASS changed after width verification. Regenerate or verify captions first.')
    if args.font_dir and not args.font_dir.is_dir():
        raise ValueError('--font-dir must be an existing font directory.')
    if args.font_dir and not any(p.suffix.lower() in ('.ttf', '.otf', '.ttc')
                                 and sha256(p) == metrics.get('font_sha256')
                                 for p in args.font_dir.iterdir() if p.is_file()):
        raise ValueError('--font-dir must contain the exact font used for caption width verification.')
    # Validate all inputs before rendering any clips.
    plates, sources = {}, {}
    for shot in timeline['shots']:
        name = shot['id']
        plate = relative_file(job, shot['plate'])
        with Image.open(plate) as image:
            if image.size != (width, height):
                raise ValueError(f'{name}: plate size must match the canvas.')
            if shot['kind'] == 'video':
                if image.mode != 'RGBA' or image.getchannel('A').getextrema()[0] == 255:
                    raise ValueError(f'{name}: video plate must have an RGBA transparent window.')
        plates[name] = plate
        if shot['kind'] == 'video':
            source = relative_file(job, shot['source'])
            info = probe(source)
            streams = [s for s in info['streams'] if s['codec_type'] == 'video'
                       and not s.get('disposition', {}).get('attached_pic')]
            if not streams:
                raise ValueError(f'{name}: source has no playable video.')
            source_duration = float(streams[0].get('duration') or info['format']['duration'])
            if shot.get('offset', 0) + shot['frames'] / fps > source_duration + 1 / fps:
                raise ValueError(f'{name}: source is too short; no implicit looping is performed.')
            sources[name] = source
    audio_path = (args.master or args.audio_video).resolve()
    audio_probe = probe(audio_path)
    audio_streams = [s for s in audio_probe['streams'] if s['codec_type'] == 'audio']
    if not audio_streams:
        raise ValueError('Missing audio stream.')
    audio_stream = audio_streams[0]
    audio_duration = float(audio_stream.get('duration') or audio_probe['format']['duration'])
    if audio_duration < duration - max(0.05, 1 / fps):
        raise ValueError('Audio must cover the complete timeline, including the outro. Pad/mix it first.')
    if int(audio_stream['sample_rate']) != 48000:
        raise ValueError('Audio input must be a verified 48kHz master.')
    if args.audio_video and audio_stream['codec_name'] != 'aac':
        raise ValueError('--audio-video requires AAC to preserve the encoded audio stream.')
    ffmpeg = executable('ffmpeg')
    build = job / 'build' / output.stem
    build.mkdir(parents=True, exist_ok=True)
    renderer = {'script': sha256(Path(__file__)), 'common': sha256(Path(__file__).with_name('media_common.py')),
                'ffmpeg': run([ffmpeg, '-version']).stdout.splitlines()[0]}
    clips = []
    for shot in timeline['shots']:
        name = shot['id']
        clip = build / f'{name}.mp4'
        audit = clip.with_suffix('.json')
        inputs = {'shot': shot, 'plate': sha256(plates[name]), 'width': width,
                  'height': height, 'fps': fps, 'renderer': renderer}
        if name in sources:
            inputs['source'] = sha256(sources[name])
        fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        cached = False
        if clip.is_file() and audit.is_file():
            record = json.loads(audit.read_text(encoding='utf-8'))
            cached = record.get('fingerprint') == fingerprint and record.get('sha256') == sha256(clip)
        if cached:
            print(f'{name}: cached', flush=True)
        else:
            plate = str(plates[name])
            if shot['kind'] == 'image':
                inputs_args = ['-loop', '1', '-framerate', str(fps), '-i', plate]
                filters = ['-vf', 'format=yuv420p']
            else:
                x, y, box_width, box_height = shot['box']
                inputs_args = ['-ss', str(shot.get('offset', 0)), '-i', str(sources[name]),
                               '-loop', '1', '-framerate', str(fps), '-i', plate]
                graph = (f'[0:v]fps={fps},scale={box_width}:{box_height}:force_original_aspect_ratio=decrease,'
                         f'pad={box_width}:{box_height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,'
                         f'setpts=PTS-STARTPTS,pad={width}:{height}:{x}:{y}:color=black[base];'
                         '[1:v]format=rgba[plate];[base][plate]overlay=0:0:format=auto,format=yuv420p[v]')
                filters = ['-filter_complex_threads', '1', '-filter_complex', graph, '-map', '[v]']
            run([ffmpeg, '-y', '-v', 'error', *inputs_args, *filters,
                 '-frames:v', str(shot['frames']), '-an', '-c:v', 'libx264', '-threads', '2',
                 '-preset', 'fast', '-crf', '19', '-r', str(fps), '-pix_fmt', 'yuv420p',
                 '-video_track_timescale', '90000', str(clip)])
            encoded = next(s for s in probe(clip)['streams'] if s['codec_type'] == 'video')
            if int(encoded.get('nb_frames', 0)) != shot['frames']:
                raise ValueError(f'{name}: encoded clip has fewer frames than required.')
            audit.write_text(json.dumps({'fingerprint': fingerprint, 'sha256': sha256(clip),
                                         'frames': shot['frames']}, indent=2), encoding='utf-8')
            print(f'{name}: rendered', flush=True)
        clips.append(clip)
    # Safe local filenames keep libass and concat parsing independent of Windows drive letters.
    (build / 'concat.txt').write_text(''.join(f"file '{clip.name}'\n" for clip in clips), encoding='utf-8')
    silent = build / 'silent.mp4'
    run([ffmpeg, '-y', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', 'concat.txt',
         '-an', '-c:v', 'copy', str(silent)], cwd=build)
    shutil.copyfile(args.subtitles, build / 'captions.ass')
    output.parent.mkdir(parents=True, exist_ok=True)
    font_args = []
    if args.font_dir:
        if not args.font_dir.is_dir():
            raise ValueError('--font-dir must be an existing font directory.')
        staged_fonts = build / 'fonts'
        staged_fonts.mkdir(exist_ok=True)
        for font in args.font_dir.iterdir():
            if font.suffix.lower() in ('.ttf', '.otf', '.ttc'):
                shutil.copyfile(font, staged_fonts / font.name)
        font_args = [':fontsdir=fonts']
    audio_args = ['-c:a', 'copy'] if args.audio_video else ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000']
    run([ffmpeg, '-n', '-v', 'error', '-i', str(silent), '-i', str(audio_path),
         '-vf', 'subtitles=captions.ass' + ''.join(font_args), '-map', '0:v:0', '-map', '1:a:0',
         '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-crf', '19',
         '-pix_fmt', 'yuv420p', '-r', str(fps), *audio_args, '-t', str(duration),
         '-movflags', '+faststart', str(output)], cwd=build)
    manifest = {'file': output.relative_to(job).as_posix(), 'sha256': sha256(output),
                'bytes': output.stat().st_size, 'duration': duration,
                'frames': sum(s['frames'] for s in timeline['shots']),
                'timeline_sha256': sha256(timeline_path), 'subtitles_sha256': sha256(args.subtitles),
                'audio_input_sha256': sha256(audio_path), 'renderer': renderer,
                'audio_mode': 'copy_aac' if args.audio_video else 'encode_master',
                'technical_review': 'pending', 'visual_review': 'pending', 'human_listening': 'pending'}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Rendered {output}; run inspection and review before marking it accepted.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, type=Path)
    parser.add_argument('--timeline', required=True, type=Path)
    parser.add_argument('--subtitles', required=True, type=Path, help='ASS generated by build_subtitles.py.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--master', type=Path, help='Already mixed, normalized, padded 48kHz audio master.')
    group.add_argument('--audio-video', type=Path, help='Prior full MP4 whose AAC is copied for a visual revision.')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--font-dir', type=Path, help='Optional directory of licensed fonts matching subtitle metrics.')
    try:
        render(parser.parse_args())
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        print(f'STOP: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
