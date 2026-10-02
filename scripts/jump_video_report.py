"""Reviewable short-clip inference report. Type and measured rotation stay separate."""
import html,re

def result_contract(prediction):
 label=prediction['predicted_label']
 match=re.fullmatch(r'([1234])A',label or '')
 return dict(schemaVersion=1,status='experimental_model_proposal',scope='short_single_element_clip',
  sourceSha256=prediction['video_sha256'],elementProposal=label,
  nominalAxelRevolutions=int(match.group(1))+.5 if match else None,
  measuredRevolutions=None,rotationAssessment=None,underrotationDegrees=None,
  extractionStatus=prediction['extraction_status'],modelOutput=prediction,
  limitations=['Type prediction is not a measurement of actual rotations.',
   'Clean/short inference for arbitrary video is not yet validated or connected.',
   'Requires a short clip containing one element; full-program search is not implemented.'])

def render_report(result,video_name):
 label=html.escape(result['elementProposal'] or 'Недостаточно видимых точек для ответа');video=html.escape(video_name,quote=True)
 nominal=result['nominalAxelRevolutions']
 nominal_text=('<p>Номинальная сложность предложенного акселя: '+str(nominal)+' оборота. Это название класса, не измерение фактического вращения.</p>') if nominal is not None else ''
 return '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FS_elem · анализ видео</title><style>body{font:18px system-ui;background:#101923;color:#e5edf4;max-width:1000px;margin:32px auto;padding:20px}video{display:block;width:100%;max-height:65vh;background:#000}p{line-height:1.5}a{color:#8df}.result{padding:20px;background:#1b2a38;border-radius:12px}</style><h1>FS_elem · пробный анализ фрагмента</h1><video controls preload="metadata" src="'''+video+'''"></video><div class="result"><h2>Предложение модели: '''+label+'''</h2>'''+nominal_text+'''<p>Фактическое число оборотов: не измерено.<br>Докрут / недокрут: пока нет проверенного ответа для нового видео.</p></div><p>Этот эксперимент принимает короткий фрагмент с одним элементом. Поиск акселя в полной программе ещё не подключён. Предложение модели требует проверки.</p><p><a href="result.json">Данные результата и происхождение</a></p></html>'''
