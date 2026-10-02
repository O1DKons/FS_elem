"""Import official program score PDFs without inferring video/expert labels.

The repeated competition/date/category line, rather than athlete name order,
delimits a table: pdfplumber can emit element 1 before the athlete row.
Run with a Python environment containing pdfplumber. The complete import is
validated before the output file is replaced; ambiguous tables fail closed.
"""
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DECIMAL = r'-?\d+\.\d{2}'
HEADER = re.compile(
    r'^(?P<competition>.+) \((?P<start>\d{2}\.\d{2}\.\d{4})-'
    r'(?P<end>\d{2}\.\d{2}\.\d{4})\) -- (?P<category>.+) '
    r'\((?P<segment>Короткая программа|Произвольная программа)\)$')
ATHLETE = re.compile(
    rf'^(?P<rank>\d+) (?P<name>[А-ЯЁ][А-Яа-яЁё -]+) '
    rf'(?P<region>[А-ЯЁ]{{2,4}}) (?P<start>\d+) '
    rf'(?P<TSS>{DECIMAL}) (?P<TES>{DECIMAL}) (?P<PCS>{DECIMAL}) '
    rf'(?P<deductions>{DECIMAL})$')
SUM = re.compile(rf'^({DECIMAL}) ({DECIMAL})$')
INFO_FLAGS = {'q', '<', '<<', '!', 'e', '*', 'F', 'nC', 'nU', 'nS', 'nUp'}
MODIFIERS = {'SEQ', 'REP', 'COMBO'}
NONJUMP_BASES = {'CCoSp', 'CSSp', 'CSp', 'CoSp', 'FCCoSp', 'FCSSp',
                 'FCSp', 'FSSp', 'LSp', 'SSp', 'ChSp', 'StSq', 'ChSq'}
CYRILLIC_LOOKALIKES = str.maketrans(dict(zip('ACEKMOPTXYacekmoptxy',
                                           'АСЕКМОРТХУасекмортху')))


class ImportFailure(ValueError):
    """A source table cannot safely be converted into an official record."""


def require(condition, message):
    if not condition:
        raise ImportFailure(message)


def normalize_category(raw, segment):
    normalized = raw.translate(CYRILLIC_LOOKALIKES).upper()
    if ' КМС ' in normalized:
        level = 'KMS'
    elif ' МС ' in normalized:
        level = 'MS'
    else:
        match = re.search(r' ([123]) СПОРТИВНЫЙ ', normalized)
        require(match, f'Unknown category level: {raw}')
        level = match[1]
    if 'ДЕВУШКИ' in normalized or 'ЖЕНЩИНЫ' in normalized:
        gender = 'F'
    elif 'ЮНОШИ' in normalized or 'МУЖЧИНЫ' in normalized:
        gender = 'M'
    else:
        raise ImportFailure(f'Unknown category gender: {raw}')
    return {'raw': raw, 'normalized': normalized, 'level': level, 'gender': gender,
            'segment': 'short' if segment == 'Короткая программа' else 'free',
            'segmentRaw': segment}


def parse_component(raw, position):
    normalized = raw.replace('Е', 'E')
    jump = re.fullmatch(r'([1-4]?)(A|Lz|F|Lo|T|S|Eu)((?:<<|<|q|!|e|\*)*)', normalized)
    base = {'position': position, 'code': raw, 'jumpFamily': None,
            'nominalRevolutions': None, 'rotationSign': None,
            'edgeSign': None, 'invalid': '*' in raw}
    if jump:
        signs = re.findall(r'<<|<|q|!|e|\*', jump[3])
        rotation = [sign for sign in signs if sign in {'q', '<', '<<'}]
        edges = [sign for sign in signs if sign in {'!', 'e'}]
        require(len(rotation) <= 1 and len(edges) <= 1 and len(signs) == len(set(signs)),
                f'Ambiguous component marks: {raw}')
        base.update(kind='jump', nominalType=jump[1] + jump[2], jumpFamily=jump[2],
                    nominalRevolutions=int(jump[1]) if jump[1] else None,
                    rotationSign=rotation[0] if rotation else None,
                    edgeSign=edges[0] if edges else None, flagsCode=signs)
        return base
    other = re.fullmatch(r'(' + '|'.join(sorted(NONJUMP_BASES)) + r')([1-4B]?)(V?)(\*?)', normalized)
    require(other and other[1] in NONJUMP_BASES, f'Unknown component: {raw}')
    base.update(kind='step' if 'Sq' in other[1] else 'spin',
                nominalType=other[1] + other[2],
                flagsCode=[value for value in (other[3], other[4]) if value])
    return base


