/** The Arynwood tree mark. Decorative wherever the product name is also shown. */
export function Logo({ className = 'logo', label }: { className?: string; label?: string }) {
  return <img src="/arynwood-logo.png" className={className} alt={label ?? ''} aria-hidden={label ? undefined : true} width={256} height={256} draggable={false} />
}
