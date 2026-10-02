"""Publish complete RTMPose pilot into the existing local viewer, atomically."""
import html
import json
from pathlib import Path
import statistics

from rtmpose_adapter import integrate

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT/'data/axel-demo-v1'
OUT = ROOT/'data/pose-rtmpose-pilot-v1'


def main():
    demo = json.loads((DEMO/'data.json').read_text())
    proposals = {c['id']:json.loads((OUT/(c['id']+'.json')).read_text()) for c in demo['clips']}
    data = integrate(demo, proposals)
    evaluation = json.loads((OUT/'evaluation.json').read_text())
    frame_count = sum(len(c['frames']) for c in demo['clips'])
    if evaluation['processedFrames'] != frame_count:
        raise ValueError('Evaluation does not cover the entire viewer')
    data['modelProvenance'] = {**data.get('modelProvenance', {}), 'RTMPose': evaluation['settings']}
    raw = [f for c in demo['clips'] for f in json.loads((OUT/(c['id']+'.raw.json')).read_text())]
    data['modelProvenance']['RTMPose']['reviewFlags'] = dict(lowConfidence=.3,
        disagreementPeer='Full', disagreementDiagonalFraction=.02, temporalDiagonalFraction=.03,
        calibrated=False)
    temp = DEMO/'data.json.tmp'
    temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False))
    temp.replace(DEMO/'data.json')
    for page in ('index.html','compare.html'):
        path = DEMO/page
        text = path.read_text()
        if 'value="RTMPose"' not in text:
            text = text.replace('<option>Full</option>', '<option>Full</option><option value="RTMPose">RTMPose · эксперимент</option>')
        if 'rtmpose-results.html' not in text:
            text = text.replace('<main>', '<main><p><a href="rtmpose-results.html">RTMPose: результаты проверки и ограничения →</a></p>', 1)
        path.write_text(text)
    rows = ''
    for label, values in evaluation['models'].items():
        paired = evaluation['paired'][label]
        rows += f"<tr><th>{html.escape(label)}</th><td>{values['predicted']} / {evaluation['located']}</td><td>{values['meanPx']:.1f}</td><td>{paired['meanPx']:.1f}</td><td>{values['maxPx']:.1f}</td></tr>"
    details = ''
    for key, values in evaluation['perFrame'].items():
        details += '<tr><th>'+html.escape(key)+'</th>'
        for label in ('Lite','Full','RTMPose'):
            v = values[label]
            details += '<td>'+('Нет точек' if v['meanPx'] is None else f"{v['meanPx']:.1f} px; {v['predicted']} точек")+'</td>'
        details += '</tr>'
    report = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FS_elem · Проверка RTMPose</title><link rel="stylesheet" href="style.css"><style>table{{border-collapse:collapse;width:100%;margin:20px 0}}td,th{{padding:12px;border-bottom:1px solid #456;text-align:left}}.scroll{{overflow:auto}}p{{max-width:1000px}}</style><main>
<p><a href="index.html">Разбор прыжка</a> · <a href="compare.html">Сравнение попыток</a></p>
<h1>RTMPose: новый вариант скелета</h1><p>Обработаны {frame_count} исходных кадров пяти попыток. В меню «Модель» появился RTMPose · эксперимент. Lite и Full сохранены; новая модель не применяется автоматически. Старые ручные коррекции к ней не относятся.</p>
<h2>Сравнение с вашей разметкой</h2><p>Шесть специально выбранных сложных кадров, {evaluation['located']} точек с координатами; {evaluation['unassessable']} неразличимых точек исключены. Ошибка — расстояние в пикселях исходного кадра 1280×720. Меньше — лучше. Пропуски учитываются отдельно.</p>
<div class="scroll"><table><tr><th>Модель</th><th>Найдено</th><th>Средняя ошибка на доступных точках, px</th><th>На {evaluation['commonPoints']} общих точках, px</th><th>Максимум, px</th></tr>{rows}</table></div>
<p>На общих точках RTMPose лучше в среднем, но по всему набору уступает Lite из-за крупных ошибок. В частности, на кадре Ладыгиной 1650 сохраняется неверное назначение сторон. Это диагностический эксперимент, а не доказательство общей точности на фигурном катании.</p>
<div class="scroll"><table><tr><th>Кадр</th><th>Lite</th><th>Full</th><th>RTMPose</th></tr>{details}</table></div>
<h2>Что изменилось в просмотрщике</h2><p>Можно переключать три модели на одном кадре и при синхронном сравнении попыток. У RTMPose показаны исходные точки: без сглаживания, перестановки сторон или ручных исправлений. Оранжевые отметки указывают на пропуски, низкий score, расхождение с Full или резкое перемещение. Это подсказки для просмотра, не подтверждённые ошибки.</p>
<p>RTMPose score не сопоставим напрямую с уверенностью MediaPipe. Порог 0,3 выбран как предварительный сигнал, а не обучен на вашей разметке. Для расхождений используется 2% диагонали кадра, для перемещений между соседними кадрами — 3%. Для Lite/Full сохранены прежние правила.</p>
<h2>Что пока остаётся проблемным</h2><p>При просмотре последовательностей у Марочкиной заметны перестановки конечностей около кадров 3651–3652 и неверная конфигурация ног на 3697. У Смирновой 1741 ошибка больше, чем у MediaPipe. RTMPose не устранил проблему сторон целиком; автоматическое смешивание моделей пока не применяется.</p><h2>Воспроизводимость и ограничения</h2><p>RTMPose-m body7 + YOLOX-m, RTMLib {html.escape(evaluation['settings']['version'])}, ONNX Runtime CPU. Медиана обработки кадра в этом прогоне: {statistics.median(f['inferenceMs'] for f in raw):.0f} мс (детекция + поза; без чтения изображения). Это пакетный расчёт заранее, не измерение скорости браузера.</p>
<p>Исходные PNG проверены по SHA-256; они совпадают с кадрами, использованными для MediaPipe. Выбирается самый крупный обнаруженный человек — правило для этих одиночных прыжков, не универсальный трекинг. При отсутствии детекции поза остаётся пустой. Никакого дообучения на этих шести кадрах не было. Перед выбором основной модели нужны новые независимые примеры.</p>
<p><a href="rtmpose-evaluation.json">Полные результаты и параметры</a> · <a href="rtmpose-anchors.jpg">Шесть кадров: оригинал, Lite, Full, RTMPose</a></p>
</main></html>'''
    (DEMO/'rtmpose-results.html').write_text(report)
    (DEMO/'rtmpose-evaluation.json').write_text(json.dumps(evaluation, ensure_ascii=False, indent=2))
    import shutil
    sheet = ROOT/'work/step23-rtmpose/anchors.jpg'
    if sheet.exists():
        shutil.copyfile(sheet, DEMO/'rtmpose-anchors.jpg')
    print(f'Published {frame_count} frames with isolated RTMPose outputs.')

if __name__ == '__main__':
    main()
