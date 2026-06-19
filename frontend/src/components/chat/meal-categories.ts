import type { MealCategory } from '../../api/types'

export const CATEGORY_LABELS: Record<MealCategory, string> = {
  breakfast: 'Breakfast',
  brunch: 'Brunch',
  lunch: 'Lunch',
  dinner: 'Dinner',
  snack: 'Snack',
}

/** Pre-select a category from the browser's local clock (user can override). */
export function defaultMealCategory(date = new Date()): MealCategory {
  const h = date.getHours()
  if (h >= 5 && h < 11) return 'breakfast'
  if (h === 11) return 'brunch'
  if (h >= 12 && h < 15) return 'lunch'
  if (h >= 15 && h < 17) return 'snack'
  if (h >= 17 && h < 22) return 'dinner'
  return 'snack'
}
