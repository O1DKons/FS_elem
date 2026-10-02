#!/usr/bin/env python3
"""Match official program protocols to video filenames; never label timed clips."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata

HOMOGLYPHS = str.maketrans('ABCEHKMOPTXY', 'АВСЕНКМОРТХУ')


def canonical(value):
    return ' '.join(unicodedata.normalize('NFKC', value).upper().translate(HOMOGLYPHS).replace('Ё', 'Е').split())


def category_key(value):
    value = canonical(value)
    level = re.search(r'\b(КМС|МС|[123])\b', value)
    gender = 'F' if re.search(r'ДЕВУШ|ДЕВОЧ|ЖЕНЩ', value) else 'M' if re.search(r'ЮНОШ|МАЛЬЧ|МУЖ', value) else None
    if not level or not gender:
        raise ValueError(f'Unrecognized category: {value}')
    return f'{level[1]}-{gender}'


def name_key(name):
    tokens = canonical(name).split()
    if len(tokens) < 2:
        raise ValueError(f'Incomplete name: {name}')
    return tokens[0], tokens[-1]


def parse_video_filename(path):
    path = Path(path)
    raw = unicodedata.normalize('NFC', path.stem)
    # Strip event and date prefixes before finding the sport level.
    if 'этап' not in raw.lower():
        raise ValueError(f'No event marker: {path.name}')
    category_part = re.split('этап', raw, maxsplit=1, flags=re.I)[1]
    match = re.search(r'(\d+)#\s*(.+?)\s*\(([^()]*)\)\s*$', raw)
    if not match:
        raise ValueError(f'Unrecognized filename: {path.name}')
    normalized = canonical(category_part)
    segment = 'short' if 'КОРОТКАЯ' in normalized else 'free' if 'ПРОИЗВОЛЬНАЯ' in normalized else None
    if segment is None:
        raise ValueError(f'No segment: {path.name}')
    return {'path': str(path), 'categoryKey': category_key(category_part), 'segment': segment,
            'startNumber': int(match[1]), 'athleteName': match[2].strip(), 'region': match[3].strip()}


def reviewed_alias(video, program, aliases):
    return any(a['videoPath'] == video['path'] and a['videoAthleteName'] == video['athleteName']
               and a['programId'] == program['id'] and a['programAthleteName'] == program['athleteName']
               and a['sourceSha256'] == program.get('sourceSha256') and a['sourceSha256']
               for a in aliases)


def match_video(video, programs, aliases=()):
    candidates = [p for p in programs if category_key(p['category']['raw']) == video['categoryKey']
                  and p['category']['segment'] == video['segment'] and p['startNumber'] == video['startNumber']]
    exact = [p for p in candidates if (name_key(p['athleteName']) == name_key(video['athleteName'])
             or reviewed_alias(video, p, aliases)) and canonical(p['region']) == canonical(video['region'])]
    if len(exact) == 1:
        return {'status': 'matched', 'programId': exact[0]['id'], 'video': video,
                'matchMethod': 'reviewed_name_alias_category_segment_start_region' if name_key(exact[0]['athleteName']) != name_key(video['athleteName']) else 'category_segment_start_given_surname_region'}
    return {'status': 'ambiguous' if len(exact) > 1 else 'identity_mismatch' if candidates else 'unmatched',
            'programId': None, 'video': video, 'candidateProgramIds': [p['id'] for p in candidates]}


def match_all(videos, programs, aliases=()):
    rows = [match_video(v, programs, aliases) for v in videos]
    counts = Counter(r['programId'] for r in rows if r['status'] == 'matched')
    for row in rows:
        if row['status'] == 'matched' and counts[row['programId']] > 1:
            row.update(status='ambiguous', reason='multiple_videos_for_program',
                       candidateProgramIds=[row['programId']], programId=None)
    return rows


def axels_in_program(program):
    axels = []
    for element in program['elements']:
        for component_index, component in enumerate(element['code'].split('+'), 1):
            match = re.fullmatch(r'([1-4])?A(<<|<|q)?([!*]*)', component)
            if not match:
                continue
            axels.append({'sequence': element['sequence'], 'elementCode': element['code'],
                          'componentIndex': component_index, 'componentCode': component,
                          'nominalAxel': f'{match[1]}A' if match[1] else None, 'rotationSign': match[2],
                          'invalid': '*' in component, 'info': element.get('flagsInfo', []), 'elementFall': element.get('fall', False), 'componentFall': None,
                          'sourcePage': element.get('sourcePage'),
                          'labelSource': 'official_protocol', 'labelScope': 'program_element',
                          'trainEligible': False, 'temporalMappingStatus': 'unlocalized',
                          'measuredRevolutions': None, 'underrotationDegrees': None})
    return axels


def protocol_source(program):
    return {'file': program.get('sourcePdf'), 'sha256': program.get('sourceSha256'), 'page': program.get('sourcePage')}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def markdown_report(programs, matches, inventory, stats):
    by_id = {p['id']: p for p in programs}
    video_counts = Counter(f"{r['video']['categoryKey']} / {r['video']['segment']}" for r in matches)
    matched_counts = Counter(f"{r['video']['categoryKey']} / {r['video']['segment']}" for r in matches if r['status'] == 'matched')
    protocol_counts = Counter(f"{category_key(p['category']['raw'])} / {p['category']['segment']}" for p in programs)
    lines = ['# Детализации и видео: Кубок федерации, 2 этап', '',
             f"Импортировано программ: **{len(programs)}**. Видео: **{len(matches)}**. Сопоставлено: **{stats['matchedVideos']}**.", '',
             f"Из них по полному имени: {stats['exactNameMatches']}; с отдельно проверенными сокращениями имени/фамилии: {stats['reviewedNameMatches']}.", '',
             'Это официальные вызовы технической бригады, а не прогнозы модели. Временные границы элементов ещё не назначены. '
             'Порядковый номер учитывает все элементы, включая вращения и дорожки. '
             'Знак отсутствует = в протоколе нет q/< /<<; это не означает отсутствие падения или других ошибок.', '',
             f"В сопоставленных видео указано **{stats['matchedAxelComponents']}** акселей (компоненты каскадов учитываются отдельно). "
             f"Из них недопустимых, со звёздочкой: **{stats['invalidAxelComponents']}**.", '',
             '| Категория / программа | Видео | Протоколы | Сопоставлено |', '|---|---:|---:|---:|']
    for key in sorted(set(video_counts) | set(protocol_counts)):
        lines.append(f'| {key} | {video_counts[key]} | {protocol_counts[key]} | {matched_counts[key]} |')
    lines += ['', 'F — девушки/женщины; M — юноши/мужчины; short — короткая, free — произвольная.', '',
              '## Аксели в сопоставленных программах', '',
              '| Спортсмен | Категория | Старт | Элементы по протоколу | Источник |', '|---|---|---:|---|---|']
    for row in sorted((r for r in matches if r['status'] == 'matched'), key=lambda r: (r['video']['categoryKey'], r['video']['segment'], r['video']['startNumber'])):
        p = by_id[row['programId']]
        axels = axels_in_program(p)
        codes = '; '.join(f"№{a['sequence']}: `{a['elementCode']}`" for a in axels) or 'нет A'
        source = protocol_source(p)
        lines.append(f"| [{p['athleteName']}](<{row['video']['path']}>) | {row['video']['categoryKey']} / {p['category']['segment']} | {p['startNumber']} | {codes} | [PDF, с. {source.get('page', '?')}](<{Path(source['file']).resolve()}>) |")
    lines += ['', '## Несопоставленные видео', '', '| Видео | Причина |', '|---|---|']
    for r in matches:
        if r['status'] != 'matched':
            lines.append(f"| {Path(r['video']['path']).name} | {r['status']} |")
    used = {r['programId'] for r in matches if r['status'] == 'matched'}
    lines += ['', '## Протоколы без установленной пары', '']
    for p in programs:
        if p['id'] not in used:
            lines.append(f"- {p['athleteName']} — {category_key(p['category']['raw'])}/{p['category']['segment']}, старт {p['startNumber']} ({p['id']}).")
    lines += ['', 'Данные для обучения клипов пока не дополнялись: сначала нужна проверка соответствия реального прыжка элементу протокола. '
              'Исходные PDF и их SHA256 сохранены рядом с этим отчётом.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--programs', type=Path, required=True)
    parser.add_argument('--videos', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reviewed-aliases', type=Path)
    args = parser.parse_args()
    data = json.loads(args.programs.read_text())
    programs = data['programs']
    videos = []
    for path in sorted(args.videos.glob('*.mp4')):
        try:
            video = parse_video_filename(path)
            stat = path.stat()
            video.update(fileSizeBytes=stat.st_size, fileMtimeNs=stat.st_mtime_ns,
                         identityScope='filename_metadata_no_content_label')
            videos.append(video)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    aliases = json.loads(args.reviewed_aliases.read_text())['aliases'] if args.reviewed_aliases else []
    rows = match_all(videos, programs, aliases)
    by_id = {p['id']: p for p in programs}
    inventory = []
    for row in rows:
        if row['status'] == 'matched':
            p = by_id[row['programId']]
            for axel in axels_in_program(p):
                inventory.append({'programId': p['id'], 'athleteName': p['athleteName'],
                                  'video': row['video'], 'source': protocol_source(p), **axel})
    stats = {'videos': len(videos), 'programs': len(programs), 'statuses': dict(Counter(r['status'] for r in rows)),
             'matchedVideos': sum(r['status'] == 'matched' for r in rows),
             'exactNameMatches': sum(r['status'] == 'matched' and r['matchMethod'].startswith('category_') for r in rows),
             'reviewedNameMatches': sum(r['status'] == 'matched' and r['matchMethod'].startswith('reviewed_') for r in rows),
             'matchedAxelComponents': len(inventory), 'invalidAxelComponents': sum(a['invalid'] for a in inventory),
             'axelCalls': dict(sorted(Counter(a['componentCode'] for a in inventory).items()))}
    provenance = {'schemaVersion': 1, 'matcherSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'programsPath': str(args.programs.resolve()),
                  'programsSha256': hashlib.sha256(args.programs.read_bytes()).hexdigest(),
                  'sourceVideoRoot': str(args.videos.resolve()),
                  'reviewedAliasesPath': str(args.reviewed_aliases.resolve()) if args.reviewed_aliases else None,
                  'reviewedAliasesSha256': hashlib.sha256(args.reviewed_aliases.read_bytes()).hexdigest() if args.reviewed_aliases else None,
                  'summary': stats}
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / 'video-matches.json', {**provenance, 'matches': rows})
    write_json(args.out / 'axel-inventory.json', {**provenance, 'axels': inventory})
    (args.out / 'report.md').write_text(markdown_report(programs, rows, inventory, stats))
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