def parse_element(line):
    tokens = line.split()
    require(len(tokens) >= 8 and tokens[0].isdigit(), f'Malformed element row: {line}')
    values = [i for i, token in enumerate(tokens) if re.fullmatch(DECIMAL, token)]
    require(len(values) == 3, f'Expected base, GOE and panel score: {line}')
    base_index, goe_index, panel_index = values
    require(base_index >= 2 and panel_index == len(tokens) - 1,
            f'Ambiguous element columns: {line}')
    info = tokens[2:base_index]
    require(all(flag in INFO_FLAGS for flag in info), f'Unknown Info flag: {line}')
    bonus = tokens[base_index + 1:goe_index]
    require(bonus in ([], ['x']), f'Unknown base-value annotation: {line}')
    judges = tokens[goe_index + 1:panel_index]
    require(3 <= len(judges) <= 9 and all(re.fullmatch(r'-?[0-5]|-', j) for j in judges),
            f'Invalid judge columns: {line}')
    components, modifiers, modifiers_raw = [], [], []
    for position, raw in enumerate(tokens[1].split('+'), 1):
        token = raw.replace('Е', 'E')
        if token in MODIFIERS:
            modifiers.append(token)
            modifiers_raw.append(raw)
        else:
            components.append(parse_component(raw, position))
    require(components, f'No element components: {line}')
    require(Decimal(tokens[base_index]) + Decimal(tokens[goe_index]) == Decimal(tokens[panel_index]),
            f'Base plus GOE differs from panel score: {line}')
    return {'sequence': int(tokens[0]), 'code': tokens[1], 'flagsInfo': info,
            'baseValue': float(tokens[base_index]), 'bonusSecondHalf': bonus == ['x'],
            'GOE': float(tokens[goe_index]),
            'judgeGOE': [None if j == '-' else int(j) for j in judges],
            'panelScore': float(tokens[panel_index]), 'fall': 'F' in info,
            'components': components, 'modifiers': modifiers,
            'modifiersRaw': modifiers_raw, 'rawLine': line}


def decimal_sum(elements, field):
    return sum((Decimal(str(e[field])) for e in elements), Decimal(0))


