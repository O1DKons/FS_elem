'use client';
import { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  FileVideo,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  Upload,
  X,
} from 'lucide-react';
import PoseOverlay from './PoseOverlay';
import { createAnalysisClient } from '../../lib/analysis-client.mjs';
import type { AnalysisHealth } from '../../lib/analysis-client.mjs';
import type {
  AnalysisJob,
  AnalysisPose,
  AnalysisResult,
} from '../../lib/analysis-types';

const client = createAnalysisClient();
const stages: Record<string, string> = {
  queued: 'Ожидание в очереди',
  probe: 'Проверка видео',
  sparse: 'Поиск движений',
  flight_family: 'Поиск акселей',
  dense: 'Уточнение позы',
  nominal: 'Определение 1A и 2A',
  export: 'Подготовка результата',
  cancelling: 'Остановка обработки',
  completed: 'Анализ завершён',
  failed: 'Ошибка обработки',
  cancelled: 'Анализ отменён',
};
const formatTime = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(2).padStart(5, '0')}`;
const message = (error: unknown) =>
  error instanceof Error ? error.message : 'Не удалось выполнить запрос.';
const readinessIssue = (issue: string) => {
  if (issue === 'Release setup/configuration is incomplete')
    return 'Завершите установку анализатора по инструкции запуска.';
  if (issue.startsWith('Run release setup:'))
    return 'Не хватает компонентов анализатора или не совпадают их контрольные суммы. Повторите проверку установки.';
  if (issue === 'Release runtime missing')
    return 'В поставке отсутствует модуль анализа. Проверьте полноту скачанного пакета.';
  if (issue.startsWith('Release code checksum differs'))
    return 'Файлы обновились. Повторите настройку анализатора после обновления.';
  return issue;
};

export default function AnalysisWorkbench() {
  const inputRef = useRef<HTMLInputElement>(null),
    videoRef = useRef<HTMLVideoElement>(null);
  const [file, setFile] = useState<File | null>(null),
    [url, setUrl] = useState('');
  const [health, setHealth] = useState<AnalysisHealth | null>(null),
    [healthError, setHealthError] = useState(''),
    [healthRetry, setHealthRetry] = useState(0);
  const [job, setJob] = useState<AnalysisJob | null>(null),
    [result, setResult] = useState<AnalysisResult | null>(null),
    [pose, setPose] = useState<AnalysisPose | null>(null);
  const [error, setError] = useState(''),
    [poseError, setPoseError] = useState(''),
    [uploading, setUploading] = useState(false),
    [cancelPending, setCancelPending] = useState(false),
    [reconnect, setReconnect] = useState(0);
  const [duration, setDuration] = useState(0),
    [time, setTime] = useState(0),
    [playing, setPlaying] = useState(false),
    [showPose, setShowPose] = useState(true),
    [videoError, setVideoError] = useState(false);
  const uploadController = useRef<AbortController | null>(null),
    generation = useRef(0),
    cancelUploadRequested = useRef(false);
  const busy =
    uploading ||
    cancelPending ||
    job?.status === 'queued' ||
    job?.status === 'running';
  useEffect(() => {
    const controller = new AbortController();
    setHealthError('');
    client
      .health(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setHealth(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setHealth(null);
          setHealthError(message(e));
        }
      });
    return () => controller.abort();
  }, [healthRetry]);
  useEffect(() => {
    if (!file) {
      setUrl('');
      return;
    }
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);
  useEffect(
    () => () => {
      generation.current++;
      uploadController.current?.abort();
    },
    [],
  );
  const jobId = job?.id,
    sourceSha = job?.sourceSha256;
  useEffect(() => {
    if (!jobId || !sourceSha) return;
    const controller = new AbortController(),
      own = generation.current;
    const isCurrent = () =>
      !controller.signal.aborted && own === generation.current;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current = await client.job(jobId, controller.signal);
        if (!isCurrent()) return;
        if (current.sourceSha256 !== sourceSha)
          throw Error('Изменился исходник задачи анализа.');
        setJob(current);
        setError('');
        if (current.status === 'completed') {
          const [r, p] = await Promise.allSettled([
            client.result(jobId, sourceSha, controller.signal),
            client.pose(jobId, sourceSha, controller.signal),
          ]);
          if (!isCurrent()) return;
          if (r.status === 'fulfilled') setResult(r.value);
          else setError(message(r.reason));
          if (p.status === 'fulfilled') setPose(p.value);
          else setPoseError(message(p.reason));
          setCancelPending(false);
          return;
        }
        if (current.status === 'failed' || current.status === 'cancelled') {
          setCancelPending(false);
          return;
        }
        timer = setTimeout(poll, 1000);
      } catch (e) {
        if (isCurrent()) {
          setError(message(e));
          setCancelPending(false);
        }
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [jobId, sourceSha, reconnect]);
  function choose(candidate: File | undefined) {
    if (!candidate || busy) return;
    if (!/\.(mp4|mov|m4v|webm)$/i.test(candidate.name)) {
      setError('Выберите видео MP4, MOV, M4V или WebM.');
      return;
    }
    if (!candidate.size || candidate.size > 512 * 1024 * 1024) {
      setError('Размер видео должен быть от 1 байта до 512 МБ.');
      return;
    }
    generation.current++;
    setFile(candidate);
    setJob(null);
    setResult(null);
    setPose(null);
    setError('');
    setPoseError('');
    setDuration(0);
    setTime(0);
    setPlaying(false);
    setVideoError(false);
  }
  async function analyze() {
    if (!file || busy) return;
    const own = ++generation.current,
      controller = new AbortController();
    uploadController.current = controller;
    cancelUploadRequested.current = false;
    setUploading(true);
    setError('');
    setPoseError('');
    setJob(null);
    setResult(null);
    setPose(null);
    videoRef.current?.pause();
    try {
      const created = await client.upload(file, controller.signal);
      if (own !== generation.current) return;
      // Keep the response so a cancelled upload cannot leave an unknown running job.
      if (cancelUploadRequested.current) {
        try {
          const cancelled = await client.cancel(created.id, controller.signal);
          if (own !== generation.current) return;
          setJob(cancelled);
        } catch (e) {
          if (own !== generation.current) return;
          setJob(created);
          setError(message(e));
          setCancelPending(false);
        }
      } else setJob(created);
    } catch (e) {
      if (own === generation.current && !controller.signal.aborted) {
        setError(message(e));
        setCancelPending(false);
      }
    } finally {
      if (own === generation.current) setUploading(false);
    }
  }
  async function cancel() {
    if (uploading) {
      cancelUploadRequested.current = true;
      setCancelPending(true);
      return;
    }
    if (!job) return;
    const own = generation.current;
    setCancelPending(true);
    try {
      const cancelled = await client.cancel(job.id);
      if (own !== generation.current) return;
      setJob(cancelled);
      setReconnect((value) => value + 1);
    } catch (e) {
      if (own !== generation.current) return;
      setError(message(e));
      setCancelPending(false);
    }
  }
  function seek(value: number) {
    const video = videoRef.current;
    if (video) {
      video.currentTime = Math.max(0, Math.min(duration || value, value));
      setTime(value);
    }
  }
  const progress = job?.progress;
  const stageLabel = uploading
    ? 'Передача видео'
    : cancelPending
      ? 'Остановка обработки'
      : job
        ? stages[job.stage] || 'Обработка видео'
        : 'Готово к загрузке';
  const geometryMismatch =
    (pose &&
      videoRef.current?.videoWidth &&
      videoRef.current.videoWidth !== pose.geometry.width) ||
    (pose &&
      videoRef.current?.videoHeight &&
      videoRef.current.videoHeight !== pose.geometry.height);
  return (
    <main className="analysis-shell">
      <header className="analysis-header">
        <a className="analysis-brand" href="/analysis">
          <span className="analysis-brand-mark">Л</span>
          <span>
            ЛЁД<span className="analysis-brand-detail">АНАЛИЗ ВИДЕО</span>
          </span>
        </a>
        <a className="analysis-editor-link" href="/">
          Разметка вручную <ArrowUpRight size={15} />
        </a>
      </header>
      <section className="analysis-heading">
        <div>
          <span className="analysis-eyebrow">Фигурное катание · 1A / 2A</span>
          <h1>
            Разберите прыжок
            <br />
            <span>по исходному видео.</span>
          </h1>
          <p>
            Загрузите запись. Система найдёт предполагаемые аксели,
            <br className="analysis-desktop-break" /> а вы сможете проверить
            каждый момент и точки движения.
          </p>
        </div>
        <div className="analysis-local-note">
          <span className="analysis-live-dot" /> Обработка на вашем компьютере
        </div>
      </section>
      <input
        ref={inputRef}
        type="file"
        accept=".mp4,.mov,.m4v,.webm,video/mp4,video/quicktime,video/webm"
        className="analysis-file-input"
        aria-label="Выбрать видео для анализа"
        disabled={busy}
        onChange={(event) => {
          choose(event.target.files?.[0]);
          event.target.value = '';
        }}
      />
      <section className="analysis-workspace">
        <div className="analysis-video-column">
          <div className="analysis-panel-header">
            <span>
              <span className="analysis-step">01</span> Исходное видео
            </span>
            {file && (
              <button
                className="analysis-text-button"
                disabled={busy}
                onClick={() => inputRef.current?.click()}
              >
                Заменить видео
              </button>
            )}
          </div>
          <div
            className={`analysis-player ${url ? 'analysis-player-loaded' : ''}`}
          >
            {url ? (
              <>
                <video
                  ref={videoRef}
                  src={url}
                  controls
                  playsInline
                  preload="metadata"
                  onLoadedMetadata={(event) => {
                    setDuration(event.currentTarget.duration);
                    setVideoError(false);
                  }}
                  onTimeUpdate={(event) =>
                    setTime(event.currentTarget.currentTime)
                  }
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onError={() => setVideoError(true)}
                />
                <PoseOverlay
                  videoRef={videoRef}
                  pose={pose}
                  enabled={showPose && !geometryMismatch}
                />
              </>
            ) : (
              <button
                className="analysis-dropzone"
                onClick={() => inputRef.current?.click()}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  choose(event.dataTransfer.files?.[0]);
                }}
              >
                <span className="analysis-upload-icon">
                  <Upload size={30} strokeWidth={1.5} />
                </span>
                <strong>Добавьте видео спортсмена</strong>
                <span>Перетащите файл сюда или нажмите для выбора</span>
                <small>MP4, MOV, M4V, WebM · до 512 МБ</small>
              </button>
            )}
          </div>
          {file && (
            <div className="analysis-file-meta">
              <FileVideo size={18} />
              <span title={file.name}>{file.name}</span>
              <small>
                {(file.size / 1024 / 1024).toFixed(1)} МБ
                {duration > 0 ? ` · ${formatTime(duration)}` : ''}
              </small>
            </div>
          )}
          {videoError && (
            <p className="analysis-notice">
              Браузер не смог воспроизвести этот формат. Анализ можно запустить,
              но для просмотра результата может потребоваться MP4 с кодеком
              H.264.
            </p>
          )}
          <div className="analysis-overlay-options">
            <label>
              <input
                type="checkbox"
                checked={showPose}
                disabled={!pose}
                onChange={(event) => setShowPose(event.target.checked)}
              />{' '}
              Показывать точки и связи
            </label>
            <span>
              {pose ? '2D · исходные кадры' : 'Появятся после анализа'}
            </span>
          </div>
          {geometryMismatch && (
            <p className="analysis-notice">
              Размеры видео и данных позы не совпадают. Наложение скрыто.
            </p>
          )}
          {poseError && (
            <p className="analysis-notice">
              Данные позы недоступны: {poseError}
            </p>
          )}
          {url && duration > 0 && (
            <div className="analysis-timeline">
              <div className="analysis-timeline-label">
                <span>
                  <span className="analysis-step">02</span> Моменты прыжков
                </span>
                <span>
                  {formatTime(time)}{' '}
                  <span className="analysis-muted">
                    / {formatTime(duration)}
                  </span>
                </span>
              </div>
              <div className="analysis-event-track">
                {result?.events.map((event) => (
                  <button
                    key={event.id}
                    title={`${event.label} · ${formatTime(event.start)}`}
                    aria-label={`Перейти к ${event.label}, ${formatTime(event.start)}`}
                    style={{
                      left: `${(event.start / duration) * 100}%`,
                      width: `${Math.max(0.8, ((event.end - event.start) / duration) * 100)}%`,
                    }}
                    onClick={() => seek(event.start)}
                  />
                ))}
              </div>
              <input
                type="range"
                min="0"
                max={duration}
                step="0.001"
                value={Math.min(time, duration)}
                aria-label="Позиция в видео"
                onChange={(event) => seek(Number(event.target.value))}
              />
              <div className="analysis-playback-row">
                <button
                  className="analysis-text-button"
                  onClick={() => {
                    const video = videoRef.current;
                    if (video) {
                      if (video.paused)
                        void video.play().catch(() => setVideoError(true));
                      else video.pause();
                    }
                  }}
                >
                  {playing ? <Pause size={15} /> : <Play size={15} />}{' '}
                  {playing ? 'Пауза' : 'Воспроизвести'}
                </button>
                <span>
                  Нажмите на оранжевую отметку, чтобы перейти к прыжку
                </span>
              </div>
            </div>
          )}
        </div>
        <aside className="analysis-results-column">
          <div className="analysis-panel-header">
            <span>
              <span className="analysis-step">03</span> Анализ
            </span>
            <span className="analysis-model-badge">Прототип</span>
          </div>
          <div className="analysis-run-card">
            <h2>{result ? 'Результат анализа' : 'Найти аксели в видео'}</h2>
            <p>
              Автоматический поиск и определение номинала 1A / 2A. Результаты
              требуют проверки.
            </p>
            <button
              className="analysis-primary-button"
              disabled={!file || busy || !health?.inferenceAvailable}
              onClick={() => void analyze()}
            >
              {uploading ? (
                <LoaderCircle className="analysis-spin" size={18} />
              ) : (
                <Play size={17} />
              )}{' '}
              {job && !busy ? 'Анализировать ещё раз' : 'Начать анализ'}
            </button>
            {busy && (
              <button
                className="analysis-cancel-button"
                disabled={cancelPending}
                onClick={() => void cancel()}
              >
                <X size={16} /> {cancelPending ? 'Остановка…' : 'Отменить'}
              </button>
            )}
            {!health?.inferenceAvailable && (
              <div className="analysis-service-notice">
                <strong>
                  {healthError
                    ? 'Сервис анализа недоступен'
                    : health
                      ? 'Анализатор ещё не готов'
                      : 'Проверяем готовность анализатора…'}
                </strong>
                {healthError && <span>{healthError}</span>}
                {health?.issues.map((issue, i) => (
                  <span key={i}>{readinessIssue(issue)}</span>
                ))}
                <button
                  className="analysis-text-button"
                  onClick={() => setHealthRetry((value) => value + 1)}
                >
                  <RefreshCw size={13} /> Проверить снова
                </button>
              </div>
            )}
          </div>
          {(job || uploading) && (
            <div className="analysis-status" role="status" aria-live="polite">
              <div>
                {busy ? (
                  <LoaderCircle size={17} className="analysis-spin" />
                ) : job?.status === 'completed' ? (
                  <Check size={17} />
                ) : (
                  <X size={17} />
                )}
                <strong>{stageLabel}</strong>
              </div>
              {busy &&
                progress !== null &&
                progress !== undefined &&
                !uploading && (
                  <>
                    <progress max="100" value={progress} />
                    <small>{Math.round(progress)}% текущего этапа</small>
                  </>
                )}
              {job?.currentFrame !== null &&
                job?.currentFrame !== undefined && (
                  <small>
                    Кадр {job.currentFrame}
                    {job.totalFrames ? ` из ${job.totalFrames}` : ''}
                  </small>
                )}
              {job?.status === 'failed' && (
                <p>{job.error || 'Обработка завершилась с ошибкой.'}</p>
              )}
              {job?.status === 'cancelled' && (
                <p>
                  Видео не проанализировано. Можно запустить новую обработку.
                </p>
              )}
            </div>
          )}
          {error && (
            <div className="analysis-error" role="alert">
              <p>{error}</p>
              {job && (
                <button
                  className="analysis-text-button"
                  onClick={() => setReconnect((value) => value + 1)}
                >
                  Обновить состояние задачи
                </button>
              )}
            </div>
          )}
          <div className="analysis-results-header">
            <h2>Найденные моменты</h2>
            <span>{result ? result.events.length : '—'}</span>
          </div>
          {result ? (
            result.events.length ? (
              <div className="analysis-event-list">
                {result.events.map((event, index) => (
                  <button
                    className="analysis-event-card"
                    key={event.id}
                    onClick={() => seek(event.start)}
                  >
                    <span className="analysis-event-number">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span>
                      <strong>
                        {event.label === 'Axel' ? 'Аксель' : event.label}
                      </strong>
                      <small>
                        {event.label === 'Axel'
                          ? 'Номинал не определён'
                          : 'Предполагаемый аксель'}{' '}
                        · {formatTime(event.start)}–{formatTime(event.end)}
                      </small>
                      {event.label === 'Axel' && (
                        <small>
                          Недостаточно данных для определения 1A / 2A
                        </small>
                      )}
                    </span>
                    <ChevronRight size={18} />
                  </button>
                ))}
              </div>
            ) : (
              <div className="analysis-empty-results">
                <Check size={22} />
                <strong>Аксели не обнаружены</strong>
                <p>
                  Анализ завершён, но модель не выделила аксель. Это не
                  исключает пропущенные прыжки — проверьте видео.
                </p>
              </div>
            )
          ) : (
            <div className="analysis-empty-results">
              <span className="analysis-empty-lines">
                ▰<br />▱<br />▱
              </span>
              <strong>
                {busy ? 'Обрабатываем видео' : 'Здесь появятся прыжки'}
              </strong>
              <p>
                {busy
                  ? 'После завершения можно перейти к каждому найденному моменту.'
                  : 'Выберите запись и начните анализ. Каждый результат будет связан с моментом на видео.'}
              </p>
            </div>
          )}
          {result && (
            <p className="analysis-result-caveat">
              1A и 2A — предполагаемые номинальные классы. Физическое вращение и
              недокрут здесь не измеряются.
            </p>
          )}
          {result?.warnings.length ? (
            <details className="analysis-limitations">
              <summary>Ограничения анализа</summary>
              {result.warnings.map((warning, i) => (
                <p key={i}>{warning}</p>
              ))}
            </details>
          ) : null}
        </aside>
      </section>
      <footer className="analysis-footer">
        <span>ЛЁД / FS_elem</span>
        <span>Видео → поиск акселя → проверка по кадрам</span>
      </footer>
    </main>
  );
}
