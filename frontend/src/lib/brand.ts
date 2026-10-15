import { useEffect, useState, type CSSProperties } from 'react'
import { api } from './community'
export type Brand = { branded:boolean; name:string; tagline:string; accent:string; site_url:string; site_label:string; shop_url:string; shop_label:string; logo_url:string }
export const defaultBrand:Brand={branded:false,name:'Arynwood Grove',tagline:'The Grove, your community – your choices',accent:'#4fd1ab',site_url:'',site_label:'Website',shop_url:'',shop_label:'Shop',logo_url:''}
export function useBrand(enabled=true){
  const [brand,setBrand]=useState(defaultBrand)
  useEffect(()=>{if(!enabled)return;let active=true;api<Brand>('/brand').then(value=>{if(active&&typeof value?.branded==='boolean')setBrand(value)}).catch(()=>{});return()=>{active=false}},[enabled])
  useEffect(()=>{if(!enabled)return;const previous=document.title;document.title=brand.name;return()=>{document.title=previous}},[brand.name,enabled])
  useEffect(()=>{
    if(!enabled||!brand.branded)return
    const icons=Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="apple-touch-icon"]'))
    const original=icons.map(icon=>({icon,href:icon.getAttribute('href'),type:icon.getAttribute('type')}))
    icons.forEach(icon=>{icon.href=brand.logo_url||'data:,';icon.removeAttribute('type')})
    return()=>{original.forEach(({icon,href,type})=>{if(href!==null)icon.setAttribute('href',href);if(type!==null)icon.setAttribute('type',type)})}
  },[brand.branded,brand.logo_url,enabled])
  return brand
}
export function brandStyle(brand:Brand):CSSProperties|undefined {
  return brand.accent===defaultBrand.accent?undefined:{'--accent':brand.accent,'--accent-hover':brand.accent,'--accent-text':brand.accent,'--accent2':brand.accent,'--accent-soft':`color-mix(in srgb, ${brand.accent} 14%, transparent)`,'--on-accent':'#0f1314'} as CSSProperties
}
