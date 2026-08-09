export function WorkspaceSkeleton() {
  return (
    <main className="app-layout is-loading" aria-label="Loading FPLAgent workspace">
      <div className="skeleton-rail skeleton-shimmer" />
      <div className="skeleton-main">
        <span className="skeleton-line skeleton-shimmer" />
        <span className="skeleton-heading skeleton-shimmer" />
        <div className="skeleton-pitch skeleton-shimmer" />
      </div>
      <div className="skeleton-side">
        <div className="skeleton-panel skeleton-shimmer" />
        <div className="skeleton-chat skeleton-shimmer" />
      </div>
      <span className="sr-only">Loading current squad, fixtures and decision evidence</span>
    </main>
  )
}