def parse_block(lines, source_pdf, sha256):
    header = HEADER.fullmatch(lines[0][1])
    athletes = [(page, line, ATHLETE.fullmatch(line)) for page, line in lines if ATHLETE.fullmatch(line)]
    require(len(athletes) == 1, f'Expected exactly one athlete, found {len(athletes)}')
    page, athlete_line, athlete = athletes[0]
    elements, totals, components, judges = [], [], [], []
    pcs_total, deduction_total, deduction_raw = [], [], []
    for line_page, line in lines[1:]:
        if ATHLETE.fullmatch(line):
            continue
        if re.match(r'^\d+ ', line):
            element = parse_element(line)
            element['sourcePage'] = line_page
            elements.append(element)
        elif SUM.fullmatch(line):
            totals.append(SUM.fullmatch(line).groups())
        elif line.startswith('# GOE '):
            judges.append(len(re.findall(r'\bJ\d+\b', line)))
        elif line.startswith(('Композиция ', 'Представление ', 'Мастерство катания ')):
            match = re.fullmatch(r'(.+?) (\d+\.\d{2}) ((?:\d+,\d{2} )+)(\d+\.\d{2})', line)
            require(match, f'Malformed program component: {line}')
            components.append({'name': match[1], 'factor': float(match[2]),
                               'judgeScores': [float(n.replace(',', '.')) for n in match[3].split()],
                               'panelScore': float(match[4])})
        elif line.startswith('Сумма за компоненты программы (умноженная) '):
            pcs_total.append(line.rsplit(' ', 1)[-1])
        elif line.startswith('Снижения '):
            deduction_total.append(line.rsplit(' ', 1)[-1])
            deduction_raw.append(line)
    require(elements and [e['sequence'] for e in elements] == list(range(1, len(elements) + 1)),
            'Missing, duplicated or unordered element sequence')
    require(len(judges) == 1 and all(len(e['judgeGOE']) == judges[0] for e in elements),
            'Judge column count mismatch')
    require(len(totals) == 1, f'Expected one element subtotal, found {len(totals)}')
    require(len(components) == 3 and len({c['name'] for c in components}) == 3,
            'Missing/duplicate program component rows')
    require(all(len(c['judgeScores']) == judges[0] for c in components),
            'Program component judge count mismatch')
    require(pcs_total == [athlete['PCS']] and deduction_total == [athlete['deductions']],
            'Summary PCS/deductions differ from table totals')
    require(decimal_sum(elements, 'baseValue') == Decimal(totals[0][0]), 'Base-value sum mismatch')
    require(decimal_sum(elements, 'panelScore') == Decimal(totals[0][1]) == Decimal(athlete['TES']),
            'TES sum mismatch')
    require(Decimal(athlete['TSS']) == Decimal(athlete['TES']) + Decimal(athlete['PCS']) + Decimal(athlete['deductions']),
            'TSS differs from TES + PCS + signed deductions')
    category = normalize_category(header['category'], header['segment'])
    warnings = []
    for element in elements:
        for component in element['components']:
            if component['kind'] == 'jump' and component['nominalRevolutions'] is None:
                warnings.append({'code': 'jump_rotation_count_unspecified_in_source',
                                 'elementSequence': element['sequence'], 'component': component['code']})
        component_flags = {flag for c in element['components'] for flag in c['flagsCode']}
        missing_code_flags = set(element['flagsInfo']) & {'q', '<', '<<', '!', 'e', '*'} - component_flags
        if missing_code_flags:
            warnings.append({'code': 'info_flags_not_present_in_element_code',
                             'elementSequence': element['sequence'], 'flags': sorted(missing_code_flags)})
    start_number = int(athlete['start'])
    identity = f'{sha256}:{start_number}'
    return {'id': 'program-' + hashlib.sha256(identity.encode()).hexdigest()[:20],
            'labelSource': 'official_protocol',
            'competition': {'name': header['competition'],
                            'dateStart': datetime.strptime(header['start'], '%d.%m.%Y').date().isoformat(),
                            'dateEnd': datetime.strptime(header['end'], '%d.%m.%Y').date().isoformat()},
            'category': category, 'athleteName': athlete['name'], 'region': athlete['region'],
            'startNumber': start_number, 'rank': int(athlete['rank']),
            'scores': {**{key: float(athlete[key]) for key in ['TSS', 'TES', 'PCS', 'deductions']},
                       'baseValue': float(totals[0][0])},
            'elements': elements, 'programComponents': components,
            'deductionsRaw': deduction_raw[0], 'athleteHeaderRaw': athlete_line,
            'sourcePdf': source_pdf, 'sourcePage': page, 'sourceSha256': sha256,
            'warnings': warnings,
            'validation': {'elementSequenceContiguous': True, 'elementCount': len(elements),
                           'baseValueSumMatches': True, 'TESMatches': True,
                           'TSSMatches': True, 'judgeCount': judges[0]}}


