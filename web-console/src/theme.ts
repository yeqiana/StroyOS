/**
 * StoryOS Centralized Theme Tokens & Color System
 * 统一主题色中枢：所有颜色契约在此处单点定义
 */

export interface ThemeColors {
  bgApp: string;
  bgWorkspace: string;
  bgSurface: string;
  bgElevated: string;
  bgHover: string;
  bgSelected: string;
  borderSubtle: string;
  borderNormal: string;
  borderStrong: string;
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  textDisabled: string;
  success: string;
  warning: string;
  retry: string;
  danger: string;
  info: string;
}

export const THEME_PALETTES: Record<'dark' | 'light' | 'light-gradient', ThemeColors> = {
  dark: {
    bgApp: '#0A0B0D',
    bgWorkspace: '#171717',
    bgSurface: '#1C1E21',
    bgElevated: '#25282C',
    bgHover: '#292D32',
    bgSelected: '#343940',
    borderSubtle: '#30343A',
    borderNormal: '#41474F',
    borderStrong: '#56606A',
    textPrimary: '#F4F6F8',
    textSecondary: '#BEC5CC',
    textTertiary: '#969FA8',
    textDisabled: '#737C86',
    success: '#3FB950',
    warning: '#D29922',
    retry: '#E3A008',
    danger: '#F85149',
    info: '#72A6F7',
  },
  light: {
    bgApp: '#FAFAFA',
    bgWorkspace: '#F1F2F4',
    bgSurface: '#FFFFFF',
    bgElevated: '#FFFFFF',
    bgHover: '#E6E9ED',
    bgSelected: '#DEE5ED',
    borderSubtle: '#E1E5EA',
    borderNormal: '#C9D0D8',
    borderStrong: '#A5AFBB',
    textPrimary: '#1C2127',
    textSecondary: '#505B66',
    textTertiary: '#6E7985',
    textDisabled: '#98A2B0',
    success: '#1A7F37',
    warning: '#9A6700',
    retry: '#BC4C00',
    danger: '#CF222E',
    info: '#326FCD',
  },
  'light-gradient': {
    bgApp: '#FAFAFA',
    bgWorkspace: '#F1F2F4',
    bgSurface: '#FFFFFF',
    bgElevated: '#FFFFFF',
    bgHover: '#E9EDF1',
    bgSelected: '#E2E8EF',
    borderSubtle: '#E1E5EA',
    borderNormal: '#C9D0D8',
    borderStrong: '#A5AFBB',
    textPrimary: '#1C2127',
    textSecondary: '#505B66',
    textTertiary: '#6E7985',
    textDisabled: '#98A2B0',
    success: '#16A34A',
    warning: '#D97706',
    retry: '#EA580C',
    danger: '#DC2626',
    info: '#326FCD',
  },
};
