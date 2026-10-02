const labels = new Set(['unknown', 'apparently_complete', 'apparently_short']);
const visibility = new Set(['clear', 'uncertain', 'not_visible']);
const sha = /^[a-f0-9]{64}$/i;
const identityKeys = ['attemptId', 'sourceSha256', 'videoId', 'lastContact', 'firstContact'];
function requireValue(ok, message) { if (!ok) throw new Error(message); }
function validTimestamp(value) {
  if (typeof value !== 'string') return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match || !Number.isFinite(Date.parse(value))) return false;
  const [, year, month, day, hour, minute, second] = match.map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1] && hour < 24 && minute < 60 && second < 60;
}
function validateIdentity(item) {
  requireValue(item && typeof item.attemptId === 'string' && item.attemptId.trim() && typeof item.videoId === 'string' && item.videoId.trim(), 'Некорректный идентификатор попытки');
  requireValue(sha.test(item.sourceSha256 || ''), 'Некорректная подпись исходного видео');
  requireValue(Number.isInteger(item.lastContact) && item.lastContact >= 0 && Number.isInteger(item.firstContact) && item.firstContact > item.lastContact, 'Некорректные границы попытки');
}
export function validateManifest(data) {
  requireValue(data?.schemaVersion === 1 && data.fps === 50 && data.width === 1280 && data.height === 720 && Array.isArray(data.items) && data.items.length > 0, 'Некорректный набор кадров');
  const ids = new Set();
  for (const item of data.items) {
    validateIdentity(item);
    requireValue(!ids.has(item.attemptId), 'Повтор идентификатора попытки'); ids.add(item.attemptId);
    requireValue(Array.isArray(item.frames) && item.frames.length > 0, 'Нет кадров');
    let previous = -1;
    for (const frame of item.frames) {
      requireValue(Number.isInteger(frame.frameIndex) && frame.frameIndex > previous && Number.isFinite(frame.time) && frame.time >= 0 && sha.test(frame.sourceFrameSha256 || ''), 'Некорректный кадр');
      requireValue(typeof frame.image === 'string' && /^(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.(?:jpg|jpeg|png|webp)$/i.test(frame.image) && !frame.image.split('/').includes('..'), 'Некорректный путь изображения');
      previous = frame.frameIndex;
    }
  }
  return data;
}
export function makeAssessment(item, draft, reviewedAt = new Date().toISOString()) {
  validateIdentity(item);
  requireValue(labels.has(draft?.rotationAssessment), 'Выберите оценку вращения');
  requireValue(visibility.has(draft?.visibility?.takeoff) && visibility.has(draft?.visibility?.landing), 'Укажите видимость отрыва и касания');
  requireValue(typeof draft.notes === 'string' && draft.notes.length <= 5000, 'Комментарий должен быть не длиннее 5000 символов');
  requireValue(validTimestamp(reviewedAt), 'Некорректное время проверки');
  return { ...Object.fromEntries(identityKeys.map(k => [k, item[k]])), rotationAssessment: draft.rotationAssessment, visibility: { takeoff: draft.visibility.takeoff, landing: draft.visibility.landing }, notes: draft.notes, reviewedAt };
}
export function exportAssessments(assessments) {
  return { schemaVersion: 1, kind: 'rotation-expert-review', assessments: assessments.map(r => makeAssessment(r, r, r.reviewedAt ?? null)) };
}
export function restoreAssessments(text, manifest) {
  try {
    const data = JSON.parse(text);
    if (data?.schemaVersion !== 1 || data.kind !== 'rotation-expert-review' || !Array.isArray(data.assessments)) return [];
    const accepted = new Map();
    for (const record of data.assessments) {
      const item = manifest.items.find(i => i.attemptId === record?.attemptId);
      if (!item || !identityKeys.every(k => item[k] === record[k])) continue;
      try { accepted.set(item.attemptId, makeAssessment(item, record, record.reviewedAt ?? null)); } catch { /* Discard invalid saved records. */ }
    }
    return [...accepted.values()];
  } catch { return []; }
}
export function mergeAssessments(importedText, localText, manifest) {
  const merged = new Map();
  for (const record of [...restoreAssessments(importedText, manifest), ...restoreAssessments(localText, manifest)]) {
    const previous = merged.get(record.attemptId);
    if (!previous || Date.parse(record.reviewedAt) > Date.parse(previous.reviewedAt)) merged.set(record.attemptId, record);
  }
  return [...merged.values()];
}
