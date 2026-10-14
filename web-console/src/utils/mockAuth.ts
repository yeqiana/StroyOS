/** Browser-only demo identity. Never a token, credential, server identity or production permission. */
export type MockAvatar = 'book'|'mountain'|'spark';
export type MockProfile={displayName:string;avatar:MockAvatar};
export type MockAuthState={
  status:'guest'|'mock'|'expired';
  profile:MockProfile|null;
  persistence:'saved'|'session-only'|'none';
};
export interface AuthAdapter {
  read():MockAuthState;
  signIn():MockAuthState;
  updateProfile(profile:MockProfile):MockAuthState;
  signOut():MockAuthState;
  expire():MockAuthState;
}
export const MOCK_AUTH_STORAGE_KEY='storyos:mock-ui-auth:v1';
export const DEFAULT_MOCK_PROFILE:MockProfile={displayName:'演示用户',avatar:'book'};
const isAvatar=(value:unknown):value is MockAvatar=>value==='book'||value==='mountain'||value==='spark';
const validName=(value:unknown):value is string=>
  typeof value==='string'&&value.trim().length>0&&value.trim().length<=30
  && !/[\u0000-\u001F\u007F]/.test(value);
const validProfile=(x:unknown):x is MockProfile=>x!==null&&typeof x==='object'
  &&validName((x as MockProfile).displayName)&&isAvatar((x as MockProfile).avatar);
const guest:MockAuthState={status:'guest',profile:null,persistence:'none'};

export function createMockAuthAdapter(store?: Pick<Storage,'getItem'|'setItem'|'removeItem'>):AuthAdapter {
  const storage=()=>store??localStorage;
  let state:MockAuthState={...guest};
  const persist=(status:'mock'|'expired',profile:MockProfile|null):MockAuthState=>{
    const next:MockAuthState={status,profile:status==='mock'?profile:null,persistence:'session-only'};
    try{
      storage().setItem(MOCK_AUTH_STORAGE_KEY,JSON.stringify({version:1,kind:'storyos-mock-ui',status,profile:next.profile}));
      if(storage().getItem(MOCK_AUTH_STORAGE_KEY)===JSON.stringify({version:1,kind:'storyos-mock-ui',status,profile:next.profile}))
        next.persistence='saved';
    }catch{/* Browser storage denied; only current page state is available. */}
    state=next;
    return next;
  };
  return {
    read(){
      try{
        const raw=storage().getItem(MOCK_AUTH_STORAGE_KEY);
        if(!raw){state={...guest};return state;}
        const data=JSON.parse(raw) as Record<string,unknown>;
        if(data.kind==='storyos-mock-ui'&&data.version===1){
          if(data.status==='mock'&&validProfile(data.profile)){
            state={status:'mock',profile:{displayName:data.profile.displayName.trim(),avatar:data.profile.avatar},persistence:'saved'};
            return state;
          }
          if(data.status==='expired'&&data.profile===null){
            state={status:'expired',profile:null,persistence:'saved'};
            return state;
          }
        }
        state={...guest};
        return state;
      }catch{state={...guest,persistence:'session-only'};return state;}
    },
    signIn(){return persist('mock',{...DEFAULT_MOCK_PROFILE});},
    updateProfile(profile){
      if(state.status!=='mock'||!validProfile(profile))return state;
      return persist('mock',{displayName:profile.displayName.trim(),avatar:profile.avatar});
    },
    signOut(){
      let persistence:MockAuthState['persistence']='none';
      try{
        storage().removeItem(MOCK_AUTH_STORAGE_KEY);
        if(storage().getItem(MOCK_AUTH_STORAGE_KEY)!==null)persistence='session-only';
      }catch{persistence='session-only';}
      state={...guest,persistence};return state;
    },
    expire(){return state.status==='mock'?persist('expired',null):state;},
  };
}
