"""Publish held-athlete-out diagnostic predictions, explicitly not production judging."""
import html,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 data=json.loads((ROOT/'work/step30-image-motion/results.json').read_text());variant=data['variants']['image_motion_only'];m=variant['metrics'];rows=[]
 labels=['Выглядит докрученным','Выглядит недокрученным']
 matrix=m['confusionTrueRowsPredictedColumns'];majority=data['variants']['training_majority']['metrics'];ncomplete=sum(matrix[0]);nshort=sum(matrix[1])
 for r,pred in zip(data['records'],variant['predictions']):
  correct=pred==r['target'];aid=html.escape(r['attemptId'],quote=True)
  rows.append(f'<tr><td>{html.escape(r["athlete"])}<small>{aid}</small></td><td>{labels[r["target"]]}</td><td>{labels[pred]}</td><td>{"Совпало" if correct else "Ошибка"}</td><td><a href="rotation-review.html?attempt={aid}">Кадры →</a></td></tr>')
 page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Движение изображения · FS_elem</title><style>body{font:17px/1.5 system-ui;background:#111b22;color:#eee;max-width:1200px;margin:32px auto;padding:20px}a{color:#65d9ff}small{display:block;color:#b2bdc7}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid #46515a}.scroll{overflow-x:auto}.notice{padding:18px;background:#27313b;border-radius:12px}h1{font-size:30px}</style><a href="index.html">← FS_elem</a><h1>Пробная классификация по движению изображения</h1><p class="notice">Исследовательский результат на уже размеченных попытках. Границы прыжка заданы человеком; это не автоматический поиск в программе и не измерение угла недокрута. Внешнего независимого теста пока нет.</p>'''
 page+=f'<p><b>{m["correct"]}/{m["n"]} совпадений ({m["accuracy"]:.0%})</b>. Докрученные: {matrix[0][0]}/{ncomplete}; недокрученные: {matrix[1][1]}/{nshort}. Тренировочное большинство: {majority["correct"]}/{m["n"]}. Средняя полнота по двум классам: {m["balancedAccuracy"]:.0%} против {majority["balancedAccuracy"]:.0%} у большинства.</p>'
 page+='''<p>Для каждого прогноза все попытки этой спортсменки исключены из обучения. Метод оценивает изменение изображения в полёте и первые 0,2 с после касания. Он использует точки тела только для выделения области спортсменки. Путаница сторон не исправляется; размытие, фон и ошибки области могут мешать.</p><p>«Ваша оценка» — сохранённое визуальное мнение, а не протокольная категория. Никаких вероятностей правильности или градусов модель здесь не выдаёт. Показаны все попытки эксперимента, включая ошибки.</p><div class="scroll"><table><thead><tr><th>Попытка</th><th>Ваша оценка</th><th>Прогноз без этой спортсменки в обучении</th><th>Результат</th><th>Просмотр</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div><p><a href="motion-results.json">Полный результат, признаки и разбиения</a> · <a href="rotation-review.html">Разметка попыток</a></p></html>'''
 demo=ROOT/'data/axel-demo-v1';(demo/'motion-results.html').write_text(page);(demo/'motion-results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
 p=demo/'index.html';s=p.read_text()
 if 'href="motion-results.html"' not in s:s=s.replace('<main>','<main><p><a href="motion-results.html">Эксперимент по докруту: прогнозы и ошибки →</a></p>')
 p.write_text(s)
 print('Published all20 held-athlete-out predictions')
if __name__=='__main__':main()
