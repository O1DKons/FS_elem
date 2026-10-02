"""Publish independently estimated ViTPose points without replacing baselines."""
import json
from pathlib import Path
from rtmpose_adapter import integrate

ROOT=Path(__file__).resolve().parents[1]
def main():
    demo=ROOT/'data/axel-demo-v1'; source=ROOT/'data/pose-vitpose-pilot-v1'
    original=json.loads((demo/'data.json').read_text())
    proposals={c['id']:json.loads((source/(c['id']+'.json')).read_text()) for c in original['clips']}
    result=integrate(original,proposals,label='ViTPose-B')
    # Preserve source model provenance alongside the viewer data.
    (demo/'vitpose-provenance.json').write_text(json.dumps({k:v['model'] for k,v in proposals.items()},indent=2))
    (demo/'data.json').write_text(json.dumps(result,ensure_ascii=False))
    evaluation=json.loads((source/'evaluation.json').read_text())
    (demo/'vitpose-evaluation.json').write_text(json.dumps(evaluation,ensure_ascii=False,indent=2))
    rows=''.join(f"<tr><td>{name}</td><td>{m['predicted']}/37</td><td>{m['meanPx']:.1f}</td></tr>" for name,m in evaluation['models'].items())
    report='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ViTPose — проверка</title><style>body{font:18px/1.6 system-ui;background:#111b22;color:#eee;max-width:900px;margin:40px auto;padding:20px}a{color:#65d9ff}td,th{text-align:left;padding:10px;border-bottom:1px solid #46515a}</style><h1>ViTPose-B: новая оценка по изображению</h1><p><a href="index.html">Открыть просмотр →</a> · <a href="compare.html">Сравнить попытки →</a></p><p>В списке моделей выберите ViTPose-B. Пересчитаны все 369 кадров пяти попыток. Розовый — анатомическая левая сторона, голубой — правая. Модель всё ещё может путать стороны.</p><p>На проблемных кадрах Марочкиной визуально улучшилось положение части плеч, коленей и голеностопов. Это не подтверждение точности всей последовательности: ошибки сторон и перекрытых суставов сохраняются.</p><h2>Контроль по вашей разметке</h2><table><tr><th>Модель</th><th>Найдено точек</th><th>Средняя ошибка, px</th></tr>'''+rows+'''</table><p>Шесть ранее размеченных сложных кадров, 1280×720; 37 доступных для оценки точек. Это диагностическая выборка, не независимый тест. У Full отсутствуют 10 точек, поэтому его среднее нельзя напрямую сравнивать с полными результатами. ViTPose не назначена основной моделью.</p><p>Точки получены из исходных изображений, без ручных исправлений, сглаживания и перестановок сторон. Оценка уверенности не является вероятностью правильного положения сустава. Пики тепловой карты выше 1 сохраняются в исходных данных; для формата просмотра оценка ограничена диапазоном 0–1.</p><p><a href="vitpose-evaluation.json">Полные результаты и настройки</a> · <a href="vitpose-provenance.json">Версии и хеши моделей</a></p></html>'''
    (demo/'vitpose-results.html').write_text(report)
    for filename in ('index.html','compare.html'):
        p=demo/filename;s=p.read_text()
        if 'value="ViTPose-B"' not in s:s=s.replace('<option value="RTMPose">','<option value="ViTPose-B">ViTPose-B · эксперимент</option><option value="RTMPose">')
        if 'href="vitpose-results.html"' not in s:s=s.replace('<main>','<main><p><a href="vitpose-results.html">ViTPose-B: новая проверка скелета →</a></p>')
        p.write_text(s)
    for filename in ('app.mjs','compare.mjs'):
        p=demo/filename;p.write_text(p.read_text().replace("model==='RTMPose'","!['Lite','Full'].includes(model)"))
    print('Published ViTPose-B:',sum(len(c['frames']) for c in result['clips']),'frames')
if __name__=='__main__':main()
