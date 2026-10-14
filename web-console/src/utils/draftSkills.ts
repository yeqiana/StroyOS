/** REA-inspired discoverable commands. UI drafts only; none calls a Runtime. */
export const DRAFT_SKILLS = [
  {id:'storyboard',command:'/分镜',label:'分镜拆解',description:'规划图文故事的逐帧叙事与镜头目的',template:'请对当前故事的图文分镜进行拆解检查：逐帧说明叙事目的、构图、人物动作与画面连续性；列出需要人工确认的帧。仅形成建议草稿，不执行生产。'},
  {id:'character',command:'/角色',label:'角色一致性',description:'核查角色契约、服装与面容锚点',template:'请根据当前作品已有的角色契约与已批准素材，列出角色面容、服装和身份一致性需要核查的帧；证据不足的项目标记为未验证。仅形成检查草稿，不修改人物契约。'},
  {id:'prompt',command:'/提示词',label:'Prompt 自检',description:'检查图文提示词是否符合批准契约',template:'请检查当前作品的图文 Prompt 是否与锁定分镜、画风和人物契约一致；按帧列出含糊、冲突或缺失的约束。仅形成检查草稿，不触发生图。'},
  {id:'blocked',command:'/阻断',label:'阻断诊断',description:'根据现有只读证据整理阻断原因',template:'请只根据当前 StoryOS 可核验的状态、日志和回执，列出阻断帧、失败阶段、证据缺口和建议的下一步检查；没有证据时明确标记未知。仅形成排障草稿，不执行重试。'}
] as const;
export function matchDraftSkills(input:string) {
  if(!input.startsWith('/')||input.includes('\n'))return [];
  const q=input.slice(1).trim().toLocaleLowerCase();
  return DRAFT_SKILLS.filter(skill=> !q || (skill.command+' '+skill.label+' '+skill.description).toLocaleLowerCase().includes(q));
}
