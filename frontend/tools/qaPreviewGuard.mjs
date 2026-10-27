export function assertQaPreviewOnly({production,hasQaArtifacts}) {
  if(production && hasQaArtifacts)throw new Error('Remove temporary public/__qa preview artifacts before a production build.');
}
