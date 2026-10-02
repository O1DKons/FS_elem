export function validate(payload, items) {
  if (payload?.schemaVersion !== 1 || !Array.isArray(payload.labels)) throw Error('Неверный формат');
  const known = new Map(items.map(i => [i.id, i.sha256]));
  const seen = new Set();
  return payload.labels.map(r => {
    if (known.get(r.id) !== r.sha256 || seen.has(r.id) || !['complete', 'short', 'unclear'].includes(r.assessment)) throw Error('Не совпадает видео или оценка');
    seen.add(r.id);
    return {id:r.id,sha256:r.sha256,assessment:r.assessment};
  });
}

export function validateAthleteGroups(payload, items, datasetSha256) {
  if (payload?.schemaVersion !== 1 || payload?.datasetSha256 !== datasetSha256 || !Array.isArray(payload.assignments)) {
    throw Error('Неверный формат групп спортсменов или другой набор видео');
  }
  const known = new Map(items.map(i => [i.id, i.sha256]));
  const seen = new Set();
  return payload.assignments.map(row => {
    const group = typeof row?.athleteGroup === 'string' ? row.athleteGroup.trim() : '';
    if (known.get(row?.id) !== row?.sha256 || seen.has(row.id) || !group || group.length > 40 || /[\u0000-\u001f\u007f]/u.test(group)) {
      throw Error('Есть неизвестное видео, повторная запись или некорректная группа спортсмена');
    }
    seen.add(row.id);
    return {id: row.id, sha256: row.sha256, athleteGroup: group};
  });
}