def parse_pages(pages, source_pdf, sha256):
    blocks, current = [], []
    observed_athletes = 0
    for page in pages:
        require(page.get('text', '').strip(), f'{source_pdf} page {page["page"]}: empty extraction')
        for raw in page['text'].splitlines():
            line = raw.strip()
            if ATHLETE.fullmatch(line):
                observed_athletes += 1
            if HEADER.fullmatch(line):
                if current:
                    blocks.append(current)
                current = []
            if current or HEADER.fullmatch(line):
                current.append((page['page'], line))
            elif re.match(r'^\d+ ', line):
                raise ImportFailure(f'{source_pdf} page {page["page"]}: data outside table boundary: {line}')
    if current:
        blocks.append(current)
    require(blocks, f'{source_pdf}: no program tables')
    programs, failures = [], []
    for i, block in enumerate(blocks, 1):
        try:
            programs.append(parse_block(block, source_pdf, sha256))
        except ImportFailure as error:
            failures.append(f'{source_pdf} page {block[0][0]} table {i}: {error}')
    require(not failures, '\n'.join(failures))
    require(len(programs) == observed_athletes, f'{source_pdf}: athlete/table count mismatch')
    require(len({p['id'] for p in programs}) == len(programs), f'{source_pdf}: duplicate start number')
    require([p['rank'] for p in programs] == list(range(1, len(programs) + 1)),
            f'{source_pdf}: missing/duplicate rank')
    require(len({json.dumps(p['category'], sort_keys=True) for p in programs}) == 1,
            f'{source_pdf}: mixed categories')
    return programs


def import_manifest(manifest_path, root=ROOT):
    import pdfplumber

    manifest_bytes = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes)
    programs, documents, failures = [], [], []
    require(isinstance(manifest.get('files'), list) and manifest['files'], 'Empty source manifest')
    require(len({s['file'] for s in manifest['files']}) == len(manifest['files']), 'Duplicate source path')
    require(len({s['sha256'] for s in manifest['files']}) == len(manifest['files']), 'Duplicate source PDF')
    for source in manifest['files']:
        try:
            path = Path(root) / source['file']
            require(hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256'],
                    f'{source["file"]}: SHA-256 mismatch')
            with pdfplumber.open(path) as pdf:
                require(len(pdf.pages) == source['pages'], f'{source["file"]}: page count mismatch')
                pages = [{'page': i, 'text': page.extract_text() or ''}
                         for i, page in enumerate(pdf.pages, 1)]
            rows = parse_pages(pages, source['file'], source['sha256'])
            programs.extend(rows)
            documents.append({'sourcePdf': source['file'], 'sourceSha256': source['sha256'],
                              'pageCount': len(pages), 'programCount': len(rows),
                              'elementCount': sum(len(row['elements']) for row in rows)})
        except (ImportFailure, OSError) as error:
            failures.append(str(error))
    require(not failures, '\n'.join(failures))
    counts = Counter((p['category']['level'], p['category']['gender'], p['category']['segment']) for p in programs)
    axels = [c for p in programs for e in p['elements'] for c in e['components'] if c['jumpFamily'] == 'A']
    return {'schemaVersion': 1, 'source': 'user_supplied_official_program_scores',
            'labelSemantics': {'rotationSign': 'Exact official code mark: q, <, <<, or null (unmarked).',
                               'unmarkedIsVisualConfirmation': False,
                               'invalidCodeRetained': True, 'containsVideoTimestamps': False,
                               'containsVisualExpertLabels': False,
                               'infoFlagsPolicy': 'Preserved separately; never counted as extra components or used to overwrite code marks.',
                               'nominalTypePolicy': 'Preserve source rotation prefix; bare A/Eu remain A/Eu, without inferring a rotation count.'},
            'manifestSha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'importerSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'extractor': {'name': 'pdfplumber', 'version': pdfplumber.__version__},
            'documents': documents, 'programs': programs,
            'summary': {'sourcePdfCount': len(documents), 'sourcePageCount': sum(d['pageCount'] for d in documents),
                        'programCount': len(programs), 'elementCount': sum(d['elementCount'] for d in documents),
                        'axelComponentCount': len(axels),
                        'axelRotationSignCounts': dict(sorted(Counter(c['rotationSign'] or 'unmarked' for c in axels).items())),
                        'categoryCounts': [{'level': key[0], 'gender': key[1], 'segment': key[2], 'programCount': count}
                                           for key, count in sorted(counts.items())],
                        'warningCount': sum(len(p['warnings']) for p in programs), 'errorCount': 0}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/new-programs-protocols-v1/manifest.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/new-programs-protocols-v1/programs.json')
    args = parser.parse_args()
    result = import_manifest(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
