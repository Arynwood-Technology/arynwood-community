/** Original Arynwood tree artwork, with Grove's green-teal lighting. */
export function Logo({ className = 'logo', label }: { className?: string; label?: string }) {
  return <span className={`grove-mark ${className}`} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}><img src="/arynwood-tree.png" alt="" draggable={false} /></span>
}
