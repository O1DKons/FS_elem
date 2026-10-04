# Analysis API v1

Local-only API; no account, remote upload, training, or telemetry. The web server proxies `/api/analysis/*` to the Python service. Max raw upload: 512 MiB. Formats: `.mp4`, `.mov`, `.m4v`, `.webm`; source duration at most 600 seconds. One inference process tree at a time, at most four waiting jobs. Service `--max-wall-seconds` bounds each job (default 5400, range 1–5400); cold release smoke uses 1800. All paths below are relative to the web origin.

- `POST /api/analysis/jobs`: raw bytes; `X-Filename: encodeURIComponent(file.name)`; `Content-Type: application/octet-stream`. Returns 202 with Job. Rejects unsupported extension (415), empty/oversized upload (400/413), full queue (429), unavailable runtime (503).
- `GET /api/analysis/jobs/{jobId}` (also `/state`): Job, 200 or 404.
- `GET /api/analysis/jobs/{jobId}/result`: Result, 200; 409 with `{error:{code:'NOT_READY',message:'...'}}` until succeeded.
- `GET /api/analysis/jobs/{jobId}/pose`: Pose, same availability as Result.
- `GET|HEAD /api/analysis/jobs/{jobId}/media`: original uploaded video, byte ranges supported. No path parameter or local filesystem disclosure.
- `DELETE /api/analysis/jobs/{jobId}`: cancel queued/running job, return Job (202 while cleanup is pending, 200 when terminal). Retains uploaded file/results for inspection; does not erase a completed result.
- `GET /api/analysis/health`: `{service:'fs-elem-analysis',status:'ready',inferenceAvailable:boolean,issues:string[],activeJobId:string|null}`. Runtime readiness requires config, executable environments and checksum-bound assets; failed setup never pretends inference is available.

Job:
```json
{"schemaVersion":1,"jobId":"opaque-uuid","state":"queued","createdAt":"ISO UTC","updatedAt":"ISO UTC","elapsedSeconds":0,"source":{"filename":"clip.mp4","sizeBytes":100,"sha256":"64hex"},"progress":{"stage":"queued","currentFrame":null,"totalFrames":null,"percent":null},"error":null,"links":{"self":"/api/analysis/jobs/opaque-uuid","result":"/api/analysis/jobs/opaque-uuid/result","pose":"/api/analysis/jobs/opaque-uuid/pose","media":"/api/analysis/jobs/opaque-uuid/media"}}
```
States: `queued`, `running`, `succeeded`, `failed`, `cancelled`. Stages: `queued`, `probe`, `sparse`, `flight_family`, `dense`, `nominal`, `export`, `cancelling`, `completed`, `failed`, `cancelled`. Percent is stage-local, or null. It is not overall ETA. Error is null or `{code:string,message:string}`. Interrupted jobs become failed after service restart; no automatic repeat analysis.

`elapsedSeconds` is an optional additive field, computed on GET without changing the saved job or its `updatedAt`. It measures queue plus processing time from `createdAt`, after the upload has been accepted. For queued/running jobs, the end is the server's current UTC time; for all terminal states, the end is saved `updatedAt`, so the value stops increasing. Invalid or timezone-naive timestamps and unknown states return null; a backwards clock yields zero. Display it as “Ожидание и обработка”; upload time is separate, and this is not an ETA. Older RC1 services omit this field. A client may derive terminal elapsed time from valid timestamps in that case, but should hide a running counter rather than substitute its own clock. The optional Result timing `totalBeforeWriteSeconds` separately measures pipeline calculation time and may be shown as “Время расчёта”.

Accepted uploads, job records, results, pose and media persist in the service's jobs directory; there is no automatic expiry or completed-result deletion. Reopening a known job UUID uses GET only and may restore a saved result after a service restart. A missing job returns 404 and must not trigger automatic upload or repeat inference. Retention depends on preserving this directory; this is not a backup guarantee.

