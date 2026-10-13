/** Removing a local project must never silently delete its saved story drafts. */
export function detachLocalDraftProject<T extends { id:string; projectId?:string }>(
  stories:T[], projectId:string
): T[] {
  return stories.map(story =>
    story.projectId === projectId && /^ep-(home|proj)-/.test(story.id)
      ? {...story, projectId:undefined}
      : story
  );
}
