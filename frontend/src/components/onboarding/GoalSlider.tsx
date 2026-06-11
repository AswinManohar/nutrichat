import React from 'react'

interface GoalSliderProps {
  label: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  unit: string;
  onChange: (val: number) => void;
  description?: string;
}

export const GoalSlider: React.FC<GoalSliderProps> = ({
  label,
  min,
  max,
  step = 1,
  value,
  unit,
  onChange,
  description,
}) => {
  return (
    <div className="flex flex-col gap-2 p-4 bg-container border border-sand-border rounded-xl">
      <div className="flex items-center justify-between">
        <div>
          <label className="text-sm font-medium text-ink">{label}</label>
          {description && <p className="text-xs text-muted mt-0.5">{description}</p>}
        </div>
        <div className="flex items-baseline gap-1 bg-sand border border-sand-border px-3 py-1 rounded-lg">
          <span className="font-display font-bold text-sage-deep text-base">{value}</span>
          <span className="text-xs text-muted">{unit}</span>
        </div>
      </div>
      
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 bg-container rounded-lg appearance-none cursor-pointer accent-sage hover:accent-sage-deep transition-colors"
      />
      
      <div className="flex justify-between text-[10px] text-muted px-0.5">
        <span>{min} {unit}</span>
        <span>{max} {unit}</span>
      </div>
    </div>
  )
}