Result:
```json
{"schemaVersion":1,"jobId":"opaque-uuid","status":"completed","source":{"sha256":"64hex","width":1920,"height":1080,"fps":50,"frameCount":100,"durationSeconds":1.98,"rotationDegrees":0},"events":[{"id":"candidate-id","startSeconds":0.5,"endSeconds":0.98,"family":"axel","nominal":"1A","nominalRevolutions":1.5,"nominalReason":"research_model_proposal","scoresUncalibrated":{"1A":0.8,"2A":0.2},"physicalAirborneTurns":null,"underrotation":null}],"candidateCount":1,"noEvents":false,"provenance":{"recipeSha256":"64hex","models":{},"exactSourceTrainingOverlap":{},"globalAthleteIndependenceVerified":false,"goal70Verified":false},"timings":{},"limitations":["Development model; results require review"]}
```
Only predicted Axels appear in events. Axel with insufficient nominal evidence has `nominal:null`, `nominalRevolutions:null`, and a reason; display “Аксель, номинал не определён”. Empty events is successful analysis with no detected Axel, not proof none occurred. 1.5/2.5 are nominal definitions, never measured rotations. No `q`, `<`, `<<` or physical-degree claim.

Pose:
```json
{"schemaVersion":1,"jobId":"opaque-uuid","source":{"sha256":"64hex","width":1920,"height":1080,"fps":50,"frameCount":100,"durationSeconds":1.98,"rotationDegrees":0},"layout":"coco-wholebody-first23","coordinateSpace":"displayed-source-pixels","scoreKind":"raw-heatmap-peak","maxNearestSeconds":{"sparse":0.065,"dense":0.025},"keypointNames":["nose"],"edges":[[5,7],[7,9]],"frames":[{"frameIndex":25,"timeSeconds":0.5,"density":"dense","candidateId":"candidate-id","points":[{"x":500,"y":200,"confidence":0.8}]}]}
```
There are exactly 23 keypointNames and 23 point entries per frame. Entry is null when missing/invalid; whole missing pose is 23 nulls. Actual source PTS, no interpolation or filled gaps. Dense observation wins over sparse at the same source frame. Raw confidences are not calibrated probabilities. Threshold drawing at >=0.3; use contain/letterbox mapping from source width/height. Sparse nearest <=0.065 sec, dense <=0.025 sec, otherwise hide. RotationDegrees records source display metadata; exported pixels correspond to browser-displayed orientation/dimensions (unverified rotation is rejected). Pose endpoints become available after completion; progress is independent of skeleton streaming.
# Stage2 additive runtime provenance

New result provenance may contain `ortThreads` with `intraOpNumThreads`2 or4 and `interOpNumThreads`1, and `runtimeSessions` grouped by `sparse`/`dense`. Each executed detector/pose record contains the actual ORT session thread options and `providers:["CPUExecutionProvider"]`. An empty dense list means no dense windows executed. Historical results may omit these fields or contain null; this does not certify their runtime settings.

The explicit profile is part of recipe identity and cache admission. It does not change the event/pose coordinate contract, nominal definitions, or null physical-turn/underrotation fields. Cached opening time remains separate from cold processing time.


## Неуспешная проверка источника: безопасная диагностика

У задачи со статусом `failed` поле `error` может содержать подтверждённую диагностику источника: `code`, `message`, `diagnostics`. В `diagnostics` ровно шесть полей: `schemaVersion=1`, `stage="probe"`, `code`, `declaredFrames`, `decodedFrames`, `failedTimestampConditions`. Значения counts — неотрицательные безопасные целые числа; логические, строковые и дробные значения не допускаются.

`SOURCE_FRAME_COUNT_MISMATCH` используется при разных counts; `SOURCE_TIMESTAMP_INVALID` — при равных counts и нарушенной временной шкале. Допустимые conditions в каноническом порядке: `first_timestamp_unavailable`, `first_timestamp_nonzero`, `nonfinite_timestamp`, `nonincreasing_timestamp`. Неизвестные или дополнительные поля, противоречащие друг другу сообщения и некорректная диагностика не становятся публичным объяснением: сохраняется общая ошибка. Приватный путь, заголовок файла и traceback не входят в диагностику.

Диагностика источника относится только к завершённой неуспешной задаче. Успех, отмена и ограничения времени/объёма сохраняют свой приоритет; запросы результата и позы неуспешной задачи по-прежнему возвращают 409. Восстановление такой задачи не запускает новый анализ. Эти сообщения не устанавливают повреждение файла или физический недокрут.
