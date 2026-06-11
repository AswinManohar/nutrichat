import React from 'react'

interface PreferenceChipsProps {
  options: { label: string; value: string }[]
  selectedValues: string[]
  onChange: (selected: string[]) => void
}

export const PreferenceChips: React.FC<PreferenceChipsProps> = ({
  options,
  selectedValues,
  onChange,
}) => {
  const toggleOption = (value: string) => {
    if (selectedValues.includes(value)) {
      onChange(selectedValues.filter((v) => v !== value))
    } else {
      onChange([...selectedValues, value])
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => {
        const isSelected = selectedValues.includes(opt.value)
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => toggleOption(opt.value)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all duration-200 ${
              isSelected
                ? 'bg-container border-sage text-sage-deep shadow-md shadow-black/5'
                : 'bg-sand border-sand-border text-muted hover:border-sand-border hover:text-ink'
            }`}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
