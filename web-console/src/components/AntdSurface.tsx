import React, {useEffect,useState} from 'react';
import {ConfigProvider,theme as antdTheme} from 'antd';
import {THEME_PALETTES} from '../theme';
const readMode=()=>(document.documentElement.classList.contains('theme-light-gradient')?'light-gradient':document.documentElement.classList.contains('theme-light')?'light':'dark') as keyof typeof THEME_PALETTES;
const AntdSurface:React.FC<{children:React.ReactNode}>=({children})=>{
 const [mode,setMode]=useState<keyof typeof THEME_PALETTES>(()=>typeof document==='undefined'?'dark':readMode());
 useEffect(()=>{const observer=new MutationObserver(()=>setMode(readMode()));observer.observe(document.documentElement,{attributes:true,attributeFilter:['class']});return ()=>observer.disconnect()},[]);
 const c=THEME_PALETTES[mode];
 return <ConfigProvider componentSize="small" theme={{algorithm:mode==='dark'?antdTheme.darkAlgorithm:antdTheme.defaultAlgorithm,token:{colorPrimary:c.info,colorBgContainer:c.bgSurface,colorText:c.textPrimary,colorTextSecondary:c.textSecondary,colorBorder:c.borderNormal,colorBorderSecondary:c.borderSubtle,borderRadius:5,fontSize:13,controlHeight:34,colorBgLayout:c.bgApp,colorBgElevated:c.bgElevated,controlOutline:c.info},components:{Table:{cellPaddingBlockSM:10,cellPaddingInlineSM:14,headerBg:c.bgElevated,headerColor:c.textSecondary,borderColor:c.borderSubtle,rowHoverBg:c.bgHover},Pagination:{itemBg:"transparent",itemActiveBg:c.bgSelected},Button:{colorPrimary:c.textPrimary,colorPrimaryHover:c.textSecondary,colorPrimaryActive:c.textPrimary,colorTextLightSolid:c.bgApp,primaryShadow:"none",defaultShadow:"none"}}}}>{children}</ConfigProvider>;
};
export default AntdSurface;
