export const formatKcal = (kcal: number): string => {
  return `${Math.round(kcal).toLocaleString()} kcal`
}

export const formatGrams = (grams: number): string => {
  return `${Math.round(grams)}g`
}

export const formatPercent = (percent: number): string => {
  return `${Math.round(percent)}%`
}
