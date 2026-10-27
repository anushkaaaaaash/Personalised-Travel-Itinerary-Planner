export function assertQaPreviewOnly({vercelEnv,hasQaArtifacts}) {
  if(vercelEnv==='production' && hasQaArtifacts)throw new Error('Remove temporary public/__qa preview artifacts before a production build.');
}
