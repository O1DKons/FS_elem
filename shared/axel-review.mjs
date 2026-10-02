export const isAxelDraft = episode => /^[1-4]A(?:q|<<|<)?\*?$/.test(episode?.protocolCode || '');

export function axelReviewVideos(videos, episodes) {
  const ids = new Set(episodes.filter(isAxelDraft).map(episode => episode.videoId));
  return videos.filter(video => video.collection === 'competition' && ids.has(video.id));
}
