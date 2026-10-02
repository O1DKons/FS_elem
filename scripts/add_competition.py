"""Append supplied competition programs and protocol jump drafts to FS_elem."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/live'
PROTOCOL = ROOT / 'data/competition/competition-2026-09-14-17.json'
FRAMES = ROOT / 'work/competition-frames'


def planned_episodes(program):
    number = program['startNumber']
    result = []
    for element in program['elements']:
        parts = element['jumpComponents']
        for index, raw_component in enumerate(parts, 1):
            component = raw_component.split('+', 1)[0]
            result.append({
                'id': f'competition-{number:02}-{element["sequence"]:02}-{index:02}',
                'videoId': f'comp-{number:02}',
                'start': None,
                'end': None,
                'note': f'Протокол: элемент №{element["sequence"]} — {element["code"]}; прыжок {index}/{len(parts)} — {component}. Границы в видео пока не подтверждены.',
                'attemptGroup': '',
                'protocolElementSequence': element['sequence'],
                'protocolComponentIndex': index,
                'protocolCode': component,
            })
    return result


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    programs = json.loads(PROTOCOL.read_text())['programs']
    if len(programs) != 50 or len({p['startNumber'] for p in programs}) != 50:
        raise ValueError('Expected 50 unique programs')
    db_path = DATA / 'fs-elem.sqlite'
    connection = sqlite3.connect(db_path, timeout=30)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        existing = {row[0] for row in connection.execute('SELECT id FROM videos')}
        proposed = {f'comp-{p["startNumber"]:02}' for p in programs}
        if proposed <= existing:
            print('already_imported')
            return
        if proposed & existing:
            raise ValueError('Partial competition import detected')
        if len(existing) != 73:
            raise ValueError(f'Unexpected existing catalog size: {len(existing)}')

        prepared = []
        for program in programs:
            number = program['startNumber']
            source = Path(program['videoPath'])
            timeline = json.loads((FRAMES / f'{number:02}.json').read_text())
            times = timeline['times']
            if not source.is_file() or not times or any(b <= a for a, b in zip(times, times[1:])):
                raise ValueError(f'Invalid video or timeline: {number}')
            if times[-1] > timeline['duration'] + .01:
                raise ValueError(f'Frame beyond video duration: {number}')
            target = DATA / 'media' / f'comp-{number:02}.mp4'
            if not target.exists():
                completed = target.with_suffix('.mp4.partial')
                if completed.exists():
                    completed.unlink()
                try:
                    subprocess.run(['cp', '-c', str(source), str(completed)], check=True, capture_output=True)
                except subprocess.CalledProcessError:
                    shutil.copy2(source, completed)
                completed.replace(target)
            source_hash = sha256(source)
            if sha256(target) != source_hash:
                raise ValueError(f'Copied video differs from source: {number}')
            video = {
                'id': f'comp-{number:02}',
                'filename': target.name,
                'sourceFilename': source.name,
                'title': f'{program["athlete"]} · произвольная программа',
                'collection': 'competition',
                'labelStatus': 'official_protocol_program_level',
                'protocolStartNumber': number,
                'duration': timeline['duration'],
                'frameCount': len(times),
                'fps': timeline['fps'],
                'width': timeline['width'],
                'height': timeline['height'],
                'sha256': source_hash,
            }
            prepared.append((video, times, planned_episodes(program)))
            print(f'prepared {number}/50', flush=True)

        backup = ROOT / 'data/backups' / f'pre-competition-{datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}.sqlite'
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup) as destination:
            connection.backup(destination)

        connection.execute('BEGIN IMMEDIATE')
        try:
            position = connection.execute('SELECT COALESCE(MAX(position),-1)+1 FROM videos').fetchone()[0]
            attempt_position = connection.execute('SELECT COALESCE(MAX(position),-1)+1 FROM attempts').fetchone()[0]
            current = json.loads(connection.execute("SELECT value FROM metadata WHERE key='document'").fetchone()[0])
            revision = current['revision'] + 1
            episodes = [json.loads(row[0]) for row in connection.execute('SELECT payload FROM attempts ORDER BY position')]
            for video, times, drafts in prepared:
                connection.execute('INSERT INTO videos VALUES (?,?,?,?)', (video['id'], position, f'media/{video["filename"]}', json.dumps(video, ensure_ascii=False)))
                connection.executemany('INSERT INTO frame_times VALUES (?,?,?)', ((video['id'], index, time) for index, time in enumerate(times)))
                position += 1
                for episode in drafts:
                    connection.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?)', (episode['id'], episode['videoId'], attempt_position, None, None, None, None, '', json.dumps(episode, ensure_ascii=False)))
                    attempt_position += 1
                    episodes.append(episode)
            next_document = {**current, 'revision': revision, 'updatedAt': datetime.now(timezone.utc).isoformat()}
            connection.execute("UPDATE metadata SET value=? WHERE key='document'", (json.dumps(next_document, ensure_ascii=False),))
            connection.execute('INSERT INTO revisions VALUES (?,?)', (revision, json.dumps({**next_document, 'episodes': episodes}, ensure_ascii=False)))
            if connection.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Foreign key check failed')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        print(f'imported {len(prepared)} videos, {sum(len(x[2]) for x in prepared)} draft jumps; backup={backup}')
    finally:
        connection.close()


if __name__ == '__main__':
    main()
