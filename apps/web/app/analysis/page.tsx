import AnalysisWorkbench from '../../components/analysis/AnalysisWorkbench';
import './analysis.css';
export const metadata = {
  title: 'Лёд · Анализ акселей',
  description:
    'Автоматический поиск акселя и реальные точки позы на исходном видео',
};
export default function AnalysisPage() {
  return <AnalysisWorkbench />;
}
