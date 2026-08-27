export default function CategoryBadge({ category }) {
  if (!category) return <span className="badge pending">pendente</span>
  return <span className={`badge ${category}`}>{category}</span>
}
